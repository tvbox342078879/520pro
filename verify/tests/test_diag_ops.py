#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_diag_ops.py — diag-ops 判据（云取 53+3+48）。

五层（病15 防御：喂真函数看真输出）：
  A 结构层：正门存在 + 有 reconcile_tasks/capture_crash/export_diag/redact 函数。
  B 53 对账层：running(1)/queued(0)→paused(2)，不改入参，幂等（重复 changed=0），非法→unknown。
  C 3 崩溃现场层：crash_<毫秒>.txt 命名 + trace 截断 + export 取最近N份各截chunk + logcat末N行。
  D 48 脱敏层：token/密码/手机号 → <redacted>；无命中→skipped；命中数正确。
  E 元变异：①注入自定义脱敏规则→真生效（非背答案）；②改坏正则→unknown 不静默；
    ③改坏状态常量→对账真变（判据有牙）；④注入 recent_n/chunk→导出窗口真变。
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MOD = os.path.join(REPO, '通用层', 'skills', 'diag-ops', 'scripts', 'diag_ops.py')

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


spec = importlib.util.spec_from_file_location('diag_ops_mod', MOD)
D = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(D)
    loaded = True
except Exception as ex:
    loaded = False
    check('模块加载', False, repr(ex))

if loaded:
    import re
    # A 结构层
    check('A 正门 diag_ops.py 存在', os.path.isfile(MOD))
    for fn in ('reconcile_tasks', 'capture_crash', 'export_diag', 'redact'):
        check(f'A 函数 {fn}', callable(getattr(D, fn, None)))

    # B 53 对账层
    tasks = [{'id': 1, 'status': 1}, {'id': 2, 'status': 0}, {'id': 3, 'status': 2}, {'id': 4, 'status': 9}]
    r = D.reconcile_tasks(tasks)
    check('B 对账 status=ok', r['status'] == 'ok', r)
    check('B changed=2（1+0 两条）', r['changed'] == 2, r)
    check('B running→paused', r['tasks'][0]['status'] == 2, r)
    check('B queued→paused', r['tasks'][1]['status'] == 2, r)
    check('B 已 paused 不动', r['tasks'][2]['status'] == 2, r)
    check('B 其他状态(9)不动', r['tasks'][3]['status'] == 9, r)
    check('B 不改入参', tasks[0]['status'] == 1, tasks)
    check('B 幂等（重复 changed=0）', D.reconcile_tasks(r['tasks'])['changed'] == 0)
    check('B 非法输入→unknown', D.reconcile_tasks('not-a-list')['status'] == 'unknown')

    # C 3 崩溃现场层
    c = D.capture_crash('NullPointer', 'boom', 1700000000000, trace='x' * 30000)
    check('C 崩溃文件名 crash_<毫秒>.txt', c['file'] == 'crash_1700000000000.txt', c)
    check('C trace 截断到 chunk', len(c['trace']) == D.EXPORT_CHUNK, len(c['trace']))
    check('C 非数字时间戳→unknown', D.capture_crash('E', 'm', 'bad')['status'] == 'unknown')
    reports = [{'ts_ms': i, 'text': 'line%d' % i} for i in range(1, 8)]
    logs = '\n'.join('log%d' % i for i in range(10))
    e = D.export_diag(reports, logcat=logs)
    check('C 导出取最近3份', len(e['reports']) == 3, e)
    check('C 最近3份是 ts 5/6/7', [p['ts_ms'] for p in e['reports']] == [5, 6, 7], e)
    check('C logcat 末行保留', e['logcat_tail'][-1] == 'log9', e)
    check('C 空输入→skipped', D.export_diag([], logcat='')['status'] == 'skipped')

    # D 48 脱敏层
    d = D.redact('token=abc123456 密码: p8n7 手机 13800138000')
    check('D 三规则命中', d['hits'] == 3, d)
    check('D 全部替换成 <redacted>', D.REDACTED in d['text'] and 'abc123456' not in d['text'], d)
    check('D 无命中→skipped', D.redact('普通日志无敏感信息')['status'] == 'skipped')
    check('D 非字符串→unknown', D.redact(123)['status'] == 'unknown')

    # E 元变异有牙
    custom = [('only-X', re.compile(r'X-\d+'), '<redacted>')]
    d2 = D.redact('X-123 token=abc123456', rules=custom)
    check('E① 注入自定义规则→只命中 X', d2['hits'] == 1 and 'X-123' not in d2['text'], d2)
    check('E①b 自定义规则不误伤 token（真读注入表）', 'abc123456' in d2['text'], d2)
    class BadRule:
        def subn(self, repl, out):
            raise re.error('坏规则')
    bad_rules = [('bad', BadRule(), '<redacted>')]
    d3 = D.redact('anything', rules=bad_rules)
    check('E② 改坏正则→unknown 不静默', d3['status'] == 'unknown', d3)
    # ③ 改坏状态常量 → 对账真变
    orig = D.INTERRUPTED_STATES
    try:
        D.INTERRUPTED_STATES = (9,)  # 只把状态9当中断
        r3 = D.reconcile_tasks([{'id': 1, 'status': 1}, {'id': 4, 'status': 9}])
        check('E③ 改中断态常量→对账真变', r3['changed'] == 1 and r3['tasks'][1]['status'] == 2, r3)
    finally:
        D.INTERRUPTED_STATES = orig
    # ④ 注入导出窗口 → 真变
    e2 = D.export_diag(reports, logcat=logs, recent_n=1, tail_lines=2)
    check('E④ 注入 recent_n=1→只1份', len(e2['reports']) == 1, e2)
    check('E④b 注入 tail_lines=2→末2行', e2['logcat_tail'] == ['log8', 'log9'], e2)

print(f'\n=== test_diag_ops: {len(PASS)}✓ / {len(FAIL)}✗ ===')
if FAIL:
    for f in FAIL:
        print('  FAIL:', f)
    raise SystemExit(1)
print('ALL PASS')
