#!/usr/bin/env python3
# test_task_wait_guard.py —— 等待闸双向自测的元测试（v0.8.79）
# 防两条假绿：① selftest 恒绿（变异闸参数后应红）；② selftest 消失/退化为空跑。
# 真源：docs/防卡死检查单.md §四；闸本体 hooks/task_wait_guard.py。

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARD = os.path.join(ROOT, 'hooks', 'task_wait_guard.py')

results = []


def case(name, cond):
    results.append((name, bool(cond)))


def guard_selftest(env_extra=None):
    env = dict(os.environ, **(env_extra or {}))
    p = subprocess.run([sys.executable, GUARD, '--selftest'],
                       capture_output=True, text=True, env=env, timeout=60)
    return p.returncode, p.stdout


# ── 1. 正向：selftest 全绿 ──
rc, out = guard_selftest()
n_all = len(re.findall(r'^  [✓✗]', out, re.M))
case('selftest rc=0 且全绿', rc == 0 and '✗' not in out
     and out.splitlines()[-1].strip().endswith('selftest: %d/%d' % (n_all, n_all)))

# ── 2. selftest 条目数 ≥ 7（防退化成空跑假绿）──
n_cases = len(re.findall(r'^  [✓✗]', out, re.M))
case('selftest 覆盖 ≥7 项', n_cases >= 7)

# ── 3. 元变异 A：DENY_AT 3→2 后 selftest 应红（第3次用例期望 deny 不再成立）──
with tempfile.TemporaryDirectory() as td:
    src = open(GUARD, encoding='utf-8').read()
    mut = src.replace('DENY_AT = 3', 'DENY_AT = 2', 1)
    case('变异点存在', mut != src)
    mpath = os.path.join(td, 'mut.py')
    open(mpath, 'w', encoding='utf-8').write(mut)
    env = dict(os.environ, _TASKWAIT_STATE=os.path.join(td, 'st.json'))
    p = subprocess.run([sys.executable, mpath, '--selftest'],
                       capture_output=True, text=True, env=env, timeout=60)
    case('元变异A: DENY_AT 3→2 → selftest 红', p.returncode != 0)

# ── 4. 元变异 B：化石过期判据失效（EXPIRE_SEC 3600→10**9）→ 化石用例应红 ──
with tempfile.TemporaryDirectory() as td:
    src = open(GUARD, encoding='utf-8').read()
    mut = src.replace('EXPIRE_SEC = 3600', 'EXPIRE_SEC = 10**9', 1)
    case('变异点B存在', mut != src)
    mpath = os.path.join(td, 'mut.py')
    open(mpath, 'w', encoding='utf-8').write(mut)
    env = dict(os.environ, _TASKWAIT_STATE=os.path.join(td, 'st.json'))
    p = subprocess.run([sys.executable, mpath, '--selftest'],
                       capture_output=True, text=True, env=env, timeout=60)
    case('元变异B: 化石过期失效 → selftest 红', p.returncode != 0)

# ── 5. fail-open 保底还在：主入口 try/except Exception → exit 0 ──
src = open(GUARD, encoding='utf-8').read()
case('fail-open 保底在位', 'except Exception:' in src and 'sys.exit(0)' in src)

# ── 6. deny 输出格式与 guard_cmd 同构（正本入口，防自造通道）──
case('deny 格式与 guard_cmd 同构',
     '"permissionDecision": \'deny\'' in src or "permissionDecision" in src)

npass = sum(1 for _, ok in results if ok)
for name, ok in results:
    print(('  ✓ ' if ok else '  ✗ ') + name)
print('test_task_wait_guard: %d/%d' % (npass, len(results)))
sys.exit(0 if npass == len(results) else 1)
