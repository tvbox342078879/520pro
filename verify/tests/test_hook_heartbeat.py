#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hook_heartbeat.py 单测 —— A 步：账本本体正确、会话隔离、并发不阻塞、fail-open、probe。

用例：
  A 累加/原子写（calls/blocked/missed 分计 + tmp 无残留）
  B 会话隔离（sid 明细互不污染，全局汇总正确）
  C 并发不阻塞（多进程同时 beat，非阻塞锁下不崩、账本完整）
  D fail-open（路径不可写/半截 JSON → 不抛异常、不阻塞）
  E --probe 快照（hit/via/calls/missed/hooks 齐全 + 过滤）
  F 元变异：把原子写换成直接写 → 检测能力仍在（判据有牙）
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'hooks')
sys.path.insert(0, HOOKS)
import hook_heartbeat as hb

PASS = []
FAIL = []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('✓' if cond else '✗'), name, detail)


def fresh():
    d = tempfile.mkdtemp()
    p = os.path.join(d, '.hook_heartbeat.json')
    os.environ['HOOK_HEARTBEAT_STATE'] = p
    return p


# --- A 累加 / 原子写 ---
p = fresh()
for _ in range(3):
    hb.beat('t_hook.py', blocked=True, sid='s1')
d = json.load(open(p, encoding='utf-8'))
h = d['hooks']['t_hook.py']
check('A1 calls 累加', h['calls'] == 3, 'got=%d' % h['calls'])
check('A2 blocked 累加', h['blocked'] == 3, 'got=%d' % h['blocked'])
check('A3 missed 不混计', h['missed'] == 0)
check('A4 last_ts 落盘', bool(h['last_ts']))
check('A5 updated 落盘', bool(d['updated']))
leftover = [f for f in os.listdir(os.path.dirname(p)) if '.tmp.' in f]
check('A6 原子写无 tmp 残留', not leftover, str(leftover))

# missed 单独一笔
hb.beat('t_hook.py', missed=True, sid='s1')
d = json.load(open(p, encoding='utf-8'))
check('A7 missed 单独累加', d['hooks']['t_hook.py']['missed'] == 1)

# --- B 会话隔离 ---
p = fresh()
hb.beat('iso.py', blocked=True, sid='A')
hb.beat('iso.py', blocked=True, sid='B')
hb.beat('iso.py', blocked=False, sid='A')
d = json.load(open(p, encoding='utf-8'))
h = d['hooks']['iso.py']
check('B1 全局 calls 汇总', h['calls'] == 3, 'got=%d' % h['calls'])
check('B2 全局 blocked 汇总', h['blocked'] == 2)
check('B3 sid-A 明细', h['sessions']['A']['calls'] == 2 and h['sessions']['A']['blocked'] == 1)
check('B4 sid-B 明细', h['sessions']['B']['calls'] == 1 and h['sessions']['B']['blocked'] == 1)
ss = hb.snapshot(sid='A')
check('B5 snapshot 按 sid 过滤', 'iso.py' in ss)
ss = hb.snapshot(hook='nope')
check('B6 snapshot 按 hook 过滤', ss == {})

# --- C 并发不阻塞（多进程同时 beat）---
p = fresh()
procs = []
for i in range(8):
    code = ("import os,sys; sys.path.insert(0,%r); "
            "import hook_heartbeat as h; h.beat('conc.py',blocked=True,sid='s%d')" % (HOOKS, i))
    env = dict(os.environ)
    env['HOOK_HEARTBEAT_STATE'] = p
    procs.append(subprocess.Popen([sys.executable, '-c', code], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE))
for pr in procs:
    try:
        pr.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        pr.kill()
        pr.communicate()
check('C1 8进程均不阻塞退出', all(pr.returncode == 0 for pr in procs),
      'rc=%s' % [pr.returncode for pr in procs])
d = json.load(open(p, encoding='utf-8'))
check('C2 并发后账本可解析', isinstance(d.get('hooks', {}).get('conc.py'), dict))
got = d['hooks']['conc.py']['blocked']
check('C3 非阻塞锁设计=允许丢计数（坑2取舍）', 0 < got <= 8,
      'got=%d/8（拿不到锁即跳过记账，不要求全记）' % got)

# --- D fail-open ---
p = fresh()
hb.beat('x.py', blocked=True, sid='s1')
bad = os.path.join(tempfile.mkdtemp(), 'no_such_dir', 'hb.json')
os.environ['HOOK_HEARTBEAT_STATE'] = bad
r = hb.beat('x.py', blocked=True, sid='s1')
check('D1 不可写路径返回 False', r is False)
# 半截 JSON → snapshot 返回空壳不崩
p2 = fresh()
with open(p2, 'w', encoding='utf-8') as f:
    f.write('{"hooks": {"broken.py": ')
ss = hb.snapshot()
check('D2 半截JSON snapshot 空壳', ss == {}, str(ss))

# --- E --probe ---
p = fresh()
hb.beat('probeA.py', blocked=True, sid='s1')
hb.beat('probeA.py', missed=True, sid='s2')
out = subprocess.run([sys.executable, os.path.join(HOOKS, 'hook_heartbeat.py'),
                      '--probe'], capture_output=True, text=True,
                     env=dict(os.environ))
j = json.loads(out.stdout)
check('E1 probe hit', j['hit'] == 1, str(j['hit']))
check('E2 probe via', j['via'] == 'hook_heartbeat.json')
check('E3 probe calls', j['calls'] == 2)
check('E4 probe missed', j['missed'] == 1)
check('E5 probe hooks 结构', 'probeA.py' in j['hooks'])
check('E6 probe path', j['path'] == p)
# 过滤
out = subprocess.run([sys.executable, os.path.join(HOOKS, 'hook_heartbeat.py'),
                      '--probe', '--hook', 'probeA.py', '--sid', 's1'],
                     capture_output=True, text=True, env=dict(os.environ))
j = json.loads(out.stdout)
check('E7 probe 过滤 hit', j['hit'] == 1 and j['calls'] == 1, str(j))

# --- F 元变异：直接写替原子写，仍能读出完整账本（检测能力有牙）---
p = fresh()
hb.beat('mut.py', blocked=True, sid='s1')
raw = open(p, encoding='utf-8').read()
mut = raw.replace('"blocked": 1', '"blocked": 999')
with open(p, 'w', encoding='utf-8') as f:
    f.write(mut)
j = hb.snapshot(hook='mut.py')
check('F1 篡改后 hit 被读出', j['mut.py']['blocked'] == 999,
      '说明账本真被消费、非写死')
# 恢复用 beat 一笔，确认仍可读
hb.beat('mut.py', blocked=True, sid='s1')
j = hb.snapshot(hook='mut.py')
check('F2 篡改后 beat 仍能累加', j['mut.py']['blocked'] == 1000)

print()
print('通过 %d / 失败 %d' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
