#!/usr/bin/env python3
"""v0.8.66 · M12 经验门接电闸（批1-①：闸建了没接电的修复）。

背景（2026-11-15 实查）：chk_contentflow（断流/账实脱节/复发超限/效果指标四判据）
此前只在巡检 run（模型自愿发起）时跑——闸建了，没接电。台账断流 11 版、
01-方法论欠账长期无人发现，正是这个缺口。本薄壳把它接进 verify.sh 必经链路。

三态（M-R60）：
  ✓ 绿/黄 —— chk_contentflow 返回 green（或 yellow 提示级：断路夹/复发超限属账面提醒，
              verify 不因黄阻断，与巡检语义一致；黄必须显式可见，不静默）
  ✗ 红    —— 返回 red（账实脱节过期/无源内容/复发超限按 M12 阈值）
  · 无法判定 —— 数据源损坏（不折叠成绿）

正向：账实一致+无新账缺 ref → 绿；反向：临时造缺 event_ref 回执 → 红（--selftest 内置双向）。
# impl: B-15 S5
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, '通用层', 'skills', 'inspect-hub', 'scripts'))


def check():
    from chk_landing import chk_contentflow          # noqa: E402（延迟导入，失败显式报）
    from inspect_hub import worst                    # noqa: E402
    ctx = {'thresholds': {}, 'worst': worst}
    worst_st = 'green'

    # ① 先探测：HEAD 变了才真扫（未变则零写盘零扰动），保证新 commit 必被探到
    try:
        sys.path.insert(0, os.path.join(REPO, 'verify'))
        from delivery_probe import scan as probe_scan, summary as debt_summary   # noqa: E402
        if os.environ.get('WB_PROBE_NO_SCAN') != '1':        # selftest 隔离：不污染真账本
            probe_scan(quiet=True)
        ds = debt_summary()
        red_age = 3
        try:
            import json as _j
            red_age = _j.load(open(os.path.join(REPO, 'verify', 'delivery_debt.json'),
                                   encoding='utf-8')).get('thresholds', {}).get('red_age_commits', 3)
        except Exception:
            pass
        if ds['open'] == 0:
            print(f"  ✓ [落库欠账] 0 条（已还 {ds['closed']} / 豁免 {ds['waived']}）")
        else:
            lvl = 'red' if ds['max_age'] > red_age else 'yellow'
            mark = '✗' if lvl == 'red' else '⚠'
            print(f"  {mark} [落库欠账] {ds['open']} 条未还（最老 {ds['max_age']} commit，阈值 {red_age}）")
            for it in ds['items'][:6]:
                print(f"       {it['id']}  龄 {it['age']}  {it['folder'].split('/')[-1]}"
                      f"  ← {it['commit']}  应为「{it['expect'][:28]}」")
            if len(ds['items']) > 6:
                print(f"       …另 {len(ds['items']) - 6} 条（--list 看全）")
            if lvl == 'red':
                worst_st = 'red'
    except Exception as ex:
        print(f"  · [落库欠账] 无法判定：探测器不可用（{str(ex)[:60]}）")
        worst_st = 'unknown'

    # ② 内容流四判据
    r = chk_contentflow(REPO, {'repo': REPO}, ctx)
    for it in r.get('items', []):
        mark = {'green': '✓', 'yellow': '⚠', 'red': '✗'}.get(it.get('s'), '·')
        print(f"  {mark} [{it.get('t')}] {it.get('e', '')[:90]}")

    sts = [worst_st, r.get('status')]
    if 'red' in sts:
        return 'red'
    if 'unknown' in sts:
        return 'unknown'
    return 'yellow' if 'yellow' in sts else 'green'


def _gate_selftest():
    """v0.8.73 闸化登记分支：五种后接形态 + 反例 + 端到端 green/yellow。

    隔离：独立临时 repo（造最小账本/计数/落点脚本），全程只读真仓、不写任何受管文件；
    gate_registry 经 ctx 注入判4（不碰 verify/病号映射表.json）。
    本轮病15 同型坑防御：识别 selftest 靠 ast 结构化节点，注释/docstring 造不出
    FunctionDef/Call → 天然排除；五种真实后接写法全覆盖，防止「只认精确锚点」漏判。
    """
    import json
    import shutil
    import tempfile
    from chk_landing import chk_contentflow, _selftest_landed   # noqa: E402（sys.path 模块顶已插）
    from inspect_hub import worst                                # noqa: E402
    fails = []
    ANCH = 'S233①'
    # ── A. 五种后接形态（应全 True）──
    forms = {
        '①def+SystemExit': "def selftest():\n    chk('S233①x', 1)\nif __name__=='__main__':\n    if '--selftest' in sys.argv:\n        raise SystemExit(selftest())\n",
        '②async+sys.exit': "import sys\nasync def selftest():\n    chk('S233①x', 1)\nif '--selftest' in sys.argv:\n    sys.exit(selftest())\n",
        '③方法/test_前缀': "class T:\n    def test_selftest(self):\n        chk('S233①x', 1)\nif '--selftest' in sys.argv:\n    T().test_selftest()\n",
        '④argparse开关': "import argparse\ndef selftest():\n    chk('S233①x', 1)\np=argparse.ArgumentParser(); p.add_argument('--selftest', action='store_true')\nselftest()\n",
        '⑤裸调用无argv': "def selftest():\n    chk('S233①x', 1)\nselftest()\n",
    }
    for k, v in forms.items():
        ok, why = _selftest_landed(v, ANCH)
        if not ok:
            fails.append(f'闸化·形态{k} 应 True：{why}')
    # ── B. 反例（应全 False；注释/docstring/空壳/未接电/锚点只在注释）──
    negs = {
        '纯注释def': "# def selftest():\n#     if '--selftest' in sys.argv: selftest()\n",
        'docstring字样': '"""def selftest(): --selftest S233①"""\nx=1\n',
        '无函数只有开关': "if '--selftest' in sys.argv:\n    print('S233①')\n",
        '空壳selftest': "def selftest():\n    pass\nif '--selftest' in sys.argv: selftest()\n",
        '有def无接电': "def selftest():\n    chk('S233①x', 1)\n",
        '锚点只在注释': "def selftest():\n    # S233①\n    chk('x', 1)\nif '--selftest' in sys.argv: selftest()\n",
    }
    for k, v in negs.items():
        ok, why = _selftest_landed(v, ANCH)
        if ok:
            fails.append(f'闸化·反例{k} 应 False（注释/docstring 不算落点）：{why}')
    # ── C. 端到端：有 gate→green / gate 指向不存在文件→仍 yellow / 无 gate→yellow ──
    tmp = tempfile.mkdtemp(prefix='exp_gate_')
    try:
        os.makedirs(os.path.join(tmp, 'verify'))
        json.dump({'entries': []}, open(os.path.join(tmp, 'archive_ledger.json'), 'w'))
        json.dump({'counters': {'病15': {'count': 7, 'status': 'active'}}, 'direction_cases': []},
                  open(os.path.join(tmp, 'experience_recurrence.json'), 'w'))
        json.dump({'flows': []}, open(os.path.join(tmp, 'verify', 'content_sources.json'), 'w'))
        open(os.path.join(tmp, '_gate_probe.py'), 'w', encoding='utf-8').write(forms['①def+SystemExit'])
        base = {'thresholds': {}, 'worst': worst}

        def item4(reg):
            r = chk_contentflow(tmp, {'repo': tmp}, dict(base, gate_registry=reg))
            return next((i for i in r['items'] if '经验复发' in i.get('t', '')), None)

        it = item4({'病15': {'script': '_gate_probe.py', 'anchor': ANCH}})
        if not it or it['s'] != 'green':
            fails.append(f'闸化·端到端 有 gate 应 green：{it}')
        it2 = item4({'病15': {'script': '__不存在__.py', 'anchor': ANCH}})
        if not it2 or it2['s'] != 'yellow':
            fails.append(f'闸化·端到端 gate 指向不存在文件应仍 yellow：{it2}')
        it3 = item4({})
        if not it3 or it3['s'] != 'yellow':
            fails.append(f'闸化·端到端 无 gate 登记应 yellow：{it3}')
        print(f"  selftest[闸化]: 形态{len(forms)}/反例{len(negs)} "
              f"端到端 green={it['s'] if it else 'None'} "
              f"不存在文件={it2['s'] if it2 else 'None'} 无登记={it3['s'] if it3 else 'None'}")
        # ── D. 多病号混合（v0.8.74 B-15 同类排查）：部分有 gate/部分无 → 只对无 gate 的 hot 报 yellow ──
        #   含 retired 非 hot 病号，断言不被误伤；正反向：补一个 gate / 撤一个 gate，计数恰变。
        mixed = {
            '病15': {'count': 7, 'status': 'active'},     # 有 gate（应 gated）
            '病10': {'count': 5, 'status': 'active'},     # 无 gate（应 ungated）
            '病1':  {'count': 4, 'status': 'active'},     # 无 gate（应 ungated）
            '病11': {'count': 3, 'status': 'retired'},    # 非 hot（不应出现在明细）
        }
        json.dump({'counters': mixed, 'direction_cases': []},
                  open(os.path.join(tmp, 'experience_recurrence.json'), 'w'))
        g_ok = {'script': '_gate_probe.py', 'anchor': ANCH}   # 合成环境复用同一落点，仅验判4 分流逻辑
        itA = item4({'病15': g_ok})
        if not itA or itA['s'] != 'yellow' or '2 病号' not in itA['t'] \
                or '病10×' not in itA['e'] or '病1×' not in itA['e'] \
                or '病15' in itA['e'] or '病11' in itA['e']:
            fails.append(f'闸化·混合A 应仅对病10/病1 报 yellow：{itA}')
        itB = item4({'病15': g_ok, '病10': g_ok})            # 补一个 gate → 只剩病1
        if not itB or itB['s'] != 'yellow' or '1 病号' not in itB['t'] \
                or '病10×' in itB['e'] or '病1×' not in itB['e']:
            fails.append(f'闸化·混合B 补 gate 后应只剩病1：{itB}')
        itC = item4({'病15': {'script': '__不存在__.py', 'anchor': ANCH}, '病10': g_ok})
        if not itC or itC['s'] != 'yellow' or '2 病号' not in itC['t'] or '病15×' not in itC['e']:
            fails.append(f'闸化·混合C 登记未落地应回到 ungated：{itC}')
        itD = item4({'病15': g_ok, '病10': g_ok, '病1': g_ok})   # 全有 → green
        if not itD or itD['s'] != 'green':
            fails.append(f'闸化·混合D 全登记应 green：{itD}')
        print(f"  selftest[闸化·混合]: A={itA['s'] if itA else 'None'} "
              f"B={itB['s'] if itB else 'None'} C={itC['s'] if itC else 'None'} "
              f"D={itD['s'] if itD else 'None'}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


# ──────────────────────── W8-B2 晋升环（self-improving-agent 的「晋升」一步） ────────────────────────
# 复用现成链路：记录(exp_distill)→复发计数(guard_cmd --bump)→复查(chk_landing 判4 hot) 已在跑，
# 唯一悬空环 = 「hot 到顶→立项」。本段补的就是这一步：复发病号达标 → 真生成一个带真实教训内容的
# 技能骨架（不是官方 init_skill 的空模板），并用 skill_contract_check 的同款判据自检生成物。
# 边界：只生成「晋升候选」到指定 out 目录，不自动进仓登记/MANIFEST/镜像——纳入哪一个是价值判断，由用户拍板。
import hashlib as _hashlib
import re as _re

PROMOTE_ANCHOR = 'S-PROMOTE①'
# 门槛取 3：规则48「复发≥3次立项」+ chk_landing.py:383 hot 判定（count>=3）同源，不另立标准。
PROMOTE_MIN = 3

# 运行时真源：与 exp_probe.py:29-42 同口径（用户级优先、仓内种子兜底、支持隔离）。
# 经验闭环步骤3/5 已把账本真源搬到用户级；promote/list 若只读仓内种子（count=16）
# 会与真账本（count=17）分叉——判据对象≠记账真源（病15）。故统一走 _live_rec。
_EXP_HOME = os.environ.get('CODEBUDDY_EXP_HOME') or os.path.join(
    os.path.expanduser('~'), '.codebuddy', 'experience')


def _live_rec(seed=None):
    """账本路径：用户级存在则用用户级，否则回退仓内种子（与 exp_probe._live_path 同款）。"""
    seed = seed or os.path.join(REPO, 'experience_recurrence.json')
    live = os.path.join(_EXP_HOME, os.path.basename(seed))
    if os.path.isfile(live):
        return live
    return seed


def _slug(exp_id):
    """病号/经验 id → 合法 ASCII 目录名（中文 id 用短 hash 保唯一，来源写进正文）。"""
    stem = _re.sub(r'[^a-z0-9]+', '-', str(exp_id).lower()).strip('-')
    if not stem or _re.search(r'[^\x00-\x7f]', str(exp_id)):
        stem = 'bug-' + _hashlib.md5(str(exp_id).encode('utf-8')).hexdigest()[:8]
    return 'exp-' + stem


def _promote_skill_check(skill_dir):
    """用 skill_contract_check 的同款判据常量自检生成物（真过机检，不自造正则）。
    返回 (ok, bad_list)：复用 DESC_RULES / SELF_CHECK / SEMVER / fm_get 判 C1/C2/C3 核心。"""
    import json as _j
    base_ok, bad = True, []
    root = os.path.abspath(skill_dir)
    sk = os.path.join(root, 'SKILL.md')
    cl = os.path.join(root, 'CHANGELOG.md')
    entry = os.path.join(root, 'scripts', os.path.basename(root) + '.py')
    # C1 结构：SKILL.md + CHANGELOG + 正门脚本
    for f in (sk, cl, entry):
        if not os.path.isfile(f):
            bad.append(f'C1 缺 {os.path.relpath(f, root)}')
    if not os.path.isfile(sk):
        return False, bad
    text = open(sk, encoding='utf-8').read()
    # 复用真源解析 front matter
    sys.path.insert(0, os.path.join(REPO, 'verify'))
    from skill_contract_check import DESC_RULES, SELF_CHECK, SEMVER, fm_get, front_matter  # noqa: E402
    fm = front_matter(text)
    name = fm_get(fm, 'name') or ''
    ver = fm_get(fm, 'version') or ''
    desc = fm_get(fm, 'description') or ''
    body = text.split('---', 2)[-1]
    if name != os.path.basename(root):
        bad.append(f'C2 name={name!r} != 目录名 {os.path.basename(root)!r}')
    if not SEMVER.search(ver):
        bad.append(f'C2 version={ver!r} 非 semver')
    if len(desc) < 40:
        bad.append(f'C2 description 仅 {len(desc)} 字')
    for tag, pat, why in DESC_RULES:
        if not _re.search(pat, desc):
            bad.append(f'{tag} 缺（{why}）')
    if not _re.search(SELF_CHECK, body):
        bad.append('D4 自省锚点缺')
    # C4 局部：CHANGELOG 首条版本 == SKILL.md version
    if os.path.isfile(cl):
        m = _re.search(r'^## v?(\d+\.\d+\.\d+)', open(cl, encoding='utf-8').read(), _re.M)
        if not m or m.group(1) != ver.lstrip('v'):
            bad.append('C4 CHANGELOG 首条版本 != SKILL.md')
    return (not bad), bad


def promote(exp_id, out_root, rec_data=None, repo=None):
    """晋升候选：复发病号达标 → 生成带真实教训的技能骨架到 out_root/<slug>/。
    返回 dict：{ok, reason, dir, check, source}。纯写 out_root，不碰真仓受管文件。
    门槛：count>=PROMOTE_MIN 且 status!=retired；否则 no-op（拒绝生成）。"""
    repo = repo or REPO
    if rec_data is None:
        import json as _json
        # 用户级优先（真源），仓内种子兜底；selftest 显式传 rec_data 绕开此路径。
        rec_data = _json.load(open(_live_rec(os.path.join(repo, 'experience_recurrence.json')),
                                   encoding='utf-8'))
    counters = (rec_data or {}).get('counters', {})
    ent = counters.get(exp_id)
    if ent is None:
        return {'ok': False, 'reason': f'{exp_id} 不在复发计数表（无据可晋升）', 'dir': None}
    cnt = int(ent.get('count', 0))
    status = ent.get('status', 'active')
    if status == 'retired':
        return {'ok': False, 'reason': f'{exp_id} 已 retired（退役经验不晋升）', 'dir': None}
    if cnt < PROMOTE_MIN:
        return {'ok': False, 'reason': f'{exp_id} count={cnt}<{PROMOTE_MIN}（未达复发门槛）', 'dir': None}

    name = _slug(exp_id)
    out = os.path.join(os.path.abspath(out_root), name)
    if os.path.exists(out):
        return {'ok': False, 'reason': f'{out} 已存在（防覆盖：晋升不覆盖已有技能）', 'dir': None}
    os.makedirs(os.path.join(out, 'scripts'), exist_ok=False)

    # ── 真实教训内容（非空架子）：来自 note / events / 关联 exp_entries ──
    note = ent.get('note', '') or ''
    events = ent.get('events', []) or []
    src_lines = [f'- {e.get("ts", "?")} · {e.get("coord", e.get("case", ""))}' for e in events[:8]]
    evid = []
    for x in (rec_data or {}).get('exp_entries', []):
        if exp_id in str(x.get('text', '')) or exp_id in str(x.get('id', '')):
            evid.append(f'- `{x.get("source_commit", "?")}` {x.get("text", "")[:160]}')
    if not evid:
        evid = [f'- 复发计数表 note：{note}'] if note else ['- （该病号暂无结构化 lesson，仅有计数事件）']

    desc = (f'当用户反馈同类问题反复复发、要把经验晋升成可执行技能时用。'
            f'能力①：从复发计数生成带真实教训的技能骨架；②：正门自检生成物是否为空架子；'
            f'③：复发未达阈值或已退役时拒绝生成。正门 scripts/{name}.py --promote。'
            f'使用前先读判据，不要用于未达阈值或已退役的经验——边界：只产出晋升候选，不自动进仓登记。')
    ver = '0.1.0'
    today = __import__('datetime').date.today().isoformat()
    skill_md = f'''---
name: {name}
version: {ver}
description: {desc}
---

# {exp_id} · 晋升候选（复发≥{PROMOTE_MIN}次）

> 本技能由经验门晋升环自动生成，**带真实教训内容**（非官方脚手架空模板）。
> 晋升来源：`experience_recurrence.json` → `counters.{exp_id}`，count={cnt}，status={status}，生成于 {today}。

## 何时用我
当用户遇到同类问题反复复发，需要把「踩坑记录」晋升为可复用判据/技能时。

## 能力清单
① 复发病号 → 生成带真实教训的技能骨架（本文件即产物）；
② 生成物经 `skill_contract_check` 同款判据自检（{PROMOTE_ANCHOR}），不是空架子；
③ 未达 {PROMOTE_MIN} 次 / 已 retired / 已存在 → 拒绝生成（no-op，防覆盖）。

## 真实教训（晋升依据）
**计数备注**：{note or '（无）'}

**复发事件**：
{chr(10).join(src_lines) or '（无事件明细）'}

**关联经验条目**：
{chr(10).join(evid)}

## 正门与自省
正门：`python3 scripts/{name}.py --promote` 回放晋升来源；`--selftest` 自检骨架完整。
**先读判据，不许直接跑**：产物落点目录须经自检为空架子红灯时不得纳入正式技能体系。

## 边界
不要用于未达 {PROMOTE_MIN} 次或已退役的经验；本环只生成「晋升候选」，不自动改 MANIFEST/skill_contracts、不同步安装副本——是否正式纳入由用户拍板。
'''
    open(os.path.join(out, 'SKILL.md'), 'w', encoding='utf-8').write(skill_md)
    open(os.path.join(out, 'CHANGELOG.md'), 'w', encoding='utf-8').write(
        f'# {name} · CHANGELOG\n\n## v{ver} — {today}\n\n- 晋升环自动生成（{exp_id} count={cnt}），含真实教训 {len(events)} 事件 / {len(evid)} 条关联经验。\n')
    gate_py = f'''#!/usr/bin/env python3
# {PROMOTE_ANCHOR} 晋升候选正门（自检锚点）
import sys
SOURCE = {{
    'exp_id': {exp_id!r}, 'count': {cnt}, 'status': {status!r},
    'events': {len(events)}, 'evidence': {len(evid)}, 'generated': {today!r},
}}
def selftest():
    ok = SOURCE['count'] >= {PROMOTE_MIN} and SOURCE['status'] != 'retired' and SOURCE['events'] >= 0
    print('  ' + ('✓' if ok else '✗') + f' 晋升来源自洽: {{SOURCE}}')
    return 0 if ok else 1
if __name__ == '__main__':
    if '--selftest' in sys.argv:
        raise SystemExit(selftest())
    print('晋升候选正门（' + {PROMOTE_ANCHOR!r} + '）: ' + str(SOURCE))
'''
    p = os.path.join(out, 'scripts', name + '.py')
    open(p, 'w', encoding='utf-8').write(gate_py)
    os.chmod(p, 0o755)
    open(os.path.join(out, 'trigger-samples.md'), 'w', encoding='utf-8').write(
        f'# 触发样本（{name}）\n\n- **T（应触发）**：同类问题又复发了，把踩坑记录晋升成技能\n'
        f'- **N（不触发）**：{exp_id} 已退役或只出现一次的经验\n'
        f'- **B（边界）**：没到 {PROMOTE_MIN} 次的经验，拒绝生成\n')
    ok, bad = _promote_skill_check(out)
    return {'ok': ok, 'reason': '生成晋升候选' if ok else '生成物自检未过', 'dir': out,
            'check': {'ok': ok, 'bad': bad},
            'source': {'exp_id': exp_id, 'count': cnt, 'status': status,
                       'events': len(events), 'evidence': len(evid)}}


def list_promotable(rec_data=None, repo=None):
    """达标可晋升病号清单 + 可复制粘贴区（仿 手机指令.md:9/63 形态）。

    三态（不折叠）：
      ready   —— 有达标病号，block 含粘贴区与逐条晋升命令（粘到会话即可触发 --promote）
      empty   —— 账本可读但无达标（诚实报无，不伪造候选）
      unknown —— 账本损坏/不可读（无法判定，不折叠成 empty）
    读用户级真源（_live_rec），门槛复用 PROMOTE_MIN，不另立阈值/不读仓内种子假装真账。
    """
    import json as _json
    if rec_data is None:
        try:
            rec_data = _json.load(open(_live_rec(os.path.join(repo or REPO,
                                                              'experience_recurrence.json')),
                                       encoding='utf-8'))
        except Exception as e:
            return {'state': 'unknown', 'items': [], 'block': '',
                    'reason': f'账本不可读（无法判定）：{e}'}
    try:
        counters = (rec_data or {}).get('counters', {})
        if not isinstance(counters, dict):
            return {'state': 'unknown', 'items': [], 'block': '',
                    'reason': 'counters 非 dict（账本损坏，无法判定）'}
        items = []
        for k, v in counters.items():
            if not isinstance(v, dict):
                return {'state': 'unknown', 'items': [], 'block': '',
                        'reason': f'counters.{k} 非 dict（账本损坏，无法判定）'}
            cnt = v.get('count', 0)
            st = v.get('status', 'active')
            try:
                cnt = int(cnt)
            except (TypeError, ValueError):
                return {'state': 'unknown', 'items': [], 'block': '',
                        'reason': f'counters.{k}.count={cnt!r} 非整数（无法判定）'}
            if cnt >= PROMOTE_MIN and st != 'retired':
                items.append({'id': k, 'count': cnt, 'status': st,
                              'note': v.get('note', '') or ''})
    except Exception as e:
        return {'state': 'unknown', 'items': [], 'block': '',
                'reason': f'账本结构异常（无法判定）：{e}'}
    items.sort(key=lambda x: (-x['count'], str(x['id'])))
    if not items:
        return {'state': 'empty', 'items': [], 'block': '',
                'reason': f'当前无达标病号（门槛 count>={PROMOTE_MIN} 且未退役）'}
    lines = ['## 【粘贴区 · 从下一行开始复制】', '',
             f'当前有 {len(items)} 个病号达标（复发≥{PROMOTE_MIN}次且未退役），'
             '可晋升为技能。复制本块粘贴到会话，逐条执行里面的晋升命令：', '']
    for x in items:
        lines.append(f'- **{x["id"]}** · 复发 {x["count"]} 次 · {x["status"]}')
        lines.append(f'  - 晋升：`python3 verify/gate_experience.py --promote "{x["id"]}" '
                     f'--out "产物/晋升候选"`')
    lines += ['', '生成的是「晋升候选」（不自动进仓/不登记/不装机），是否纳入由我拍板。', '',
              '**【粘贴区 结束】**']
    return {'state': 'ready', 'items': items, 'block': '\n'.join(lines),
            'reason': f'{len(items)} 个病号达标'}


def _promote_selftest():
    """正反向验证：达标真生成可过检技能 / 未达标·退役·不存在·已存在全 no-op / 篡改生成物自检必红。"""
    import shutil
    import tempfile
    fails = []
    tmp = tempfile.mkdtemp(prefix='promote_')
    fixture = {
        'counters': {
            '病测A': {'count': 3, 'status': 'active', 'note': '同型坑三度复发',
                     'events': [{'ts': 'd1', 'coord': '首次'}, {'ts': 'd2', 'coord': '复发'},
                                {'ts': 'd3', 'coord': '再复发'}]},
            '病测B': {'count': 1, 'status': 'active', 'note': '仅一次'},
            '病测C': {'count': 9, 'status': 'retired', 'note': '已退役'},
        },
        'exp_entries': [{'id': 'EXP-t1', 'source_commit': 'abc1234',
                         'text': '病测A：判据识别范围宽于对象范围，改为锚定起始位'}],
    }
    try:
        # 正向：count=3 active → 真生成 + 自检绿 + 含真实教训
        r = promote('病测A', tmp, rec_data=fixture, repo=tmp)
        if not r['ok'] or not r.get('check', {}).get('ok'):
            fails.append(f'正向 病测A 应生成且自检绿：{r}')
        else:
            body = open(os.path.join(r['dir'], 'SKILL.md'), encoding='utf-8').read()
            if '同型坑三度复发' not in body or 'abc1234' not in body:
                fails.append('正向 生成物缺真实教训（note/commit 未落地→空架子）')
            if not os.path.isfile(os.path.join(r['dir'], 'scripts', os.path.basename(r['dir']) + '.py')):
                fails.append('正向 生成物缺可跑正门脚本')
        # 反向1：count=1 → 拒绝
        r2 = promote('病测B', tmp, rec_data=fixture, repo=tmp)
        if r2['ok'] or '未达' not in r2['reason']:
            fails.append(f'反向1 count=1 应拒绝：{r2}')
        # 反向2：retired → 拒绝
        r3 = promote('病测C', tmp, rec_data=fixture, repo=tmp)
        if r3['ok'] or 'retired' not in r3['reason']:
            fails.append(f'反向2 已退役应拒绝：{r3}')
        # 反向3：不存在的 id → 拒绝
        r4 = promote('病测X', tmp, rec_data=fixture, repo=tmp)
        if r4['ok'] or '不在' not in r4['reason']:
            fails.append(f'反向3 不存在 id 应拒绝：{r4}')
        # 反向4：已存在 → 防覆盖拒绝
        r5 = promote('病测A', tmp, rec_data=fixture, repo=tmp)
        if r5['ok'] or '已存在' not in r5['reason']:
            fails.append(f'反向4 已存在应防覆盖：{r5}')
        # 反向5：篡改生成物描述五组 → 自检必红（证明自检不是摆设）
        if not r.get('check', {}).get('ok'):
            fails.append('反向5 前置失败：正向生成物自检未绿，无法验篡改')
        else:
            sk = os.path.join(r['dir'], 'SKILL.md')
            s = open(sk, encoding='utf-8').read()
            # 用五组锚点全不命中的描述替换 front matter description（保留 name/version 不动，只测描述五组判据）
            s = _re.sub(r'(?m)^description:.*$', 'description: 一句话占位没有任何触发声明也没有能力枚举没有正门没有自省也没有边界约束文字足够长', s, count=1)
            open(sk, 'w', encoding='utf-8').write(s)
            ok2, bad2 = _promote_skill_check(r['dir'])
            if ok2:
                fails.append(f'反向5 篡改五组后自检仍绿——自检是摆设（bad={bad2}）')
        print(f'  selftest[晋升]: 正向生成={r.get("ok")} 自检={r.get("check", {}).get("ok")} '
              f'拒绝4例={not r2["ok"] and not r3["ok"] and not r4["ok"] and not r5["ok"]} 篡改必红=✓')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


def _list_selftest():
    """--list 三态 + 用户级优先。CODEBUDDY_EXP_HOME mock 隔离，临时 monkeypatch
    模块级 _EXP_HOME（步骤5坑：不 monkeypatch 会让真函数读到默认用户级账本→假绿）。"""
    import json as _j
    import tempfile
    import shutil
    fails = []
    tmp = tempfile.mkdtemp(prefix='listp_')
    old_home = _EXP_HOME
    fixture = {'counters': {
        '病甲': {'count': 17, 'status': 'active', 'note': '判据对象分叉'},
        '病乙': {'count': 3, 'status': 'active'},
        '病丙': {'count': 9, 'status': 'retired'},
        '病丁': {'count': 1, 'status': 'active'},
    }}
    try:
        # ① ready：达标病号=病甲+病乙（病丙退役/病丁未达排除）
        r = list_promotable(rec_data=fixture)
        ids = [x['id'] for x in r['items']]
        if r['state'] != 'ready' or set(ids) != {'病甲', '病乙'}:
            fails.append(f'① ready 应含甲/乙排除丙/丁：{r["state"]}/{ids}')
        # ② 粘贴区形态：标题+结束标记+逐条晋升命令（真可复制块，非空话）
        if ('## 【粘贴区 · 从下一行开始复制】' not in r['block']
                or '**【粘贴区 结束】**' not in r['block']
                or '--promote "病甲"' not in r['block']
                or '--promote "病乙"' not in r['block']):
            fails.append('② 粘贴块缺标记或晋升命令')
        # ③ 排序：count 高的在前（病甲 17 > 病乙 3）
        if ids and ids[0] != '病甲':
            fails.append(f'③ 应按 count 降序：{ids}')
        # ④ empty：全不达标 → 诚实报无，不伪造
        r2 = list_promotable(rec_data={'counters': {'病丁': {'count': 1, 'status': 'active'}}})
        if r2['state'] != 'empty' or r2['items'] or r2['block']:
            fails.append(f'④ 无达标应 empty：{r2["state"]}/{r2["items"]}')
        # ⑤ unknown：账本损坏（counters 非 dict）→ 无法判定，不折叠 empty
        r3 = list_promotable(rec_data={'counters': []})
        if r3['state'] != 'unknown':
            fails.append(f'⑤ 损坏应 unknown：{r3["state"]}')
        # ⑥ 用户级优先（真函数读文件）：模块级 _EXP_HOME 指向 tmp，用户级写 count=17，
        #    仓内种子写 count=1 → 必须读用户级（病15 对象范围=真账本而非种子）
        globals()['_EXP_HOME'] = tmp
        _j.dump({'counters': {'病真实': {'count': 17, 'status': 'active'}}},
                open(os.path.join(tmp, 'experience_recurrence.json'), 'w', encoding='utf-8'),
                ensure_ascii=False)
        r4 = list_promotable(repo=tmp)  # seed=tmp/experience_recurrence.json 与 live 同名→live 优先
        if r4['state'] != 'ready' or [x['id'] for x in r4['items']] != ['病真实']:
            fails.append(f'⑥ 应读用户级真账本：{r4["state"]}/{r4["items"]}')
        print(f'  selftest[list]: 三态={r["state"]}/{r2["state"]}/{r3["state"]} '
              f'达标={ids} 粘贴块=✓ 用户级优先=✓')
    finally:
        globals()['_EXP_HOME'] = old_home
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


def selftest():
    """正反向：红/黄/绿三态在真数据上现形；反向靠临时构造缺 ref 回执。
    v0.8.73 追加闸化登记分支（_gate_selftest）：五种形态/反例/端到端 green-yellow。
    W8-B2 追加晋升环（_promote_selftest）：达标真生成 / 四类拒绝 / 篡改必红。"""
    import json
    import shutil
    import tempfile
    led = os.path.join(REPO, 'archive_ledger.json')
    bak = tempfile.mktemp()
    shutil.copy(led, bak)
    fails = []
    try:
        # 闸化登记分支（独立临时 repo，不碰真账本，放在造违例之前）
        fails += _gate_selftest()
        # W8-B2 晋升环正反验证（独立临时目录，不碰真账本）
        fails += _promote_selftest()
        # 新需求：--list 达标清单三态 + 用户级优先（独立临时目录）
        fails += _list_selftest()
        # 正向：真数据跑一遍，应可判定（green/yellow 都算通过，red 算违例——当前真数据应无 red）
        st = check()
        if st in ('red',):
            fails.append(f'正向：真数据出现 red（{st}）——先清真账再谈闸')
        # 反向：造一条 result=ok 且缺 event_ref、非 legacy round 的新账 → 应 red
        d = json.load(open(led, encoding='utf-8'))
        rows = d if isinstance(d, list) else d.get('entries', [])
        rows.append({'ts': '2026-11-15T99:99:99', 'round': 'selftest-bad', 'artifact': 'x',
                     'target': '🧬 520进化论/05-复盘与判例', 'result': 'ok', 'event_ref': '', 'note': 'selftest'})
        json.dump(d, open(led, 'w'), ensure_ascii=False, indent=1)
        st2 = check()
        if st2 != 'red':
            fails.append(f'反向：造缺 ref 新账后仍 {st2}——闸抓不住无源内容')
        print(f"  selftest: 正向={st} 反向={st2}")
    finally:
        shutil.copy(bak, led)
        os.remove(bak)
    if fails:
        for f in fails:
            print(f'  ✗ {f}')
        return 1
    print('  ✓ 正反向全通过（闸化五形态+反例+端到端 green/yellow；真数据绿/黄、造违例即红）')
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    if '--list' in sys.argv:
        # 达标清单：python3 gate_experience.py --list
        # 输出可复制粘贴区（仿手机指令.md），粘到会话即可逐条触发 --promote。
        import json as _json
        res = list_promotable()
        print(_json.dumps({'state': res['state'], 'items': res['items'],
                           'reason': res['reason']}, ensure_ascii=False, indent=1))
        if res['block']:
            print()
            print(res['block'])
        sys.exit(1 if res['state'] == 'unknown' else 0)
    if '--promote' in sys.argv:
        # 晋升候选：python3 gate_experience.py --promote <病号id> --out <目录>
        import json as _json
        i = sys.argv.index('--promote')
        eid = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        oi = sys.argv.index('--out') if '--out' in sys.argv else -1
        out = sys.argv[oi + 1] if oi >= 0 else os.path.join(REPO, '产物', '晋升候选')
        if not eid:
            print('用法：--promote <病号id> [--out <目录>]'); sys.exit(2)
        res = promote(eid, out)
        print(_json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(0 if res['ok'] else 1)
    st = check()
    print(f"[experience-gate] M12 经验门状态: {st}")
    sys.exit(1 if st == 'red' else 0)
