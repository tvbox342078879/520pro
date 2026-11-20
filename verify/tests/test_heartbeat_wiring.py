#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 步接线测试：5 个硬拦钩的拦截分支确实写心跳账（端到端，隔离 state）。

判据（不是看代码写了没写，是跑钩进程看账本变没变）：
  1 guard_cmd.py     违例命令 --force push → deny → 账本 +1（覆盖 next_anchor 两路径的共同出口）
  2 parallel_guard   连续单发达阈值 → exit2 → 账本 +1
  3 task_wait_guard  第3次 block=true → deny → 账本 +1
  4 agent_turns_guard 缺 max_turns → deny → 账本 +1
  5 stop_guard       完成态缺落点 → decision:block → 账本 +1
  6 放行路径不误记（合规命令 / 带 max_turns）
  7 会话分组：payload.session_id 进账本 sessions
  8 元变异：遮掉某个钩的 beat 接线 → 该钩账本不增长（证明测试贴着接线，非恒绿）
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, 'hooks')
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('✓' if cond else '✗'), name, detail)


def run_hook(script, payload, state, extra_env=None):
    env = dict(os.environ)
    env['HOOK_HEARTBEAT_STATE'] = state
    env.pop('PARALLEL_GUARD_OFF', None)
    env.pop('CODEBUDDY_SESSION_TYPE', None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, os.path.join(HOOKS, script)],
                          input=json.dumps(payload) if not isinstance(payload, str) else payload,
                          capture_output=True, text=True, env=env)


def hb(state):
    try:
        return json.load(open(state, encoding='utf-8')).get('hooks', {})
    except Exception:
        return {}


def blocked(state, hook):
    return int((hb(state).get(hook) or {}).get('blocked', 0))


