#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""discipline_trace.py — 施工纪律 S-09 / 派单语言 的统一判据（Stop 拽回 · S-discipline）

为什么有:
  施工纪律 S-09「查类指令先扫会话页面」与「派子代理全程中文」此前都是纯人工条款
  （见 docs/施工纪律闭环.md），写进规则文件却没进执行信号，模型按提示走必然漏。
  本模块把它们变成 Stop 可判的确定性形态，接进 stop_guard 的 judge_* 拽回链。

判据对象（病15：识别范围≠对象范围——只判标记在不在，不判会话真没真扫）:
  S-09：查/看类指令的回复正文里，有没有会话范围取证标记
        （会话.jsonl:<行> / transcript / payloads/ / 会话记录 之一）。
        不判"是否真扫了会话"——那是语义判断，机器做不了，也不该做。
  派单语言：本轮派子代理的 prompt 首句有无中文约束短语（全程简体中文）。

三态（B-02 不折叠）:
  true    = 查类回复缺会话标记 / 派单段缺中文约束 → 拽回
  false   = 标记齐全，或非查类指令（免疫）→ 放行
  unknown = 无查类信号、无派单信号、空文本 → 放行（宁放过不误伤）
"""
import re

# 查证完成态断言：只在「声称做了跨源/全量查证」时才要求会话标记。
# 为什么不收泛化"查/看"动词（实测教训）：技术回复天然含"查类指令/查看关键词/
# 检索会话"等词，一放宽就把正常技术讨论判成违规（误伤→用户关钩子）。
# "查类指令先扫会话"的真正解法是 session_evidence 的 UserPromptSubmit 主动注入
# （把证据喂到嘴边，不靠判据事后审文本）；本判据只保留"声称全量查证却没列会话
# 出处"这一种确定性形态，职责=事后验标，与注入机制分工。
QUERY_MARK = re.compile(
    r'(?:四个范围.{0,6}(?:扫|查)|全量查证|跨源查证|全仓.{0,4}扫了|'
    r'已扫.{0,4}会话|搜索范围.{0,6}(?:都|全).{0,3}扫|查证结论.{0,4}(?:如下|是))')

# 会话范围取证标记：任一出现即认为扫过会话（宽松，宁放过不误伤）
# 新增 L<行号>@<时间戳> 格式——session_evidence 注入的证据行号，模型引用即凭据。
SCOPE_MARKS = [
    r'会话\.jsonl\s*:?\s*\d+',       # 会话.jsonl:65888
    r'\.jsonl:\d+',                   # xxx.jsonl:123
    r'\bL\d+@\d+',                    # 📎会话证据 L69295@1795101823127（注入格式）
    r'📎会话证据',                    # 直接引用注入标记
    r'transcript',                    # transcript_path / transcript
    r'payloads/',                     # traces/.../payloads/
    r'会话记录', r'会话原文', r'会话历史',  # 中文表述
]

# 派单段的中文约束短语
ZH_CONSTRAINT = re.compile(r'(?:全程(?:使用)?简体?中文|全程中文|自然语言.{0,8}中文)')

# 派单信号：出现这些说明本轮在派子代理
DISPATCH_MARK = re.compile(r'(?:派子代理|子代理|派单|Agent\s*工具|subagent)')


def _is_query(text):
    """文本里有没有查/看类指令信号。"""
    return bool(QUERY_MARK.search(text or ''))


def _has_scope(text):
    return any(re.search(p, text or '', re.I) for p in SCOPE_MARKS)


def _is_dispatch(text):
    return bool(DISPATCH_MARK.search(text or ''))


def _has_zh_constraint(text):
    return bool(ZH_CONSTRAINT.search(text or ''))


def verify(text, scope='s09'):
    """三态：'true' / 'false' / 'unknown'。

    scope='s09'      —— 查类指令缺会话标记 → true
    scope='dispatch' —— 派单段缺中文约束 → true
    """
    if not text or not text.strip():
        return 'unknown'
    if scope == 's09':
        if not _is_query(text):
            return 'unknown'          # 非查类，免疫
        return 'false' if _has_scope(text) else 'true'
    if scope == 'dispatch':
        if not _is_dispatch(text):
            return 'unknown'          # 无派单信号，免疫
        return 'false' if _has_zh_constraint(text) else 'true'
    return 'unknown'


def unresolved(text):
    """任一作用域命中真阴性即拽回。"""
    return verify(text, 's09') == 'true' or verify(text, 'dispatch') == 'true'


def cli():
    import sys, json
    if len(sys.argv) < 3:
        print('用法: discipline_trace.py verify <文本> [s09|dispatch]')
        return
    print(json.dumps({'verdict': verify(sys.argv[2],
                                        sys.argv[3] if len(sys.argv) > 3 else 's09'),
                      'unresolved': unresolved(sys.argv[2])}, ensure_ascii=False))


if __name__ == '__main__':
    cli()
