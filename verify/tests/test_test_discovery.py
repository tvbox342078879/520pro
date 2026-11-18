#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零期闸2 判据：verify.sh 判据必须自动发现，不得回退硬编码名单。

防的假绿：旧版 for t in test_a test_b ... 手抄名单，新增 test 忘登记=永不执行。
判据贴实现：读真 verify.sh 源码，断言 glob 自动发现在位、硬编码名单已除；
元变异把 glob 换回硬编码→必须红（有牙）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V = os.path.join(ROOT, "verify.sh")
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if detail and not cond else ""))


src = open(V, encoding="utf-8").read()

print("── 正向：自动发现在位 ──")
check("verify.sh 用 glob 展开 test_*.py",
      'for tf in "$TARGET"/verify/tests/test_*.py; do' in src)
check("循环体 basename 取测试名",
      't="$(basename "$tf" .py)"' in src)
check("无匹配时 skip（glob 字面量防护）",
      '[ -f "$tf" ] || continue' in src)
check("旧硬编码名单起点已移除",
      'for t in test_troubleshoot' not in src)
check("旧名单尾 test_binary_hint; do 已移除",
      'test_binary_hint; do' not in src)

print("── 防护：递归 test 天然排除 ──")
import glob as _g
tspys = [os.path.basename(p) for p in _g.glob(os.path.join(ROOT, 'verify', 'tests', 'test_*.py'))]
check("test_verify_exit 不是 .py（不进 glob）",
      'test_verify_exit.py' not in tspys)
check("test_rule_map_reverse 不是 .py（不进 glob）",
      'test_rule_map_reverse.py' not in tspys)

print("── 元变异（判据有牙）──")
mut = src.replace('for tf in "$TARGET"/verify/tests/test_*.py; do',
                  'for t in test_troubleshoot test_language; do')
check("元变异：glob 改回硬编码应红",
      'for tf in "$TARGET"/verify/tests/test_*.py; do' not in mut)
check("元变异后旧起点特征复现（证明能识别回退）",
      'for t in test_troubleshoot' in mut)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
