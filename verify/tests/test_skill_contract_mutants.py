#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_skill_contract_mutants.py — C1-C7 判据的必红变异（拆掉任一条判据必须翻红）

【为什么需要这个文件】
verify.sh 每天报「技能契约 84 项通过」，但在此之前没有任何一条测试证明过
这些 ✓ 是「会红的 ✓」。判据坏掉的样子是静默的：
  · 把 C5 的 sha256 换成 os.path.samefile —— symlink 场景下永远相同，副本脱节也不报
  · 把 C3 的 re.search 换成 `in` —— 正则里的 `|` 变成字面量，五组永远判缺
  · 把 C4 的三处对账少接一处 —— 版本漂移照样绿
输出还是 84 ✓，仓库已经坏了。**判据全绿 ≠ 判据有效。**

【做法】
造一个自包含的临时副本（仓 + 假 install root），对每条判据各打一个变异，断言三件事：
  ① 变异真的落盘（不是「我改了它应该红了」）
  ② 对应判据项变红
  ③ 变红理由指向预期原因（不是随便哪条红了就算过）
最后还原并重跑基线，确认没有残留污染。

【三条纪律（都是这个仓库踩过的）】
  1. 变异前必须先读原文再写。`open(p,'w').write(open(p).read().replace(...))`
     会先截断再读，写出空文件——变异没生效，测试却「绿」了（lib_refs 那轮的真实事故）。
  2. 断言落盘，不靠意图。每个变异函数自己 re-read 校验新内容在、旧内容不在。
  3. 还原后内存比对全文。少还原一个字节，下一个用例就跑在污染状态上，
     红的原因就说不清了。

退出码：0 全通 / 1 有用例未按预期变红
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CHK = os.path.join(ROOT, 'verify', 'skill_contract_check.py')

fails = []


def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


def read(p):
    return open(p, encoding='utf-8', errors='ignore').read()


def write(p, s):
    open(p, 'w', encoding='utf-8').write(s)


def build():
    """tmp/repo（整仓副本，排除 .git）+ tmp/install/<name>（假安装根）。

    假安装根让本测试自包含：不依赖本机是否装过技能，CI/新机上也能跑。
    """
    tmp = tempfile.mkdtemp(prefix='skillmut-')
    repo = os.path.join(tmp, 'repo')
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))

    import json
    reg = json.load(open(os.path.join(repo, 'verify', 'skill_contracts.json'), encoding='utf-8'))
    install = os.path.join(tmp, 'install')
    os.makedirs(install)
    for name, spec in reg['skills'].items():
        src = os.path.join(repo, spec['path'])
        if os.path.isdir(src):
            # 完整复制：C5 逐文件 sha256 比对，少一件就成「装副本缺失」
            shutil.copytree(src, os.path.join(install, name),
                            ignore=shutil.ignore_patterns('__pycache__'))
    return tmp, repo, install, reg


def run(repo, install):
    p = subprocess.run([sys.executable, CHK, '--repo', repo, '--install', install,
                        '--require-mirror'],
                       capture_output=True, text=True, timeout=180)
    return p.stdout + p.stderr, p.returncode


def line_of(out, cid, name):
    for l in out.split('\n'):
        if f'[{cid}]' in l and name in l:
            return l.strip()
    return ''


def verdict(out, cid, name):
    """'✗' / '⚠' / '✓' / '·' / ''（无该行）"""
    l = line_of(out, cid, name)
    for m in ('✗', '⚠', '✓', '·'):
        if f'] {name}:' in l and m in l:
            return m
    return ''


def summary(out):
    for l in out.split('\n'):
        if l.startswith('结果：'):
            return l.strip()
    return ''

# ── 变异用例：(说明, 判据项, 目标技能, 期望关键词, 变异函数) ─────────────
# 变异函数返回 (undo, 内容快照)；undo 无参调用即还原。


