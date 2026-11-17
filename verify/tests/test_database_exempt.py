#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_database_exempt.py — 遗留登记:8「空 database 被清理误挪」的机器判据。

真源缺口（2026-11-14 第1次实例）：手机端清理把 5 个刚重建的空探源库挪进「待清理」。
根因：cmd_classify 旧版只跳 folder，database 节点落到规则匹配后被 --yes 搬走；
       cmd_scan 靠「folder 限定」歪打正着不投，但 dedup 路径不看 kind。

两层判据：
  A 行为层：mock 云端调用，跑真实 cmd_classify/cmd_scan——database 不被移动/投递，
            非 database 仍正常处理（不误伤）。
  B 源码层：check_exempt(src) 精确锚定 cmd_classify/cmd_scan 函数体内的 database
            豁免分支（病15 不扫全文）；喂删掉分支的坏源码应红（元变异，证判据贴实现）。
"""
import contextlib
import io
import os
import re
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, '通用层', 'skills', 'space-hub', 'scripts', 'space_hub.py')
sys.path.insert(0, os.path.dirname(SRC))
import space_hub as s  # noqa: E402

PASS, FAIL = [], []
DB_ID, DB_KW, DOC_ID = 'EMPTY_DB_1', 'DB_KW', 'DOC_1'
ROOT_KIDS = [
    {'id': DB_ID, 'title': '空探源库', 'kind': 'database'},
    {'id': DB_KW, 'title': '废弃测试库', 'kind': 'database'},
    {'id': DOC_ID, 'title': '测试报告.md', 'kind': 'doc'},
]


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


# ── B 源码层判据（纯函数，可喂变异） ─────────────────────────────
def _func_body(src, name):
    """截取 `def name(...)` 到下一个顶层 def 之前的函数体（病15 精确锚定）。"""
    m = re.search(r'^def %s\(' % re.escape(name), src, re.M)
    if not m:
        return ''
    nxt = re.search(r'^def ', src[m.end():], re.M)
    return src[m.end(): m.end() + (nxt.start() if nxt else len(src))]


def check_exempt(src, name):
    """该函数体内必须有 database 豁免分支（命中豁免标记串）。"""
    body = _func_body(src, name)
    return "kind == 'database'" in body and '豁免' in body


# ── A 行为层：mock 云端，跑真实函数 ──────────────────────────────
def setup():
    s.resolve_space = lambda *a, **kw: None
    s._find_inbox = lambda: ('INBOX', None)
    s._classify_rules = lambda: {'rules': [
        {'match': ['探源库', '测试库', '报告'], 'target': '🧬 520进化论/01-方法论'}]}
    s._kids = lambda pid: ROOT_KIDS if pid == '' else []
    s.load_state = lambda: {'inbox': 'INBOX', 'items': [], 'audit': []}
    s.save_state = lambda d: None
    s.ROOTS = ['']
    s.KW = ('废弃', '待删', '🗑')
    s.STRUCT_KEEP, s.EMPTY_KEEP = ('归档', '总库'), ('库',)
    s.EMPTY_NEVER_AUTOPOST, s.DEFAULT_DEDUP = True, 2
    s._struct_hits = lambda t: [k for k in s.STRUCT_KEEP if k in t]
    s._ensure_path = lambda t: 'TARGET_FID'
    moved = []
    s.cmd_move = lambda a: (moved.append(a.node) or 0)
    s.cmd_add = lambda a: (moved.append(a.node) or 0)
    return moved


def run_classify(yes):
    moved = setup()
    a = types.SimpleNamespace(yes=yes, dry_run=not yes, show_skipped=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = s.cmd_classify(a)
    return rc, buf.getvalue(), moved


def run_scan(dry):
    moved = setup()
    a = types.SimpleNamespace(dry_run=dry, dedup=2)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = s.cmd_scan(a)
    return rc, buf.getvalue(), moved


src = open(SRC, encoding='utf-8').read()

print('【A1】classify 执行（--yes）：database 不被移动、文档仍归纳')
rc, out, moved = run_classify(True)
check('rc=0', rc == 0, rc)
check('空库不被移动', DB_ID not in moved, moved)
check('含废弃KW的库也不被移动', DB_KW not in moved, moved)
check('普通文档仍被归纳（不误伤）', DOC_ID in moved, moved)
check('跳过原因写明 database 豁免', 'database 节点豁免' in out, out[:400])

print('【A2】scan 执行（非 dry-run）：database 不被投递')
rc, out, moved = run_scan(False)
check('rc=0', rc == 0, rc)
check('scan 不投递任何 database', DB_ID not in moved and DB_KW not in moved, moved)
check('scan 标注 database 永久豁免', 'database 节点永久豁免' in out, out[:600])

print('【B】源码层判据 + 元变异')
check('真源 cmd_classify 有 database 豁免', check_exempt(src, 'cmd_classify'))
check('真源 cmd_scan 有 database 豁免', check_exempt(src, 'cmd_scan'))
# 元变异：把两个函数体的豁免分支整段删掉 → 判据必须翻红
mutated = src
for fn in ('cmd_classify', 'cmd_scan'):
    body = _func_body(mutated, fn)
    if body:
        clean = re.sub(r"\s*# ★ 遗留登记:8.*?(?=\n        )", '', body, flags=re.S)
        clean = re.sub(r"\n\s*if kind == 'database':.*?continue\n", '\n', clean, flags=re.S)
        mutated = mutated.replace(body, clean, 1)
check('元变异：删豁免分支后 classify 判据转红', not check_exempt(mutated, 'cmd_classify'))
check('元变异：删豁免分支后 scan 判据转红', not check_exempt(mutated, 'cmd_scan'))

print(f'\n通过 {len(PASS)} / 失败 {len(FAIL)}')
sys.exit(0 if not FAIL else 1)
