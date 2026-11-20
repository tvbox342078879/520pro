#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""registry.py — 网盘 provider 统一注册表（云取借鉴第 10 条：adapter 统一底座）。

【解决什么问题】
此前每个技能各维护一张平台差异表：share-parser 的分享正则表、transfer-poll 的
轮询间隔/文案表。新增一家网盘要在多处各改一遍（"一个一个改"），漏改即静默出错。
本模块把四类专业差异收敛到唯一一张 PLATFORMS 表：
  - 分享链接正则（share_parser 用）
  - 转存轮询间隔（transfer_poll 用）
  - 进行中进度文案（transfer_poll 用）
  - 有效期代码映射（share_parser 用，全局共享，不属于单平台）
新增平台 = 在 PLATFORMS 加一条记录，四类投影自动可见；主流程零改。

【这是什么形态】
lib 类：无 SKILL.md、平台不注册不路由、不进上下文，只被 share-parser /
transfer-poll 按相对路径 import（两技能 scripts 的 parents[2] = skills 根，
与用户级 ~/.codebuddy/skills/ 结构对称）。版本真源在 manifest.json。

【三态诚实】
- 平台不在册 → 投影函数返回 None / 走调用方默认值，不硬造。
- 未知有效期代码 → 调用方显式报错（不在此吞）。
- 正则编译失败 → 显式抛，不静默跳过坏规则。

判据：verify/tests/test_pan_registry.py（单一真源有牙 + 元变异）。
"""
import re

# ── 唯一真源：每家网盘一条，含它全部差异维度 ──
# 字段：name / share_pattern(正则串,None=无分享表) / share_group / poll_ms(None=用默认)
#       / progress_text(None=用默认)
PLATFORMS = [
    {'name': 'quark',
     'share_pattern': r'pan\.quark\.cn/s/([A-Za-z0-9]+)', 'share_group': 1,
     'poll_ms': 1000, 'progress_text': '夸克操作仍在处理中，请稍后刷新'},
    {'name': 'baidu',
     'share_pattern': r'pan\.baidu\.com/s/(1[A-Za-z0-9_-]+)', 'share_group': 1,
     'poll_ms': None, 'progress_text': None},
    {'name': '115',
     'share_pattern': r'115(?:cdn|rc)?\.com/(sw[A-Za-z0-9]{8,})-([A-Za-z0-9]{4,8})',
     'share_group': 1, 'poll_ms': None, 'progress_text': None},
    {'name': 'lanzou',
     'share_pattern': r'lanzou[a-z]*\.com/([A-Za-z0-9]+)', 'share_group': 1,
     'poll_ms': None, 'progress_text': None},
    {'name': 'xunlei',
     'share_pattern': r'pan\.xunlei\.com/s/([A-Za-z0-9]+)', 'share_group': 1,
     'poll_ms': None, 'progress_text': None},
    {'name': 'mobile',
     'share_pattern': r'caiyun\.139\.com/(?:s|share)/([A-Za-z0-9]+)', 'share_group': 1,
     'poll_ms': None, 'progress_text': None},
    {'name': 'guangya',
     'share_pattern': None, 'share_group': None,
     'poll_ms': 750, 'progress_text': '光鸭操作仍在处理中，请稍后刷新列表确认结果'},
    {'name': 'uc',
     'share_pattern': None, 'share_group': None,
     'poll_ms': 1000, 'progress_text': 'UC 操作仍在处理中，请稍后刷新'},
]

# ── 全局共享：有效期代码映射（DEX ShareExpire.fromCode/toText 实证，不属于单平台）──
EXPIRE_CODES = {-1: '永久有效', 1: '1 天', 3: '3 天', 7: '7 天', 15: '15 天'}

# ── 默认值（平台未在册或该维度未声明时）──
DEFAULT_POLL_MS = 1000
DEFAULT_PROGRESS_TEXT = '操作仍在处理中，请稍后刷新'


def platform_names():
    """在册平台名列表（顺序＝表内顺序，稳定）。"""
    return [p['name'] for p in PLATFORMS]


def share_rules():
    """投影 → share-parser 的规则表 [(name, compiled_regex, group), ...]。

    只含声明了 share_pattern 的平台；正则在此编译，坏规则显式抛（不静默跳过）。
    """
    rules = []
    for p in PLATFORMS:
        pat = p.get('share_pattern')
        if pat is None:
            continue
        rules.append((p['name'], re.compile(pat, re.I), p['share_group']))
    return rules


def expire_codes():
    """投影 → 有效期代码映射（返回副本，防调用方改脏真源）。"""
    return dict(EXPIRE_CODES)


def poll_intervals():
    """投影 → transfer-poll 的 {平台: 间隔ms}，只含声明了 poll_ms 的平台。"""
    return {p['name']: p['poll_ms'] for p in PLATFORMS if p.get('poll_ms') is not None}


def progress_texts():
    """投影 → transfer-poll 的 {平台: 进度文案}，只含声明了 progress_text 的平台。"""
    return {p['name']: p['progress_text'] for p in PLATFORMS if p.get('progress_text') is not None}


def default_poll_ms():
    return DEFAULT_POLL_MS


def default_progress_text():
    return DEFAULT_PROGRESS_TEXT


def _self_check():
    names = platform_names()
    cases = [
        (len(names) == 8 and len(set(names)) == 8),
        (len(share_rules()) == 6),                       # 6 家有分享正则
        (len(poll_intervals()) == 3),                    # 3 家有轮询间隔
        (poll_intervals().get('guangya') == 750),
        ('quark' in dict((n, 1) for n, _, _ in share_rules())),
        (expire_codes()[-1] == '永久有效'),
    ]
    return all(cases)


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description='网盘 provider 统一注册表（lib，被技能 import）')
    ap.add_argument('--list', action='store_true', help='列出在册平台及四类投影')
    ap.add_argument('--selftest', action='store_true', help='自省自检')
    a = ap.parse_args()
    if a.selftest:
        ok = _self_check()
        print('SELFTEST %s' % ('OK' if ok else 'FAIL'))
        return 0 if ok else 2
    if a.list:
        out = {
            'platforms': platform_names(),
            'share_platforms': [n for n, _, _ in share_rules()],
            'poll_intervals': poll_intervals(),
            'progress_platforms': sorted(progress_texts()),
            'expire_codes': expire_codes(),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
