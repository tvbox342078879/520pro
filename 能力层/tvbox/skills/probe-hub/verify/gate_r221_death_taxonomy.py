#!/usr/bin/env python3
"""gate_r221_death_taxonomy.py — M-R221 死因分型闸门（SCAN → GATE，S227）

立规理由：自愈的核心不是 AI 而是失效分型。403 ≠ 选择器失效 ≠ 证书过期 ≠ 结构改版，
分型错了修复必然瞎打（S169 把"证书过期"与"站点真死"塌成同一个失败，活源被判死）。

本闸门只查**客观可断言**的东西，不做主观判断（M-R136）：
  ① 七型域固定：DEATH_CAUSES 恰好是七元组，多一型少一型都拦
     —— 域被悄悄扩/缩，下游 REPAIR_ROUTE 与 strategies.json 就会漏路由
  ② 路由无遗漏：REPAIR_ROUTE 必须覆盖除 ''（通过）外的全部六型
  ③ 三态不塌陷：'无法判定' 必须映射到 '未定·网络' 且该型路由为"先复验不修"
     —— 这条是 M-R60 的制度化，历史上真出过事
  ④ 分型唯一事实源：repair/ 内不得自行定义死因常量或路由表（M-R38）
  ⑤ 策略可落地：strategies.json 覆盖全部六型，且 '结构性' 必须指 rewrite
     （若指 patch，整站改版会被当成小补，改不好的同时又写坏文件）

三态纪律：本脚本只输出 通过 / 失败 / 无法判定。
  · 导入失败、文件缺失 → 无法判定（exit 2 之外的独立码），绝不折叠成通过。
退出码：0=通过；1=失败（有硬伤）；2=无法判定（跑不了，非通过）。

用法: python3 verify/gate_r221_death_taxonomy.py <repo_root>
注意: 参数只含路径字符，符合 hooks/gate_stats.sh 的 safe_cmd 白名单。
"""
import ast
import json
import os
import sys

# R3 杀开关（第四十八·amendment-2·S1）：gate_r221 作为升 red 门禁接入 kill switch。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import gate_kill as _gk
except Exception:
    class _gk:
        @staticmethod
        def is_off(name):
            return False

EXIT_PASS, EXIT_FAIL, EXIT_UNDETERMINED = 0, 1, 2

EXPECTED_CAUSES = ('', '域名层', '接口层', '内容层', '语法层', '结构性', '未定·网络')
EXPECTED_ROUTE_KEYS = {'域名层', '接口层', '内容层', '语法层', '结构性', '未定·网络'}


def _fail(msgs, checks):
    print(f'✗ M-R221 分型闸门未通过（{len(msgs)} 项硬伤 / 共 {checks} 项）')
    for m in msgs[:12]:
        print('  ✗ ' + m)
    if len(msgs) > 12:
        print(f'  ... 另有 {len(msgs) - 12} 项')
    if _gk.is_off("gate_r221"):
        print("[WARN 观察轮·kill switch] gate_r221 已被杀开关关闭：red 降级为 WARN，本轮回填不阻断（判据仍报未通过）")
        sys.exit(0)
    sys.exit(EXIT_FAIL)


def _undetermined(why):
    print(f'⚠ M-R221 分型闸门无法判定（非通过，M-R60）：{why}')
    sys.exit(EXIT_UNDETERMINED)


def _find_hub(repo=None):
    """定位 probe-hub 目录。

    显式传了 repo 却找不到 → 返回 None（调用方报「无法判定」，绝不回退到脚本自身目录，
    否则用户以为在检查 A 目录，实际查了 B 目录，是张冠李戴式假绿）。
    未传参 → 从脚本位置反推（probe-hub/verify/ 的上一级）。
    """
    if repo:
        cands = [os.path.join(repo, '能力层', 'tvbox', 'skills', 'probe-hub'),
                 os.path.join(repo, 'skills', 'probe-hub')]
    else:
        cands = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for c in cands:
        if os.path.isdir(os.path.join(c, 'scripts')):
            return os.path.abspath(c)
    return None


