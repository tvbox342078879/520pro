#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程F-2 回归：外置文档索引与目录**一一对应**

判据（少一条多一条都红）：
  ① 索引里的文件名集合 == 目录里的实际文件集合（排除索引自身）；
  ② 索引里每个链接目标真实存在；
  ③ 索引条目数 == 文件数（与①等价，单独报便于读）。

为什么要有：S130 瘦身后的 `manual_*.md` / `外置_*.md` 一旦改名，SKILL 里的指针会断，
而"索引表"最容易变成没人更新的死表——它比 SKILL 更容易腐烂（没人读它就没人在意）。
用法：python3 verify/tests/test_doc_index.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGETS = [
    ('能力层/tvbox/skills/tvbox-pipeline/docs', 'manual_', 'manual_索引.md'),
    ('能力层/tvbox/skills/probe-hub/docs', '外置_', '外置_索引.md'),
]
FAIL, PASS = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + detail))


def main():
    for rel_dir, prefix, index_name in TARGETS:
        d = os.path.join(REPO, rel_dir)
        idx = os.path.join(d, index_name)
        print(f'【{prefix}*】{rel_dir}')
        if not os.path.isdir(d):
            check('目录存在', False, d)
            continue
        if not os.path.exists(idx):
            check(f'{index_name} 存在', False, idx)
            continue
        files = {f for f in os.listdir(d)
                 if f.startswith(prefix) and f.endswith('.md') and f != index_name}
        body = open(idx, encoding='utf-8').read()
        listed = set(re.findall(r'(?<=\]\()' + re.escape(prefix) + r'[^)]+\.md', body))
        check(f'条目数=文件数（{len(listed)}/{len(files)}）', len(listed) == len(files),
              f'缺: {sorted(files - listed)} 多: {sorted(listed - files)}')
        check('文件名集合一致', listed == files,
              f'缺: {sorted(files - listed)} 多: {sorted(listed - files)}')
        missing = [f for f in listed if not os.path.exists(os.path.join(d, f))]
        check('链接目标都存在', not missing, str(missing))
        print()
    print('结果：%d ✓ / %d ✗' % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
