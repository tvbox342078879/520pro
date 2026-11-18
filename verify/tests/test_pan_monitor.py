#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_pan_monitor.py — 网盘监测层（上游取料仓）机器判据。

两层判据（病15 防御：判据识别范围 ≠ 对象范围）：
  A 行为层：指纹/差集/三态/due/evaluate/状态零明文——喂造好样本验纯函数。
  B 源码层：check_no_cookie_persist 精确锚定 save_targets 函数体的字段白名单；
            喂删掉白名单的坏源码应红（元变异，证判据贴实现，非永远绿）。
"""
import ast
import os
import sys
import tempfile
import time as _t

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO, '通用层', 'skills', 'learn-hub', 'scripts')
sys.path.insert(0, SCRIPTS)
import pan_monitor as M  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


def items(*triples):
    return [{'fid': f, 'name': n, 'size': s} for f, n, s in triples]


def check_no_cookie_persist(src):
    """精确锚定 save_targets 函数体：必须引用 FIELDS 标识符（AST 词级，非子串）。

    病15 防御：判据识别范围必须是"标识符 FIELDS"，不能是子串——否则
    WIPED_FIELDS 仍含 FIELDS 子串，坏实现会假绿（本测自己就踩过一次）。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'save_targets':
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            return 'FIELDS' in names and 'clean' in names
    return False


def check_baidu_dispatch(src):
    """判据：fetch_listing 必须把 baidu 分派到百度原生链路，不许拿夸克 API path 套百度。

    病15 防御：锚定 fetch_listing 函数体内的分派分支 + _fetch_baidu 定义存在，
    不扫全文注释；且必须是 'baidu' 平台判断 + 复用 _baidu_shareinfo/_baidu_collect。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    if '_fetch_baidu' not in defs:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'fetch_listing':
            seg = ast.get_source_segment(src, node) or ''
            return ("'baidu'" in seg and '_fetch_baidu' in seg
                    and '_baidu_shareinfo' in src and '_baidu_collect' in src)
    return False


def check_two_functions(src):
    """显式判据：监测同时具备「测活」「测更新」两个命名出口（用户 2026-11-18 要求）。

    测活出口 = live_label(三态→活/失效/无法判定)；测更新出口 = diff_new + fingerprint。
    判据锚定函数定义存在 + cmd_check 输出同时含两个功能字样（病15：不扫全文注释）。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    has_live = 'live_label' in defs
    has_fresh = 'diff_new' in defs and 'fingerprint' in defs
    # 输出层两功能都得显式出现（不是隐藏在流程里）
    out_ok = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'cmd_check':
            seg = ast.get_source_segment(src, node) or ''
            out_ok = '测活' in seg and '测更新' in seg
    return has_live and has_fresh and out_ok


# ── A1 指纹 ──
i1 = items(('f1', 'a.pdf', 100), ('f2', 'b.mp4', 200))
i1r = items(('f2', 'b.mp4', 200), ('f1', 'a.pdf', 100))
i2 = items(('f1', 'a.pdf', 100), ('f2', 'b.mp4', 200), ('f3', 'c.zip', 300))
check('指纹相同一致', M.fingerprint(i1) == M.fingerprint(i1))
check('指纹顺序无关', M.fingerprint(i1) == M.fingerprint(i1r))
check('指纹新增即变', M.fingerprint(i1) != M.fingerprint(i2))

# ── A2 差集去重 ──
check('差集只出新 fid', [x['fid'] for x in M.diff_new(i2, {'f1', 'f2'})] == ['f3'])
check('差集全已知则空', M.diff_new(i1, {'f1', 'f2'}) == [])

# ── A3 三态分类 ──
check('412 归无法判定', M.classify_text('HTTP 412 precondition failed') == M.ST_UNK)
check('timeout 归无法判定', M.classify_text('timeout') == M.ST_UNK)
check('登录墙归无法判定', M.classify_text('需要登录 login') == M.ST_UNK)
check('404 归确定取不到', M.classify_text('分享不可用 code=404 已删除') == M.ST_MISS)
check('正常归 ok', M.classify_text('200 ok 清单已取') == M.ST_OK)

# ── A4 due 判定 ──
future = M.next_due('每周', base_ts=0)
past = M.next_due('每周', base_ts=_t.time())
check('到期源 due=True', M.is_due({'next_due': future}, now_ts=_t.time()) is True)
check('未到期 due=False', M.is_due({'next_due': past}, now_ts=_t.time()) is False)
check('无 next_due 保守到期', M.is_due({}, now_ts=_t.time()) is True)
check('坏 next_due 保守到期', M.is_due({'next_due': 'bad'}, now_ts=_t.time()) is True)

