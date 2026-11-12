#!/usr/bin/env python3
"""gate_r222_repair_contract.py — M-R222 修源模块自包含/不造假闸门（SCAN → GATE，S227）

立规理由：'搞进来了以后可不好再隔离出去，以后还有新东西的'——repair/ 必须随时能 git mv
独立出去。隔离面就是 schemas/ 两份契约；一旦模块内私接上级 probe.py，摘除时必然连带崩。
并预置防造假条款：通道没接通就必须说 not_applicable，绝不许返回 repaired 冒充成功。

只查客观可断言的事实（M-R136 不造假 / M-R57 错误不折叠成 ok）：
  ① 隔离面完整：schemas/ 下两份契约齐备且是合法 JSON
  ② 无反向依赖：repair/*.py 不得 import 上级 probe（隔离性被破坏则整站不可摘除）
  ③ 校验器真能拦：validate() 必须拒绝非法 status/strategy/verdict 与缺必填
     —— 只验'函数存在'等于没验，必须喂非法值看它拒
  ④ 防造假：'修好了但没备份' 必须被拒
     —— backup_path 是安全网的证据，缺它就是无回滚能力的 repaired
  ⑤ 诚实自述：未接通通道时不得对外声称具备修复能力（engine 模块 docstring/常量自述）

三态纪律：导入失败/文件缺失 → 无法判定(exit 2)，绝不折叠成通过。
退出码：0=通过；1=失败；2=无法判定。

用法: python3 verify/gate_r222_repair_contract.py <repo_root>
"""
import ast
import json
import os
import sys

# R3 杀开关（第四十八·amendment-2·S1）：gate_r222 作为升 red 门禁接入 kill switch。
# 判据真值不变（仍报未通过），仅当杀开关关闭该门禁时 red→WARN 降级（不阻断 exit 0）。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import gate_kill as _gk
except Exception:
    class _gk:
        @staticmethod
        def is_off(name):
            return False

EXIT_PASS, EXIT_FAIL, EXIT_UNDETERMINED = 0, 1, 2

REQUIRED_SCHEMAS = ('checkup_report.schema.json', 'repair_result.schema.json')
# 反向依赖禁令：repair/ 内不得出现这些上级模块引用（会破坏可摘除性）
FORBIDDEN_TARGETS = ('probe', 'livecheck')


def _fail(msgs, n):
    print(f'✗ M-R222 契约闸门未通过（{len(msgs)} 项硬伤 / 共 {n} 项）')
    for m in msgs[:12]:
        print('  ✗ ' + m)
    if _gk.is_off("gate_r222"):
        print("[WARN 观察轮·kill switch] gate_r222 已被杀开关关闭：red 降级为 WARN，本轮回填不阻断（判据仍报未通过）")
        sys.exit(0)
    sys.exit(EXIT_FAIL)


def _undetermined(why):
    print(f'⚠ M-R222 契约闸门无法判定（非通过，M-R60）：{why}')
    sys.exit(EXIT_UNDETERMINED)


def _imports_of(path):
    """返回该文件所有 import 的目标名（含 from X import 的 X）。"""
    try:
        tree = ast.parse(open(path, encoding='utf-8').read())
    except Exception:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append(node.module)
            elif node.level:                       # from . import x
                out += [a.name for a in node.names]
    return out


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
        if os.path.isdir(os.path.join(c, 'repair')):
            return os.path.abspath(c)
    return None


