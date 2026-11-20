#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""share_parser.py — 网盘分享链接统一解析（云取借鉴 26+33，share-parser 正门）。

两个能力（DEX 方法体内实证，见 /tmp/yunget_round4_ops.txt）：
  A 统一平台解析：共享 URL 正则 + 平台 shareId 正则表；新增平台只加一条正则，不动主流程。
    密码双通道——先查 URL query（pwd/pass/password），回退全文中文标签（提取码/访问码/密码）。
  B 有效期代码映射：-1/1/3/7/15 → 永久有效/1天/3天/7天/15天；未知值显式报错，不静默。

设计：纯函数 + 规则表驱动——判据喂真实链接/文本样本看真实输出，不读源码字符串。
三态：parsed（解析成功）/ no_match（无平台命中）/ unknown（无法判定）；未知有效期代码抛异常。
"""
import argparse
import json
import re
import sys

# ── 平台 shareId 规则表（新增平台只加一条，不动 parse_share 主流程）──
# (平台名, shareId 正则, shareId 捕获组序号)
PLATFORM_RULES = [
    ('quark', re.compile(r'pan\.quark\.cn/s/([A-Za-z0-9]+)', re.I), 1),
    ('baidu', re.compile(r'pan\.baidu\.com/s/(1[A-Za-z0-9_-]+)', re.I), 1),
    ('115', re.compile(r'115(?:cdn|rc)?\.com/(sw[A-Za-z0-9]{8,})-([A-Za-z0-9]{4,8})', re.I), 1),
    ('lanzou', re.compile(r'lanzou[a-z]*\.com/([A-Za-z0-9]+)', re.I), 1),
    ('xunlei', re.compile(r'pan\.xunlei\.com/s/([A-Za-z0-9]+)', re.I), 1),
    ('mobile', re.compile(r'caiyun\.139\.com/(?:s|share)/([A-Za-z0-9]+)', re.I), 1),
]
URL_RE = re.compile(r'https?://[^\s<>"\']+', re.I)

# ── 密码双通道：URL query 优先，全文中文标签回退 ──
PWD_QUERY_RE = re.compile(r'[?&](?:pwd|pass|passcode|password)=([A-Za-z0-9]{4,12})', re.I)
PWD_TEXT_RE = re.compile(r'(?:提取码|访问码|密码)[：:\s]*([A-Za-z0-9]{4,8})', re.I)

# ── 有效期代码映射（DEX ShareExpire.fromCode/toText 实证）──
EXPIRE_CODES = {-1: '永久有效', 1: '1 天', 3: '3 天', 7: '7 天', 15: '15 天'}


class UnknownExpireCode(Exception):
    """未知有效期代码——显式报错，不静默折叠。"""


def extract_urls(text):
    """从任意文本里截出 URL 列表（urlRegex）。"""
    if not isinstance(text, str):
        return []
    return [m.group(0).rstrip('.,;，。；') for m in URL_RE.finditer(text)]


def extract_pwd(text, url=None):
    """密码双通道：URL query 优先，回退全文中文标签。返回 (pwd, channel) 或 (None, None)。"""
    if url:
        m = PWD_QUERY_RE.search(url)
        if m:
            return m.group(1), 'url'
    m = PWD_TEXT_RE.search(text or '')
    if m:
        return m.group(1), 'text'
    return None, None


def parse_share(text, rules=None):
    """主流程：trim → URL 截取 → 平台正则取 shareId → 密码双通道 → ParsedShare。
    rules 可注入（判据喂自定义规则表，验"新增平台只加一条"）；返回三态 dict。"""
    rules = PLATFORM_RULES if rules is None else rules
    if not isinstance(text, str) or not text.strip():
        return {'status': 'unknown', 'reason': '空输入', 'platform': None,
                'share_id': None, 'pwd': None, 'pwd_channel': None}
    s = text.strip()
    urls = extract_urls(s)
    target = urls[0] if urls else s
    for name, rx, group in rules:
        m = rx.search(target)
        if not m:
            continue
        try:
            share_id = m.group(group)
        except IndexError:
            # 规则表配错捕获组序号（扩展点人为失误）→ 无法判定，不抛崩、不硬造 share_id。
            return {'status': 'unknown', 'reason': '规则捕获组配置错误',
                    'platform': name, 'share_id': None, 'pwd': None, 'pwd_channel': None}
        pwd, channel = extract_pwd(s, url=target)
        return {'status': 'parsed', 'platform': name, 'share_id': share_id,
                'pwd': pwd, 'pwd_channel': channel, 'url': target}
    return {'status': 'no_match', 'reason': '无平台正则命中', 'platform': None,
            'share_id': None, 'pwd': None, 'pwd_channel': None}


def expire_text(code):
    """有效期代码 → 展示文本；未知值抛 UnknownExpireCode（不静默）。"""
    try:
        return EXPIRE_CODES[code]
    except (KeyError, TypeError):
        raise UnknownExpireCode('未知的分享有效期代码：%r' % (code,))


def _self_check():
    cases = [
        (parse_share('https://pan.quark.cn/s/abc123XYZ 提取码: a1b2')['platform'] == 'quark'),
        (parse_share('https://pan.baidu.com/s/1AbC_dEf 密码：x9k2')['pwd'] == 'x9k2'),
        (parse_share('https://pan.quark.cn/s/abc123?pwd=w1234')['pwd_channel'] == 'url'),
        (parse_share('这是一段没有链接的文字')['status'] == 'no_match'),
        (expire_text(-1) == '永久有效' and expire_text(15) == '15 天'),
    ]
    return all(cases)


def main():
    ap = argparse.ArgumentParser(description='网盘分享链接统一解析（share-parser 正门）')
    ap.add_argument('text', nargs='?', help='含链接/提取码的文本')
    ap.add_argument('--expire', type=int, help='有效期代码 → 文本')
    ap.add_argument('--selftest', action='store_true', help='自省自检')
    ap.add_argument('--json-out', help='结果写入 JSON 文件')
    a = ap.parse_args()
    if a.selftest:
        ok = _self_check()
        print('SELFTEST %s' % ('OK' if ok else 'FAIL'))
        return 0 if ok else 2
    if a.expire is not None:
        try:
            out = {'code': a.expire, 'text': expire_text(a.expire)}
        except UnknownExpireCode as ex:
            out = {'status': 'unknown', 'reason': str(ex)}
            print(json.dumps(out, ensure_ascii=False))
            return 3
    else:
        out = parse_share(a.text or '')
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if a.json_out:
        with open(a.json_out, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == '__main__':
    sys.exit(main())
