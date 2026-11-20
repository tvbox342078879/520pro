#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_share_parser.py — share-parser 判据（云取 26+33 借鉴）。

五层（病15 防御：判据识别范围≠对象范围，喂真函数看真输出，不读源码字符串）：
  A 结构层：正门 share_parser.py 存在 + 有 parse_share/extract_pwd/expire_text/extract_urls 函数。
  B 平台规则层：夸克/百度/115/迅雷/移动链接真样本 → 正确 platform + share_id；无命中 → no_match。
  C 密码双通道层：URL query pwd 优先；正文中文标签回退；两路都无 → None；channel 正确。
  D 有效期层：-1/1/3/7/15 → 正确文案；未知代码抛 UnknownExpireCode（不折叠）。
  E 元变异有牙：①注入精简规则表验规则驱动（新增平台只加一条）；②改坏规则表后 parse_share 真转 no_match
    （防"判据对实现没接"假绿）；③未知代码从抛异常改成返回默认 → D 层转红。
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MOD = os.path.join(REPO, '通用层', 'skills', 'share-parser', 'scripts', 'share_parser.py')

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


spec = importlib.util.spec_from_file_location('share_parser_mod', MOD)
P = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(P)
    loaded = True
except Exception as ex:
    loaded = False
    check('模块加载', False, repr(ex))

if loaded:
    # A 结构层
    check('A 正门 share_parser.py 存在', os.path.isfile(MOD))
    for fn in ('parse_share', 'extract_pwd', 'expire_text', 'extract_urls'):
        check(f'A 函数 {fn}', callable(getattr(P, fn, None)))

    # B 平台规则层（真链接样本）
    cases = [
        ('https://pan.quark.cn/s/abc123XYZ', 'quark', 'abc123XYZ'),
        ('https://pan.baidu.com/s/1AbCdEf_gh', 'baidu', '1AbCdEf_gh'),
        ('https://pan.xunlei.com/s/XL999abc', 'xunlei', 'XL999abc'),
        ('https://caiyun.139.com/s/AB12cd34', 'mobile', 'AB12cd34'),
    ]
    for text, plat, sid in cases:
        r = P.parse_share(text)
        check(f'B 平台 {plat}', r['platform'] == plat, r)
        check(f'B shareId {plat}', r['share_id'] == sid, r)
    r115 = P.parse_share('https://115.com/swABCDEF12-abcd')
    check('B 平台 115', r115['platform'] == '115', r115)
    r = P.parse_share('这是一段没有链接的文字')
    check('B 无命中 → no_match', r['status'] == 'no_match', r)
    check('B 空输入 → unknown', P.parse_share('   ')['status'] == 'unknown')

    # C 密码双通道层
    pwd, ch = P.extract_pwd('提取码: a1b2', url='https://pan.quark.cn/s/abc?pwd=w1234')
    check('C URL query 优先', pwd == 'w1234' and ch == 'url', (pwd, ch))
    pwd, ch = P.extract_pwd('https://pan.baidu.com/s/1AbCd 访问码：x9k2')
    check('C 正文中文标签回退', pwd == 'x9k2' and ch == 'text', (pwd, ch))
    pwd, ch = P.extract_pwd('密码：p8n7', url='https://pan.quark.cn/s/abc')
    check('C 密码标签命中', pwd == 'p8n7' and ch == 'text', (pwd, ch))
    pwd, ch = P.extract_pwd('无任何提取码', url='https://pan.quark.cn/s/abc')
    check('C 两路都无 → None', pwd is None and ch is None, (pwd, ch))
    r = P.parse_share('https://pan.quark.cn/s/abc123?pwd=w1234')
    check('C parse_share 集成 URL 通道', r['pwd'] == 'w1234' and r['pwd_channel'] == 'url', r)

    # D 有效期层
    for code, txt in [(-1, '永久有效'), (1, '1 天'), (3, '3 天'), (7, '7 天'), (15, '15 天')]:
        check(f'D 有效期 {code}', P.expire_text(code) == txt, P.expire_text(code))
    for bad in (0, 99, 'x', None):
        try:
            P.expire_text(bad)
            check(f'D 未知代码 {bad} 抛异常', False, '没抛')
        except P.UnknownExpireCode:
            check(f'D 未知代码 {bad} 抛异常', True)

    # E 元变异有牙
    # ① 注入只有一条规则的规则表 → 百度链接不再命中（验规则驱动，非硬编码 if）
    import re
    only_quark = [('quark', re.compile(r'pan\.quark\.cn/s/([A-Za-z0-9]+)', re.I), 1)]
    r = P.parse_share('https://pan.baidu.com/s/1AbCdEf', rules=only_quark)
    check('E① 精简规则表 → 百度 no_match（规则驱动）', r['status'] == 'no_match', r)
    # ② 注入自定义新平台规则 → 解析成功（新增平台只加一条）
    new_rule = [('newplat', re.compile(r'new\.example\.com/s/([A-Za-z0-9]+)', re.I), 1)]
    r = P.parse_share('https://new.example.com/s/NEW123', rules=new_rule)
    check('E② 新增一条规则即解析（不动主流程）',
          r['platform'] == 'newplat' and r['share_id'] == 'NEW123', r)
    # ③ 元变异：改坏捕获组序号 → 优雅降级 unknown，不抛崩（函数真读规则表，非背答案）
    bad_rule = [('quark', re.compile(r'pan\.quark\.cn/s/([A-Za-z0-9]+)', re.I), 2)]
    r = P.parse_share('https://pan.quark.cn/s/abc123', rules=bad_rule)
    check('E③ 改坏捕获组 → unknown 不抛崩（判据有牙）', r['status'] == 'unknown', r)

print(f'\n=== test_share_parser: {len(PASS)}✓ / {len(FAIL)}✗ ===')
if FAIL:
    for f in FAIL:
        print('  FAIL:', f)
    raise SystemExit(1)
print('ALL PASS')