def main():
    hub = _find_hub(sys.argv[1] if len(sys.argv) > 1 else None)
    if not hub:
        where = sys.argv[1] if len(sys.argv) > 1 else '脚本上级目录'
        _undetermined(f'找不到 probe-hub（检查了 {where}）——不是通过')
    lc_path = os.path.join(hub, 'scripts', 'livecheck.py')
    if not os.path.exists(lc_path):
        _undetermined(f'找不到 {lc_path}')
    sys.path.insert(0, os.path.dirname(lc_path))
    sys.path.insert(0, hub)
    try:
        from livecheck import DEATH_CAUSES, REPAIR_ROUTE, death_cause
    except Exception as e:
        _undetermined(f'livecheck 导入失败: {type(e).__name__}: {e}')

    bad, n = [], 0

    # ① 七型域固定
    n += 1
    if tuple(DEATH_CAUSES) != EXPECTED_CAUSES:
        bad.append(f'死因域被改动: 期望 {EXPECTED_CAUSES}，实为 {tuple(DEATH_CAUSES)}')

    # ② 路由无遗漏
    n += 1
    got = set(REPAIR_ROUTE)
    missing = EXPECTED_ROUTE_KEYS - got
    extra = got - EXPECTED_ROUTE_KEYS
    if missing:
        bad.append(f'REPAIR_ROUTE 漏路由 {sorted(missing)}')
    if extra:
        bad.append(f'REPAIR_ROUTE 有域外死因 {sorted(extra)}')

    # ③ 三态不塌陷（M-R60 的制度化，历史真出过事）
    n += 1
    try:
        if death_cause('通过', '一切正常') != '':
            bad.append('三态塌陷: 通过 未被归为无死因')
        dc_undet = death_cause('无法判定', 'timeout 30s')
        if dc_undet != '未定·网络':
            bad.append(f'三态塌陷: 无法判定 被判为 {dc_undet!r}，应为 未定·网络')
        if '复验' not in REPAIR_ROUTE.get('未定·网络', ''):
            bad.append('三态塌陷: 未定·网络 的路由不是「先复验」，会把活源拖进修复链')
        # 关键反例：无法判定 不得产生任何"修复"型路由
        if '换域' in REPAIR_ROUTE.get('未定·网络', ''):
            bad.append('三态塌陷: 未定·网络 竟然走换域修复（活源会被改死）')
    except Exception as e:
        bad.append(f'death_cause 调用异常: {type(e).__name__}: {e}')

    # ④ 分型唯一事实源：repair/ 不得自建死因常量（M-R38）
    n += 1
    repair_dir = os.path.join(hub, 'repair')
    offenders = []
    for name in sorted(os.listdir(repair_dir)) if os.path.isdir(repair_dir) else []:
        if not name.endswith('.py'):
            continue
        p = os.path.join(repair_dir, name)
        try:
            tree = ast.parse(open(p, encoding='utf-8').read())
        except Exception:
            continue
        for node in tree.body:
            # 只看模块级赋值：DEATH_CAUSES = (...) / REPAIR_ROUTE = {...}
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in ('DEATH_CAUSES', 'REPAIR_ROUTE'):
                        offenders.append(f'{name}:{node.lineno} 重定义 {t.id}')
    if offenders:
        bad.append('分型口径被复制（M-R38 违背）: ' + '; '.join(offenders))

    # ⑤ 策略可落地
    n += 1
    st_path = os.path.join(repair_dir, 'strategies.json')
    if not os.path.exists(st_path):
        bad.append(f'缺 {st_path}')
    else:
        try:
            routes = json.load(open(st_path, encoding='utf-8'))['routes']
        except Exception as e:
            _undetermined(f'strategies.json 解析失败: {e}')
        lack = EXPECTED_ROUTE_KEYS - set(routes)
        if lack:
            bad.append(f'strategies.json 漏策略 {sorted(lack)}')
        st = (routes.get('结构性') or {}).get('strategy')
        if st != 'rewrite':
            bad.append(f"结构性 应路由到 rewrite（整站重写），实为 {st!r}"
                       '—— 整站改版当小补改，既改不好又会写坏文件')

    if bad:
        _fail(bad, n)
    print(f'✓ M-R221 分型闸门通过（{n} 项：七型域 / 路由无遗漏 / 三态不塌陷 / 唯一事实源 / 策略可落地）')
    sys.exit(EXIT_PASS)


if __name__ == '__main__':
    main()