def mut_c1(repo, install):
    """C1 结构：删掉 required_files 里的一件。"""
    p = os.path.join(repo, '通用层/skills/artifact-store/CHANGELOG.md')
    orig = read(p)
    os.remove(p)
    assert not os.path.exists(p), '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_c2(repo, install):
    """C2 头部：version 写成非法 semver（2.7 缺修订号）。"""
    p = os.path.join(repo, '通用层/skills/space-hub/SKILL.md')
    orig = read(p)
    new = re.sub(r'(?m)^version:\s*"[\d.]+"', 'version: "2.7"', orig, count=1)
    write(p, new)
    got = read(p)
    assert 'version: "2.7"' in got and got != orig, '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_c3(repo, install):
    """C3 描述五组：删掉 description 里全部负边界词。

    只动 front matter，正文不动——D5 查的是 desc，正文里还有「不要用于」不能算数。
    """
    p = os.path.join(repo, '通用层/skills/artifact-store/SKILL.md')
    orig = read(p)
    parts = orig.split('---')
    assert len(parts) >= 3, 'front matter 结构异常，变异无法进行'
    head = parts[1]
    for w in ('不要用于', '不适用于', '别用于', '边界'):
        head = head.replace(w, '此处')
    write(p, '---'.join([parts[0], head] + parts[2:]))
    got = read(p)
    assert got != orig, '变异未落盘'
    for w in ('不要用于', '不适用于', '别用于', '边界'):
        assert w not in got.split('---')[1], f'负边界词 {w} 未删除'
    return (lambda: write(p, orig)), orig


def mut_c4(repo, install):
    """C4 版本四处：CHANGELOG 首条版本改成 v0.0.1。"""
    p = os.path.join(repo, '通用层/skills/inspect-hub/CHANGELOG.md')
    orig = read(p)
    m = re.search(r'(?m)^## v([\d.]+)', orig)
    assert m, 'CHANGELOG 首条无版本号，变异无法进行'
    old = m.group(1)
    new = orig.replace(f'## v{old}', '## v0.0.1', 1)
    write(p, new)
    assert '## v0.0.1' in read(p), '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_c5(repo, install):
    """C5 镜像一致：仓内改一个字节，安装副本不动。"""
    p = os.path.join(repo, '通用层/skills/learn-hub/scripts/learn.py')
    orig = read(p)
    write(p, orig + '\n# mutation probe\n')
    got = read(p)
    assert '# mutation probe' in got and got != orig, '变异未落盘'
    return (lambda: write(p, orig)), orig


def mut_c6(repo, install):
    """C6 触发样本：T 组删到不足阈值（T≥8 → 5）。"""
    p = os.path.join(repo, '能力层/tvbox/skills/probe-hub/references/trigger-samples.md')
    orig = read(p)
    parts = re.split(r'(?m)^### (T\d+)\s*$', orig)
    keep, i = [parts[0]], 1
    while i < len(parts):
        tag, body = parts[i], parts[i + 1]
        if tag not in ('T04', 'T05', 'T06', 'T07', 'T08'):
            keep += [f'### {tag}\n', body]
        i += 2
    write(p, ''.join(keep))
    got = read(p)
    assert '### T04' not in got and '### T03' in got, '变异未落盘（T 组未按预期删除）'
    return (lambda: write(p, orig)), orig


def mut_c7(repo, install):
    """C7 体积：把 SKILL.md 撑过 40KB（阈值 40KB，必须真超）。"""
    p = os.path.join(repo, '通用层/skills/artifact-store/SKILL.md')
    orig = read(p)
    write(p, orig + '\n' + ('填充说明。' * 4000) + '\n')
    size = os.path.getsize(p)
    assert size > 40 * 1024, f'变异未落盘：{size}B 未超 40KB（先算字节，别信感觉）'
    return (lambda: write(p, orig)), orig


CASES = [
    ('C1 删 required_files 一件', 'C1', 'artifact-store', '缺件', mut_c1),
    ('C2 version 非法 semver', 'C2', 'space-hub', '非 semver', mut_c2),
    ('C3 删 description 负边界', 'C3', 'artifact-store', 'negative_boundary', mut_c3),
    ('C4 CHANGELOG 版本改错', 'C4', 'inspect-hub', '版本不一致', mut_c4),
    ('C5 仓内改动不重装', 'C5', 'learn-hub', '内容不同', mut_c5),
    ('C6 触发样本 T 组不足', 'C6', 'probe-hub', '样本分组不足', mut_c6),
    ('C7 SKILL.md 超体积上限', 'C7', 'artifact-store', '上限', mut_c7),
]


