#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_artifact_scan.py — artifact.py 分类器回归（拆掉任一规则必须翻红）

artifact-store v1.0.3 的执行体。本文件是「秤」：
  1) 跑 `artifact.py self-check` 的 8 个构造样本（.git 保护 / 字节码可再生 /
     普通产物候选 / 符号链接不跟 / 轮次按会话 / 白名单拒绝）；
  2) 元检查——脚本本体必须**没有删除分支**：出现 os.remove / shutil.rmtree /
     unlink 即判红。这条防的是「说好只读，改着改着加了删除」。

改坏分类逻辑或给脚本加删除调用，本回归必须失败。
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(ROOT, '通用层', 'skills', 'artifact-store', 'scripts', 'artifact.py')

fails = []


def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


# ── 1. 分类器 8 样本 ────────────────────────────────────────
print('分类器自检')
if not os.path.isfile(SCRIPT):
    check('执行体存在', False, SCRIPT)
else:
    proc = subprocess.run([sys.executable, SCRIPT, 'self-check'],
                          capture_output=True, text=True, timeout=60)
    for line in proc.stdout.splitlines():
        if line.strip().startswith(('✓', '✗')):
            print('  ' + line.strip())
    check('self-check 全绿', proc.returncode == 0, f'rc={proc.returncode}')
    check('8 例全过', proc.stdout.count('✓') == 8, f'通过 {proc.stdout.count("✓")} 例')

# ── 2. 元检查：脚本无删除分支 ───────────────────────────────
print('只读性元检查')
if os.path.isfile(SCRIPT):
    src = open(SCRIPT, encoding='utf-8').read()
    banned = {
        'os.remove': r'\bos\.remove\s*\(',
        'os.unlink': r'\bos\.unlink\s*\(',
        'shutil.rmtree': r'\bshutil\.rmtree\s*\(',
        'pathlib.unlink': r'\.unlink\s*\(',
        'subprocess rm': r'\brm\s+-[rf]',
    }
    hits = [name for name, pat in banned.items() if re.search(pat, src)]
    check('脚本无删除调用', not hits, '发现: ' + ', '.join(hits) if hits else '')

print(f'失败 {len(fails)} 处')
sys.exit(1 if fails else 0)
