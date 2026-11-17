#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三通道安装副本同步器的变异回归：SYNCED/NOOP/SKIP/FAIL 四态都要真。

不碰真 ~/.codebuddy：临时 git 仓 + 临时 HOME。验证：
  ① 目标存在且旧 → 真复制 + 回读一致（SYNCED）
  ② 目标已最新 → NOOP 且不写（mtime 不变，幂等）
  ③ 目标不存在 → SKIP 不创建（不凭空造副本）
  ④ 元变异：把 cp 短路成 true → 回读不一致 → FAIL rc=1（证明回读校验有效、不是嘴上幂等）
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, 'hooks', 'sync_channels.sh')
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + detail))


def setup(base):
    d = os.path.join(base, 'r')
    home = os.path.join(base, 'home')
    os.makedirs(d)
    os.makedirs(os.path.join(home, '.codebuddy', 'rules'))
    os.makedirs(os.path.join(d, '通用层', 'rules'))
    os.makedirs(os.path.join(d, '能力层', 'tvbox'))
    os.makedirs(os.path.join(d, '.codebuddy'))
    subprocess.run(['git', 'init', '-q'], cwd=d)
    shutil.copy(SCRIPT, os.path.join(d, 'sync.sh'))
    return d, home


def write(p, text):
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)


def run(d, home, script='sync.sh'):
    env = dict(os.environ)
    env['HOME'] = home
    return subprocess.run(['bash', script], cwd=d, capture_output=True, text=True, env=env)


def main():
    if not os.path.exists(SCRIPT):
        check('hooks/sync_channels.sh 存在', False, SCRIPT)
        print('结果：0 ✓ / 1 ✗')
        return 1
    check('T1 hooks/sync_channels.sh 存在', True)
    r = subprocess.run(['bash', '-n', SCRIPT], capture_output=True, text=True)
    check('T2 bash -n 语法过', r.returncode == 0, r.stderr)

    base = tempfile.mkdtemp(prefix='syncch-')
    try:
        d, home = setup(base)
        src = os.path.join(d, '通用层', 'rules', 'core-8.md')
        dst = os.path.join(home, '.codebuddy', 'rules', 'core-8.md')
        write(src, '新规则 v2\n')
        write(dst, '旧规则 v1\n')
        # T3 SYNCED
        r = run(d, home)
        check('T3 目标旧 → SYNCED 且回读一致 rc=0',
              r.returncode == 0 and 'SYNCED' in r.stdout and open(dst, encoding='utf-8').read() == '新规则 v2\n',
              f'rc={r.returncode} out={r.stdout[-160:]}')
        # T4 NOOP + 不写（mtime 不变）
        mtime0 = os.stat(dst).st_mtime_ns
        r = run(d, home)
        mtime1 = os.stat(dst).st_mtime_ns
        check('T4 目标已最新 → NOOP 且未重写（mtime 不变）',
              r.returncode == 0 and 'NOOP' in r.stdout and mtime0 == mtime1,
              f'rc={r.returncode} mtime {mtime0}→{mtime1}')
        # T5 SKIP 不创建
        missing = os.path.join(home, '.codebuddy', 'rules', '施工纪律.md')
        if os.path.exists(missing):
            os.remove(missing)
        write(os.path.join(d, '通用层', 'rules', '施工纪律.md'), '施工纪律 v2\n')
        r = run(d, home)
        check('T5 目标未安装 → SKIP 且不凭空创建',
              r.returncode == 0 and 'SKIP' in r.stdout and not os.path.exists(missing),
              f'rc={r.returncode} out={r.stdout[-160:]}')
        # T6 元变异：cp 短路 → 回读不一致 → FAIL
        s = open(SCRIPT, encoding='utf-8').read()
        mut = s.replace('if ! cp "$src" "$dst"; then', 'if false; then')
        check('T6 前置：变异真写进副本', mut != s and 'if false; then' in mut, '替换点没命中')
        mp = os.path.join(d, 'sync-mut.sh')
        write(mp, mut)
        write(dst, '又一个旧值\n')
        r = run(d, home, script='sync-mut.sh')
        check('T6 cp 被废 → 回读不一致 → FAIL rc=1（证明回读校验有效）',
              r.returncode == 1 and '回读不一致' in r.stdout,
              f'rc={r.returncode} out={r.stdout[-160:]}')
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print('结果：%d ✓ / %d ✗' % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
