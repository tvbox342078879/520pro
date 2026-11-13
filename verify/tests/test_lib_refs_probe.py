#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_lib_refs_probe.py — lib_refs_check.py 的 `--probe` 回归（含 6 个必红变异）

为什么要有本文件：一个只会打 ✓ 的检查器等于没有检查器（B-13 要落点证据）。
所以这里造**假的 LIB + 假的仓**，逐个把「平台真的会做的破坏」注射进去，
断言检查器必须变红——红的姿势还得对（红在 L1 / L2 / L3 哪一层、报的是哪个参数）。

覆盖：
  ✓ 基线全绿（且不把 `--limit 60` 这类数据误判成枚举值）
  ✓ 参数改名        → L3 失配，指名 `--op`
  ✓ 枚举值删除      → L3 失配，指名 `--op set-records`
  ✓ 脚本 import 炸  → L2 探活失败（文件还在也可能炸，L1 看不见）
  ✓ 子命令改名      → L3 子命令失配
  ✓ 文件消失        → L1 失配
  ✓ 无 CLI 契约脚本 → 不执行，判「无法判定」rc=2（不拿 --help 去撞未知脚本）

改坏任一层判据，本回归必须失败。
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(ROOT, 'verify', 'lib_refs_check.py')

DB_EDIT = '''import argparse
p = argparse.ArgumentParser(description='一次调用改表并回读核验')
p.add_argument('--database-id', required=True)
p.add_argument('--op', choices=['add-field', 'set-records'])
p.add_argument('--limit', type=int)
p.parse_args()
'''

# 与真实 space_hub._db_query 同形：脚本走变量、参数走局部 argv、两者在同一函数里
DB_WRAP = '''import argparse
p = argparse.ArgumentParser()
p.add_argument('--database-id')
p.add_argument('--op', choices=['add-field', 'set-records'])
p.parse_args()
'''

SPACE_API = '''import sys
import argparse
APIS = {'space.workspace.list-nodes': ['--space-id', '--limit']}
api = sys.argv[1] if len(sys.argv) > 1 else ''
if api in APIS:
    p = argparse.ArgumentParser(prog='space_api.py ' + api)
    for f in APIS[api]:
        p.add_argument(f)
    p.parse_args(sys.argv[2:])
else:
    if api.startswith('space.'):
        # 真平台行为：未知 api 是 rc=0 + 一行 error 载荷（不是非零退出）
        print('{"error": "code=INVALID_PARAMS; msg=unknown api: ' + api + '"}')
    else:
        print('usage: space_api.py <api> [--stdin]')
        print('apis:')
        for k in APIS:
            print('  ' + k)
'''

NO_CLI = '''print('我是没有 CLI 契约的脚本，收到 --help 会照跑主逻辑')
'''

CALLER = '''def api(*a, **kw):
    return a


def use():
    api('database/db_edit.py', '--database-id', 'db1', '--op', 'set-records', '--limit', '60')
    api('space_api.py', 'space.workspace.list-nodes', '--space-id', 's1', '--limit', '60')


DBW = f'{LIB}/database/db_wrap.py'


def _db_call(script, argv):
    return script, argv


def _db_edit():
    argv = ['--database-id', 'db1', '--op', 'set-records']
    return _db_call(DBW, argv)
'''

fails = []


def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


def build(mutate=None):
    """造一套假环境：tmp/lib（正本侧）+ tmp/repo（调用侧）。mutate(lib, repo) 供变异。

    ⚠️ 想拿**真** library 做变异时，务必 `cp -rL $(readlink -f ~/.codebuddy/skills/library) /tmp/x`
    并断言 `[ ! -L /tmp/x ]`：`cp -r` 遇到软链只复制**链接本身**，`cd /tmp/x` 会直接进真库，
    变异就打在用户装好的平台上（2026-11-13 真踩：把 db_query 的 `--ask` 改成了 `--query`，
    已按 add_argument 行原样还原并验证 `--help` 恢复）。
    """
    tmp = tempfile.mkdtemp(prefix='librefs_')
    lib, repo = os.path.join(tmp, 'lib'), os.path.join(tmp, 'repo')
    os.makedirs(os.path.join(lib, 'database'))
    os.makedirs(os.path.join(repo, 'skill', 'scripts'))
    open(os.path.join(lib, 'database', 'db_edit.py'), 'w').write(DB_EDIT)
    open(os.path.join(lib, 'database', 'db_wrap.py'), 'w').write(DB_WRAP)
    open(os.path.join(lib, 'space_api.py'), 'w').write(SPACE_API)
    open(os.path.join(lib, 'no_cli.py'), 'w').write(NO_CLI)
    open(os.path.join(repo, 'skill', 'scripts', 'caller.py'), 'w').write(CALLER)
    if mutate:
        mutate(lib, repo)
    return tmp, lib, repo


