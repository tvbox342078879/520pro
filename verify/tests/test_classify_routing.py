#!/usr/bin/env python3
"""test_classify_routing.py — 归类路由判据的变异回归（拆掉实现必须翻红）。

正例 1：仓库真源当前状态 → OK
反例 3：注入破坏 → FAIL（证明判据不是摆设）
  ① 主题夹规则塞入交付词「完工」
  ② 交付词规则归口改到主题夹
  ③ base_blueprint 恢复"人读交付归 02/03/05"
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY = os.path.dirname(HERE)
sys.path.insert(0, VERIFY)

import classify_routing_check as C

RULES_REL = C.RULES_REL
BLUE_REL = C.BLUE_REL


def load():
    with open(os.path.join(C.ROOT, RULES_REL), encoding='utf-8') as f:
        rules = json.load(f).get('rules', [])
    with open(os.path.join(C.ROOT, BLUE_REL), encoding='utf-8') as f:
        blue = f.read()
    return rules, blue


passed = failed = 0


def check(name, cond, detail=''):
    global passed, failed
    if cond:
        passed += 1
        print(f'  ✓ {name}')
    else:
        failed += 1
        print(f'  ✗ {name} {detail}')


rules, blue = load()

# 正例：真源应绿
ok, errs = C.check(rules, blue)
check('正例：真源归类路由正确', ok, str(errs))

# 反例①：主题夹规则塞入交付词
bad1 = copy.deepcopy(rules)
for r in bad1:
    if str(r.get('target', '')).startswith(C.TOPIC_PREFIX):
        r['match'] = list(r.get('match', [])) + ['完工']
        break
ok1, _ = C.check(bad1, blue)
check('反例①：主题夹含交付词必须红', not ok1)

# 反例②：交付词规则归口改到主题夹
bad2 = copy.deepcopy(rules)
for r in bad2:
    if set(r.get('match', [])) & C.DELIVER_WORDS:
        r['target'] = '🧬 520进化论/03-子项目演进'
        break
ok2, _ = C.check(bad2, blue)
check('反例②：交付词归错夹必须红', not ok2)

# 反例③：蓝图旧措辞重现
bad3 = blue + '\n人读交付归 02/03/05 子夹。\n'
ok3, _ = C.check(rules, bad3)
check('反例③：蓝图旧措辞重现必须红', not ok3)

print(f'\n正向 1 + 反向 3：通过 {passed} / 失败 {failed}')
sys.exit(0 if failed == 0 else 1)
