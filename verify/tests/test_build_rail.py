#!/usr/bin/env python3
"""test_build_rail.py — S 段对账判据的变异回归（拆掉实现必须翻红）。

6 个用例：正例 + 五种漏同步形态（漏登记/写错编号/正文没落/必入缺失/缺注释）。
证明这是"会红的判据"，不是摆设。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'verify'))

import build_rail_check as B  # noqa: E402

fails = []


def case(name, cond, detail=''):
    if cond:
        print(f'  ✓ {name}')
    else:
        fails.append(f'{name}{("：" + detail) if detail else ""}')
        print(f'  ✗ {name}{("：" + detail) if detail else ""}')


SLA = """# 施工纪律
1. **S-01 进度锚点**：进度可找回。
2. **S-04 简洁输出**：结论前置。
3. **S-07 素材为准**：不编造。
"""

MOB = """# 手机指令
## 【粘贴区 · 从下一行开始复制】

<!-- build-rail: S-01,S-04,S-07 -->
你是我的助手。
15. **S-01 进度锚点**：进度可找回。
16. **S-04 简洁输出**：结论前置。
17. **S-07 素材为准**：不编造。
**【粘贴区 结束】**
说明段。
"""

print('[T1 正例]')
st, p = B.check(SLA, MOB)
case('T1 登记+正文齐全 → OK', st == 'OK', f'{st}:{p}')

print('[T2-T6 五种漏同步形态必须红]')

st, p = B.check(SLA + '4. **S-09 搜索顺序**：四范围。\n', MOB)
case('T2 真源加了 S-09 未在手机登记 → FAIL(漏同步)',
     st == 'FAIL' and any('没登记' in x for x in p), f'{st}:{p}')

st, p = B.check(SLA, MOB.replace('build-rail: S-01,S-04,S-07', 'build-rail: S-01,S-04,S-99'))
case('T3 登记写错编号 S-99 → FAIL',
     st == 'FAIL' and any('不存在' in x for x in p), f'{st}:{p}')

st, p = B.check(SLA, MOB.replace('16. **S-04 简洁输出**：结论前置。\n', ''))
case('T4 注释登记了但正文没落 S-04 → FAIL(假对账)',
     st == 'FAIL' and any('正文缺标记' in x for x in p), f'{st}:{p}')

st, p = B.check(SLA, MOB.replace('<!-- build-rail: S-01,S-04,S-07 -->',
                                '<!-- build-rail: S-01,S-07 -->'))
case('T5 必入清单 S-04 缺失 → FAIL',
     st == 'FAIL' and any('必入清单' in x for x in p), f'{st}:{p}')

st, p = B.check(SLA, MOB.replace('<!-- build-rail: S-01,S-04,S-07 -->\n', ''))
case('T6 缺 build-rail 注释 → FAIL',
     st == 'FAIL' and any('缺 build-rail' in x for x in p), f'{st}:{p}')

if fails:
    for f in fails:
        print(f'  ✗ {f}')
    print(f'\n{len(fails)} 项失败')
    sys.exit(1)
print('\nS 段对账变异回归全部通过（6 用例：正例 1 + 漏同步 5）')
sys.exit(0)
