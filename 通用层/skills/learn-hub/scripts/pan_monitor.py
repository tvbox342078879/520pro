#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网盘监测（上游取料仓）—— learn-hub pan.py 的 companion。

定位：定期查分享清单 → 发现新增文件 → 产出「待转存清单」。不下载、不转存。
转存由下游 pan.py save 消费队列完成（两层用清单文件解耦）。

复用（不重造）：
  - pan.py: pan_parse_share_ex / _pan_req / _load_pan_cookie（同目录 import）
  - learn.py: ST_OK/ST_MISS/ST_UNK/_UNKNOWN_MARKS（三态单一真源）
  - probe-hub monitor: 清单 + 周期到期范式（add/due/check）

零明文（B-05）：cookie 只读本地文件/环境变量，绝不写入 targets/queue（字段白名单）。
三态不折叠：412/登录墙/网络 → unknown（不动指纹、不推队列）；明确 404 → miss。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pan as _pan                                            # noqa: E402
from learn import ST_OK, ST_MISS, ST_UNK, _UNKNOWN_MARKS      # noqa: E402

TARGETS = os.path.join(_HERE, 'pan_monitor_targets.json')
QUEUE = os.path.join(_HERE, 'pan_monitor_queue.json')
_MISS_MARKS = ('404', '已删除', '已失效', '不存在', '分享不可用', '410', '403')
_CADENCE_DAYS = {'每日': 1, '每周': 7, '每月': 30}
LIVE_LABEL = {ST_OK: '活', ST_MISS: '失效', ST_UNK: '无法判定'}
FIELDS = ('url', 'passcode', 'cadence', 'last_checked', 'next_due',
          'last_fingerprint', 'known_fids', 'status')


# ── 功能一：测活（三态 → 活/失效/无法判定，显式出口）───────────
def live_label(tri):
    """测活结果的人读标签；三态不折叠——「无法判定」不并入「失效」。"""
    return LIVE_LABEL.get(tri, LIVE_LABEL[ST_UNK])


# ── 纯函数（测试可直接验）─────────────────────────────────────
def classify_text(text):
    """三态分类：unknown 优先于 miss——登录墙/412 不是"资源不存在"。"""
    t = str(text or '')
    low = t.lower()
    if any(m in low for m in _UNKNOWN_MARKS):
        return ST_UNK
    if any(m in t for m in _MISS_MARKS):
        return ST_MISS
    return ST_OK


def fingerprint(items):
    """清单指纹：按 fid:size 排序后 sha256——顺序无关、内容变即变。"""
    key = '|'.join(sorted(f"{x.get('fid', '')}:{x.get('size', 0)}"
                          for x in (items or [])))
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def diff_new(items, known_fids):
    """差集：只返回 fid 不在 known_fids 的条目；保持输入顺序。"""
    known = set(known_fids or ())
    return [x for x in (items or []) if x.get('fid') and x['fid'] not in known]


