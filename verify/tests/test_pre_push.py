#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre-push 本地闸的变异回归：证明它真能拦、且不递归。

为什么不用真 verify.sh 测：pre-push 调 secret_scan.py + verify.sh --repo-only，
在临时仓里跑全量判据又慢又依赖安装落点，不可控。这里用**假判据脚本**（rc 由环境变量
控制）替身，让"注入必红→必须拒、全绿→必须放行、废掉校验→同一输入放行"三态都可复现。

铁律（病15）：剥注释后再查 `git push`——注释里写了这句话，整行 grep 会假阳性。
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, 'hooks', 'pre-push')
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + detail))


def code_only(path):
    """剥掉整行注释与行内注释后的代码正文（病15：识别范围≠对象范围）。"""
    out = []
    for line in open(path, encoding='utf-8').read().splitlines():
        s = line.split('#', 1)[0]
        if s.strip():
            out.append(s)
    return '\n'.join(out)


def make_tmp(base):
    d = os.path.join(base, 'r')
    os.makedirs(d)
    subprocess.run(['git', 'init', '-q'], cwd=d)
    # 假判据：rc 由环境变量控制
    with open(os.path.join(d, 'secret_scan.py'), 'w', encoding='utf-8') as f:
        f.write('import os,sys\nsys.exit(int(os.environ.get("FAKE_SECRET_RC","0")))\n')
    with open(os.path.join(d, 'verify.sh'), 'w', encoding='utf-8') as f:
        f.write('exit ${FAKE_VERIFY_RC:-0}\n')
    shutil.copy(HOOK, os.path.join(d, 'pre-push')) if os.path.exists(HOOK) else None
    return d


def run(d, env_over=None):
    env = dict(os.environ)
    env.pop('FAKE_SECRET_RC', None)
    env.pop('FAKE_VERIFY_RC', None)
    if env_over:
        env.update({k: str(v) for k, v in env_over.items()})
    return subprocess.run(['bash', 'pre-push'], cwd=d, capture_output=True, text=True, env=env)


def main():
    if not os.path.exists(HOOK):
        check('hooks/pre-push 存在', False, HOOK)
        print('结果：0 ✓ / 1 ✗')
        return 1
    # T1-T3 静态
    check('T1 hooks/pre-push 存在', True)
    r = subprocess.run(['bash', '-n', HOOK], capture_output=True, text=True)
    check('T2 bash -n 语法过', r.returncode == 0, r.stderr)
    code = code_only(HOOK)
    check('T3 防递归：代码正文无 git push 调用（注释里提到不算）',
          'git push' not in code, [l for l in code.splitlines() if 'git push' in l])
    check('T3b 两个校验调用点都在（secret_scan + verify.sh）',
          'secret_scan.py' in code and 'verify.sh' in code)

    base = tempfile.mkdtemp(prefix='prepush-')
    try:
        d = make_tmp(base)
        # T4 全绿放行
        r = run(d, {'FAKE_SECRET_RC': 0, 'FAKE_VERIFY_RC': 0})
        check('T4 密钥干净 + 仓库自洽 → 放行 rc=0', r.returncode == 0 and 'pre-push 通过' in r.stdout,
              f'rc={r.returncode} out={r.stdout[-120:]}')
        # T5 密钥脏必拒
        r = run(d, {'FAKE_SECRET_RC': 1, 'FAKE_VERIFY_RC': 0})
        check('T5 密钥扫描失败 → 拒 rc=1', r.returncode == 1 and '密钥/卫生扫描未通过' in r.stdout,
              f'rc={r.returncode} out={r.stdout[-120:]}')
        # T6 带病必拒（绕过 commit 闸的代码）
        r = run(d, {'FAKE_SECRET_RC': 0, 'FAKE_VERIFY_RC': 1})
        check('T6 仓库自检失败 → 拒 rc=1', r.returncode == 1 and '仓库自检未通过' in r.stdout,
              f'rc={r.returncode} out={r.stdout[-120:]}')
        # T7 元变异：把两个校验调用短路成 true，则原本必拒的输入放行——证明拒绝来自校验
        src = open(HOOK, encoding='utf-8').read()
        mut = src.replace('python3 "$ROOT/secret_scan.py" --strict', 'true')
        mut = mut.replace('bash "$ROOT/verify.sh" --repo-only', 'true')
        check('T7 前置：变异真写进副本（两处调用被替换）',
              mut != src and 'python3 "$ROOT/secret_scan.py" --strict' not in mut,
              '替换点没命中')
        mp = os.path.join(d, 'pre-push-mut')
        with open(mp, 'w', encoding='utf-8') as f:
            f.write(mut)
        env = dict(os.environ)
        env['FAKE_SECRET_RC'] = '1'
        env['FAKE_VERIFY_RC'] = '1'
        r = subprocess.run(['bash', os.path.basename(mp)], cwd=d, capture_output=True, text=True, env=env)
        # 假脚本在异地，变异版 root 仍是临时仓；校验被短路后两个假脚本都不跑 → 放行
        check('T7 校验被废后同一输入放行（证明 T5/T6 的拒绝来自校验）',
              r.returncode == 0, f'rc={r.returncode} out={r.stdout[-120:]}')
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print('结果：%d ✓ / %d ✗' % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
