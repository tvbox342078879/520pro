#!/usr/bin/env python3
# ad-audit 正门薄壳：转调 learn-hub/scripts/pan.py ad-audit（不重复实现 OCR 链）。
# 装在哪都能用：从自身位置推 skills 根，find learn-hub 同级目录。
import os
import sys
import subprocess


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    # here=.../skills/ad-audit/scripts → 上溯两级到 skills 根
    skills_root = os.path.dirname(os.path.dirname(here))
    pan = os.path.join(skills_root, 'learn-hub', 'scripts', 'pan.py')
    if not os.path.exists(pan):
        print('无法判定：learn-hub/scripts/pan.py 不在同 skills 根下——'
              '确认两个技能装到同一根（仓内 通用层/skills 或 ~/.codebuddy/skills）', file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, pan, 'ad-audit'] + sys.argv[1:])


if __name__ == '__main__':
    sys.exit(main())
