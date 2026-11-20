#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hook_ledger.py —— 钩子自证账本查询入口（C 步）。

回答一个问题：**钩子装了，到底拦没拦过？** 不靠模型自报，读 hook_heartbeat
落的真账。三个视图：
  --summary   每钩拦了几次 / 调用几次 / 零计数的钩子（装了但从没拦过）
  --coverage  已注册钩子 vs 有账钩子 → 找出「装了但无计数器」的缺口
  --check     数据自洽（计数非负、hit 与 sessions 汇总一致、无串账）

诚实边界（B-02 三态）：账本只证「钩子自报拦过 N 次」，**不证拦得对**；
「拦得对不对」仍靠各钩判据 + verify/tests。把「拦过」说成「拦对」是折叠，
禁止。账本里没有任何记录 ≠ 没拦过，可能是没装/没接/路径错——coverage 区分。

用法：
  python3 verify/hook_ledger.py --summary
  python3 verify/hook_ledger.py --coverage
  python3 verify/hook_ledger.py --check
  python3 verify/hook_ledger.py --probe
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'hooks'))
import hook_heartbeat as hb


def _registered_scripts(root=REPO):
    """从 install.sh 的钩子复制清单提取「已装机脚本名」——复用 gate_scan 的同源事实。"""
    try:
        text = open(os.path.join(root, 'install.sh'), encoding='utf-8', errors='ignore').read()
    except OSError:
        return []
    import re
    # install.sh 里 cp "$ROOT/hooks/X.py" "$HOME/.codebuddy/hooks/X.py"
    scripts = set(re.findall(r'cp\s+"\$ROOT/hooks/([\w]+\.py)"', text))
    # hook_heartbeat.py 是账本库（被各钩 import），不是拦截钩，不参与"装了但拦没拦过"的覆盖判定
    scripts.discard('hook_heartbeat.py')
    return sorted(scripts)


def summary(state=None):
    hooks = hb.snapshot()
    rows = []
    for name in sorted(hooks):
        v = hooks[name]
        rows.append({
            'hook': name,
            'calls': int(v.get('calls', 0)),
            'blocked': int(v.get('blocked', 0)),
            'missed': int(v.get('missed', 0)),
            'sessions': len(v.get('sessions') or {}),
            'last_ts': v.get('last_ts', ''),
        })
    return {'rows': rows, 'total_blocked': sum(r['blocked'] for r in rows),
            'total_calls': sum(r['calls'] for r in rows)}


def coverage():
    reg = _registered_scripts()
    hooked = set(hb.snapshot().keys())
    with_ledger = sorted(r for r in reg if r in hooked)
    never_hit = sorted(r for r in with_ledger
                       if int((hb.snapshot().get(r) or {}).get('blocked', 0)) == 0)
    no_counter = sorted(r for r in reg if r not in hooked)
    return {'registered': reg, 'with_ledger': with_ledger,
            'never_hit': never_hit, 'no_counter': no_counter}


def check():
    """数据自洽校验：返回问题列表（空=自洽）。"""
    problems = []
    hooks = hb.snapshot()
    for name, v in hooks.items():
        calls = int(v.get('calls', 0))
        blocked = int(v.get('blocked', 0))
        missed = int(v.get('missed', 0))
        if calls < 0 or blocked < 0 or missed < 0:
            problems.append('%s: 出现负计数' % name)
        if int(v.get('blocked', 0)) > calls:
            problems.append('%s: blocked(%d) > calls(%d)' %
                            (name, v.get('blocked', 0), calls))
        # hit 与 sessions 汇总一致（有会话明细时）
        sess = v.get('sessions') or {}
        if sess:
            sb = sum(int(s.get('blocked', 0)) for s in sess.values())
            sc = sum(int(s.get('calls', 0)) for s in sess.values())
            if sb != int(v.get('blocked', 0)):
                problems.append('%s: sessions.blocked汇总(%d)≠全局(%d)' %
                                (name, sb, v.get('blocked', 0)))
            if sc != calls:
                problems.append('%s: sessions.calls汇总(%d)≠全局(%d)' %
                                (name, sc, calls))
    return problems


def probe():
    s = summary()
    c = coverage()
    problems = check()
    print(json.dumps({
        'probe': True,
        'via': 'hook_heartbeat.json',
        'hit': s['total_blocked'],
        'hooks_with_ledger': len(c['with_ledger']),
        'registered': len(c['registered']),
        'no_counter': c['no_counter'],
        'inconsistent': problems,
    }, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description='钩子自证账本查询')
    ap.add_argument('--summary', action='store_true')
    ap.add_argument('--coverage', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--probe', action='store_true')
    a = ap.parse_args()
    if a.summary:
        print(json.dumps(summary(), ensure_ascii=False, indent=2))
    elif a.coverage:
        print(json.dumps(coverage(), ensure_ascii=False, indent=2))
    elif a.check:
        p = check()
        print(json.dumps({'ok': not p, 'problems': p}, ensure_ascii=False))
        sys.exit(1 if p else 0)
    elif a.probe:
        probe()
    else:
        ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
