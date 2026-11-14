#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""commit-msg 四字段闸的变异回归（工程纪律 §9「先查再造」+ 交接闭环）

为什么要这个测试：四字段本身只是格式检查，**Reuse 与暂存清单的对账**才是把
「纸面承诺」变成「机制」的那一步——没有对账，AI 写一句「新建 0」就能带着三个新文件过关。

铁律（本轮会话踩过）：**先断言输入真落盘 / 真进暂存，再看闸的判定**。
否则测试自己骗人——例 4 如果忘了 git add，暂存是空的，闸会放行，
你会误判成「对账失效」，然后去改一段本来没坏的代码。

每例都在**临时 git 仓库**里跑（真目录、非软链），不碰本仓库暂存区。
用法：python3 verify/tests/test_commit_fields.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, 'hooks', 'commit-msg')
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + detail))


def sh(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


def make_repo(base):
    d = os.path.join(base, 'r')
    os.makedirs(d)
    sh(['git', 'init', '-q'], d)
    sh(['git', 'config', 'user.email', 't@example.com'], d)
    sh(['git', 'config', 'user.name', 't'], d)
    return d


def clean(d):
    """清暂存 + 清工作区（.git 除外），保证每例从零开始。"""
    sh(['git', 'reset', '-q'], d)
    for root, dirs, files in os.walk(d):
        if '.git' in dirs:
            dirs.remove('.git')
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except OSError:
                pass


def stage(d, rel, content='x\n'):
    """造文件并 git add，返回是否真进了暂存（不变量，必须先断言）。"""
    p = os.path.join(d, rel)
    parent = os.path.dirname(p)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(content)
    sh(['git', 'add', '-A'], d)
    # ★ 必须 -c core.quotepath=false：git 默认把中文名转义成 "docs/\346\226\260..."，
    #   直接比对永远不相等——首版就栽在这里，例 4 的前置断言假红（钩子其实是对的）。
    out = sh(['git', '-c', 'core.quotepath=false', 'diff', '--cached', '--name-only'], d).stdout
    return rel in out.splitlines()


def run_hook(d, msg, hook=None):
    mf = os.path.join(d, '.commitmsg')
    with open(mf, 'w', encoding='utf-8') as f:
        f.write(msg)
    return sh(['bash', hook or HOOK, mf], d)


GOOD = (
    "v9.9.9 测试提交\n\n正文：做了什么。\n\n"
    "Verify: bash verify.sh → 0 ✗ / 0 失败\n"
    "Lesson: 无\n"
    "Next: 做事 — 起点：a.py — 完成判据：跑通\n"
    "Reuse: docs/工程纪律.md 扩展\n"
)


def case1_missing_next(d):
    msg = "t\n\nVerify: bash verify.sh → 0 ✗ / 0 失败\nLesson: 无\nReuse: x 扩展\n"
    r = run_hook(d, msg)
    check('例1 缺 Next 行 → 拒', r.returncode != 0 and '缺 Next' in r.stdout,
          f'rc={r.returncode} out={r.stdout[-120:]}')


def case2_next_no_criteria(d):
    msg = GOOD.replace('Next: 做事 — 起点：a.py — 完成判据：跑通',
                       'Next: 做事 — 起点：a.py')
    assert '完成判据：' not in msg.split('Next: ')[1].split('\n')[0], '变异未落盘'
    r = run_hook(d, msg)
    check('例2 Next 缺「完成判据」→ 拒', r.returncode != 0 and '完成判据' in r.stdout,
          f'rc={r.returncode} out={r.stdout[-120:]}')


def case3_lesson_no_ledger(d):
    msg = GOOD.replace('Lesson: 无', 'Lesson: 病4（第 2 次）')
    assert '病4' in msg, '变异未落盘'
    staged = sh(["git", "-c", "core.quotepath=false", "diff", "--cached", "--name-only"], d).stdout
    check('例3 前置：暂存里确实没有通病台账', 'docs/通病台账.md' not in staged, f'staged={staged!r}')
    r = run_hook(d, msg)
    check('例3 声称复发却未改台账 → 拒', r.returncode != 0 and '通病台账' in r.stdout,
          f'rc={r.returncode} out={r.stdout[-120:]}')


def case4_reuse_lie(d):
    msg = GOOD.replace('Reuse: docs/工程纪律.md 扩展', 'Reuse: 复用现有件，新建 0')
    assert '新建 0' in msg, '变异未落盘'
    ok = stage(d, 'docs/新机制.md')
    check('例4 前置：新文件真进了暂存', ok, '没 add 成功，后面的判定无意义')
    r = run_hook(d, msg)
    check('例4 Reuse 写「新建 0」却新增文件 → 拒',
          r.returncode != 0 and '实际新增' in r.stdout,
          f'rc={r.returncode} out={r.stdout[-140:]}')


def case5_meta_mutation(d):
    """元变异：把钩子 ④ 的对账分支短路，例 4 的同一输入必须能溜过去。

    这一例证明的是「例 4 的拒绝来自对账，不是来自别的检查」——
    判据被废掉时仍然全绿，正是假绿的样子。
    """
    src = open(HOOK, encoding='utf-8').read()
    mut = src.replace('if [ -n "$ACTUAL" ]; then', 'if false; then')
    check('例5 前置：变异真写进钩子副本', mut != src and 'if false; then' in mut,
          '替换点没命中，元变异无效')
    mp = os.path.join(d, 'hook_mut.sh')
    with open(mp, 'w', encoding='utf-8') as f:
        f.write(mut)
    msg = GOOD.replace('Reuse: docs/工程纪律.md 扩展', 'Reuse: 复用现有件，新建 0')
    r = run_hook(d, msg, hook=mp)
    check('例5 对账被废后同一输入放行（证明例4 的拒绝来自对账）', r.returncode == 0,
          f'rc={r.returncode} out={r.stdout[-140:]}')


def case6_good_passes(d):
    r = run_hook(d, GOOD)
    check('例6 四字段齐全 → 放行', r.returncode == 0, f'rc={r.returncode} out={r.stdout[-140:]}')


def case7_declared_but_not_added(d):
    msg = GOOD.replace('Reuse: docs/工程纪律.md 扩展',
                       'Reuse: 新建 docs/查过的文件.md —— 已查 registry/工程纪律/通病台账/verify，无重叠')
    assert '新建 docs/查过的文件.md' in msg, '变异未落盘'
    r = run_hook(d, msg)
    check('例7 声明新建但未 add 该文件 → 拒',
          r.returncode != 0 and '没有新增它' in r.stdout,
          f'rc={r.returncode} out={r.stdout[-120:]}')


def case8_new_without_four_checks(d):
    msg = GOOD.replace('Reuse: docs/工程纪律.md 扩展',
                       'Reuse: 新建 docs/x.md —— 我觉得需要')
    ok = stage(d, 'docs/x.md')
    check('例8 前置：新文件真进了暂存', ok)
    r = run_hook(d, msg)
    check('例8 声称新建但没写「已查」→ 拒',
          r.returncode != 0 and '没写四查' in r.stdout,
          f'rc={r.returncode} out={r.stdout[-120:]}')


def case9_new_disease_no_ledger(d):
    """「新病：」与「病N（第K次）」同等对待——不然写个新病名就能绕过回流。"""
    msg = GOOD.replace('Lesson: 无', 'Lesson: 新病：中文名转义后比对永远失败')
    assert '新病：' in msg, '变异未落盘'
    r = run_hook(d, msg)
    check('例9 「新病：」却未改台账 → 拒',
          r.returncode != 0 and '通病台账' in r.stdout,
          f'rc={r.returncode} out={r.stdout[-120:]}')


def case10_lesson_with_ledger(d):
    """反向用例：记了病且台账**真改了** → 必须放行。

    这个用例是补窟窿的。首版只测「没改台账要拒」，没测「改了台账别误拒」，
    结果真提交时被自己的闸拦住：台账是既有文件，改动是 M，
    而首版用的是 --diff-filter=A（只列新增），永远查不到它。
    **只测拒绝不测放行，闸会变成假阳性制造机。**
    """
    # 先让台账成为已跟踪文件（真实场景里它早就在库里），再修改它
    assert stage(d, 'docs/通病台账.md', '旧内容\n'), '初始台账未进暂存'
    sh(['git', 'commit', '-q', '-m', 'init', '--no-verify'], d)
    check('例10 前置：台账改动类型是 M（不是 A）',
          stage(d, 'docs/通病台账.md', '旧内容\n## 病10\n'),
          '若这一步不是修改语义，用例就模拟不到真实场景')
    msg = GOOD.replace('Lesson: 无', 'Lesson: 病10（第 2 次）')
    r = run_hook(d, msg)
    check('例10 记了病且台账已改 → 放行（防假阳性）', r.returncode == 0,
          f'rc={r.returncode} out={r.stdout[-140:]}')


def case11_lazy_next(d):
    """B-14 禁词：三段齐全但内容是懒词——形式合规、语义为零，也算没方向。"""
    msg = GOOD.replace('Next: 做事 — 起点：a.py — 完成判据：跑通',
                       'Next: 后续优化 — 起点：a.py — 完成判据：跑通')
    assert '后续优化' in msg, '变异未落盘'
    r = run_hook(d, msg)
    check('例11 Next 用 B-14 懒词「后续优化」→ 拒',
          r.returncode != 0 and '懒词' in r.stdout,
          f'rc={r.returncode} out={r.stdout[-120:]}')


def case12_registry_hint(d):
    """软提示：新建 docs/*.md 未登记 registry → 放行但有 ⚠（不是硬拦）。"""
    os.makedirs(os.path.join(d, 'docs'), exist_ok=True)
    with open(os.path.join(d, 'docs', 'registry.md'), 'w', encoding='utf-8') as f:
        f.write('| 事实 | 真源 |\n|---|---|\n| 版本 | `VERSION` |\n')
    # 只 add 新文件，不把 registry.md 带进暂存（钩子只看工作区文件是否存在）
    p = os.path.join(d, 'docs', '新机制.md')
    with open(p, 'w', encoding='utf-8') as f:
        f.write('x\n')
    sh(['git', 'add', 'docs/新机制.md'], d)
    staged = sh(['git', '-c', 'core.quotepath=false', 'diff', '--cached', '--name-only'], d).stdout
    check('例12 前置：新文件真进了暂存', 'docs/新机制.md' in staged.splitlines(), f'staged={staged!r}')
    msg = GOOD.replace('Reuse: docs/工程纪律.md 扩展',
                       'Reuse: 新建 docs/新机制.md —— 已查 registry/工程纪律/通病台账/verify，无重叠')
    r = run_hook(d, msg)
    check('例12 新文件未登记 registry → 放行但出声（软提示）',
          r.returncode == 0 and '⚠' in r.stdout and 'registry.md' in r.stdout,
          f'rc={r.returncode} out={r.stdout[-160:]}')


def main():
    if not os.path.exists(HOOK):
        check('hooks/commit-msg 存在', False, HOOK)
        print('结果：0 ✓ / 1 ✗')
        return 1
    base = tempfile.mkdtemp(dir=os.path.expanduser('~/.codebuddy'), prefix='cmtest-')
    # 铁律：必须是真目录，不是软链（上一轮在 /tmp 软链上打变异，改到了真实库）
    check('临时仓是真目录且非软链', not os.path.islink(base), base)
    try:
        d = make_repo(base)
        for fn in (case1_missing_next, case2_next_no_criteria, case3_lesson_no_ledger,
                   case4_reuse_lie, case5_meta_mutation, case6_good_passes,
                   case7_declared_but_not_added, case8_new_without_four_checks,
                   case9_new_disease_no_ledger, case10_lesson_with_ledger,
                   case11_lazy_next, case12_registry_hint):
            clean(d)
            fn(d)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print('结果：%d ✓ / %d ✗' % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
