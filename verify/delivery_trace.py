#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# impl: B-18 S2   ← 交付正文缺「N 条有出处 / M 条无出处」计数对 → Stop 拽回
"""delivery_trace.py — B-18 产出可溯源的可机检形态判据（L4）。

判据对象 = 已成文的**交付正文**（stop_guard 的 last_assistant_message），
判「交付段是否同时给出「N 条有出处」与「M 条无出处」两个计数」。

为什么形态可机检、对象不是语义（病15 防线，EXP-7b1769d-l）：
  B-18 规则原文要求「交付时报 N 条有出处 / M 条无出处 两个数」——这是**固定计数
  模板**，判它是否在场是确定性形态判断，不是「事实是否真能溯源」的语义判断。
  后者机器判不了，仍是人工项。判据识别范围必须 = 对象范围：只认**交付段标记**
  出现且有交付正文，不把正文里讨论规则的元话语、过程描述、口头「做完了」当交付。

三态（B-02 不折叠）：
  true   = 交付段 + 计数对齐全
  false  = 交付段存在但计数对缺失（真阴性 → 拽回补计数）
  unknown = 无交付段 / 空 / 非字符串（无法判定，不冒充红）

诚实边界：判的是「计数模板在不在」，不是「出处真不真」；模型伪造计数机器判不了。
"""
import re

# 交付段标记：明确的交付小节/交付口吻，排除泛化的「做完/完成/已修复」（那是 B-13）
_DELIVERY_MARK = re.compile(
    r'(?:^|\n)\s*#{0,4}\s*(?:\*{0,2})(?:交付(物|内容|成果|报告|段|清单|说明)?|产出|交付报告)'
    r'[：:\s]'
    r'|(?:^|\n)\s*[=\-]{2,}\s*交付'
    r'|交付(?:物|成果)?[：:]\s*\S',
)
# 计数模板：两数各判一次，避免「只报有出处、漏报无出处」被当成齐全
_HAS_SRC = re.compile(r'\d+\s*条有出处')
_NO_SRC = re.compile(r'\d+\s*条无出处')
# 元话语豁免：正文在「讨论/引用」计数模板本身，不是在交付——这类不作为交付段证据
_META_TALK = re.compile(r'(规则|模板|格式|要求).{0,12}(有出处|无出处)|(有出处|无出处).{0,12}(规则|模板|格式|要求)')


def has_delivery_marker(text):
    """文本里是否有明确交付段标记（不是泛化的完成断言）。"""
    return bool(_DELIVERY_MARK.search(text or ''))


def has_count_pair(text):
    """是否同时给出「N 条有出处」与「M 条无出处」两个数。"""
    t = text or ''
    return bool(_HAS_SRC.search(t) and _NO_SRC.search(t))


def verify(text):
    """返回 'true'/'false'/'unknown'（B-02 三态）。"""
    if not isinstance(text, str) or not text.strip():
        return 'unknown'
    if not has_delivery_marker(text):
        return 'unknown'                      # 非交付正文，不要求计数（病15 识别范围收窄）
    if has_count_pair(text):
        return 'true'
    return 'false'                            # 有交付段但缺计数对 → 需拽回补数


def unresolved(text):
    """硬闸判据：交付段缺计数对 → 需拽回；true/unknown 放行。"""
    return verify(text) == 'false'


def cli():
    import sys
    if len(sys.argv) < 2:
        print('用法：python3 delivery_trace.py "<文本>"  （0=true, 1=false, 2=unknown）')
        return 2
    text = sys.argv[1]
    v = verify(text)
    print('交付溯源：%s（交付标记=%s 计数对=%s）'
          % (v, has_delivery_marker(text), has_count_pair(text)))
    return {'true': 0, 'false': 1, 'unknown': 2}[v]


if __name__ == '__main__':
    raise SystemExit(cli())