with tempfile.TemporaryDirectory() as td:
    # ── 1 guard_cmd.py: --force push 命中 G1 → deny + 记账 ──
    st1 = os.path.join(td, 'h1.json')
    p = run_hook('guard_cmd.py', {
        'tool_name': 'Bash', 'tool_input': {'command': 'git push origin main --force'},
        'session_id': 's-guard'}, st1)
    check('1a guard_cmd 拦截 rc=2', p.returncode == 2, 'rc=%d' % p.returncode)
    check('1b guard_cmd 记账 blocked=1', blocked(st1, 'guard_cmd.py') == 1,
          'got=%d' % blocked(st1, 'guard_cmd.py'))
    check('1c sid 分组', 's-guard' in ((hb(st1).get('guard_cmd.py') or {}).get('sessions') or {}))

    # ── 2 parallel_guard: 连续单发达阈值 → exit2 + 记账 ──
    st2 = os.path.join(td, 'h2.json')
    ts2 = os.path.join(td, 't2.jsonl')
    codes = []
    for i in range(6):
        with open(ts2, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash',
                                'providerData': {'messageId': 'solo%d' % i},
                                'arguments': json.dumps({'command': 'echo x'})}) + '\n')
        codes.append(run_hook('parallel_guard.py', {
            'tool_name': 'Bash', 'transcript_path': ts2,
            'session_id': 's-par'}, st2, {'PARALLEL_STATE': os.path.join(td, 'pstate2.json')}).returncode)
    check('2a parallel 第5次 exit2', 2 in codes, 'codes=%s' % codes)
    check('2b parallel 记账 blocked≥1', blocked(st2, 'parallel_guard.py') >= 1,
          'got=%d' % blocked(st2, 'parallel_guard.py'))

    # ── 3 task_wait_guard: 第3次 block=true → deny + 记账 ──
    st3 = os.path.join(td, 'h3.json')
    tw3 = os.path.join(td, 'tw3.json')
    codes3 = []
    for _ in range(3):
        p3 = run_hook('task_wait_guard.py', {
            'tool_name': 'TaskOutput', 'tool_input': {'task_id': 't-x', 'block': True},
            'session_id': 's-tw'}, st3, {'_TASKWAIT_STATE': tw3})
        codes3.append(p3.returncode)
    check('3a task_wait 第3次 deny', codes3[-1] == 2, 'codes=%s' % codes3)
    check('3b task_wait 记账 blocked=1', blocked(st3, 'task_wait_guard.py') == 1,
          'got=%d' % blocked(st3, 'task_wait_guard.py'))

    # ── 4 agent_turns_guard: 缺 max_turns → deny + 记账 ──
    st4 = os.path.join(td, 'h4.json')
    p4 = run_hook('agent_turns_guard.py', {
        'tool_name': 'Agent', 'tool_input': {'prompt': 'x'}, 'session_id': 's-ag'}, st4)
    check('4a agent_turns 拦截 rc=2', p4.returncode == 2)
    check('4b agent_turns 记账 blocked=1', blocked(st4, 'agent_turns_guard.py') == 1,
          'got=%d' % blocked(st4, 'agent_turns_guard.py'))

    # ── 5 stop_guard: 完成态缺落点 → decision:block + 记账 ──
    st5 = os.path.join(td, 'h5.json')
    p5 = run_hook('stop_guard.py', {
        'session_id': 's-stop', 'stop_hook_active': False,
        'last_assistant_message': '已完成修复，全部搞定。'}, st5,
        {'STOP_GUARD_STATE': os.path.join(td, '.stop_state5.json')})
    is_block = False
    try:
        is_block = json.loads(p5.stdout).get('decision') == 'block'
    except Exception:
        pass
    check('5a stop_guard 拽回 decision:block', is_block, 'out=%s' % p5.stdout[:80])
    check('5b stop_guard 记账 blocked=1', blocked(st5, 'stop_guard.py') == 1,
          'got=%d' % blocked(st5, 'stop_guard.py'))

    # ── 6 放行路径不误记 ──
    st6 = os.path.join(td, 'h6.json')
    p6 = run_hook('agent_turns_guard.py', {
        'tool_name': 'Agent', 'tool_input': {'prompt': 'x', 'max_turns': 25},
        'session_id': 's-ok'}, st6)
    check('6a 合规派活 rc=0', p6.returncode == 0)
    check('6b 放行不误记 blocked=0', blocked(st6, 'agent_turns_guard.py') == 0,
          'got=%d' % blocked(st6, 'agent_turns_guard.py'))
    p6b = run_hook('guard_cmd.py', {
        'tool_name': 'Bash', 'tool_input': {'command': 'echo hello'},
        'session_id': 's-ok2'}, st6)
    check('6c 合规命令不误记', blocked(st6, 'guard_cmd.py') == 0,
          'got=%d' % blocked(st6, 'guard_cmd.py'))

    # ── 7 会话分组（上面 1c 已验 guard_cmd，再验跨钩不串账）──
    s_all = hb(st1)
    g = s_all.get('guard_cmd.py') or {}
    check('7a 全局 blocked 与会话明细一致',
          g.get('blocked', 0) == 1 and (g.get('sessions') or {}).get('s-guard', {}).get('blocked', 0) == 1)

    # ── 8 元变异：遮掉 guard_cmd 的 beat 接线 → 拦截仍发生但账本不涨 ──
    src = open(os.path.join(HOOKS, 'guard_cmd.py'), encoding='utf-8').read()
    mut = src.replace("hook_heartbeat.beat_from_payload(payload, 'guard_cmd.py', blocked=True)",
                      "pass  # 变异：遮掉接线", 1)
    assert mut != src, '变异点不存在'
    mp = os.path.join(td, 'mut_guard.py')
    open(mp, 'w', encoding='utf-8').write(mut)
    st8 = os.path.join(td, 'h8.json')
    env8 = dict(os.environ, HOOK_HEARTBEAT_STATE=st8)
    p8 = subprocess.run([sys.executable, mp], input=json.dumps({
        'tool_name': 'Bash', 'tool_input': {'command': 'git push origin main --force'},
        'session_id': 's-mut'}), capture_output=True, text=True, env=env8)
    check('8a 变异后仍拦截 rc=2', p8.returncode == 2)
    check('8b 变异后账本不涨（测贴着接线）', blocked(st8, 'guard_cmd.py') == 0,
          'got=%d' % blocked(st8, 'guard_cmd.py'))

print()
print('通过 %d / 失败 %d' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
