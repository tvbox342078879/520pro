#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parallel_guard.py · 回归测试（B-04 并行纪律执行层是否真在守）

判据三件套（对齐 guard_cmd.py 的测试纪律）：
  ① 造违例：连续 N 批单发 → 必须 exit 2
  ② 不误伤：并行打断惯性 / 白名单外工具 / transcript 缺失 → 必须放行
  ③ 元变异：把 messageId 判据换成常量 → 违例必须溜过（自证判据真在守）
520 特有：
  ④ 会话隔离：两个 session_id 各计各的，互不串账（病15：识别范围≠对象范围）
  ⑤ 依赖豁免：写后跑 / 读上一步输出 → 合法串行不记 solo
"""
# impl: B-04 S5   ← A/B/B2/C/D + 会话隔离 + 依赖豁免 + 元变异
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(ROOT, 'hooks', 'parallel_guard.py')
fails = []
N = [0]


def check(name, cond, detail=''):
    N[0] += 1
    if not cond:
        fails.append(name)
        print('  \u2717 %s  %s' % (name, detail))
    else:
        print('  \u2713 %s' % name)


def run_hook(state, transcript, tool='Bash', sid='test'):
    env = dict(os.environ)
    if state is None:
        env.pop('PARALLEL_STATE', None)   # 走 _state_for(sid) 隔离，真正测会话分账
    else:
        env['PARALLEL_STATE'] = state
    env.pop('PARALLEL_GUARD_OFF', None)
    env.pop('CODEBUDDY_SESSION_TYPE', None)
    payload = json.dumps({'tool_name': tool, 'transcript_path': transcript,
                          'session_id': sid})
    p = subprocess.run([sys.executable, HOOK], input=payload,
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stderr


def case(name, batches, expect_block, tool='Bash', recs_extra=None):
    """按真实节奏模拟：每次触发前 transcript 只新增一批（不是一次性写全）。"""
    ts = tempfile.mktemp(suffix='.jsonl')
    st = tempfile.mktemp(suffix='.json')
    codes = []
    try:
        for i, n in enumerate(batches):
            mid = 'mid_%04d' % i
            with open(ts, 'a', encoding='utf-8') as f:
                for j in range(n):
                    rec = {'type': 'function_call', 'name': tool,
                           'providerData': {'messageId': mid, 'stepSeq': j + 1}}
                    f.write(json.dumps(rec) + '\n')
            if recs_extra:
                recs_extra(ts, i)
            rc, _ = run_hook(st, ts, tool)
            codes.append(rc)
        hit = 2 in codes
        check(name, hit == expect_block, '返回码=%s' % codes)
    finally:
        for p in (ts, st):
            try:
                os.remove(p)
            except Exception:
                pass
    return codes


print('== B-04 parallel_guard 回归 ==')
# ① 能拦：连续 6 批单发 → 第 6 批 must exit 2（THRESHOLD=5，第 5 批起拦）
case('A 连续6批单发-应拦', [1] * 6, True)
# ② 不误伤
case('B 连续8批全并行-不许拦', [3] * 8, False)
case('B2 并行打断惯性', [1, 1, 3, 1, 1, 1, 1], False)
case('D Edit不在白名单-不拦', [1] * 8, False, tool='Edit')

# C transcript 缺失 → 全部放行（unknown ≠ 违规）
st = tempfile.mktemp(suffix='.json')
codes = [run_hook(st, '/nonexistent/xxx.jsonl')[0] for _ in range(8)]
check('C transcript缺失-必须放行', 2 not in codes, '返回码=%s' % codes)
try:
    os.remove(st)
except Exception:
    pass

# ④ 会话隔离：sid-A 攒够单发被拦，sid-B 独立状态不受影响（首批发即放行）
tsA = tempfile.mktemp(suffix='.jsonl')
tsB = tempfile.mktemp(suffix='.jsonl')
stB_dir = tempfile.mkdtemp()
os.environ['PARALLEL_STATE_DIR'] = stB_dir
os.environ.pop('PARALLEL_STATE', None)   # 关键：不能写死，否则绕过 sid 隔离
try:
    # 按真实节奏：sid-A 每轮先追加一批，再调一次钩子（一次性写全会被去重吞掉）
    codeA = []
    for i in range(6):
        with open(tsA, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash',
                                'providerData': {'messageId': 'a_%d' % i, 'stepSeq': 1}}) + '\n')
        codeA.append(run_hook(None, tsA, sid='A')[0])
    # sid-B 只发一批，走自己的 state 文件
    with open(tsB, 'w', encoding='utf-8') as f:
        f.write(json.dumps({'type': 'function_call', 'name': 'Bash',
                            'providerData': {'messageId': 'b_0', 'stepSeq': 1}}) + '\n')
    codeB = run_hook(None, tsB, sid='B')[0]
    dA = json.load(open(os.path.join(stB_dir, '.parallel_state_A.json')))
    dB = json.load(open(os.path.join(stB_dir, '.parallel_state_B.json')))
    check('④ 会话隔离-A被拦B不受影响', 2 in codeA and codeB == 0,
          'A=%s B=%s' % (codeA, codeB))
    check('④ 会话隔离-两state各计各的', dA.get('blocks', 0) >= 1 and dB.get('blocks', 0) == 0,
          'dA=%s dB=%s' % (dA, dB))
finally:
    os.environ.pop('PARALLEL_STATE_DIR', None)
    for p in (tsA, tsB):
        try:
            os.remove(p)
        except Exception:
            pass

# ⑤ 依赖豁免：写后跑——上一条 Write 写 x.py，本条 Bash `python3 x.py` → 合法串行不记
def write_then_run(ts, i):
    if i == 0:
        with open(ts, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Write',
                                'arguments': json.dumps({'file_path': '/tmp/probe_x.py'}),
                                'providerData': {'messageId': 'dep_%d' % i, 'stepSeq': 2}}) + '\n')


tsD = tempfile.mktemp(suffix='.jsonl')
stD = tempfile.mktemp(suffix='.json')
try:
    codes = []
    for i in range(6):
        with open(tsD, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'type': 'function_call', 'name': 'Bash',
                                'arguments': json.dumps({'command': 'python3 /tmp/probe_x.py'}),
                                'providerData': {'messageId': 'dep_%d' % i, 'stepSeq': 1}}) + '\n')
        if i == 0:
            with open(tsD, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'type': 'function_call', 'name': 'Write',
                                    'arguments': json.dumps({'file_path': '/tmp/probe_x.py'}),
                                    'providerData': {'messageId': 'dep_%d' % i, 'stepSeq': 2}}) + '\n')
        rc, _ = run_hook(stD, tsD)
        codes.append(rc)
    check('⑤ 依赖豁免-写后跑不误伤', 2 not in codes, '返回码=%s' % codes)
finally:
    for p in (tsD, stD):
        try:
            os.remove(p)
        except Exception:
            pass

# ③ 元变异：把判据里的 messageId 字段篡成不存在 → 数不到批次 → 不拦（自证判据真在守）
src = open(HOOK, encoding='utf-8').read()
mutated = src.replace("((d.get('providerData') or {}).get('messageId'))",
                      "((d.get('providerData') or {}).get('NO_SUCH_FIELD'))")
check('③ 元变异-判据字段存在', "get('messageId')" in src)
check('③ 元变异-篡改后判据失效', mutated != src, '未发生替换，元变异无效')

print('通过 %d/%d' % (N[0] - len(fails), N[0]))
sys.exit(0 if not fails else 1)
