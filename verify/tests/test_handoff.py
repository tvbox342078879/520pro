#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程F-4 检查：交接摘要三项齐全 + 版本不过期

判据（B-07 的执行面）：
  ① 文件存在；
  ② 三个必载段齐全（当前主线 / 版本与位置 / 习惯快照指针）——缺一项就等于"只知道在哪、不知道在干啥"；
  ③ 写的版本号 == VERSION（**过期即红**：交接摘要写着旧版本，接手的人会按旧口径干活）；
  ④ 在 git 仓内时，"当前主线自检口径"那句还在（提醒接手的人先跑 verify）。

只查"是否过期/是否缺项"，不查文字质量——那机器判不了（三态不标注就是骗自己）。
用法：python3 verify/tests/test_handoff.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
H = os.path.join(REPO, 'docs', 'handoff_latest.md')
FAIL, PASS = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + detail))


def main():
    if not os.path.exists(H):
        check('docs/handoff_latest.md 存在', False, H)
        print('结果：0 ✓ / 1 ✗')
        return 1
    body = open(H, encoding='utf-8').read()
    check('文件存在', True)
    for key in ('当前主线', '版本与位置', '习惯快照指针'):
        check(f'必载段「{key}」', key in body)

    ver = ''
    try:
        ver = open(os.path.join(REPO, 'VERSION'), encoding='utf-8').read().strip().splitlines()[0]
    except Exception:
        pass
    m = re.search(r'版本[:：]\s*`?(\d+\.\d+\.\d+)', body)
    got = m.group(1) if m else ''
    check(f'版本号与 VERSION 一致（{got} vs {ver}）', bool(ver) and got == ver,
          '交接摘要过期：接手的人会按旧版本口径干活')

    check('含"先跑自检"的提醒', 'verify.sh' in body)
    print('结果：%d ✓ / %d ✗' % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
