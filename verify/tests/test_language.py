#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程F-6 检查：中文文档里的「整段英文残留」

判据（窄口径，宁漏不误报）：
  连续 >=6 行满足全部条件才算一段英文残留：
    ① 不含任何中文字符；
    ② 不是空行/标题/表格/列表/引用行；
    ③ 不含 `/`、反引号、`=`（那多半是命令、路径、配置，不算"说明文字"）；
    ④ 不在 ``` 代码块内。
为什么这么窄：520 的 SKILL 里本来就大量出现英文命令、路径、字段名——按"出现英文单词"
判会天天红，红了就没人看。真正要抓的是**整段英文说明被粘进中文文档**（换模型/复制外文
资料时最常见），那种段落里通常一个命令都没有。

用法：python3 verify/tests/test_language.py
退出码：0 无残留 / 1 有残留
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CJK = re.compile(r'[\u4e00-\u9fff]')
TARGETS = [
    '通用层/skills/*/SKILL.md',
    '能力层/tvbox/skills/*/SKILL.md',
    'docs/registry.md',
    'docs/handoff_latest.md',
]
MIN_RUN = 6


def runs_in(path):
    lines = open(path, encoding='utf-8', errors='ignore').read().splitlines()
    incode, cur, out = False, [], []
    for i, l in enumerate(lines, 1):
        s = l.strip()
        if s.startswith('```'):
            incode = not incode
            if cur:
                out.append((cur[0], len(cur))); cur = []
            continue
        if incode:
            if cur:
                out.append((cur[0], len(cur))); cur = []
            continue
        structural = (not s) or s.startswith(('#', '|', '-', '*', '>')) or ('/' in s) or ('`' in s) or ('=' in s)
        if structural:
            if cur:
                out.append((cur[0], len(cur))); cur = []
            continue
        if CJK.search(s):
            if cur:
                out.append((cur[0], len(cur))); cur = []
        else:
            cur.append(i)
    if cur:
        out.append((cur[0], len(cur)))
    return [(a, n) for a, n in out if n >= MIN_RUN]


def main():
    import glob
    bad = 0
    checked = 0
    for pat in TARGETS:
        for p in glob.glob(os.path.join(REPO, pat)):
            checked += 1
            rs = runs_in(p)
            rel = os.path.relpath(p, REPO).replace('\\', '/')
            if rs:
                bad += 1
                print(f'  ✗ [{rel}] 英文整段 {len(rs)} 处：' +
                      '、'.join(f'L{a}起{n}行' for a, n in rs[:3]))
            else:
                print(f'  ✓ [{rel}] 无英文整段')
    print(f'\n结果：{checked - bad} ✓ ｜ {bad} ✗（检查 {checked} 份文档）')
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
