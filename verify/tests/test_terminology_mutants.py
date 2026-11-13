#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_terminology_mutants.py — T1-T5 口径判据的必红变异

【为什么需要】
`verify/terminology_check.py` 348 行、5 类判据，在本文件之前**一条测试都没有**。
它查的是文档：编号有没有跳号、引用有没有断链、规则说的验证入口是否真的存在。
文档是这个仓里改得最勤的东西，所以这 5 条判据最容易在「顺手改一句」里悄悄失效——
失效的样子是继续输出「口径机检通过」。

【做法】
临时副本上对每条判据各打一个变异（改真源或改文档），断言：
  ① 变异真的落盘 ② 对应 T 项变红 ③ 理由指向预期原因
最后还原并重跑基线。

退出码：0 全通 / 1 有用例未按预期变红
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CHK = os.path.join(ROOT, 'verify', 'terminology_check.py')

fails = []


def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


def read(p):
    return open(p, encoding='utf-8', errors='ignore').read()


def write(p, s):
    open(p, 'w', encoding='utf-8').write(s)


def run(repo):
    p = subprocess.run([sys.executable, CHK, '--repo', repo],
                       capture_output=True, text=True, timeout=180)
    return p.stdout + p.stderr, p.returncode


def line_of(out, cid):
    for l in out.split('\n'):
        if f'[{cid}]' in l:
            return l.strip()
    return ''


def verdict(out, cid):
    l = line_of(out, cid)
    for m in ('✗', '⚠', '✓', '·'):
        if f'] ' in l and m in l:
            return m
    return ''


def summary(out):
    for l in out.split('\n'):
        if l.startswith('结果：'):
            return l.strip()
    return ''


C8 = '通用层/rules/core-8.md'
RMAP = 'verify/rule_map.json'


def mut_t1_shift(repo):
    """T1：B-05 写成 B-07 —— 编号与序号错位。"""
    p = os.path.join(repo, C8)
    orig = read(p)
    new = orig.replace('**B-05 零明文凭证**', '**B-07 零明文凭证**', 1)
    write(p, new)
    assert new != orig and '**B-07 零明文凭证**' in read(p), '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_t1_notag(repo):
    """T1：删掉第 3 条的 B-03 标注 —— 序号还在，标签悬空。"""
    p = os.path.join(repo, C8)
    orig = read(p)
    m = re.search(r'(?m)^(3\.\s+\*\*)B-03(\s)', orig)
    assert m, '第 3 条 B-03 标注未找到，变异无法进行'
    new = orig[:m.start()] + m.group(1) + m.group(2) + orig[m.end():]
    write(p, new)
    assert '**B-03 ' not in read(p), '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_t2_gap(repo):
    """T2：删掉 M4 条目 —— 元规则编号跳号。"""
    p = os.path.join(repo, C8)
    orig = read(p)
    lines = orig.split('\n')
    keep, deleted = [], 0
    for l in lines:
        if re.match(r'^- \*\*M4\s', l):
            deleted += 1
            continue
        keep.append(l)
    assert deleted == 1, f'M4 条目应恰好 1 条，实际 {deleted}'
    write(p, '\n'.join(keep))
    assert not re.search(r'(?m)^- \*\*M4\s', read(p)), '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_t3_deadlink(repo):
    """T3：文档里写一条不存在的仓内路径。"""
    p = os.path.join(repo, 'docs/handoff_latest.md')
    orig = read(p)
    write(p, orig + '\n见 `docs/这个文件不存在_变异.md`\n')
    assert '这个文件不存在_变异' in read(p), '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_t4_anchor(repo):
    """T4：改掉某个 machine 项的 anchor —— 映射过期（实现漂移但映射没跟）。"""
    p = os.path.join(repo, RMAP)
    orig = read(p)
    d = json.loads(orig)
    rules = d.get('rules') or {}
    key = next((k for k, v in rules.items() if v.get('kind') == 'machine'
                and (v.get('anchor') or '').strip()), None)
    assert key, '没有 machine 项可变异'
    old_anchor = rules[key]['anchor']
    rules[key]['anchor'] = old_anchor + '__已删除的锚点__'
    write(p, json.dumps(d, ensure_ascii=False, indent=2))
    assert '__已删除的锚点__' in read(p), '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_t4_drop(repo):
    """T4：映射表少一条 —— 规则说它有验证入口，映射里没有。"""
    p = os.path.join(repo, RMAP)
    orig = read(p)
    d = json.loads(orig)
    rules = d.get('rules') or {}
    key = sorted(rules)[0]
    dropped = rules.pop(key)
    write(p, json.dumps(d, ensure_ascii=False, indent=2))
    assert key not in (json.loads(read(p)).get('rules') or {}), '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_t5_prefix(repo):
    """T5：规则里新造一个未登记前缀 C-01。"""
    p = os.path.join(repo, C8)
    orig = read(p)
    write(p, orig + '\n> 另见 C-01 语义约束（未登记前缀，应被 T5 拦下）。\n')
    assert 'C-01' in read(p), '变异未落盘'
    return (lambda: write(p, orig)), orig


CASES = [
    ('T1 B 编号与序号错位', 'T1', '错位', mut_t1_shift),
    ('T1 条款缺 B-xx 标注', 'T1', '缺 B-xx', mut_t1_notag),
    ('T2 M 编号跳号', 'T2', '跳号', mut_t2_gap),
    ('T3 文档引用断链', 'T3', '断链', mut_t3_deadlink),
    ('T4 映射 anchor 漂移', 'T4', '锚点', mut_t4_anchor),
    ('T4 映射缺一条', 'T4', '规则无映射', mut_t4_drop),
    ('T5 未登记前缀 C-01', 'T5', 'C-01', mut_t5_prefix),
]


def main():
    if not os.path.isfile(CHK):
        print(f'  ✗ 检查器不存在：{CHK}')
        return 1

    tmp = tempfile.mkdtemp(prefix='termmut-')
    repo = os.path.join(tmp, 'repo')
    try:
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))
    except Exception as e:
        print(f'  ✗ 造副本失败：{e}')
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    try:
        base_out, base_rc = run(repo)
        base = summary(base_out)
        check('基线无失败', base_rc == 0 and '0 ✗' in base, base)
        print(f'    {base}')

        print('\n逐条变异（每条都必须变红）')
        for desc, cid, keyword, fn in CASES:
            undo, orig = fn(repo)
            try:
                out, rc = run(repo)
                v = verdict(out, cid)
                line = line_of(out, cid)
                check(f'{desc} → {cid} 变红', v == '✗', f'实际 {v or "无该行"}：{line[:120]}')
                check(f'{desc} → 理由指向预期', keyword in line, f'期望含「{keyword}」，实际：{line[:120]}')
                check(f'{desc} → 退出码 2', rc == 2, f'rc={rc}')
            finally:
                undo()

        out, rc = run(repo)
        check('全部还原后基线恢复', summary(out) == base, f'{summary(out)} vs {base}')
        check('退出码回到 0', rc == 0, f'rc={rc}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print(f'✗ {len(fails)} 项未通过：{fails[:5]}')
        return 1
    print(f'✓ T1-T5 判据全部可按预期变红（{len(CASES)} 条）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
