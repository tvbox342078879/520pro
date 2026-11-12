#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程F-3 检查：每技能是否有「按症状排」的故障排查文档

判据（三态，不折叠）：
  ✓ 有 docs/TROUBLESHOOTING.md，`## ` 条目 ≥5，且无占位标记
  ✗ 有文件但条目 <5 或含占位（TODO/待补/写这里）——**这比没有更糟**：看起来有答案
  · 还没有该文件（在册待补，不算通过）

为什么门槛是 5 条：少于 5 条基本等于"只写了自己记得的那一条"，
而真正会让人卡住的往往是第 3、4 种失败形态。5 是下限不是目标。

用法：python3 verify/tests/test_troubleshoot.py [--min 5]
退出码：0 无 ✗（· 不算失败）/ 1 有 ✗
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 只认明确的占位形态：裸"待补"会误伤正文里对状态名的引用（如「⚪ 在册待补」）
PLACEHOLDER = re.compile(r'TODO|写这里|（此处|XXX|（待补|^\s*-\s*待补', re.M)

SKILL_DIRS = [
    '通用层/skills/artifact-store', '通用层/skills/feature-gate',
    '通用层/skills/inspect-hub', '通用层/skills/learn-hub',
    '通用层/skills/machine-bootstrap', '通用层/skills/skill-evolution',
    '通用层/skills/space-hub',
    '能力层/tvbox/skills/probe-hub', '能力层/tvbox/skills/tvbox-pipeline',
    '能力层/tvbox/skills/tvbox-core',
]


def main(argv):
    need = 5
    if '--min' in argv:
        need = int(argv[argv.index('--min') + 1])
    ok = bad = todo = 0
    for rel in SKILL_DIRS:
        name = os.path.basename(rel)
        p = os.path.join(REPO, rel, 'docs', 'TROUBLESHOOTING.md')
        if not os.path.exists(p):
            print(f'  · [{name}] 还没有 docs/TROUBLESHOOTING.md（在册待补，不算通过）')
            todo += 1
            continue
        body = open(p, encoding='utf-8').read()
        # 只数二级标题（`## 1. …`），文档自己的说明段与一级标题不算
        n = len(re.findall(r'(?m)^##\s+\S', body))
        ph = PLACEHOLDER.search(body)
        if n < need:
            print(f'  ✗ [{name}] 只有 {n} 条（要求 ≥{need}）')
            bad += 1
        elif ph:
            print(f'  ✗ [{name}] 含占位标记「{ph.group(0)}」——看起来有答案比没有更糟')
            bad += 1
        else:
            print(f'  ✓ [{name}] {n} 条症状')
            ok += 1
    print(f'\n结果：{ok} ✓ ｜ {bad} ✗ ｜ {todo} ·（待补）')
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