def next_due(cadence, base_ts=None):
    """按周期算下次到期（ISO8601）；未知周期保守取每周。"""
    days = _CADENCE_DAYS.get(cadence or '每周', 7)
    ts = (time.time() if base_ts is None else base_ts) + days * 86400
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def is_due(target, now_ts=None):
    """到期判定：无 next_due / 无法解析 → 保守当到期（宁可多查不漏料）。"""
    nd = (target or {}).get('next_due') or ''
    if not nd:
        return True
    try:
        dt = datetime.strptime(nd, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return (time.time() if now_ts is None else now_ts) >= dt.timestamp()


def evaluate(target, fetcher):
    """对单 target 跑一次检查。fetcher(url, passcode) -> {'state','items'}。

    返回 (更新后的 target 副本, 新增 items, 三态)。不改入参、不碰网络（fetcher 注入）。
    unknown/miss 都不动指纹、不推队列——这是三态不折叠的落点。
    """
    try:
        res = fetcher(target.get('url', ''), target.get('passcode', '')) or {}
    except Exception as e:
        res = {'state': ST_UNK, 'items': [], 'error': str(e)}
    tri = res.get('state') or ST_UNK
    updated = dict(target or {})
    if tri != ST_OK:
        updated['status'] = 'miss' if tri == ST_MISS else 'unknown'
        return updated, [], tri
    items = res.get('items') or []
    fp = fingerprint(items)
    known = set(updated.get('known_fids') or ())
    new = diff_new(items, known)
    updated.update({
        'last_fingerprint': fp,
        'known_fids': sorted(known | {x['fid'] for x in items if x.get('fid')}),
        'last_checked': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'next_due': next_due(updated.get('cadence')),
        'status': 'ok',
    })
    return updated, new, ST_OK


# ── 网络层：走 pan.py 底层请求（只读、不下载、不转存）────────────
def norm_baidu_items(raw):
    """百度 _baidu_collect 条目 → 统一结构 {fid,name,size}；过滤目录。

    百度 fs_id（整数）→ fid（字符串），与夸克/UC/迅雷的 fid 归一，指纹/差集共用。
    """
    out = []
    for r in (raw or []):
        if r.get('isdir'):
            continue
        out.append({'fid': str(r.get('fs_id')), 'name': r.get('name') or '',
                    'size': int(r.get('size') or 0)})
    return out


def _fetch_baidu(pwd_id, passcode, url, limit=500):
    """百度分享列清单：复用 pan.py 百度原生链路（shareinfo→stoken→collect）。

    与夸克/UC/迅雷的 /1/clouddrive API **不同构**——百度必须走网页端
    share 接口（pan.py:227 的 info 分派同源）。errno=-12（提取码/登录态）归 unknown，
    不动指纹、不推队列。
    """
    ck = _pan._load_pan_cookie('baidu')
    if not ck:
        return {'state': ST_UNK, 'items': [], 'platform': 'baidu',
                'pwd_id': pwd_id, 'error': '缺百度 cookie'}
    ok, shareid, share_uk, _bd, err = _pan._baidu_shareinfo(pwd_id, passcode, ck)
    if not ok:
        return {'state': classify_text(err), 'items': [], 'platform': 'baidu',
                'pwd_id': pwd_id, 'error': err}
    # 带密码分享走 randsk→BDCLND cookie（TVBox 实证）;公开分享跳过 verify。
    # 不再用 "stoken 为空=失败" ——公开分享 stoken 本就为空却是成功（病15 同型）。
    ck_use = ck
    if passcode:
        rk, e = _pan._baidu_randsk(pwd_id, passcode, ck)
        if e:
            return {'state': classify_text(e), 'items': [], 'platform': 'baidu',
                    'pwd_id': pwd_id, 'error': e}
        ck_use = _pan._baidu_authed_cookie(ck, rk)
    out = []
    e2 = _pan._baidu_collect(pwd_id, passcode, ck_use, shareid, share_uk, out)
    if e2:
        return {'state': classify_text(e2), 'items': [], 'platform': 'baidu',
                'pwd_id': pwd_id, 'error': e2}
    items = norm_baidu_items(out)[:limit]
    return {'state': ST_OK, 'items': items, 'platform': 'baidu',
            'pwd_id': pwd_id, 'partial': False}


def fetch_listing(url, passcode='', limit=500):
    """复用 pan.py 底层列清单；返回 {'state','items',...}。"""
    pwd_id, plat = _pan.pan_parse_share_ex(url)
    if not pwd_id:
        return {'state': ST_UNK, 'items': [], 'error': '认不出分享 id', 'platform': ''}
    if plat == 'baidu':
        return _fetch_baidu(pwd_id, passcode, url, limit=limit)
    ok, r = _pan._pan_req(
        '/1/clouddrive/share/sharepage/token?pr=ucpro&fr=pc&uc_param_str=',
        {'pwd_id': pwd_id, 'passcode': passcode or ''}, platform=plat)
    if not ok:
        return {'state': classify_text(r), 'items': [], 'error': str(r),
                'platform': plat, 'pwd_id': pwd_id}
    if r.get('status') != 200:
        msg = f"{r.get('code', '')} {r.get('message', '')}"
        return {'state': classify_text(msg), 'items': [], 'error': msg,
                'platform': plat, 'pwd_id': pwd_id}
    st = r['data']['stoken']
    queue, items, seen, partial = [('0', '')], [], 0, False
    while queue and seen < limit:
        pdir, prefix = queue.pop(0)
        q = (f'/1/clouddrive/share/sharepage/detail?pr=ucpro&fr=pc'
             f'&pwd_id={pwd_id}&stoken={quote(st, safe="")}&pdir_fid={pdir}'
             f'&force=0&_page=1&_size=200&_fetch_total=1')
        ok, d = _pan._pan_req(q, platform=plat)
        if not ok:
            partial = True
            break
        for f in ((d.get('data') or {}).get('list') or []):
            seen += 1
            name = f'{prefix}{f.get("file_name") or ""}'
            if f.get('dir'):
                queue.append((f['fid'], name + '/'))
            else:
                items.append({'fid': f.get('fid'), 'name': name,
                              'size': int(f.get('size') or 0)})
    # 部分目录读取失败 → 清单不完整 → unknown，不推队列（避免漏料被误判为"无新增"）
    return {'state': ST_UNK if partial else ST_OK, 'items': items,
            'platform': plat, 'pwd_id': pwd_id, 'partial': partial}


# ── 状态文件（字段白名单，零明文）──────────────────────────────
def _atomic_write(path, obj):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_targets(path=None):
    try:
        d = json.load(open(path or TARGETS, encoding='utf-8'))
        return d.get('targets', []) if isinstance(d, dict) else []
    except Exception:
        return []


def save_targets(path, targets):
    """白名单落盘：cookie/token 一律不进状态文件（B-05 零明文）。"""
    clean = [{k: t[k] for k in FIELDS if k in t} for t in (targets or [])]
    _atomic_write(path, {'version': 1, 'targets': clean})


def load_queue(path=None):
    try:
        d = json.load(open(path or QUEUE, encoding='utf-8'))
        return d.get('items', []) if isinstance(d, dict) else []
    except Exception:
        return []


def save_queue(path, items):
    qf = ('fid', 'name', 'size', 'url', 'platform', 'state', 'created', 'updated')
    clean = [{k: x[k] for k in qf if k in x} for x in (items or [])]
    _atomic_write(path, {'version': 1, 'items': clean})


# ── 命令层 ────────────────────────────────────────────────────
def cmd_add(a):
    url = (a.url or '').strip()
    pwd_id, plat = _pan.pan_parse_share_ex(url)
    if not pwd_id:
        print('❌ 认不出分享 id（需夸克/UC/迅雷/百度分享链接）')
        return 2
    targets = load_targets()
    if any(t.get('url') == url for t in targets):
        print('ℹ️ 已在监测清单（幂等）')
        return 0
    cadence = a.every or '每周'
    targets.append({'url': url, 'passcode': a.passcode or '', 'cadence': cadence,
                    'status': 'new', 'next_due': next_due(cadence),
                    'last_fingerprint': '', 'known_fids': []})
    save_targets(TARGETS, targets)
    print(f'✅ 已登记监测源：{plat} {pwd_id}｜周期 {cadence}')
    return 0


def cmd_due(a):
    now = time.time()
    due = [t for t in load_targets() if is_due(t, now)]
    if a.json:
        print(json.dumps(due, ensure_ascii=False, indent=1))
        return 0
    if not due:
        print('（无到期监测源）')
        return 0
    for t in due:
        print(f'  · {t.get("url", "")[:70]}｜周期 {t.get("cadence")}'
              f'｜上次 {t.get("last_checked") or "从未"}')
    return 0


def cmd_check(a):
    targets = load_targets()
    now = time.time()
    queue = load_queue()
    out, n_new, n_unk, n_miss = [], 0, 0, 0
    for t in targets:
        if not a.all_ and not is_due(t, now):
            continue
        updated, new, tri = evaluate(t, fetch_listing)
        out.append(updated)
        if tri == ST_UNK:
            n_unk += 1
        elif tri == ST_MISS:
            n_miss += 1
        exist = {(q.get('url'), q.get('fid')) for q in queue}
        for x in new:
            key = (t['url'], x['fid'])
            if key in exist:
                continue
            exist.add(key)
            queue.append({
                'url': t['url'], 'fid': x['fid'], 'name': x.get('name', ''),
                'size': x.get('size', 0), 'platform': updated.get('platform', ''),
                'state': 'pending',
                'created': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            })
            n_new += 1
        print(f'  · {t.get("url", "")[:55]}｜测活={live_label(tri)}｜测更新=+{len(new)}')
    if not a.dry:
        save_targets(TARGETS, out)
        save_queue(QUEUE, queue)
    else:
        print('（--dry：未写状态文件）')
    print(f'检查完成：查了 {len(out)} 源｜新料入队 {n_new}｜无法判定 {n_unk}｜失效 {n_miss}')
    return 0


def cmd_queue(a):
    q = load_queue()
    if a.json:
        print(json.dumps(q, ensure_ascii=False, indent=1))
        return 0
    if not q:
        print('（待转存队列空）')
        return 0
    for x in q:
        print(f'  [{x.get("state")}] {x.get("name")}｜{x.get("url", "")[:50]}')
    return 0


def cmd_save(a):
    """消费队列：逐条调 pan.py save --fid（现成转存正门，不重造转存逻辑）。"""
    pp = os.path.join(_HERE, 'pan.py')
    q = load_queue()
    pend = [x for x in q if x.get('state') == 'pending']
    if not pend:
        print('（无待转存条目）')
        return 0
    if not a.yes:
        for x in pend[:20]:
            print(f'  · {x.get("name")}｜{x.get("url", "")[:50]}')
        print(f'\n共 {len(pend)} 条待转存。加 --yes 才真转存（调 pan.py save）。')
        return 0
    ok_n = fail_n = 0
    for x in pend:
        cmd = [sys.executable, pp, 'save', '--url', x['url'], '--fid', x['fid']]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout)
            rc, tail = r.returncode, ((r.stdout or '') + (r.stderr or ''))[-200:]
        except Exception as e:
            rc, tail = -1, f'{type(e).__name__}: {e}'
        if rc == 0:
            x['state'] = 'done'
            ok_n += 1
        else:
            x['state'] = 'failed'
            x['error'] = tail
            fail_n += 1
        print(f'  [{"ok" if x["state"] == "done" else "fail"}] {x.get("name")}')
        save_queue(QUEUE, q)  # 逐条落盘，防中断丢进度
    print(f'转存完成：成功 {ok_n}｜失败 {fail_n}（失败留 failed 可重放）')
    return 0 if fail_n == 0 else 1


