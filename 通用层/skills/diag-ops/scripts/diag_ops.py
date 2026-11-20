#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_ops.py — 诊断运维三件套（云取借鉴 53+3+48，diag-ops 正门）。

三项能力（证据等级见 SKILL.md §6）：
  53 启动对账：进程重启把 running(1)/queued(0) 一条 UPDATE 收敛为 paused(2)，幂等——
    实证 /tmp/yunget_round4_ops.txt:34-37 SQL "UPDATE download_task SET status = 2 WHERE status = 1 OR status = 0"。
  3 崩溃现场：UncaughtExceptionHandler → crash_<毫秒>.txt → recordCrash → 导出
    最近 3 份各截 16384 字 + logcat 末 3 万行（转录归纳，DEX 类名实证）。
  48 日志脱敏：正则表 redact → <redacted>（DEX LogRedactor.kt 类名实证）。

设计：纯函数 + 规则表驱动（脱敏规则可注入）；判据喂真样本看输出，不读源码字符串。
三态：ok / skipped / unknown；对账幂等（重复跑 changed=0）。
"""
import argparse
import json
import re
import sys

# ── 53 状态常量（SQL 实证 status 1/0 → 2）──
STATUS_QUEUED, STATUS_RUNNING, STATUS_PAUSED = 0, 1, 2
INTERRUPTED_STATES = (STATUS_QUEUED, STATUS_RUNNING)


def reconcile_tasks(tasks):
    """启动对账：把 queued(0)/running(1) 收敛为 paused(2)，幂等。
    返回 dict：status=ok，changed=本次改动数，tasks=收敛后新列表（不改入参）。"""
    if not isinstance(tasks, list):
        return {'status': 'unknown', 'reason': '任务表非列表', 'changed': 0, 'tasks': []}
    out, changed = [], 0
    for t in tasks:
        if not isinstance(t, dict):
            return {'status': 'unknown', 'reason': '任务条目非字典', 'changed': 0, 'tasks': []}
        t2 = dict(t)
        if t2.get('status') in INTERRUPTED_STATES:
            t2['status'] = STATUS_PAUSED
            changed += 1
        out.append(t2)
    return {'status': 'ok', 'changed': changed, 'tasks': out}


# ── 3 崩溃现场：导出窗口常量（转录归纳）──
EXPORT_RECENT_N = 3
EXPORT_CHUNK = 16384
LOGCAT_TAIL_LINES = 30000


def capture_crash(exc_type, message, ts_ms, trace=''):
    """崩溃落盘记录：crash_<毫秒>.txt 元信息（不真的写盘，落盘归调用方）。"""
    if not isinstance(ts_ms, (int, float)):
        return {'status': 'unknown', 'reason': '时间戳必须是数字'}
    return {'status': 'ok', 'file': 'crash_%d.txt' % int(ts_ms),
            'type': str(exc_type), 'message': str(message),
            'trace': str(trace)[:EXPORT_CHUNK]}


def export_diag(reports, logcat='', recent_n=EXPORT_RECENT_N,
                chunk=EXPORT_CHUNK, tail_lines=LOGCAT_TAIL_LINES):
    """导出最近 N 份崩溃报告（各截 chunk 字）+ logcat 末 tail_lines 行。
    reports: [{'ts_ms':..,'text':..}, ...]；按 ts_ms 排序取最近。"""
    if not isinstance(reports, list):
        return {'status': 'unknown', 'reason': '报告列表非列表'}
    valid = [r for r in reports if isinstance(r, dict) and isinstance(r.get('ts_ms'), (int, float))]
    valid.sort(key=lambda r: r['ts_ms'])
    recent = valid[-recent_n:] if recent_n > 0 else []
    parts = [{'ts_ms': r['ts_ms'], 'text': str(r.get('text', ''))[:chunk]} for r in recent]
    log_lines = str(logcat).splitlines()
    tail = log_lines[-tail_lines:] if tail_lines > 0 else []
    return {'status': 'ok' if (parts or tail) else 'skipped',
            'reports': parts, 'logcat_tail': tail,
            'total_reports': len(valid)}


# ── 48 日志脱敏：规则表（DEX LogRedactor 正则→<redacted>）──
REDACT_RULES = [
    ('token', re.compile(r'(?i)(token|api[_-]?key|secret)[：:= ]+([A-Za-z0-9_\-]{6,})'), '<redacted>'),
    ('password', re.compile(r'(?i)(密码|password|pwd)[：:= ]+(\S{4,})'), '<redacted>'),
    ('phone', re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)'), '<redacted>'),
]
REDACTED = '<redacted>'


def redact(text, rules=None):
    """日志脱敏：规则表驱动替换；返回 (脱敏文本, 命中次数)。规则可注入（判据验表驱动）。"""
    rules = REDACT_RULES if rules is None else rules
    if not isinstance(text, str):
        return {'status': 'unknown', 'reason': '输入非字符串'}
    out, hits = text, 0
    for name, rx, repl in rules:
        try:
            out, n = rx.subn(repl, out)
        except Exception:
            return {'status': 'unknown', 'reason': '脱敏规则 %s 非法' % name}
        hits += n
    return {'status': 'ok' if hits else 'skipped', 'text': out, 'hits': hits,
            'redacted': REDACTED}


def _self_check():
    r = reconcile_tasks([{'id': 1, 'status': 1}, {'id': 2, 'status': 0}, {'id': 3, 'status': 2}])
    ok1 = (r['status'] == 'ok' and r['changed'] == 2
           and [t['status'] for t in r['tasks']] == [2, 2, 2]
           and reconcile_tasks(r['tasks'])['changed'] == 0)
    c = capture_crash('NullPointer', 'boom', 1700000000000)
    ok2 = c['file'] == 'crash_1700000000000.txt'
    e = export_diag([{'ts_ms': i, 'text': 'x' * 20} for i in range(5)], logcat='a\nb')
    ok3 = (e['status'] == 'ok' and len(e['reports']) == 3 and e['logcat_tail'] == ['a', 'b'])
    d = redact('token=abc123456 密码: p8n7 13800138000')
    ok4 = (d['hits'] >= 2 and REDACTED in d['text'])
    return ok1 and ok2 and ok3 and ok4


def main():
    ap = argparse.ArgumentParser(description='诊断运维三件套（diag-ops 正门）')
    ap.add_argument('cmd', nargs='?', help='reconcile/redact 或 JSON 文件路径')
    ap.add_argument('--logcat', help='logcat 文本（测试用）')
    ap.add_argument('--selftest', action='store_true', help='自省自检')
    ap.add_argument('--json-out', help='结果写入 JSON 文件')
    a = ap.parse_args()
    if a.selftest:
        ok = _self_check()
        print('SELFTEST %s' % ('OK' if ok else 'FAIL'))
        return 0 if ok else 2
    if a.cmd and a.cmd.endswith('.json'):
        with open(a.cmd, encoding='utf-8') as f:
            payload = json.load(f)
        if 'tasks' in payload:
            out = reconcile_tasks(payload['tasks'])
        elif 'reports' in payload:
            out = export_diag(payload['reports'], a.logcat or payload.get('logcat', ''))
        elif 'text' in payload:
            out = redact(payload['text'])
        else:
            out = {'status': 'unknown', 'reason': 'JSON 需含 tasks/reports/text 之一'}
    elif a.cmd == 'redact':
        out = redact(a.logcat or '')
    else:
        out = {'status': 'unknown', 'reason': '给 JSON 文件路径或 redact 文本；--selftest 自检'}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if a.json_out:
        with open(a.json_out, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == '__main__':
    sys.exit(main())
