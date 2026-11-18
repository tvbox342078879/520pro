#!/usr/bin/env python3
"""机制判据：踩坑→能力→直达（exp_direct）闭环。

验证三件事（真阳性/真阴性/无法判定，B-02）：
  ① 数据：exp_entries 带 fixed_path + symptom 字段（命中才有解法可直达）
  ② 查询：exp_probe.match(symptom) 命中返回 fixed_path，不命中返回 None
  ③ 呈现：next_anchor 注入段含「💡直达」且命中即记账（注入≠复用，调 hit）

先红后绿：改动前本文件应 FAIL。
"""
import os
import sys
import json
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'verify'))

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name)


# ① 数据层：真实经验库里存在带 fixed_path 的条目
try:
    rec = json.load(open(os.path.join(ROOT, 'experience_recurrence.json'), encoding='utf-8'))
    es = rec.get('exp_entries') or []
    with_fp = [e for e in es if e.get('fixed_path')]
    check('exp_entries 有 fixed_path 字段（命中可直达）', len(with_fp) > 0)
    check('fixed_path 指回真实文件落点（.py/.md/.sh/.json/命令）',
          len(with_fp) > 0 and all(
              any(tok in str(e['fixed_path']) for tok in
                  ('.py', '.md', '.sh', '.json', 'pan ', 'probe '))
              for e in with_fp[:5]))
except Exception as ex:
    check('exp_entries 有 fixed_path 字段（命中可直达）', False)
    print('    err=%r' % ex)

# ② 查询层：match(symptom) 命中/不命中
try:
    import exp_probe
    check('exp_probe 有 match(symptom) 直达查询接口', hasattr(exp_probe, 'match'))
    if hasattr(exp_probe, 'match'):
        # 用词库里真实存在的症状（白名单判据子串匹配致假绿），验证命中能带出落点
        hit = exp_probe.match('白名单判据用子串匹配 FIELDS 坏实现假绿', rec=rec)
        check('命中症状返回 fixed_path', bool(hit) and bool(hit.get('fixed_path')))
        miss = exp_probe.match('完全无关的量子 berry 相位', rec=rec)
        check('不相关症状不误命中（真阴性）', not miss)
except Exception as ex:
    check('exp_probe 有 match(symptom) 直达查询接口', False)
    print('    err=%r' % ex)

# ③ 呈现层：注入段升级为「💡直达」且命中记账
try:
    anchor = open(os.path.join(ROOT, 'hooks', 'next_anchor.py'), encoding='utf-8').read()
    check('next_anchor 注入段含「💡直达」', '💡直达' in anchor)
    check('命中即调 exp_distill.hit 记账（注入≠复用）',
          'hit(' in anchor and ('exp_distill' in anchor or 'fixed_path' in anchor))
except Exception as ex:
    check('next_anchor 注入段含「💡直达」', False)
    print('    err=%r' % ex)

print('\n%d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
