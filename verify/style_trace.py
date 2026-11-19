#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style_trace.py — S-04 简洁输出的可机检形态判据（L2 硬化）。

S-04 不在 rule_map（施工纪律 S 段独立登记，T4/T5 不扫），其"proven_by"不适用——
诚实边界：这是**形态抽检**判据，判一段已成文的回复文本是否踩了 S-04 明令禁止的
三类形态（开场白/客套、追加拓展提问、过度铺垫），不是判"生成那一刻的思考长度"。

病15 防线：判据对象=真函数喂真样本，不查源码字符串；
反向覆盖"看着像但合规"的形态（如正文里合法引用客套词、技术性反问），防一律误伤。
"""
import re

# S-04 明令禁止的三类形态（原文见 通用层/rules/施工纪律.md:11）
_OPENERS = re.compile(
    r'^\s*(好的[，,。]?|收到[，,。]?|明白了?[，,。]?|我来|让我|首先[，,]?|'
    r'这是一个?很好的?问题|感谢(您的?)?(提问|分享)|经过(我|仔细)?(思考|分析))',
)
_FILLER_HEAD = re.compile(r'^\s*\*{3,}|\*{2,}以下|以下是我的|让我来为你')
# 追加拓展提问：结尾抛给用户的新问题（非任务内澄清），S-04「不主动追加拓展提问"
_TAIL_ASK = re.compile(r'(你(想|要不要|需要|觉得)|是否(需要|希望)|要不要我|需要我(继续|帮忙)吗)[？?]?\s*$')


def style_check(text):
    """返回 (ok, hits)：ok=True 合规；False 命中禁形；hits 列出命中项。
    text 非字符串/空 → (True, [])（空不构成违规，无法判定不冒充红）。
    """
    if not isinstance(text, str) or not text.strip():
        return True, []
    body = text.strip()
    hits = []
    if _OPENERS.search(body):
        hits.append('开场白/客套')
    if _FILLER_HEAD.search(body):
        hits.append('过度铺垫')
    # 只看最后一行是否追加提问（避免正文合法反问被误伤）
    last_line = body.rstrip().split('\n')[-1].strip()
    if _TAIL_ASK.search(last_line):
        hits.append('结尾追加拓展提问')
    return (not hits), hits


def proven_line(text):
    """给 proven_by.got 用的实测一句话；调用方喂真样本后填回 rule_map。"""
    ok, hits = style_check(text)
    return 'OK' if ok else 'HIT:' + '/'.join(hits)


def cli():
    import sys
    if len(sys.argv) < 2:
        print('用法：python3 style_trace.py "<回复文本>"  （0=合规 1=命中禁形）')
        return 2
    ok, hits = style_check(sys.argv[1])
    if ok:
        print('OK  合规（未见开场白/过度铺垫/结尾追加提问）')
        return 0
    print('HIT 命中 S-04 禁形：%s' % '、'.join(hits))
    return 1


if __name__ == '__main__':
    raise SystemExit(cli())
