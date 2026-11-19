#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session_evidence.py — S-09 会话证据「丑喂」模块（UserPromptSubmit 注入 · S-discipline）

为什么有:
  施工纪律 S-09「查类指令先扫会话页面」升机检后仍靠用户反复提醒——根因是
  判据判「回复有无会话标记」（事后、语义、收窄到完成态断言），日常查类
  根本不触发（病15：判据识别范围≠对象范围）。本模块换正门：不拦模型、
  不提醒模型，而是 hook 在 UserPromptSubmit 阶段主动从会话 jsonl 检索
  检索与本轮 prompt 相关的历史片段，连行号喂进 additionalContext——
  把「记得去查」改成「查好的结果直接喂到嘴边」。

三态（B-02 不折叠）:
  hits 非空 = 检索到相关片段 → 注入证据
  hits 为空 = 未命中 / 文件不可读 / 非查类 → 返回空串，不硬凑（"没查到"≠"没有"）
  读失败     = 静默降级返回空串，绝不拦截（UserPromptSubmit 永不拦截铁律）

全文件流式读数策略（596MB 文件，单行是长 JSON）:
  open 逐行迭代 + 绝对行号，实测 0.12~0.37s（grep 同量级）。
  放弃"尾部 seek"：尾部 3MB 仅覆盖最近约 200 行，够不到 6 万行前的历史话题
  （"回忆当时云取借鉴"类查询必然失败）——病15：读法识别范围≠查询对象范围。
  只保留命中行（≤MAX_HITS），不整读进内存；单行超长截断显示但保留绝对行号。
