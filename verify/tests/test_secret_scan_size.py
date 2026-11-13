#!/usr/bin/env python3
"""test_secret_scan_size.py — 大文件闸（git-as-DB 边界）变异回归

拆掉实现必须翻红：>10MB 文件必须让 secret_scan 以 rc=2 退出并点名该文件；
正常小文件仓必须 rc=0。另验边界值（恰好 ≤ 上限）不误伤。
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(ROOT, 'secret_scan.py')
LIMIT = 10 * 1024 * 1024

fails = []


def run(tmp):
    r = subprocess.run([sys.executable, SCRIPT, tmp],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def check(name, cond, detail=''):
    if cond:
        print(f'  ✓ {name}')
    else:
        fails.append(f'{name}: {detail}')
        print(f'  ✗ {name}——{detail}')


# C1 超限文件 → rc=2 且点名（正样本：证明闸会命中）
with tempfile.TemporaryDirectory() as tmp:
    big = os.path.join(tmp, '大包.tar')
    with open(big, 'wb') as f:
        f.write(b'\0' * (LIMIT + 1024))
    with open(os.path.join(tmp, '小文件.md'), 'w', encoding='utf-8') as f:
        f.write('正常内容\n')
    rc, out = run(tmp)
    check('C1 超限文件被抓', rc == 2 and '大包.tar' in out and '10MB' in out,
          f'rc={rc}, out={out[:200]!r}')

# C2 全小文件 → rc=0（防永远红）
with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, 'a.md'), 'w', encoding='utf-8') as f:
        f.write('# 正常\n')
    with open(os.path.join(tmp, 'b.json'), 'w', encoding='utf-8') as f:
        f.write('{"k": "v"}\n')
    rc, out = run(tmp)
    check('C2 全小文件放行', rc == 0, f'rc={rc}, out={out[:200]!r}')

# C3 边界值：恰好 10MB（不超）→ rc=0；10MB+1 字节 → rc=2（闸在正确的位置）
with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, '边界.tar'), 'wb') as f:
        f.write(b'\0' * LIMIT)
    rc, out = run(tmp)
    check('C3a 恰好 10MB 放行', rc == 0, f'rc={rc}')
with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, '边界.tar'), 'wb') as f:
        f.write(b'\0' * (LIMIT + 1))
    rc, out = run(tmp)
    check('C3b 10MB+1 翻红', rc == 2, f'rc={rc}')

print('============================================')
if fails:
    print(f'✗ {len(fails)} 项失败')
    for f in fails:
        print(f'  ✗ {f}')
    sys.exit(1)
print('✓ 大文件闸回归通过（4 用例）')