def run(lib, repo, *args):
    env = dict(os.environ, LIB_REFS_LIB=lib, LIB_REFS_ROOT=repo)
    p = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True,
                       text=True, env=env, timeout=120)
    return p.returncode, p.stdout + p.stderr


def main():
    # ── 1. 基线：必须全绿，且 `--limit 60` 不得被当枚举值 ──────────────────
    print('基线')
    tmp, lib, repo = build()
    try:
        rc, out = run(lib, repo, '--probe')
        check('全绿 rc=0', rc == 0, f'rc={rc} {out[:200]}')
        check('报告探活全通', '探活全通' in out, out[:200])
        check('数字不当枚举（`60` 不报失配）', '60' not in out, out[:200])
        check('子命令级 --help 生效（无假阳性）', '参数契约失配' not in out, out[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ── 2~7. 逐层注射破坏，必须红在对的层 ─────────────────────────────────
    cases = []

    def rename_flag(lib, repo):
        p = os.path.join(lib, 'database', 'db_edit.py')
        s = open(p).read().replace("'--op'", "'--action'")
        open(p, 'w').write(s)
    cases.append(('参数改名 → L3', rename_flag, '--probe --strict', 1,
                  ['参数契约失配', '--op']))

    def wrap_flag(lib, repo):
        # 只改包装脚本：变量中转 + 局部 argv，正则截片段看不见的那种写法
        p = os.path.join(lib, 'database', 'db_wrap.py')
        s = open(p).read().replace("'--op'", "'--action'")   # 先读完再截断，否则写出空文件
        open(p, 'w').write(s)
    cases.append(('包装写法（变量+局部 argv）→ L3', wrap_flag, '--probe --strict', 1,
                  ['参数契约失配', '--op', 'caller.py']))

    def drop_enum(lib, repo):
        p = os.path.join(lib, 'database', 'db_edit.py')
        s = open(p).read().replace("['add-field', 'set-records']", "['add-field']")
        open(p, 'w').write(s)
    cases.append(('枚举值被删 → L3', drop_enum, '--probe --strict', 1,
                  ['参数契约失配', 'set-records']))

    def break_import(lib, repo):
        p = os.path.join(lib, 'database', 'db_edit.py')
        open(p, 'w').write('import no_such_module_520pro\n' + DB_EDIT)
    cases.append(('import 炸 → L2', break_import, '--probe --strict', 1,
                  ['探活失败', 'no_such_module_520pro']))

    def rename_sub(lib, repo):
        p = os.path.join(lib, 'space_api.py')
        s = open(p).read().replace('space.workspace.list-nodes', 'space.workspace.list_nodes')
        open(p, 'w').write(s)
    cases.append(('子命令改名 → L3', rename_sub, '--probe --strict', 1,
                  ['子命令已不存在', 'space.workspace.list-nodes']))

    def drop_file(lib, repo):
        os.remove(os.path.join(lib, 'database', 'db_edit.py'))
    cases.append(('正本文件消失 → L1', drop_file, '--probe --strict', 1,
                  ['外部正本引用失配', 'db_edit.py']))

    def no_cli_ref(lib, repo):
        p = os.path.join(repo, 'skill', 'scripts', 'caller.py')
        open(p, 'a').write("\n\ndef use2():\n    api('no_cli.py', '--whatever')\n")
    cases.append(('无 CLI 契约 → 不执行、无法判定', no_cli_ref, '--probe', 2,
                  ['无法判定', '不贸然执行']))

    for title, mut, args, want_rc, want_tokens in cases:
        print(title)
        tmp, lib, repo = build(mut)
        try:
            rc, out = run(lib, repo, *args.split())
            check(f'rc={want_rc}', rc == want_rc, f'实际 rc={rc} · {out[:300]}')
            for tok in want_tokens:
                check(f'输出含 `{tok}`', tok in out, out[:300])
            # 真判据：无 CLI 契约的脚本不能被真执行（它的 print 就是副作用探针）
            check('无 CLI 契约的脚本没被强行执行', '收到 --help 会照跑主逻辑' not in out, out[:300])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ── 8. 只读性：检查器不得写/删任何东西 ────────────────────────────────
    print('只读性元检查')
    src = open(SCRIPT, encoding='utf-8').read()
    banned = {'os.remove': r'\bos\.remove\s*\(', 'shutil.rmtree': r'\bshutil\.rmtree\s*\(',
              'open(...,w': r"open\([^)]*,\s*['\"]w['\"]", 'os.rmdir': r'\bos\.rmdir\s*\('}
    hits = [n for n, p in banned.items() if __import__('re').search(p, src)]
    check('检查器无写/删分支', not hits, '发现: ' + ', '.join(hits) if hits else '')

    print(f'失败 {len(fails)} 处')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
