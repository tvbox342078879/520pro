#!/usr/bin/env python3
# impl: B-19 S5   ← 步骤5 闭环完成判据（停增三态：seal/plateau 真函数 + mock 账本，非自报）
"""经验闭环 v3 步骤5 · 闭环收口判据的独立回归（test_exp_closure）。

验证三件事（真跑对象，非 AST 查存在）：
  ① 判据模块 selftest 真 subprocess 跑通（10 例正反）——验「接电能跑」；
  ② seal/plateau 端到端：真造账本→封盘→无复发停增→新复发达标→手改倒退 unknown；
  ③ 防挂空：verify.sh 同时接了 --selftest 与 test_exp_closure（判据不在执行路径=没写）。

病15 防护：本判据对象=exp_closure.py 的 seal/plateau 真函数 + 临时账本文件，
不靠模块源码里有无某字符串、不靠注释锚点；全部 mock 隔离，不污染真账本。
"""
import os
import sys
import json
import subprocess
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'verify'))

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('  ' + detail if not cond else ''))


CLOSURE = os.path.join(ROOT, 'verify', 'exp_closure.py')

# ① 真 subprocess 跑 selftest（接电等价：verify.sh 就是这么调的）
try:
    r = subprocess.run([sys.executable, CLOSURE, '--selftest'],
                       capture_output=True, text=True, timeout=30)
    tail = [l for l in r.stdout.splitlines() if 'selftest' in l]
    check('步骤5/selftest 真 subprocess rc=0', r.returncode == 0, r.stdout[-200:])
    check('步骤5/selftest 10✓/0✗（输出可读）',
          bool(tail) and '10 ✓' in tail[-1] and '0 ✗' in tail[-1], str(tail))
except Exception as ex:
    check('步骤5/selftest 真 subprocess', False, str(ex))

# ② seal/plateau 端到端（真函数 + 临时账本，非字符串）
try:
    import exp_closure as ec
    td = tempfile.mkdtemp()
    try:
        fp = os.path.join(td, 'experience_recurrence.json')
        c0 = {'counters': {'病Z': {'count': 2, 'status': 'active',
              'events': [{'ts': '2026-11-01 10:00', 'coord': 'e1'},
                         {'ts': '2026-11-02 10:00', 'coord': 'e2'}]}}}
        json.dump(c0, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)

        # 未封盘 → unknown
        check('端到端/未封盘 unknown', ec.plateau('病Z', seed=fp)['state'] == 'unknown')
        # 封盘
        sr = ec.seal('病Z', seed=fp, now='2026-11-03 00:00')
        check('端到端/seal 成功', sr['state'] == 'sealed')
        # 无复发 → plateau
        check('端到端/无复发 plateau', ec.plateau('病Z', seed=fp)['state'] == 'plateau')
        # 加一条收口后 event + count+1 → recurring
        d = json.load(open(fp, encoding='utf-8'))
        d['counters']['病Z']['count'] = 3
        d['counters']['病Z']['events'].append({'ts': '2026-11-05 10:00', 'coord': '复发'})
        json.dump(d, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        pr = ec.plateau('病Z', seed=fp)
        check('端到端/新复发 recurring 且带 count 差',
              pr['state'] == 'recurring' and pr['count'] == 3 and pr['base_count'] == 2, str(pr))
        # 手写 count 变小（洗绿）→ unknown
        d = json.load(open(fp, encoding='utf-8'))
        d['counters']['病Z']['count'] = 1
        json.dump(d, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        check('端到端/手改倒退 unknown（不洗绿）', ec.plateau('病Z', seed=fp)['state'] == 'unknown')
    finally:
        shutil.rmtree(td, ignore_errors=True)
except Exception as ex:
    check('步骤5/seal-plateau 端到端', False, str(ex))
    import traceback
    traceback.print_exc()

# ③ 防挂空：verify.sh 真接了 selftest 与 test_exp_closure（判据不在执行路径=没写）
try:
    vsh = open(os.path.join(ROOT, 'verify.sh'), encoding='utf-8').read()
    check('步骤5/verify.sh 接 exp_closure --selftest', 'exp_closure.py" --selftest' in vsh)
    check('步骤5/verify.sh 接闭环收口回读', 'exp_closure.py"' in vsh and '闭环收口回读' in vsh)
    check('步骤5/verify.sh 自动发现覆盖 test_exp_closure',
          'for tf in "$TARGET"/verify/tests/test_*.py; do' in vsh
          and os.path.isfile(os.path.join(ROOT, 'verify', 'tests', 'test_exp_closure.py')))
except Exception as ex:
    check('步骤5/防挂空接线', False, str(ex))

print('\n%d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
