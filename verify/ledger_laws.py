#!/usr/bin/env python3
"""ledger_laws.py — 台账四律机检（旧生态 M-R75/82/86/93 → 520 判据化）

为什么要单列：这四条在旧生态是 DOC/SCAN 级"教训"，迁进 520 后若只写进 docs，
等于写了没人读——`docs/加载机制与可靠性.md` 已实测 **docs 不参与加载**。所以这里
只挑**能机检**的形态做成判据；检不了的（如"靠显式收口才能变绿"）留给人工复核与
`docs/通病台账.md`，不假装覆盖（B-02 三态不折叠）。

判据：
  L1 状态终态化（M-R75）：台账状态字段停在中间态（待查/未知/空）的比例是否过半。
     中间态 = 无人负责的悬空；过半即"这批账没人管"，不是风格问题。
  L2 指纹可对账（M-R82）：**已检查过**的条目是否留下稳定指纹。留了指纹，下次采集
     不到才能判"消失"；没有指纹，"采集器坏了"与"东西真没了"无法区分。
     阈值 90% 是**防恶化线**，不是达标线——当前实际值照实报出。
  L3 已结区幂等（M-R86）：已结/已归档区按业务主键不得重复。重复不是多一行，是
     账目数字本身失真。
  L4 退出码不驻全局（M-R93）：只覆盖两种可精确判定的形态——模块级可变退出码全局、
     `sys.exit(x or 0)`。其余形态（`except SystemExit: pass`）无法与"测试用例故意
     吞码"区分，**本判据不声称覆盖**，列人工复核清单。

用法: python3 verify/ledger_laws.py [--repo PATH]
退出: 0 全绿/仅有无法判定；1 有 ✗
"""
import json
import os
import re
import sys

MID_STATES = {'待查', '未知', '未定', 'pending', 'unknown', '?', '', None}
TARGETS = '能力层/tvbox/skills/probe-hub/scripts/monitor_targets.json'
SPACE_STATE = '通用层/skills/space-hub/scripts/space_hub_state.json'
FINGERPRINT_WARN_RATE = 0.90     # 防恶化线，非达标线
MID_STATE_MAX_RATE = 0.50

results = []


def rec(tag, mark, msg):
    results.append((tag, mark, msg))
    print(f'  {mark} [{tag}] {msg}')


def load(repo, rel):
    p = os.path.join(repo, rel)
    if not os.path.isfile(p):
        return None
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return False          # 存在但解析失败：三态里的"无法判定"


def l1_status_terminated(repo):
    """M-R75：状态字段必须落在终态枚举，禁长期中间态。"""
    d = load(repo, TARGETS)
    if d is None:
        rec('L1', '·', f'{TARGETS} 不存在——状态终态化无法判定（新机未采集时正常）')
        return
    if d is False:
        rec('L1', '·', f'{TARGETS} 解析失败——无法判定（不得当作通过）')
        return
    rows = d.get('targets') or []
    if not rows:
        rec('L1', '·', '监测册为空——无样本，无法判定')
        return
    bad = []
    for field in ('存活状态', '活跃度'):
        vals = [r.get(field) for r in rows if isinstance(r, dict)]
        if not vals:
            continue
        mid = sum(1 for v in vals if v in MID_STATES)
        rate = mid / len(vals)
        if rate > MID_STATE_MAX_RATE:
            bad.append(f'{field} 中间态 {mid}/{len(vals)}（{rate:.1%} > {MID_STATE_MAX_RATE:.0%}）')
        else:
            print(f'       · {field} 中间态 {mid}/{len(vals)}（{rate:.1%}，未过半）')
    if bad:
        rec('L1', '✗', '状态长期悬空（中间态过半 = 这批账无人负责）：' + '；'.join(bad))
    else:
        rec('L1', '✓', f'状态字段中间态未过半（{len(rows)} 条样本，阈值 {MID_STATE_MAX_RATE:.0%}）')


def l2_fingerprint(repo):
    """M-R82：检查过的条目必须留指纹，否则跨次对账失效。"""
    d = load(repo, TARGETS)
    if d is None or d is False:
        rec('L2', '·', f'{TARGETS} 缺失或不可解析——指纹对账无法判定')
        return
    rows = [r for r in (d.get('targets') or []) if isinstance(r, dict)]
    checked = [r for r in rows if r.get('上次检查')]
    if not checked:
        rec('L2', '·', '尚无已检查条目——指纹对账无法判定')
        return
    nofp = [r for r in checked if not r.get('内容指纹')]
    rate = len(nofp) / len(checked)
    if rate > FINGERPRINT_WARN_RATE:
        rec('L2', '✗', f'已检查条目无指纹 {len(nofp)}/{len(checked)}（{rate:.1%} > 防恶化线 '
                       f'{FINGERPRINT_WARN_RATE:.0%}）——"消失"与"采集器坏了"无法区分')
    else:
        rec('L2', '✓', f'已检查条目无指纹 {len(nofp)}/{len(checked)}（{rate:.1%}，未超防恶化线 '
                       f'{FINGERPRINT_WARN_RATE:.0%}；该项是防恶化线不是达标线，欠账另见通病台账）')