# ── A5 evaluate（注入 fetcher，不碰网络）──
t = {'url': 'https://pan.quark.cn/s/abc', 'cadence': '每周',
     'known_fids': ['f1'], 'last_fingerprint': M.fingerprint(i1)}
upd, new, tri = M.evaluate(t, lambda u, p: {'state': 'ok', 'items': i2})
check('evaluate ok 出新 fid', [x['fid'] for x in new] == ['f2', 'f3'], [x['fid'] for x in new])
check('evaluate 更新指纹', upd['last_fingerprint'] == M.fingerprint(i2))
check('evaluate 不更改入参', t['known_fids'] == ['f1'])
unk_upd, unk_new, _ = M.evaluate(t, lambda u, p: {'state': 'unknown', 'items': i2})
check('evaluate unknown 不推队列',
      unk_new == [] and unk_upd['last_fingerprint'] == t['last_fingerprint'])
miss_upd, _, _ = M.evaluate(t, lambda u, p: {'state': 'miss', 'items': []})
check('evaluate miss 标失效', miss_upd.get('status') == 'miss')

# ── A7 功能一：测活（三态 → 活/失效/无法判定，显式出口）──
check('测活 ok→活', M.live_label(M.ST_OK) == '活', M.live_label(M.ST_OK))
check('测活 miss→失效', M.live_label(M.ST_MISS) == '失效', M.live_label(M.ST_MISS))
check('测活 unknown→无法判定', M.live_label(M.ST_UNK) == '无法判定', M.live_label(M.ST_UNK))

# ── A6 状态文件零明文 ──
with tempfile.TemporaryDirectory() as d:
    tp = os.path.join(d, 'targets.json')
    M.save_targets(tp, [{'url': 'u', 'cookie': 'FAKE_COOKIE_SENTINEL',
                         'passcode': '1234', 'status': 'ok'}])
    raw = open(tp, encoding='utf-8').read()
    check('targets 不含 cookie 字段', 'cookie' not in raw)
    check('targets 不含凭证值', 'FAKE_COOKIE_SENTINEL' not in raw)
    check('targets 保留 passcode', '1234' in raw)
    check('targets 回读正常', M.load_targets(tp)[0]['url'] == 'u')

# ── B 元变异：判据贴实现 ──
src = open(os.path.join(SCRIPTS, 'pan_monitor.py'), encoding='utf-8').read()
check('源码判据：真实现有白名单', check_no_cookie_persist(src))
bad = src.replace('FIELDS', 'WIPED_FIELDS')
check('元变异：坏实现被判红', not check_no_cookie_persist(bad))

# ── B2 元变异：两功能判据贴实现 ──
check('两功能：测活+测更新出口都在', check_two_functions(src))
bad2 = src.replace('def live_label', 'def live_label_X').replace('测更新', '刷新')
check('元变异：拆掉任一功能应红', not check_two_functions(bad2))

# ── B3 元变异：百度分派判据贴实现 ──
check('百度分派：baidu 走原生链路', check_baidu_dispatch(src))
bad3 = src.replace("if plat == 'baidu':", "if plat == 'xxxxx':")
check('元变异：拆掉百度分派应红', not check_baidu_dispatch(bad3))

# ── A8 百度清单归一化（fs_id→fid、过滤目录）──
braw = [
    {'fs_id': 111, 'name': 'a.pdf', 'isdir': False, 'size': 100},
    {'fs_id': 222, 'name': 'sub/', 'isdir': True, 'size': 0},
    {'fs_id': 333, 'name': 'sub/b.mp4', 'isdir': False, 'size': 200},
]
bnorm = M.norm_baidu_items(braw)
check('百度条目 fid=fs_id', [x['fid'] for x in bnorm] == ['111', '333'], bnorm)
check('百度条目过滤目录', len(bnorm) == 2)
check('百度条目保留 name/size', bnorm[1]['name'] == 'sub/b.mp4' and bnorm[1]['size'] == 200)
check('百度指纹可用于差集', M.fingerprint(bnorm) == M.fingerprint(items(('111', 'a.pdf', 100), ('333', 'sub/b.mp4', 200))))

print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
sys.exit(1 if FAIL else 0)
