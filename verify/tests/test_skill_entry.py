#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤2 加载链判据：能力封 skill 后「能被路由 + 正门能真跑」双验。

病15 防线：C1 结构判据只查 entry 文件存在，抓不到「路径推导错、薄壳转调失败」
（本次两个薄壳首版都推错层级、--help/--status 全报无法判定）。本判据真 subprocess
跑薄壳，识别范围对齐对象范围——存在≠能跑。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PASS, FAIL = [], []


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    print(('  ✓ ' if ok else '  ✗ ') + name + ((' — ' + str(detail)) if detail else ''))


def run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except Exception as e:
        return -1, repr(e)


# 1) 在册：两技能登记进契约表
import json
try:
    contracts = json.load(open(os.path.join(ROOT, 'verify/skill_contracts.json'), encoding='utf-8'))
    skills = contracts.get('skills', {})
    for n in ('ad-audit', 'push-safe'):
        check('%s 在 skill_contracts.json 在册' % n, n in skills)
except Exception as e:
    check('契约表可读', False, repr(e))

# 2) 薄壳真转调（不是 AST 查存在，是真跑）
ad = os.path.join(ROOT, '通用层/skills/ad-audit/scripts/ad_audit.py')
rc, out = run([sys.executable, ad, '--help'])
check('ad-audit 薄壳真转调 pan.py ad-audit（--help 出 usage 非「无法判定」）',
      rc == 0 and 'usage:' in out and 'ad-audit' in out and '无法判定' not in out,
      out[:80].replace('\n', ' '))

ps = os.path.join(ROOT, '通用层/skills/push-safe/scripts/push_safe.sh')
rc, out = run(['bash', ps, '--status'])
# 病15 防线：正门 --status 的 `tail -5` 会带出共享推送日志原文（hooks/git_push_safe.sh:38），
# 拿日志里的具体字样（「无法判定：」等）做断言会在并发推送时自锁——
# 推→pre-push 跑本判据→本判据读到本次推送日志→误红→推失败（2026-11-18 实测死锁）。
# 正解：只验「薄壳转调到达正门且出三态标记之一」，日志内容可变不参与断言；
# 薄壳路径推导错时正门不在位（含「不在位」）仍被排除，识别范围回归对象范围。
status_markers = ('最近一次推送', '尚无推送记录', '无法判定：日志无')
check('push-safe 薄壳真转调 hooks/git_push_safe.sh（--status 出三态之一，非「不在位」）',
      any(m in out for m in status_markers) and '不在位' not in out,
      out[:80].replace('\n', ' '))

# 3) 触发词前置（description 前 40 字含「当用户」）——复用契约机检 C9 口径
sys.path.insert(0, os.path.join(ROOT, 'verify'))
try:
    import skill_contract_check as scc
    for n in ('ad-audit', 'push-safe'):
        spec = skills.get(n, {})
        base = os.path.join(ROOT, spec.get('path', ''))
        desc = scc.fm_get(scc.front_matter(scc.read(os.path.join(base, 'SKILL.md'))), 'description')
        ok, msg = scc.check_frontload(desc)
        check('%s 触发语义前置（C9）' % n, ok, msg)
except Exception as e:
    check('C9 口径可复用', False, repr(e))

print('\n%d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