"""
import json
import os
import re

MAX_HITS = 3                       # 最多注入 3 条证据
SUMMARY_LEN = 200                  # 单条摘要截断长度（超长行含工具输出）

# 查类指令信号：命中才触发会话检索（动词，作信号不作检索词）
QUERY_SIGNAL = re.compile(
    r'(?:查|看一下|查看|搜|找|看看|检索|盘点|核查|取证|探查|回忆|当时|之前.{0,4}怎么|'
    r'借鉴|遗留|闭环|历史|记不记得|说过)')

# 停用词 / 纯查类动词：从检索词里剔除（纳入会导致每轮全命中，病15反面）
STOPWORDS = {
    '一下', '看看', '查看', '检索', '盘点', '核查', '取证', '探查', '回忆',
    '怎么', '什么', '那个', '这个', '是否', '有没有', '如何', '为啥', '为何',
    '当时', '之前', '现在', '事情', '问题', '规则', '一下', '进行', '相关',
}

# 高区分度词：单个命中即算相关（专名/编号/commit sha/会话文件）。
# 去掉 .py/.md/纯数字——它们几乎每行都有，纳入会把整个会话当证据（病15反面·全命中）。
HIGH_SIG = re.compile(r'(?:[\w-]+\.jsonl|S-\d{2}|B-\d{2}|[0-9a-f]{7,}|云取|YunGet|cred.vault|pan\.py)')

# 自指串：会话里 hook/系统注入的提示文本与摘要块，不算对话证据
SELF_REF = re.compile(
    r'(?:📎会话证据|思考闸|additionalContext|⏭ 上一轮|🪪 环境身份|🔒 B-12|'
    r'<cb_summary>|<conversation_history_summary>|<system-reminder>|'
    r'Summary of the conversation so far|DO NOT re-run)')

# 会话行里"人机对话"的类型与角色（实测顶层是 type/role/content，非 message.role）
MSG_TYPES = {'message'}
ROLES = {'user', 'assistant'}


def is_query(prompt):
    """是不是查类指令（触发会话检索的信号）。"""
    return bool(QUERY_SIGNAL.search(prompt or ''))


# 中文虚词/结构字：n-gram 里含这些的不作检索词（"借鉴点都""有啥"这类垃圾词）
FUNCTION_CHARS = set('的了在是有和都不我这你他她它啥吗呢吧啊点说经已把被从对向给让使把很也会就都还')

# 中文关键词切分符：动词/疑问词/标点——用它把 prompt 切块，块内再做 n-gram
CUT = re.compile(
    r'(?:看一下|看看|查看|检索|盘点|核查|取证|探查|回忆|当时|之前|怎么|什么|那个|'
    r'这个|是否|有没有|如何|为啥|为何|现在|事情|问题|规则|进行|相关|说的|当时|'
    r'查|找|搜|看|的|了|吗|呢|吧|啊|，|。|？|！|、|；|：|,|\.|\s)')


def extract_keywords(prompt):
    """从 prompt 提取检索词：英文/路径/编号整取，中文先切块再 2-4 字滑窗 n-gram。

    中文必须 n-gram——连续长词（"云取借鉴点都"）在原文里往往不存在，
    原文是"云取 YunGet 借鉴"这种分开的表述（病15：词形≠原文字形）。
    短词优先（2字在前）保证"云取""借鉴"不被"云取借鉴点都"挤出前 N。
    """
    text = prompt or ''
    kws = []
    for m in re.findall(r'[A-Za-z][\w-]*|[\w-]+\.(?:jsonl|py|md|json|sh)', text):
        if len(m) >= 2 and m.lower() not in STOPWORDS:
            kws.append((len(m), m))
    for block in CUT.split(text):
        for h in re.findall(r'[\u4e00-\u9fa5]+', block):
            if len(h) < 2:
                continue
            ngrams = set()
            for n in (2, 3, 4):
                for i in range(len(h) - n + 1):
                    g = h[i:i + n]
                    if any(c in FUNCTION_CHARS for c in g):
                        continue
                    if g not in STOPWORDS:
                        ngrams.add(g)
            for g in ngrams:
                kws.append((len(g), g))
    kws.sort(key=lambda x: x[0])               # 短词优先
    seen, out = set(), []
    for _, k in kws:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            out.append(k)
    return out[:14]


def _content_of(obj):
    """从会话行取人类对话正文；工具输出/hook 提示返回 None。"""
    if not isinstance(obj, dict):
        return None
    if obj.get('type') not in MSG_TYPES or obj.get('role') not in ROLES:
        return None
    content = obj.get('content')
    if isinstance(content, list):           # 多段 content，拼文本段
        parts = [c.get('text', '') for c in content
                 if isinstance(c, dict) and isinstance(c.get('text'), str)]
        content = ' '.join(parts)
    if not isinstance(content, str) or not content.strip():
        return None
    return content


def scan_session(path, keywords, max_hits=MAX_HITS, prefer='recent'):
    """grep 子进程扫会话 → 关键词共现打分 → 取最相关的 N 条。失败返回空串不拦。

    每条命中 = dict(line=绝对行号, ts, role, summary, score)。
    为什么要打分：高频词（云取 2875 处、壳分析在前）按位置取会挤掉真出处
      （57 条借鉴在 6.6 万行）——病15：位置顺序≠相关度。按"共现词数×词长"
      打分，"云取+借鉴+57条"同现的行得分远高于只提"云取"的闲聊。
    prefer='recent'（默认）= 同分取行号大者（最近），'first' = 同分取小者。
    性能：grep 全文件 0.12s + 候选行 JSON 解析约 0.3s，合计 <0.5s。
    """
    import subprocess
    if not path or not os.path.isfile(path) or not keywords:
        return []
    kws = [k for k in keywords if k and isinstance(k, str)]
    if not kws:
        return []
    strong_kws = [k for k in kws if HIGH_SIG.search(k)]
    pattern_kws = strong_kws if strong_kws else kws
    safe = [re.escape(k) for k in pattern_kws
            if re.search(r'[\w\u4e00-\u9fa5]', k)]
    if not safe:
        return []
    pattern = '|'.join(safe)
    try:
        r = subprocess.run(
            ['grep', '-n', '-E', pattern, path],   # 全量，不加 -m（真出处可能在很后面）
            capture_output=True, text=True, timeout=10,
            errors='replace')
        raw_lines = r.stdout.splitlines()
    except Exception:
        return []
    if not raw_lines:
        return []

    hits = []
    for raw in raw_lines:
        if ':' not in raw:
            continue
        lineno_s, _, body = raw.partition(':')
        if not lineno_s.isdigit():
            continue
        try:
            obj = json.loads(body)
        except Exception:
            continue
        content = _content_of(obj)
        if not content or SELF_REF.search(content):
            continue
        low = content.lower()
        matched = [k for k in kws if (k.lower() if k.isascii() else k) in low]
        if not matched:
            continue
        # 打分：强词命中权 3，其余按词长；共现越多分越高
        score = sum((3 if HIGH_SIG.search(k) else 1) * min(len(k), 4)
                    for k in matched)
        ts = str(obj.get('timestamp', ''))[:13]
        summary = content.replace('\n', ' ')[:SUMMARY_LEN]
        if len(content) > SUMMARY_LEN:
            summary += '…'
        hits.append({'line': int(lineno_s), 'ts': ts,
                     'role': obj.get('role', ''), 'summary': summary,
                     'score': score})

    # 分数降序；同分按行号（recent 取大/靠后，first 取小/靠前）
    hits.sort(key=lambda h: (-h['score'], -h['line'] if prefer == 'recent' else h['line']))
    return hits[:max_hits]


def format_evidence(hits):
    """拼成单行注入文案；无命中返回空串（三态诚实，不硬凑）。"""
    if not hits:
        return ''
    parts = []
    for h in hits:
        ts = ('@' + h['ts']) if h.get('ts') else ''
        parts.append('L%s%s %s:%s' % (h.get('line', '?'), ts,
                                      h.get('role', '?'), h.get('summary', '')))
    return '｜📎会话证据%d条：%s' % (len(hits), ' ｜ '.join(parts))


def _default_session_path():
    """当前会话 jsonl： projects/workspace 下 mtime 最新的 .jsonl。找不到返回空串。"""
    import glob
    base = os.path.expanduser('~/.codebuddy/projects/workspace')
    fs = glob.glob(os.path.join(base, '*.jsonl'))
    if not fs:
        return ''
    try:
        return max(fs, key=os.path.getmtime)
    except Exception:
        return ''


def inject(prompt, session_path=None):
    """UserPromptSubmit 注入主入口：非查类/未命中/读失败都返回空串。"""
    if not is_query(prompt):
        return ''
    kws = extract_keywords(prompt)
    if not kws:
        return ''
    path = session_path or _default_session_path()
    hits = scan_session(path, kws)
    return format_evidence(hits)


def cli():
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == 'inject':
        print(inject(' '.join(sys.argv[2:])))
        return
    if len(sys.argv) >= 3 and sys.argv[1] == 'keywords':
        print(json.dumps(extract_keywords(' '.join(sys.argv[2:])), ensure_ascii=False))
        return
    print('用法: session_evidence.py inject <prompt> | keywords <prompt>')


if __name__ == '__main__':
    cli()
