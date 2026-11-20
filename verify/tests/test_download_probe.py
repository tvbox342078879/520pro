#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_download_probe.py — download-probe 判据（云取 28+52 借鉴）。

四层（病15 防御：判据识别范围≠对象范围，喂真函数看真输出，不读源码字符串）：
  A 结构层：正门 probe.py 存在 + 有 probe/classify/is_internal_ip/ssrf_safe 四函数。
  B 函数层-is_internal_ip：回环/私网/CGNAT/保留 → True；公网 → False（喂真实 IP 字面量）。
  C 函数层-classify：206/bytes→range_ok；200+text/html→html_blocked+unknown；
     200 无 bytes→range_ignored；异常状态→unknown（喂真实 headers/body）。
  D 函数层-ssrf_safe/probe：内网 resolve→拒；假 opener 喂假 206/HTML 响应→真实结果；
     元变异去掉 HTML 识别后 C 层必须转红（防"判据对实现没接"假绿）。
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MOD = os.path.join(REPO, '通用层', 'skills', 'download-probe', 'scripts', 'probe.py')

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


spec = importlib.util.spec_from_file_location('probe_mod', MOD)
P = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(P)
    loaded = True
except Exception as ex:
    loaded = False
    check('模块加载', False, repr(ex))

if loaded:
    # A 结构层
    check('A 正门 probe.py 存在', os.path.isfile(MOD))
    for fn in ('probe', 'classify', 'is_internal_ip', 'ssrf_safe'):
        check(f'A 函数 {fn}', callable(getattr(P, fn, None)))

    # B is_internal_ip
    for ip in ('127.0.0.1', '10.0.0.1', '192.168.1.1', '172.16.0.1',
               '169.254.1.1', '100.64.0.1', '::1'):
        check(f'B 内网IP {ip} 判危险', P.is_internal_ip(ip) is True)
    for ip in ('8.8.8.8', '1.1.1.1', '93.184.216.34', '2001:4860:4860::8888'):
        check(f'B 公网IP {ip} 判安全', P.is_internal_ip(ip) is False)

    # C classify 三态 + HTML 拦截
    r = P.classify(206, {'Accept-Ranges': 'bytes'})
    check('C 206+bytes → range_ok', r['status'] == 'range_ok', r)
    r = P.classify(200, {'Accept-Ranges': 'bytes'})
    check('C 200+bytes → range_ok', r['status'] == 'range_ok', r)
    r = P.classify(200, {'Content-Type': 'text/html; charset=utf-8'}, b'<html>blocked')
    check('C 200+text/html → html_blocked', r['html_blocked'] is True, r)
    check('C 200+text/html → unknown(不折叠成功)', r['status'] == 'unknown', r)
    r = P.classify(200, {'Content-Type': 'text/html'}, b'<!DOCTYPE html>...')
    check('C body嗅探 Doctype → html_blocked', r['html_blocked'] is True, r)
    r = P.classify(200, {'Content-Length': '9999'})
    check('C 200无bytes → range_ignored', r['status'] == 'range_ignored', r)
    r = P.classify(302, {}, b'')
    check('C 302 → unknown', r['status'] == 'unknown', r)
    r = P.classify(404, {'Content-Type': 'application/octet-stream'})
    check('C 404非html → unknown', r['status'] == 'unknown', r)

    # D ssrf_safe + probe 端到端（假 opener，不触网）
    safe, _ = P.ssrf_safe('http://127.0.0.1/x', resolve=lambda h: ['127.0.0.1'])
    check('D 内网resolve→拒', safe is False)
    safe, _ = P.ssrf_safe('http://8.8.8.8/x', resolve=lambda h: ['8.8.8.8'])
    check('D 公网resolve→放行', safe is True)

    class FakeResp:
        def __init__(self, status, headers, body):
            self.status = status
            self.headers = type('H', (), {'items': lambda s: list(headers.items())})()
            self._body = body

        def read(self, n):
            return self._body[:n]

    fake206 = lambda req, timeout: FakeResp(206, {'Accept-Ranges': 'bytes'}, b'abc')
    out = P.probe('http://8.8.8.8/f', opener=fake206, resolve=lambda h: ['8.8.8.8'])
    check('D probe 假206 → range_ok', out['status'] == 'range_ok' and out['ssrf_safe'], out)

    fakehtml = lambda req, timeout: FakeResp(
        200, {'Content-Type': 'text/html'}, b'<html>error</html>')
    out = P.probe('http://8.8.8.8/f', opener=fakehtml, resolve=lambda h: ['8.8.8.8'])
    check('D probe 假HTML页 → blocked', out['html_blocked'] is True and out['status'] == 'unknown', out)

    out = P.probe('http://10.0.0.1/f', opener=fake206, resolve=lambda h: ['10.0.0.1'])
    check('D probe 内网URL → SSRF拒', out['ssrf_safe'] is False, out)

    # E 元变异有牙：把 classify 的 HTML 识别拿掉，C 层 HTML 判据必须转红
    import inspect
    import textwrap
    src = open(MOD, encoding='utf-8').read()
    mutated = src.replace("html_blocked = HTML_CT in ct or head.lstrip().lower().startswith(\n        (b'<!doctype html', b'<html'))", "html_blocked = False")
    if mutated != src:
        ns = {}
        exec(compile(mutated, MOD, 'exec'), ns)
        r2 = ns['classify'](200, {'Content-Type': 'text/html'}, b'<html>x')
        check('E 元变异去HTML识别→判据转红', r2['html_blocked'] is False)
    else:
        check('E 元变异注入', False, '未找到替换锚点')

print()
print(f'通过 {len(PASS)}/{len(PASS)+len(FAIL)}')
import sys
sys.exit(0 if not FAIL else 1)
