#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程F-5 回归：测活报告「怎么读这组数据」
四种情形必须各自说对话，且不许出现"用无法判定当分母"或"编 p95"。
用法：python3 verify/tests/test_reading_guide.py
"""
import io
import os
import re
import sys
import contextlib

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, '能力层', 'tvbox', 'skills', 'probe-hub', 'scripts'))
import livecheck as L  # noqa: E402

FAIL, PASS = [], []


def cap(ok, ng, un):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        L._print_reading_guide(ok, ng, un, ok + ng + un)
    return buf.getvalue()


def check(name, cond, out=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + out))


print('【1】正常批：分母只算有结论的条数')
o = cap([{'elapsed_ms': 100}, {'elapsed_ms': 200}],
        [{'elapsed_ms': 300, 'death_cause': '接口层'}, {'elapsed_ms': 4000, 'death_cause': '接口层'}],
        [{'elapsed_ms': 5000, 'death_cause': '未定·网络'}])
check('通过率 2/4（排除 1 条无法判定）', '通过率 50%（2/4）' in o, o)
check('p95 与中位都给', 'p95' in o and '中位' in o, o)
check('死因分布含接口层×2', '接口层×2' in o, o)

print('【2】全无法判定：不是 0%')
o = cap([], [], [{'elapsed_ms': 900, 'death_cause': '未定·网络'}])
check('写"判不了"且明确不是 0%', '不是 0%' in o and '判不了' in o, o)

print('【3】样本不足：不报 p95')
o = cap([{'elapsed_ms': 100}], [], [])
check('标注样本 <5 不具代表性', '样本 <5' in o, o)
check('不出现 p95 数值结论', re.search(r'p95 \d', o) is None, o)

print('【4】无耗时：不编数')
o = cap([{'death_cause': ''}], [{'death_cause': ''}], [])
check('无耗时走"不编数"分支', ('未采集到耗时' in o) or ('样本 <5' in o), o)

print('\n结果：%d ✓ / %d ✗' % (len(PASS), len(FAIL)))
sys.exit(0 if not FAIL else 1)
