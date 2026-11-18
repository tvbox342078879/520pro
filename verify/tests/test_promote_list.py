#!/usr/bin/env python3
# impl: B-19 S5   ← 达标可晋升入口（--list 可复制粘贴区 + 用户级真源，非自报/不分叉）
"""达标可晋升入口的独立回归（test_promote_list）。

验证四件（真跑对象，非 AST 查存在）：
  ① gate_experience --selftest 真 subprocess 跑通（含 _list_selftest 三态+用户级优先）；
  ② 真账本交叉：--list 报的达标病号 == 直接读用户级账本按 PROMOTE_MIN/退役过滤的结果
     （病15：判据对象范围=真账本，不是仓内种子 count=16，也不是源码字符串）；
  ③ 端到端「同步」：隔离账本→--list 出可复制粘贴区→抠出晋升命令→真跑该命令
     →候选真生成且自检绿（证明粘贴块里的命令不是摆设，粘到会话可执行）；
  ④ 防挂空：verify.sh 真接了 gate_experience --list。

全部 mock 隔离（CODEBUDDY_EXP_HOME），不污染真用户级账本。
"""
import os
import sys
import json
import re
import shlex
import subprocess
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATE = os.path.join(ROOT, 'verify', 'gate_experience.py')
USER_EXP = os.path.join(os.path.expanduser('~'), '.codebuddy', 'experience',
                        'experience_recurrence.json')

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('  ' + detail if not cond else ''))


# ① 真 subprocess 跑 selftest（接电等价：verify.sh 就是这么调的）
try:
    r = subprocess.run([sys.executable, GATE, '--selftest'],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    check('入口/selftest 真 subprocess rc=0', r.returncode == 0, r.stdout[-300:])
    check('入口/selftest 含 list 三态+用户级优先',
          'selftest[list]' in r.stdout and '用户级优先=✓' in r.stdout, r.stdout[-300:])
except Exception as ex:
    check('入口/selftest 真 subprocess', False, str(ex))

# ② 真账本交叉：--list 达标项 == 用户级账本按门槛过滤（对象范围=真账本）
try:
    r = subprocess.run([sys.executable, GATE, '--list'],
                       capture_output=True, text=True, timeout=30, cwd=ROOT)
    check('入口/--list 真账本 rc=0', r.returncode == 0, r.stderr[-200:])
    m = re.search(r'\{.*?\n\}', r.stdout, re.S)
    payload = json.loads(m.group(0)) if m else {}
    listed = {x['id'] for x in payload.get('items', [])}
    real = set()
    if os.path.isfile(USER_EXP):
        d = json.load(open(USER_EXP, encoding='utf-8'))
        MIN = 3
        for k, v in d.get('counters', {}).items():
            if isinstance(v, dict) and int(v.get('count', 0)) >= MIN and v.get('status', 'active') != 'retired':
                real.add(k)
    check('入口/达标项==用户级账本过滤（非仓内种子/非字符串假绿）',
          listed == real, f'list={listed} real={real}')
    check('入口/state 三态之一', payload.get('state') in ('ready', 'empty', 'unknown'),
          str(payload.get('state')))
except Exception as ex:
    check('入口/真账本交叉', False, str(ex))

# ③ 端到端「同步」：隔离账本 → --list 出粘贴块 → 抠命令 → 真跑 → 候选生成
try:
    td = tempfile.mkdtemp(prefix='plist_e2e_')
    env = dict(os.environ)
    env['CODEBUDDY_EXP_HOME'] = td
    try:
        fp = os.path.join(td, 'experience_recurrence.json')
        fixture = {'counters': {
            '病端到端': {'count': 5, 'status': 'active', 'note': '端到端同步验证的教训内容',
                      'events': [{'ts': 'd1', 'coord': '首次'}, {'ts': 'd2', 'coord': '复发'}]}}}
        json.dump(fixture, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)

        lr = subprocess.run([sys.executable, GATE, '--list'],
                            capture_output=True, text=True, timeout=30, cwd=ROOT, env=env)
        check('端到端/隔离账本 --list rc=0', lr.returncode == 0, lr.stderr[-200:])
        check('端到端/粘贴区标识完整',
              '## 【粘贴区 · 从下一行开始复制】' in lr.stdout
              and '**【粘贴区 结束】**' in lr.stdout, lr.stdout[-300:])
        cmd = re.search(r'python3 verify/gate_experience\.py --promote "[^"]+" --out "[^"]+"', lr.stdout)
        check('端到端/粘贴块含可执行晋升命令', bool(cmd), lr.stdout[-300:])
        if cmd:
            # 抠出的命令在仓库根真跑；--out 指到隔离目录，不污染仓
            out_dir = os.path.join(td, '产物')
            real_cmd = cmd.group(0).replace('--out "产物/晋升候选"', '--out "%s"' % out_dir)
            parts = shlex.split(real_cmd)  # 剥引号：避免病号 id 变成带引号的字面量
            pr = subprocess.run([sys.executable] + parts[1:],
                                capture_output=True, text=True, timeout=60, cwd=ROOT, env=env)
            check('端到端/粘贴命令真跑 rc=0', pr.returncode == 0, pr.stdout[-300:])
            res = json.loads(pr.stdout) if pr.stdout.strip().startswith('{') else {}
            check('端到端/候选真生成且自检绿', res.get('ok') is True
                  and res.get('check', {}).get('ok') is True, str(res)[:300])
            dpath = res.get('dir')
            check('端到端/候选 SKILL.md 落盘', bool(dpath) and os.path.isfile(os.path.join(dpath, 'SKILL.md')))
    finally:
        shutil.rmtree(td, ignore_errors=True)
except Exception as ex:
    check('入口/端到端同步', False, str(ex))
    import traceback
    traceback.print_exc()

# ④ 防挂空：verify.sh 真接了 --list
try:
    vsh = open(os.path.join(ROOT, 'verify.sh'), encoding='utf-8').read()
    check('入口/verify.sh 接 gate_experience --list', '--list' in vsh and 'gate_experience.py" --list' in vsh)
    check('入口/verify.sh 自动发现覆盖 test_promote_list',
          'for tf in "$TARGET"/verify/tests/test_*.py; do' in vsh
          and os.path.isfile(os.path.join(ROOT, 'verify', 'tests', 'test_promote_list.py')))
except Exception as ex:
    check('入口/防挂空接线', False, str(ex))

print('\n%d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
