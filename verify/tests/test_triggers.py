#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""惊门（M8）触发词冲突检测器 · 回归测试（工程G-1）

跑法：python3 verify/tests/test_triggers.py
退出码：0 全过 / 2 有失败

为什么这条要单独测：惊门的判据几乎全是"字面包含"，而中文里
「归 X 管」和「不要 X」共用同一批字面词——判据稍宽就一片假红，
稍严就漏真冲突。故用真仓库做正例、临时改动做反例，双向卡住。
"""
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, '通用层', 'skills', 'inspect-hub', 'scripts'))
import inspect_hub as H  # noqa: E402

ART = os.path.join(REPO, '通用层', 'skills', 'artifact-store', 'SKILL.md')
fails = []


def check(name, got, want):
    ok = got == want
    print(('  ✓ ' if ok else '  ✗ ') + name + ('' if ok else f'（期望 {want}，实得 {got}）'))
    if not ok:
        fails.append(name)


def status():
    return H.chk_triggers(REPO, {}, {})['status']


def texts():
    return [i['t'] for i in H.chk_triggers(REPO, {}, {})['items']]


def with_edit(old, new, fn):
    """临时改 ART 文件 → 跑 fn → 无论如何恢复原样。"""
    bak = open(ART, encoding='utf-8').read()
    try:
        assert old in bak, f'用例前提不成立：{old!r} 不在文件里'
        open(ART, 'w', encoding='utf-8').write(bak.replace(old, new, 1))
        return fn()
    finally:
        open(ART, 'w', encoding='utf-8').write(bak)


print('【正例】真仓库应无撞车')
r = H.chk_triggers(REPO, {}, {})
check('状态为 green', r['status'], 'green')
check(f"覆盖率 {r['covered']}/{r['total']}（须全覆盖）", r['covered'], r['total'])
check('触发词总数 > 200', r['words'] > 200, True)
check('必须输出"只查字面"的边界说明',
      any('只查字面' in t for t in texts()), True)

print('【反例①】跨技能撞词 → 红')
check('撞词判红', with_edit('触发词：本地瘦身', '触发词：清理', status), 'red')

print('【反例②】删掉全部触发词来源 → 黄（不是绿）')
# v0.8.31 起触发词有两个来源：description 前置的「」口语词 + 正文「触发词：」段。
# 只删正文段已不足以造出"缺词"——两处都删光才算真的没有触发词。


def strip_all_triggers():
    bak = open(ART, encoding='utf-8').read()
    try:
        t = bak.replace('「本地瘦身」「手机变卡」「清理产物」「项目混在一起了」「会话治理」', '', 1)
        t = t.replace('触发词：本地瘦身 / 手机变卡 / 手机越用越卡 / 本地磁盘满了 / 产物归档 / '
                      '本地清理 / 清本地 / 记忆减负 / 会话治理 / 上下文纪律。 ', '', 1)
        open(ART, 'w', encoding='utf-8').write(t)
        return status()
    finally:
        open(ART, 'w', encoding='utf-8').write(bak)


check('缺词判黄', strip_all_triggers(), 'yellow')

print('【反例③】同技能重复登记 → 黄')
check('内部重复判黄', with_edit('触发词：本地瘦身', '触发词：本地瘦身 / 本地瘦身', status), 'yellow')

print('【反例④】样本不足 → 无法判定（不许装绿）')
d = tempfile.mkdtemp()
try:
    os.makedirs(os.path.join(d, '通用层', 'skills'))
    shutil.copytree(os.path.join(REPO, '通用层', 'skills', 'inspect-hub'),
                    os.path.join(d, '通用层', 'skills', 'inspect-hub'))
    check('仅 1 个技能判 unknown', H.chk_triggers(d, {}, {})['status'], 'unknown')
finally:
    shutil.rmtree(d)
d2 = tempfile.mkdtemp()
try:
    check('空目录判 unknown', H.chk_triggers(d2, {}, {})['status'], 'unknown')
finally:
    shutil.rmtree(d2)

print('【反例⑤】归一化应吃掉大小写/空白/括号注释，但不该吃掉不同的词')
check('大小写折叠后算同词', H._norm_word('HLS 净化'), H._norm_word('hls净化'))
check('括号注释被去掉', H._norm_word('清理（云端）'), '清理')
check('不同词仍不同', H._norm_word('整理') != H._norm_word('整理成笔记'), True)

print('【恢复】真仓库回到 green')
check('恢复后 green', status(), 'green')

print()
if fails:
    print(f'✗ {len(fails)} 项失败：' + '、'.join(fails))
    sys.exit(2)
print('✓ 惊门回归全过')