def main():
    if not os.path.isfile(CHK):
        print(f'  ✗ 检查器不存在：{CHK}')
        return 1

    print('造临时副本（仓 + 假安装根）')
    tmp, repo, install, reg = build()
    try:
        base_out, base_rc = run(repo, install)
        base = summary(base_out)
        check('基线无失败（副本与真仓一致）', base_rc == 0 and '0 ✗' in base, base)
        print(f'    {base}')

        print('\n逐条变异（每条都必须变红）')
        for desc, cid, name, keyword, fn in CASES:
            undo, orig = fn(repo, install)
            try:
                out, rc = run(repo, install)
                v = verdict(out, cid, name)
                line = line_of(out, cid, name)
                went_red = v in ('✗', '⚠')
                check(f'{desc} → {cid} 变红', went_red, f'实际 {v or "无该行"}：{line[:120]}')
                check(f'{desc} → 理由指向预期', keyword in line, f'期望含「{keyword}」，实际：{line[:120]}')
                # 不误伤：指的是**别的技能**不该跟着红。
                # 同一技能内多条判据连带红是真实耦合、不是误伤——删 CHANGELOG 必然让
                # C4（首条无版本号）与 C5（装副本多一件）一起响，改 version 必然让
                # C4（版本不一致）与 C5（内容不同）一起响。把它们当误伤会把正确行为判错。
                others = [l.strip()[:60] for l in out.split('\n')
                          if ('  ✗ [' in l or '  ⚠ [' in l) and f'] {name}:' not in l]
                base_others = [l.strip()[:60] for l in base_out.split('\n')
                               if ('  ✗ [' in l or '  ⚠ [' in l) and f'] {name}:' not in l]
                check(f'{desc} → 不误伤其他技能', len(others) <= len(base_others),
                      f'{others} vs 基线 {base_others}')
            finally:
                undo()
                # 还原校验：文件必须**在**且内容逐字相同。
                # 不能写成「不存在也算过」——C1 删的正是文件，undo 失败时该分支会放行。
                rp = _path_of(cid, name, repo)
                check(f'{desc} → 已还原',
                      os.path.exists(rp) and read(rp) == orig,
                      '还原后文件缺失或内容不一致')

        out, rc = run(repo, install)
        check('全部还原后基线恢复', summary(out) == base, f'{summary(out)} vs {base}')
        check('退出码回到 0', rc == 0, f'rc={rc}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print(f'✗ {len(fails)} 项未通过：{fails[:5]}')
        return 1
    print(f'✓ C1-C7 判据全部可按预期变红（{len(CASES)} 条）')
    return 0


def _path_of(cid, name, repo):
    """还原校验用：返回该用例实际变异的文件路径。"""
    return {
        ('C1', 'artifact-store'): os.path.join(repo, '通用层/skills/artifact-store/CHANGELOG.md'),
        ('C2', 'space-hub'): os.path.join(repo, '通用层/skills/space-hub/SKILL.md'),
        ('C3', 'artifact-store'): os.path.join(repo, '通用层/skills/artifact-store/SKILL.md'),
        ('C4', 'inspect-hub'): os.path.join(repo, '通用层/skills/inspect-hub/CHANGELOG.md'),
        ('C5', 'learn-hub'): os.path.join(repo, '通用层/skills/learn-hub/scripts/learn.py'),
        ('C6', 'probe-hub'): os.path.join(repo, '能力层/tvbox/skills/probe-hub/references/trigger-samples.md'),
        ('C7', 'artifact-store'): os.path.join(repo, '通用层/skills/artifact-store/SKILL.md'),
    }[(cid, name)]


if __name__ == '__main__':
    sys.exit(main())
