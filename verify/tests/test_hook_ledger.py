#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C 步测试：hook_ledger 四视图（summary/coverage/check/probe）+ 自洽有牙 + 隔离。

用例：
  A summary 汇总 calls/blocked/sessions，零计数钩保留
  B coverage 识别「装了但无计数器」和「有账但零拦截」
  C check 自洽：正常账本 ok；篡改造矛盾（blocked>calls / session汇总不符）→ 报红
  D probe 输出 hit/via/hooks_with_ledger/registered/inconsistent
  E 隔离：改 HOOK_HEARTBEAT_STATE 到临时，不读生产账本
  F 元变异：把 coverage 的 no_counter 判据改坏 → 缺口识别失效可见（测贴着实现）
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, 'verify'))
sys.path.insert(0, os.path.join(REPO, 'hooks'))

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('✓' if cond else '✗'), name, detail)


def write_ledger(path, hooks):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'hooks': hooks, 'updated': '2026-11-20 00:00:00'}, f, ensure_ascii=False)


def h(calls, blocked, missed=0, sessions=None):
    return {'calls': calls, 'blocked': blocked, 'missed': missed,
            'last_ts': '2026-11-20 00:00:00', 'sessions': sessions or {}}


with tempfile.TemporaryDirectory() as td:
    st = os.path.join(td, 'hb.json')
    os.environ['HOOK_HEARTBEAT_STATE'] = st
    hl = importlib.import_module('hook_ledger')

    # 从真实注册清单取一个名字造零拦截钩（never_hit 只认已注册+零拦截）
    reg_probe = hl.coverage()['registered']
    real_zero = next((r for r in reg_probe if r != 'guard_cmd.py'), 'parallel_guard.py')
    write_ledger(st, {
        'guard_cmd.py': h(10, 3, sessions={'s1': {'calls': 6, 'blocked': 2, 'missed': 0},
                                          's2': {'calls': 4, 'blocked': 1, 'missed': 0}}),
        real_zero: h(5, 0, sessions={'s3': {'calls': 5, 'blocked': 0, 'missed': 0}}),
    })

    # A summary
    s = hl.summary()
    by = {r['hook']: r for r in s['rows']}
    check('A1 两钩进汇总', len(s['rows']) == 2, str(len(s['rows'])))
    check('A2 calls/blocked 汇总', s['total_calls'] == 15 and s['total_blocked'] == 3,
          'calls=%d blocked=%d' % (s['total_calls'], s['total_blocked']))
    check('A3 零拦截钩保留', by[real_zero]['blocked'] == 0)
    check('A4 sessions 计数', by['guard_cmd.py']['sessions'] == 2)

    # B coverage
    c = hl.coverage()
    check('B1 已注册钩子非空', len(c['registered']) > 0, str(len(c['registered'])))
    check('B2 有账钩子识别', 'guard_cmd.py' in c['with_ledger'])
    check('B3 零拦截识别', real_zero in c['never_hit'], str(c['never_hit']))
    check('B4 无计数器缺口=注册但无账', all(r not in c['with_ledger'] for r in c['no_counter']))

    # C check 自洽
    check('C1 正常账本 ok', hl.check() == [], str(hl.check()))
    # 篡改1：blocked > calls
    write_ledger(st, {'bad.py': h(2, 5)})
    p = hl.check()
    check('C2 blocked>calls 报红', any('blocked' in x for x in p), str(p))
    # 篡改2：session 汇总与全局不符
    write_ledger(st, {'bad.py': h(4, 2, sessions={'s1': {'calls': 3, 'blocked': 1, 'missed': 0}})})
    p = hl.check()
    check('C3 session汇总不符报红', any('汇总' in x for x in p), str(p))
    # 篡改3：负计数
    write_ledger(st, {'bad.py': h(-1, 0)})
    p = hl.check()
    check('C4 负计数报红', any('负' in x for x in p), str(p))

    # D probe
    write_ledger(st, {'guard_cmd.py': h(8, 2)})
    out = subprocess.run([sys.executable, os.path.join(REPO, 'verify', 'hook_ledger.py'),
                          '--probe'], capture_output=True, text=True,
                         env=dict(os.environ))
    j = json.loads(out.stdout)
    check('D1 probe hit', j['hit'] == 2, str(j['hit']))
    check('D2 probe via', j['via'] == 'hook_heartbeat.json')
    check('D3 probe 结构', 'hooks_with_ledger' in j and 'registered' in j
          and 'inconsistent' in j)
    check('D4 probe 自洽', j['inconsistent'] == [])

    # E 隔离：换到空账本，不读生产
    st2 = os.path.join(td, 'empty.json')
    os.environ['HOOK_HEARTBEAT_STATE'] = st2
    hl2 = importlib.import_module('hook_ledger')  # 同模块，函数内每次 _load 读 env
    s2 = hl2.summary()
    check('E1 空账本零钩', s2['total_blocked'] == 0 and s2['rows'] == [], str(s2))
    os.environ['HOOK_HEARTBEAT_STATE'] = st  # 复原

    # F 元变异：把 coverage 的 no_counter 判据改坏 → 缺口识别失效
    src = open(os.path.join(REPO, 'verify', 'hook_ledger.py'), encoding='utf-8').read()
    mut = src.replace("no_counter = sorted(r for r in reg if r not in hooked)",
                      "no_counter = []  # 变异：永远报告无缺口", 1)
    assert mut != src, '变异点不存在'
    mp = os.path.join(td, 'mut_ledger.py')
    open(mp, 'w', encoding='utf-8').write(mut)
    # 用变异版覆盖 import：直接 exec 到独立命名空间
    ns = {'__file__': mp, '__name__': 'mut_ledger'}
    exec(compile(mut, mp, 'exec'), ns)
    write_ledger(st, {'guard_cmd.py': h(1, 1)})  # 大部分注册钩无账 → 应有缺口
    c_mut = ns['coverage']()
    c_real = hl.coverage()
    check('F1 真版识别缺口', len(c_real['no_counter']) > 0,
          '缺口=%d' % len(c_real['no_counter']))
    check('F2 变异版缺口消失（测贴着实现）', c_mut['no_counter'] == [])

print()
print('通过 %d / 失败 %d' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
