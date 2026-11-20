#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe.py — 下载能力探测（云取借鉴 28+52，download-probe 正门）。

两个能力：
  A Range 能力探测：发 Range: bytes=0-0，读 ETag/Last-Modified/Accept-Ranges，
    分 200/206 分支，识别 text/html 假成功错误页（机房 IP 被拦返页）。
  B SSRF 防护：探测目标拒 loopback/私网/保留地址，请求永不打向内网。

设计：纯函数 + 可注入 opener——判据喂真实结构输入看真实输出，不读源码字符串。
三态：range_ok / range_ignored / unknown；html_blocked 单独标记，不折叠成成功。
"""
import argparse
import ipaddress
import json
import socket
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# 机房 IP 常见假成功页：Content-Type 是 text/html 而非真实资源。
HTML_CT = 'text/html'

# 探测请求只带一个字节，避免下载真实内容。
PROBE_RANGE = 'bytes=0-0'


def is_internal_ip(ip_text):
    """纯函数：IP 是否属内网/回环/保留/链路本地 —— SSRF 判据核心。
    用 ipaddress 标准分类，不靠字符串前缀猜（病15：识别范围≠对象范围）。"""
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        # 不是合法 IP 字面量（可能是域名），由 is_internal_host 负责解析后判定
        return None
    return (ip.is_loopback or ip.is_private or ip.is_reserved
            or ip.is_link_local or ip.is_multicast or ip.is_unspecified
            or ip_text.startswith('100.') and ip.version == 4)  # 100.64/10 CGNAT


def is_internal_host(host):
    """域名 → 解析所有 A/AAAA，任一内网即判危险；解析失败一律 fail-closed（拒）。
    resolve 可注入（测试离线喂 IP），避免真实 DNS 依赖。"""
    if is_internal_ip(host) is True:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True  # 解析不出 → 当危险处理，不放行探测
    for info in infos:
        ip = info[4][0]
        if is_internal_ip(ip) is True:
            return True
    return False


def ssrf_safe(url, resolve=None):
    """URL 是否可安全探测。resolve(host) -> [ip,...] 可注入。"""
    parsed = urlparse(url if '://' in url else 'http://' + url)
    host = parsed.hostname or ''
    if not host:
        return False, '无 host'
    if resolve is None:
        if is_internal_host(host):
            return False, 'host 解析为内网/保留地址或解析失败'
    else:
        ips = resolve(host) or []
        if not ips:
            return False, 'resolve 无结果（fail-closed）'
        for ip in ips:
            if is_internal_ip(ip) is True:
                return False, f'解析到内网/保留地址 {ip}'
    return True, 'host 非内网'


def classify(status, headers, body_head=b''):
    """纯函数：由响应三要素判三态 + 是否 HTML 拦截页。
    headers 大小写不敏感；body_head 嗅探 <html 兜住 Content-Type 缺失的假页。"""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    ct = str(h.get('content-type', ''))
    accept_ranges = str(h.get('accept-ranges', ''))
    head = body_head[:256] if isinstance(body_head, bytes) else str(body_head).encode()
    html_blocked = HTML_CT in ct or head.lstrip().lower().startswith(
        (b'<!doctype html', b'<html'))
    if html_blocked:
        return {'status': 'unknown', 'html_blocked': True,
                'reason': '返回 HTML 页（疑被拦/假成功），不折叠为成功'}
    if status == 206 or 'bytes' in accept_ranges.lower():
        return {'status': 'range_ok', 'html_blocked': False,
                'reason': '206 或 Accept-Ranges: bytes —— 支持 Range 续传'}
    if status == 200:
        return {'status': 'range_ignored', 'html_blocked': False,
                'reason': '200 且无 bytes 宣告 —— Range 被忽略，走单流'}
    return {'status': 'unknown', 'html_blocked': False,
            'reason': f'非常规状态 {status} —— 无法判定'}


def probe(url, opener=None, resolve=None, timeout=8):
    """正门探测。opener(req, timeout) 可注入（测试喂假响应）；
    真实路径用 urlopen。返回 dict，含 ssrf_safe / status / html_blocked / headers / reason。"""
    safe, why = ssrf_safe(url, resolve=resolve)
    if not safe:
        return {'url': url, 'ssrf_safe': False, 'status': 'unknown',
                'html_blocked': False, 'headers': {}, 'reason': 'SSRF 拒绝：' + why}
    req = Request(url, headers={'Range': PROBE_RANGE, 'User-Agent': 'download-probe/1.0'})
    fn = opener or (lambda r, t: urlopen(r, timeout=t))
    try:
        resp = fn(req, timeout)
        code = getattr(resp, 'status', None) or getattr(resp, 'code', 200)
        headers = dict(resp.headers.items()) if hasattr(resp, 'headers') else {}
        body = resp.read(256) if hasattr(resp, 'read') else b''
    except Exception as ex:
        return {'url': url, 'ssrf_safe': True, 'status': 'unknown',
                'html_blocked': False, 'headers': {}, 'reason': '探测异常：' + repr(ex)}
    result = classify(code, headers, body)
    result.update({'url': url, 'ssrf_safe': True,
                   'headers': headers, 'http_status': code})
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description='下载能力探测（Range + SSRF，云取 28+52 借鉴）')
    ap.add_argument('url', nargs='?', help='要探测的直链 URL')
    ap.add_argument('--json-out', help='结果 JSON 落盘路径（可选）')
    a = ap.parse_args(argv)
    if not a.url:
        ap.print_help()
        return 0
    out = probe(a.url)
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    if a.json_out:
        with open(a.json_out, 'w', encoding='utf-8') as f:
            f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
