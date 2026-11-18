#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_baidu_transfer.py — 百度 share/transfer 转存契约判据。

契约真源：云取 YunGet v2.7.12 BaiduApi$transfer$2 smali 实证 + 2026-11-18 本机
带登录态真跑 errno=0。旧实现的三处致命差异固化为判据：
  ① uk 的参数名必须是 from=（旧写 uk= → errno=2 参数错误）
  ② sekey=<randsk> 必须进 URL query（旧缺失）
  ③ bdstoken/sekey/ondup 在 query，body 只有 fsidlist+path（旧全塞 body）
病15 防御：判据读 `_baidu_transfer_req` 的**真实返回构造**，非源码子串猜；
元变异拆掉任一关键参数应红（证明判据贴实现、有牙）。
"""
import os
import sys
import urllib.parse as up

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO, '通用层', 'skills', 'learn-hub', 'scripts')
sys.path.insert(0, SCRIPTS)
import pan  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


def req(sid='50504599287', uk='1101451575119', bt='b026da3d',
        rk='QUbV8e4FYk%2FrwB', fsids=('621144773951214',), to='/'):
    return pan._baidu_transfer_req(sid, uk, bt, rk, list(fsids), to)


url, body, hdr = req()
q = up.parse_qs(up.urlsplit(url).query)
b = up.parse_qs(body.decode('utf-8'))

print('── 参数落点（真构造，非子串）──')
check('URL 路径是 /share/transfer', up.urlsplit(url).path == '/share/transfer', url)
check('分享者 uk 用 from= 参数（非 uk=）',
      q.get('from') == ['1101451575119'] and 'uk' not in q, q)
check('sekey=randsk 在 query（parse_qs 已解码）',
      q.get('sekey') == [up.unquote('QUbV8e4FYk%2FrwB')], q.get('sekey'))
check('bdstoken 在 query 不在 body',
      q.get('bdstoken') == ['b026da3d'] and 'bdstoken' not in b, (q.get('bdstoken'), list(b)))
check('ondup=newcopy 在 query', q.get('ondup') == ['newcopy'], q.get('ondup'))
check('app_id=250528 / web=1 / clienttype=0',
      q.get('app_id') == ['250528'] and q.get('web') == ['1'] and q.get('clienttype') == ['0'], q)
check('body 只有 fsidlist+path 两项', set(b) == {'fsidlist', 'path'}, list(b))
check('fsidlist 是 JSON 数组字符串',
      b.get('fsidlist') == ['["621144773951214"]'], b.get('fsidlist'))
check('多 fs_id 保持数组',
      up.parse_qs(req(fsids=('111', '222', '333'))[1].decode())['fsidlist'] == ['["111", "222", "333"]'])
check('path 在 body（urlencode 编码 /→%2F）',
      '%2F' in body.decode() and b.get('path') == ['/'], body.decode())

print('── 请求头 ──')
check('带 Origin: pan.baidu.com', hdr.get('Origin') == 'https://pan.baidu.com', hdr.get('Origin'))
check('form-urlencoded + charset',
      'application/x-www-form-urlencoded' in hdr.get('Content-Type', '')
      and 'UTF-8' in hdr.get('Content-Type', ''), hdr.get('Content-Type'))

print('── 三态 / 边界 ──')
check('公开分享（rk 空）sekey 为空不报错',
      up.parse_qs(up.urlsplit(req(rk='')[0]).query, keep_blank_values=True).get('sekey') == [''],
      up.urlsplit(req(rk='')[0]).query)
check('空 fsids 产出空数组', up.parse_qs(req(fsids=())[1].decode())['fsidlist'] == ['[]'])

print('── 元变异（判据有牙：拆关键参数应红）──')
_src = open(os.path.join(SCRIPTS, 'pan.py'), encoding='utf-8').read()
check('真源码含 from= 契约', "'&from=' + str(share_uk)" in _src)
check('真源码含 sekey 契约', "'&channel=chunlei&sekey=' + (randsk or '')" in _src)
check('真源码含 ondup=newcopy', "'&ondup=newcopy&web=1&app_id='" in _src)
# --to 默认 '0'(fid) → 百度路径 '/' 映射
check('--to 0→/ 映射在位（百度要路径不要 fid）',
      "baidu_to = '/' if to == '0' else to" in _src)
mut = _src.replace("'&from=' + str(share_uk)", "'&uk=' + str(share_uk)")
check('元变异：把 from 改回 uk 应红（判据贴实现）', "'&from=' + str(share_uk)" not in mut)

print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
sys.exit(1 if FAIL else 0)
