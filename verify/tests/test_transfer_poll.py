#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_transfer_poll.py — transfer-poll 判据（云取 32+56/23 借鉴）。

六层（病15 防御：判据识别范围≠对象范围，喂真函数看真输出，不读源码字符串）：
  A 结构层：正门 transfer_poll.py 存在 + 四函数可调用。
  B 间隔表层：光鸭 750 / 夸克 1000 / UC 1000；陌生平台 → 默认 1000；注入表驱动。
  C 状态机层：done/success → done；failed/error → failed；running/未知 → pending 继续轮询。
  D 设备标识层：random_device_id → 32 hex 且随机；device_sign → div101.+32hex；盐注入真影响结果。
  E 元变异有牙：①改间隔表 → poll_interval 真变（规则驱动）；②改哈希链顺序 → 签名真变（非背答案）。
  F CLI 端到端：真跑 subprocess --interval / --status / --device-id / --sign / --selftest。
"""
import importlib.util
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MOD = os.path.join(REPO, '通用层', 'skills', 'transfer-poll', 'scripts', 'transfer_poll.py')

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


spec = importlib.util.spec_from_file_location('transfer_poll_mod', MOD)
P = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(P)
    loaded = True
except Exception as ex:
    loaded = False
    check('模块加载', False, repr(ex))

if loaded:
    # A 结构层
    check('A 正门 transfer_poll.py 存在', os.path.isfile(MOD))
    for fn in ('poll_interval', 'classify_task', 'random_device_id', 'device_sign'):
        check(f'A 函数 {fn}', callable(getattr(P, fn, None)))

    # B 间隔表层
    check('B 光鸭 750', P.poll_interval('guangya') == 750)
    check('B 夸克 1000', P.poll_interval('quark') == 1000)
    check('B UC 1000', P.poll_interval('uc') == 1000)
    check('B 陌生平台 → 默认 1000', P.poll_interval('unknown_plat') == 1000)
    check('B 注入表驱动', P.poll_interval('x', table={'x': 42}) == 42)

    # C 状态机层
    for st in ('done', 'success', 'completed', '2'):
        r = P.classify_task(st)
        check(f'C {st} → done', r['status'] == 'done' and r['continue_polling'] is False, r)
    for st in ('failed', 'error', 'canceled', '-1'):
        r = P.classify_task(st)
        check(f'C {st} → failed', r['status'] == 'failed' and r['continue_polling'] is False, r)
    r = P.classify_task('running')
    check('C running → pending', r['status'] == 'pending', r)
    check('C pending 继续轮询', r['continue_polling'] is True, r)
    r = P.classify_task('weird_state')
    check('C 未知状态 → pending 不折叠', r['status'] == 'pending', r)
    r = P.classify_task('running', platform='guangya')
    check('C 光鸭进度文案', '光鸭' in r['text'], r)
    r = P.classify_task('failed', detail='任务状态查询失败')
    check('C 失败文案透传 detail', r['text'] == '任务状态查询失败', r)

    # D 设备标识层
    d1, d2 = P.random_device_id(), P.random_device_id()
    check('D deviceId 32 hex', len(d1) == 32 and all(c in '0123456789abcdef' for c in d1), d1)
    check('D deviceId 随机', d1 != d2, (d1, d2))
    import re
    sg = P.device_sign('device123', 'saltA')
    check('D 签名 div101. 前缀', sg.startswith('div101.'), sg)
    check('D 签名 div101.+32hex', re.fullmatch(r'div101\.[0-9a-f]{32}', sg) is not None, sg)
    check('D 盐真影响结果', P.device_sign('id', 'saltA') != P.device_sign('id', 'saltB'))
    check('D 同 id 同盐确定性', P.device_sign('id', 's') == P.device_sign('id', 's'))

    # E 元变异有牙
    # ① 注入改间隔表 → poll_interval 真变（函数真读表，非硬编码 if）
    check('E① 注入间隔表 → 真变', P.poll_interval('x', table={'x': 999}) == 999)
    # ② 独立重算签名链，验证脚本真按 SHA1→MD5 顺序（非返回写死值）
    import hashlib
    expect = 'div101.' + hashlib.md5(
        hashlib.sha1(('device123' + 'saltA').encode()).hexdigest().encode()
    ).hexdigest()
    check('E② 签名链 SHA1→MD5 真算对', sg == expect, (sg, expect))
    # ③ 前缀常量可注入验（若把前缀改掉，签名形态必变）
    check('E③ 前缀常量在签名里', P.DEVICE_SIGN_PREFIX == 'div101.')

    # F CLI 端到端（真 subprocess，防"函数对但没接线"）
    def run(*args):
        return subprocess.run(['python3', MOD, *args], capture_output=True, text=True)
    r = run('--selftest')
    check('F CLI selftest rc=0', r.returncode == 0 and 'OK' in r.stdout, r.stdout)
    r = run('--interval', 'guangya')
    check('F CLI interval=750', json.loads(r.stdout)['interval_ms'] == 750, r.stdout)
    r = run('--status', 'running', '--platform', 'quark')
    d = json.loads(r.stdout)
    check('F CLI status=pending', d['status'] == 'pending' and d['continue_polling'], d)
    r = run('--device-id')
    check('F CLI device-id 32hex', len(json.loads(r.stdout)['device_id']) == 32, r.stdout)
    r = run('--sign', 'id1', '--salt', 's1')
    check('F CLI sign div101.', json.loads(r.stdout)['device_sign'].startswith('div101.'), r.stdout)

print(f'\n=== test_transfer_poll: {len(PASS)}✓ / {len(FAIL)}✗ ===')
if FAIL:
    for f in FAIL:
        print('  FAIL:', f)
    raise SystemExit(1)
print('ALL PASS')