def build_parser():
    ap = argparse.ArgumentParser(
        description='网盘监测（上游取料仓）：查清单 → 比指纹 → 出待转存清单')
    sp = ap.add_subparsers(dest='cmd')
    ad = sp.add_parser('add', help='登记监测源')
    ad.add_argument('--url', required=True)
    ad.add_argument('--passcode', default='')
    ad.add_argument('--every', default='每周', choices=['每日', '每周', '每月'])
    du = sp.add_parser('due', help='列出到期源')
    du.add_argument('--json', action='store_true')
    ck = sp.add_parser('check', help='查清单 + 比指纹 + 新料入队')
    ck.add_argument('--dry', action='store_true')
    ck.add_argument('--all', dest='all_', action='store_true', help='忽略到期，全查')
    qu = sp.add_parser('queue', help='看待转存清单')
    qu.add_argument('--json', action='store_true')
    sv = sp.add_parser('save', help='消费队列 → 调 pan.py save（--yes 才真转）')
    sv.add_argument('--yes', action='store_true')
    sv.add_argument('--timeout', type=int, default=120)
    sp.add_parser('self-check', help='判据自检（指纹/三态/去重/零明文）')
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if not a.cmd:
        build_parser().print_help()
        return 0
    if a.cmd == 'self-check':
        # 测试文件在 <repo>/verify/tests/；pan_monitor.py 在 <repo>/通用层/skills/learn-hub/scripts/
        _repo = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(_HERE))))
        r = subprocess.run([sys.executable, os.path.join(
            _repo, 'verify', 'tests', 'test_pan_monitor.py')],
            capture_output=True, text=True)
        print(r.stdout or r.stderr)
        return r.returncode
    return {'add': cmd_add, 'due': cmd_due, 'check': cmd_check,
            'queue': cmd_queue, 'save': cmd_save}.get(a.cmd, lambda _: 0)(a)


if __name__ == '__main__':
    sys.exit(main() or 0)