def main():
    hub = _find_hub(sys.argv[1] if len(sys.argv) > 1 else None)
    if not hub:
        where = sys.argv[1] if len(sys.argv) > 1 else '脚本上级目录'
        _undetermined(f'找不到 probe-hub（检查了 {where}）——不是通过')
    repair_dir = os.path.join(hub, 'repair')
    if not os.path.isdir(repair_dir):
        _undetermined(f'找不到 {repair_dir}')

    bad, n = [], 0

    # ① 隔离面完整（纯静态，不依赖 import 成功）
    n += 1
    for fn in REQUIRED_SCHEMAS:
        p = os.path.join(repair_dir, 'schemas', fn)
        if not os.path.exists(p):
            bad.append(f'隔离面缺失: schemas/{fn}')
            continue
        try:
            json.load(open(p, encoding='utf-8'))
        except Exception as e:
            bad.append(f'schemas/{fn} 非法 JSON: {e}')

    # ② 无反向依赖（可摘除性的硬前提）
    # ★ 必须用纯静态 AST 先查，不能等 import 失败再说 ——
    #   若这里先 import，一旦注入了 import probe，engine 自身就导入失败，
    #   闸门会退化成"无法判定"，把真实的隔离性破坏说成"我判不了"。
    #   变异测试实测踩过：注入 import probe 后返回 2 而非 1。
    n += 1
    viol = []
    for name in sorted(os.listdir(repair_dir)):
        if not name.endswith('.py'):
            continue
        for mod in _imports_of(os.path.join(repair_dir, name)):
            head = mod.split('.')[0]
            if head in FORBIDDEN_TARGETS:
                viol.append(f'{name} -> {mod}')
    if viol:
        bad.append('反向依赖上级模块（摘除时会连带崩）: ' + '; '.join(viol))

    # 隔离面或依赖已被破坏时，后续需要 import 的检查无法进行 —— 直接判失败。
    # 这是"发现硬伤"，不是"判不了"：缺陷已被确证，不该降级成无法判定。
    if any('反向依赖' in b or '隔离面' in b for b in bad):
        _fail(bad, 2)

    sys.path.insert(0, hub)
    try:
        import importlib
        engine = importlib.import_module('repair.engine')
    except Exception as e:
        _undetermined(f'repair.engine 导入失败: {type(e).__name__}: {e}')

    # ③ 校验器真能拦（喂非法值，看它拒）
    n += 1
    ok_base = {'schema_version': '1.0', 'target': 'x', 'strategy': 'patch',
               'status': 'repaired', 'attempts': 1, 'backup_path': '/tmp/x.bak'}
    try:
        if engine.validate(ok_base, 'repair_result.schema.json')[0] is not True:
            bad.append('合法样本被拒（校验器过严，正常产出无法落地）')
        for field, val in (('status', 'ok'), ('status', 'success'),
                           ('status', '修好了'), ('strategy', 'magic')):
            o = dict(ok_base); o[field] = val
            if engine.validate(o, 'repair_result.schema.json')[0]:
                bad.append(f'校验器漏放非法值 {field}={val!r}（假成功从这里进来）')
    except Exception as e:
        bad.append(f'validate 调用异常: {type(e).__name__}: {e}')

    # ③b checkup 三态域不得被放宽
    n += 1
    try:
        ck = {'schema_version': '1.0', 'target': 'x', 'kind': 'vod', 'verdict': '通过',
              'death_cause': '', 'repair_route': '', 'evidence': 'e',
              'checked_at': '2026-11-03T00:00:00Z'}
        if engine.validate(ck, 'checkup_report.schema.json')[0] is not True:
            bad.append('checkup 合法样本被拒')
        for badv in ('正常', 'dead', '挂了'):
            o = dict(ck); o['verdict'] = badv
            if engine.validate(o, 'checkup_report.schema.json')[0]:
                bad.append(f'checkup verdict 漏放 {badv!r}（三态被放宽）')
    except Exception as e:
        bad.append(f'checkup validate 异常: {type(e).__name__}: {e}')

    # ④ 防造假：repaired 但没备份 → 必须拒
    n += 1
    try:
        o = dict(ok_base)
        del o['backup_path']
        if engine.validate(o, 'repair_result.schema.json')[0]:
            bad.append('缺 backup_path 仍判通过（无回滚能力的 repaired 被放行）')
    except Exception as e:
        bad.append(f'防造假校验异常: {type(e).__name__}: {e}')

    # ⑤ 诚实自述：模块不得伪造"已具备修复能力"的自述常量
    n += 1
    try:
        src = open(os.path.join(repair_dir, 'engine.py'), encoding='utf-8').read()
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in ('CAN_REPAIR', 'REPAIR_CAPABLE'):
                        if isinstance(node.value, ast.Constant) and node.value.value is True:
                            bad.append(f'声称具备修复能力 {t.id}=True（须由实跑结果决定，不得硬编码）')
    except Exception as e:
        bad.append(f'engine.py 解析异常: {type(e).__name__}: {e}')

    if bad:
        _fail(bad, n)
    print(f'✓ M-R222 契约闸门通过（{n} 项：隔离面 / 无反向依赖 / 校验器能拦 / 防造假 / 诚实自述）')
    sys.exit(EXIT_PASS)


if __name__ == '__main__':
    main()
