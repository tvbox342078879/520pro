#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# impl: B-06 S2   ← 前提断言（规则/文件在某处/已退役）无文件:行号引证 → Stop 拽回
"""premise_trace.py — B-06 事实源的可机检形态判据（L5）。

判据对象 = 结论里的**前提断言**（stop_guard 的 last_assistant_message），
判「断言是否给出『文件 + 行号』引证」。

为什么形态可机检、对象不是语义（病15 防线，EXP-7b1769d-l）：
  B-06 原文举例「某规则已退役」「某文件在某处」——这是**固定断言句式**，
  判它是否带文件:行号引证是确定性形态判断，不是「事实是否真的成立」的语义判断。
  后者机器判不了，仍是人工项。判据识别范围必须 = 对象范围：只认**状态断言句式**
  （规则/条款/技能/脚本/文件/配置/B-xx + 已退役/已删除/不存在/在某处/在 PATH/位于），
  不把过程描述、元话语讨论、否定语境、泛化完成断言（B-13 域）当断言。

三态（B-02 不折叠）：
  true    = 有状态断言 + 同句或全文有「文件:行号」引证
  false   = 有状态断言但无任何文件:行号引证（真阴性 → 拽回补引证）
  unknown = 无状态断言 / 空 / 非字符串 / 仅元话语 / 否定语境（无法判定，不冒充红）

与 B-13 对象错开：B-13 判「宣称完成但无落点」；B-06 判「声称某事实状态但无引证」。
一个是对自己工作的完成断言，一个是对外部事实的存在/状态断言，互不替代。

诚实边界：判的是「文件:行号引证在不在」，不是「引证指向的事实真不真」；模型伪造
引证机器判不了。
"""
import re

# 状态断言句式：主体（规则/文件/条款/技能/脚本/配置/B-xx）+ 状态词（退役/删除/位置）
# 收窄到 B-06 原文举例的形态，不收泛化的「完成了 X」（那是 B-13）
_SUBJECT = (r'(?:规则|条款|条目|技能|脚本|文件|配置|命令|接口|函数|模块|'
            r'B-\d{2}|V-[A-Z0-9-]+|G\d|F\d{2})')
_STATE = (r'(?:已?(?:退役|删除|移除|废止|下线|不存在|不再(?:存在|生效|维护))'
          r'|在\s*\S|位于|存于|路径(?:是|为)|放在)')
_PREMISIVE = re.compile(_SUBJECT + r'([^。！？\n]{0,18}?)' + _STATE)  # 捕获主体与状态词之间的间隔
# 倒装：「在某处的规则 X」——也属 B-06 形态
_PREMISIVE_REV = re.compile(r'(?:在|位于|存于)\s*\S{1,60}'
                            r'(?:的|里|中)?\s*(?:规则|条款|技能|脚本|文件|配置|B-\d{2})')

# 文件:行号引证（复用 B-13 EVIDENCE_PATS 的文件:行号形态，保持同一口径）
_CITATION = re.compile(
    r'[\w./~-]+\.(?:py|md|sh|json|js|ts|tsx|yml|yaml|html|css|toml|txt)\s*[:：]\s*\d+'
    r'|第\s*\d+\s*行'
    r'|[\w./~-]+\.(?:py|md|sh|json|js|ts|tsx|yml|yaml|html|css|toml)\s+第\s*\d+\s*行'
)
# 元话语豁免：正文在「讨论/引用」断言句式本身（如规则说明、教学），不作为事实断言
_META_TALK = re.compile(
    r'(?:规则|判据|模板|格式|原文|要求|例如|比如|举例).{0,16}'
    r'(?:已退役|已删除|在某处|位于|不存在)'
    r'|(?:已退役|已删除|在某处|位于|不存在).{0,16}(?:规则|判据|模板|格式|原文|说法|句式)'
)
# 否定语境：断言词前 6 字内，或主体与状态词之间的间隔里有否定词 → 正常表述，不拽回
_NEG = re.compile(r'(?:未|没|没有|无法|不能|不算|尚未|并不|不会|还没|未完全)'
                  r'[\u4e00-\u9fa5]{0,6}$')


def has_premise(text):
    """是否有状态断言句式（B-06 对象；排除元话语/否定语境）。"""
    t = text or ''
    found = False
    for m in _PREMISIVE.finditer(t):
        gap = m.group(1) or ''                     # 主体与状态词之间的间隔（否定词在这里）
        if _NEG.search(gap) or _META_TALK.search(t[max(0, m.start() - 12):m.end() + 12]):
            continue
        found = True
        break
    if not found:
        for m in _PREMISIVE_REV.finditer(t):
            ctx = t[max(0, m.start() - 6):m.start()]
            if _NEG.search(ctx) or _META_TALK.search(t[max(0, m.start() - 12):m.end() + 12]):
                continue
            found = True
            break
    return found


def has_citation(text):
    """是否给出文件:行号引证。"""
    return bool(_CITATION.search(text or ''))


def verify(text):
    """返回 'true'/'false'/'unknown'（B-02 三态）。"""
    if not isinstance(text, str) or not text.strip():
        return 'unknown'
    if not has_premise(text):
        return 'unknown'                      # 无状态断言，不要求引证（病15 识别范围收窄）
    return 'true' if has_citation(text) else 'false'


def unresolved(text):
    """硬闸判据：状态断言无引证 → 需拽回；true/unknown 放行。"""
    return verify(text) == 'false'


def cli():
    import sys
    if len(sys.argv) < 2:
        print('用法：python3 premise_trace.py "<文本>"  （0=true, 1=false, 2=unknown）')
        return 2
    text = sys.argv[1]
    v = verify(text)
    print('前提断言溯源：%s（断言=%s 引证=%s）'
          % (v, has_premise(text), has_citation(text)))
    return {'true': 0, 'false': 1, 'unknown': 2}[v]


if __name__ == '__main__':
    raise SystemExit(cli())
