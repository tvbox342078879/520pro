#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_gate_scan.py — verify/gate_scan.py 的三件套测试（病10 / 病13）

三条件（判据才算判据）：
  ① 能造违例：裸 git diff --cached / 缺 --probe 的钩子 → 红
  ② 具体判据拦下：红项理由指向预期原因（病号 + 文件）
  ③ 把判据改坏能溜过：元变异——把 QUOTEPATH 常量改坏后，违例文件能穿过（自证判据真在守）

退出码 0 全通 / 1 有用例未按预期。
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCAN = os.path.join(ROOT, 'verify', 'gate_scan.py')

fails = []


def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


def run(args, cwd=None):
    r = subprocess.run([sys.executable, SCAN] + args, capture_output=True, text=True,
                       timeout=60, cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w', encoding='utf-8').write(text)


# ── ① 正向：真源仓库两 gate 全绿 ──
rc, out = run(['--root', ROOT])
check('真源全绿 rc=0', rc == 0, out[-200:])
check('输出含两 gate 全绿标记', '[quotepath] 全绿' in out and '[hook-probe] 全绿' in out, out[-200:])

# ── ② 造违例：quotepath ──
with tempfile.TemporaryDirectory() as td:
    w(os.path.join(td, 'scripts', 'bad.sh'),
      'files=$(git diff --cached --name-only)\n')
    rc, out = run(['--gate', 'quotepath', '--root', td])
    check('裸 diff --cached 被拦 rc=2', rc == 2, out[-200:])
    check('红项指向 bad.sh 且带病号', 'bad.sh' in out and '病10' in out, out[-200:])

    w(os.path.join(td, 'scripts', 'bad.sh'),
      'files=$(git -c core.quotepath=false diff --cached --name-only)\n')
    rc, out = run(['--gate', 'quotepath', '--root', td])
    check('带 -c 后放行 rc=0', rc == 0, out[-200:])

    w(os.path.join(td, 'scripts', 'bad.sh'),
      '# 仅注释：git diff --cached --name-only\n')
    rc, out = run(['--gate', 'quotepath', '--root', td])
    check('注释行豁免 rc=0', rc == 0, out[-200:])

    w(os.path.join(td, 'scripts', 'bad.sh'),
      'n=$(git -C "$T" ls-files | wc -l)\n')
    rc, out = run(['--gate', 'quotepath', '--root', td])
    check('裸 ls-files 同样被拦', rc == 2 and '病10' in out, out[-200:])

# ── ③ 造违例：hook-probe ──
with tempfile.TemporaryDirectory() as td:
    w(os.path.join(td, 'install.sh'),
      'cp "$ROOT/hooks/na.py" "$HOME/.codebuddy/hooks/na.py"\n')
    w(os.path.join(td, 'hooks', 'na.py'),
      "if '--probe' in sys.argv: ...\nprobe = {'hit': False, 'via': 'none'}\n")
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('合规平台钩子放行 rc=0', rc == 0, out[-200:])

    w(os.path.join(td, 'hooks', 'na.py'), "if '--probe' in sys.argv: ...\n")
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('缺 hit/via 被拦', rc == 2 and 'via' in out and '病13' in out, out[-200:])

    os.remove(os.path.join(td, 'hooks', 'na.py'))
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('注册但文件不存在被拦', rc == 2 and '不存在' in out, out[-200:])

    w(os.path.join(td, 'install.sh'), 'echo nothing-here\n')
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('install.sh 无注册被拦', rc == 2 and '提取不到' in out, out[-200:])

# ── ④ 元变异：把判据改坏，违例必须溜过（自证判据真在守） ──
with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as vd:
    vdir = os.path.join(vd, 'scripts')
    w(os.path.join(vdir, 'bad.sh'), 'f=$(git diff --cached --name-only)\n')
    src = open(SCAN, encoding='utf-8').read()
    mutated = src.replace("QUOTEPATH = 'core.quotepath=false'",
                          "QUOTEPATH = 'X-MUTATED-NOT-EXIST'")
    check('变异真的落盘', 'X-MUTATED-NOT-EXIST' in mutated)
    mpath = os.path.join(td, 'scan_copy.py')
    open(mpath, 'w', encoding='utf-8').write(mutated)
    r = subprocess.run([sys.executable, mpath, '--gate', 'quotepath', '--root', vdir],
                       capture_output=True, text=True, timeout=60)
    check('判据改坏后违例溜过 rc=0', r.returncode == 0, (r.stdout + r.stderr)[-200:])

# ── ⑤ verify.sh 必须真的挂了这道闸（防"测试绿但段被删"） ──
vsh = open(os.path.join(ROOT, 'verify.sh'), encoding='utf-8').read()
check('verify.sh 注册 gate_scan 调用', 'gate_scan.py' in vsh)

print('test_gate_scan：%d 例，失败 %d' % (12, len(fails)))
sys.exit(1 if fails else 0)