def l3_settled_idempotent(repo):
    """M-R86：已结区按业务主键不得重复。"""
    d = load(repo, SPACE_STATE)
    if d is None or d is False:
        rec('L3', '·', f'{SPACE_STATE} 缺失或不可解析——已结区幂等无法判定')
        return
    log = d.get('archive_log') or []
    if not log:
        rec('L3', '·', '已结区为空——无样本，无法判定')
        return
    seen, dup = {}, []
    for e in log:
        k = (e or {}).get('node_id')
        if not k:
            dup.append('<空键>')
            continue
        if k in seen:
            dup.append(k)
        seen[k] = True
    if dup:
        rec('L3', '✗', f'已结区重复 {len(dup)} 条（账目数字失真）：{", ".join(map(str, dup[:5]))}')
    else:
        rec('L3', '✓', f'已结区 {len(log)} 条按 node_id 唯一，无重复')


GLOBAL_RC_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=', re.M)
EXIT_OR_ZERO_RE = re.compile(r'sys\.exit\([^()\n]*\bor\s+0\s*\)')
SKIP_DIRS = ('.git', 'node_modules', '__pycache__', 'tests')


def _is_rc_global(name):
    """变量名是否"退出码全局"。按 `_` 分词精确判，不做子串匹配。

    首版写成 `_[A-Z0-9_]*RC[A-Z0-9_]*=`，把 `_SEARCH_BOX_TPL` 里的 SEA(RC)H 也算进去
    （误报 7 处，含 space_hub.py）。子串匹配是典型的"代理指标测错东西"（B-19），
    故改为分词后要求 RC 独立成段，或整名为 EXIT/EXIT_CODE。
    另外排除 `*_RE`（正则常量，如本文件的 GLOBAL_RC_RE）——否则检查器自指（病1）。
    """
    if name.endswith('_RE'):
        return False
    parts = [p for p in name.strip('_').split('_') if p]
    return 'RC' in parts or name.upper() in ('EXIT', 'EXIT_CODE', 'EXITCODE')


def _code_only(src):
    """剥离注释与字符串字面量后再匹配，**保留行结构**。

    两个坑都是实测踩出来的：
      ① 不剥离 → 判据文本里举的反例（docstring 中的 `sys.exit(x or 0)`）被自己抓住（病1 自指）。
      ② 剥离时用 `' '.join(...)` 拼成一行 → 行首锚点 `^` 失效，模块级赋值 `_RC = 0`
         因不在"行首"而漏判（C4 变异因此没翻红，判据形同虚设）。
    故按 token 的 start row 归行，再逐行拼接。
    """
    import io
    import tokenize
    rows = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            rows.setdefault(tok.start[0], []).append(tok.string)
    except Exception:
        return src                      # 无法 tokenize（语法错）→ 退回原文，不隐藏
    return '\n'.join(' '.join(rows[k]) for k in sorted(rows))


def l4_exit_code(repo):
    """M-R93：退出码判定唯一、有证据、不住在全局。"""
    hits = []
    for dp, dns, fns in os.walk(repo):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if not fn.endswith('.py'):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, repo).replace('\\', '/')
            try:
                t = _code_only(open(p, encoding='utf-8', errors='ignore').read())
            except Exception:
                continue
            for m in GLOBAL_RC_RE.finditer(t):
                if _is_rc_global(m.group(1)):
                    hits.append(f'{rel}: 模块级退出码全局 `{m.group(1)}`')
            for m in EXIT_OR_ZERO_RE.finditer(t):
                hits.append(f'{rel}: `{m.group(0)}`（None 会被当成 0=成功）')
    if hits:
        rec('L4', '✗', f'退出码判定不可靠 {len(hits)} 处：{hits[0]}'
                       + (f'（另 {len(hits)-1} 处）' if len(hits) > 1 else ''))
    else:
        rec('L4', '✓', '无模块级退出码全局、无 sys.exit(x or 0)（形态①②靠人工复核，本判据不声称全覆盖）')


def main():
    argv = sys.argv[1:]
    repo = '.'
    if '--repo' in argv:
        i = argv.index('--repo')
        repo = argv[i + 1] if i + 1 < len(argv) else '.'
    repo = os.path.abspath(repo)
    print(f'【台账四律】repo={repo}')
    l1_status_terminated(repo)
    l2_fingerprint(repo)
    l3_settled_idempotent(repo)
    l4_exit_code(repo)
    ok = sum(1 for _, m, _ in results if m == '✓')
    bad = sum(1 for _, m, _ in results if m == '✗')
    skip = sum(1 for _, m, _ in results if m == '·')
    print(f'\n结果：{ok} ✓ ｜ {bad} ✗ ｜ {skip} ·（无法判定）')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
