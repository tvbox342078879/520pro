#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据 L2 高频人工判据硬化：B-07/B-03 行为留痕三态 + S-04 形态抽检。

病15 防线：判据对象=真函数喂真样本 / 真 T4 跑变异 repo，不查源码字符串存在。
三态（B-02）：true/false/unknown 分列，unknown 不冒充通过。
三元变异（各自转红才有牙）：
  M1 去 b07_trace 的 +no-handoff 分支 → 真阴性样本漏判
  M2 去 b03_trace 的 last_repo 回退判否 → 回退猜仓被放过
  M3 去 T4 的 proven_by 空项检查 → 升级无实测的假绿被放过
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERIFY = os.path.join(ROOT, 'verify')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rt = load('rule_trace', os.path.join(VERIFY, 'rule_trace.py'))
st = load('style_trace', os.path.join(VERIFY, 'style_trace.py'))
tc = load('terminology_check', os.path.join(VERIFY, 'terminology_check.py'))

fails = []


def ck(label, cond, detail=''):
    ok = bool(cond)
    print(('  ✓ ' if ok else '  ✗ ') + label + ('' if ok else '  ← ' + str(detail)))
    if not ok:
        fails.append(label)


print('── B-07 三态（真函数喂真 probe 样本）──')
for name, probe, want in [
    ('真读handoff→true', {'event': 'SessionStart', 'via': 'session-start+handoff'}, 'true'),
    ('开机没读到→false', {'event': 'SessionStart', 'via': 'session-start+no-handoff'}, 'false'),
    ('via不全→unknown', {'event': 'SessionStart', 'via': 'session-start'}, 'unknown'),
    ('错事件→unknown', {'event': 'UserPromptSubmit', 'via': 'cwd'}, 'unknown'),
    ('空→unknown', {}, 'unknown'),
]:
    got = rt.b07_trace(probe)
    ck(name, got == want, got)

print('── B-03 三态 ──')
for name, probe, want in [
    ('cwd定位→true', {'event': 'UserPromptSubmit', 'via': 'cwd', 'root': '/workspace/520pro'}, 'true'),
    ('command定位→true', {'event': 'UserPromptSubmit', 'via': 'command', 'root': '/workspace/520pro'}, 'true'),
    ('last_repo回退→false', {'event': 'UserPromptSubmit', 'via': 'last_repo', 'root': '/workspace/520pro'}, 'false'),
    ('none→false', {'event': 'UserPromptSubmit', 'via': 'none', 'root': ''}, 'false'),
    ('cwd无root→unknown', {'event': 'UserPromptSubmit', 'via': 'cwd', 'root': ''}, 'unknown'),
    ('错事件→unknown', {'event': 'SessionStart', 'via': 'cwd'}, 'unknown'),
]:
    got = rt.b03_trace(probe)
    ck(name, got == want, got)

print('── verdict 派发 ──')
_st = {'probe': {'event': 'SessionStart', 'via': 'session-start+handoff'}}
ck('verdict B-07 派发正确', rt.verdict(_st, 'B-07') == 'true')
ck('verdict B-03 派发正确（错事件unknown）', rt.verdict(_st, 'B-03') == 'unknown')
ck('verdict 未知规则→unknown', rt.verdict(_st, 'X-99') == 'unknown')

print('── S-04 形态抽检（含病15反向）──')
for name, text, want_ok in [
    ('好的开场→命中', '好的，我来帮你查一下。结果如下。', False),
    ('收到开场→命中', '收到。已经处理完毕。', False),
    ('过度铺垫→命中', '让我来为你详细分析一下这个问题。', False),
    ('结论前置→合规', '部署已成功。凭什么：sha 一致。下一步：验收。', True),
    ('结尾追加问→命中', '已完成部署。你需要我继续吗？', False),
    ('正文合法反问→合规', '标准是能否加载。为什么要开新会话？因为规则启动时注入。', True),
    ('空串→合规(无法判定不冒充红)', '', True),
]:
    ok, hits = st.style_check(text)
    ck(name, ok == want_ok, hits)

print('── 端到端：CLI 三态出口码 ──')
with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
    json.dump({'probe': {'event': 'UserPromptSubmit', 'via': 'last_repo', 'root': '/x'}}, f)
    sp = f.name
p = subprocess.run([sys.executable, os.path.join(VERIFY, 'rule_trace.py'), 'B-03', '--state', sp],
                   capture_output=True, text=True)
ck('CLI 真阴性出口=1', p.returncode == 1, p.stdout.strip())
os.unlink(sp)

print('── T4 machine 升级必须给实测（proven_by 空项检查在位）──')
# 真跑一遍当前 rule_map 的 T4，应绿（B-07/B-03 已填实）
out = subprocess.run([sys.executable, os.path.join(VERIFY, 'terminology_check.py'), '--repo', ROOT],
                     capture_output=True, text=True)
# 用退出码判（0=全部口径绿）。不查「✗ 字样」——汇总行「0 ✗」本身含该字符，会造成假红
ck('当前 rule_map 口径全绿（T4 proven_by 填实+T7 强度对齐）', out.returncode == 0,
   'rc=%s, tail=%s' % (out.returncode, out.stdout[-160:]))

print('\n结果：%s' % ('全部通过' if not fails else str(len(fails)) + ' 项失败：' + ','.join(fails)))
sys.exit(0 if not fails else 2)
