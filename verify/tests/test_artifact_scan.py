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

# ── 2. 端到端 dry-run：多轮样本必须给出「哪几个文件」 ─────────
# 分类器样本只证明「分对了类」，不证明「人能看到要归档的清单」。
# 用户验收只问一句：跑一下，能不能告诉我这 12 个文件是哪 12 个？
print('端到端 dry-run 试点')
if os.path.isfile(SCRIPT):
    import shutil
    import tempfile
    # 白名单只允许 ~/.codebuddy 之下（脚本自身的闸，不能为了测试放宽）。
    # 所以在白名单内造临时目录，跑完删掉；顺手验证闸对 /tmp 是拒的。
    base = os.path.expanduser(os.path.join('~', '.codebuddy'))
    root = tempfile.mkdtemp(prefix='.artifact-e2e-', dir=base)
    try:
        for day, name in ((1, 'old'), (10, 'mid'), (13, 'new')):
            d = os.path.join(root, name + '-session')
            os.makedirs(d)
            for i in range(1, 13):
                open(os.path.join(d, f'out_{i}.json'), 'w').write('{"n":%d}' % i)
        # old 会话里塞一个含 .git 的仓库副本 + 字节码，验证它们不进归档清单
        repo = os.path.join(root, 'old-session', 'repo')
        os.makedirs(os.path.join(repo, '.git', 'objects'))
        open(os.path.join(repo, '.git', 'objects', 'pack'), 'wb').write(b'0' * 500)
        open(os.path.join(repo, 'main.py'), 'w').write('print(1)')
        pyc = os.path.join(root, 'old-session', '__pycache__')
        os.makedirs(pyc)
        open(os.path.join(pyc, 'x.pyc'), 'wb').write(b'0' * 100)
        # 时间戳必须最后设：新建子目录会刷新父目录 mtime，先设后建等于白设
        # （这一点是 runway 实测，不是假设：上一版就因此把 old 判成了「最新」）
        for day, name in ((1, 'old'), (10, 'mid'), (13, 'new')):
            os.utime(os.path.join(root, name + '-session'), (1000 + day, 1000 + day))
        # 三个会话各 12 个文件；只有最老的 old 该进候选（keep=2 留两轮）
        proc = subprocess.run([sys.executable, SCRIPT, 'scan', '--root', root,
                               '--keep', '2', '--list', '50'],
                              capture_output=True, text=True, timeout=60)
        out = proc.stdout
        check('多轮样本 rc=1（有候选且有保护区，需人确认）', proc.returncode == 1,
              f'rc={proc.returncode} {proc.stderr[:120]}')
        cand = [l for l in out.splitlines() if '[归档候选]' in l]
        check('有且仅有最老会话进候选', len(cand) == 1 and 'old-sess' in cand[0],
              f'候选行: {cand}')
        listed = [l for l in out.splitlines() if l.strip().endswith('.json')]
        check('归档清单列出 12 个文件', len(listed) == 12, f'列出 {len(listed)} 条')
        check('清单逐条可读（含文件名）', any('out_1.json' in l for l in listed), out[:300])
        check('含 .git 的子树不进归档清单',
              not any('repo/' in l or '.git' in l for l in listed), out[:300])
        check('字节码不进归档清单', not any('.pyc' in l for l in listed), out[:300])
        # 反向：白名单外的根必须被拒（UNKNOWN + rc=2），不许静默当空目录扫
        bad = subprocess.run([sys.executable, SCRIPT, 'scan', '--root', '/tmp'],
                             capture_output=True, text=True, timeout=60)
        check('白名单外的根 rc=2 且报 UNKNOWN',
              bad.returncode == 2 and 'UNKNOWN' in bad.stderr, f'rc={bad.returncode} {bad.stderr[:120]}')
    finally:
        shutil.rmtree(root, ignore_errors=True)

# ── 3. 元检查：脚本无删除分支 ───────────────────────────────
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
