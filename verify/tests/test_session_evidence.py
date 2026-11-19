#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_session_evidence.py — S-09 会话证据注入 + 判据回归测试

覆盖：
  ①extract_keywords：动词/虚词剔除、专名保留、n-gram 拆分、去重短词优先
  ②scan_session：grep 命中、打分排序、自指串过滤、读失败降级
  ③format_evidence：命中含行号、未命中空串（三态诚实）
  ④discipline_trace：完成态三态、注入行号放行、技术回复免疫
  ⑤病15变异：注入模块关闭/缺失时，Stop 判据仍能独立拽回（不被架空）
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # verify/
sys.path.insert(0, ROOT)

import session_evidence as se
import discipline_trace as dt

N = [0]
FAIL = []


def ck(cond, name):
    N[0] += 1
    if not cond:
        FAIL.append(name)
        print('  ✗', name)


# ---------- ① 关键词提取 ----------
print('① extract_keywords')
kw = se.extract_keywords('看看当时说的云取借鉴点都有啥')
ck('云取' in kw, '专名云取保留')
ck('借鉴' in kw, 'n-gram拆出借鉴')
ck('取借' not in kw or '取借' in kw, '垃圾n-gram不致命(可留)')
ck(not any(c in k for k in kw for c in '啥吗呢'), '疑问虚词不进关键词')
kw2 = se.extract_keywords('查看 S-09 判据在 check_live.py 里')
ck(any('S-09' in k for k in kw2), '编号S-09保留')
ck(any('.py' in k or 'check_live' in k for k in kw2), '路径.py保留')
ck(se.extract_keywords('') == [], '空串空列表')

# ---------- ② 会话检索 ----------
print('② scan_session（用临时样本，不碰真实596MB）')
sample = '\n'.join([
    '{"id":"1","timestamp":1790000000000,"type":"message","role":"assistant","content":[{"type":"output_text","text":"全量查证结论：云取借鉴57条见 session.jsonl:65888"}]}',
    '{"id":"2","timestamp":1790000001000,"type":"function_call","content":"云取 借鉴 工具输出不算证据"}',
    '{"id":"3","timestamp":1790000002000,"type":"message","role":"user","content":"<cb_summary> 云取 借鉴 这是系统摘要不算证据 </cb_summary>"}',
    '{"id":"4","timestamp":1790000003000,"type":"message","role":"assistant","content":"开工写代码 修了bug 无关内容"}',
])
tmp = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False, encoding='utf-8')
tmp.write(sample)
tmp.close()
try:
    hits = se.scan_session(tmp.name, ['云取', '借鉴', '查证'])
    ck(any(h['line'] == 1 for h in hits), '命中真对话行L1')
    ck(all(h['line'] != 2 for h in hits), 'function_call排除')
    ck(all(h['line'] != 3 for h in hits), 'cb_summary自指串排除')
    ck(all(h['line'] != 4 for h in hits), '无关行排除')
    ck(hits and all('score' in h for h in hits), '命中带score字段')
    ck(se.scan_session(tmp.name, []) == [], '空关键词空结果')
    ck(se.scan_session('/nonexistent/x.jsonl', ['云取']) == [], '文件不存在降级空')
finally:
    os.unlink(tmp.name)

# ---------- ③ 文案 ----------
print('③ format_evidence')
ck(se.format_evidence([]) == '', '未命中空串')
fmt = se.format_evidence([{'line': 12, 'ts': '1790000000000', 'role': 'assistant', 'summary': '云取借鉴'}])
ck('L12' in fmt and '云取借鉴' in fmt, '命中含行号+摘要')
ck('\n' not in fmt, '单行文案（不占多行）')

# ---------- ④ 判据三态 ----------
print('④ discipline_trace 三态')
ck(dt.verify('技术回复含查类指令 查看关键词 检索会话', 's09') == 'unknown', '技术回复免疫')
ck(dt.verify('全量查证结论如下：规则在 core-8.md', 's09') == 'true', '全量查证无出处拽回')
ck(dt.verify('全量查证结论如下：见 L65888@1795101823127', 's09') == 'false', '注入行号放行')
ck(dt.verify('跨源查证完成，见 会话.jsonl:65888', 's09') == 'false', '会话jsonl放行')
ck(dt.verify('', 's09') == 'unknown', '空文本unknown')
ck(dt.verify('派子代理去查', 'dispatch') == 'true', '派单缺中文拽回')
ck(dt.verify('派子代理全程简体中文去查', 'dispatch') == 'false', '派单带中文放行')

# ---------- ⑤ 病15变异：注入关闭判据仍独立 ----------
print('⑤ 病15变异：判据不依赖注入')
# 即使 session_evidence 模块从未被调用，纯文本"全量查证无出处"仍须拽回
_orig = se.inject
se.inject = lambda *a, **k: ''   # 模拟注入被关掉
try:
    ck(dt.verify('全量查证结论如下：都在 core-8.md', 's09') == 'true',
       '注入关闭时判据仍独立拽回（未被架空）')
finally:
    se.inject = _orig
# 反向：注入产出证据行号后，模型引用该行号能过判据（一喂一验闭环）
ev = se.format_evidence([{'line': 65888, 'ts': '1793844944828', 'role': 'assistant', 'summary': '云取借鉴'}])
ck(dt.verify('全量查证结论：' + ev, 's09') == 'false', '注入证据引用后放行（一喂一验）')

print('\ntest_session_evidence：%d 例，失败 %d' % (N[0], len(FAIL)))
if FAIL:
    print('失败项:', ' / '.join(FAIL))
    sys.exit(1)
