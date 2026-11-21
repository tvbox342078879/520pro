#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_skill_sync_check.py — skill-sync-check 判据（云取第4条·查更新）。

四层（病15 防御：喂真函数看真输出，不读源码字符串）：
  A 结构层：正门存在 + 有 parse_version/compare_versions/build_update_report。
  B 版本比较层：点分数字逐段比（behind/ahead/same）、补零等价（1.0==1.0.0）、
    跨段（1.2>1.1.9）、非法（v1/空/非字符串/浮点）→ unknown fail-closed。
  C 报告层：喂真 contracts dict——behind/ahead/missing/unknown 各就位，summary 计数对。
  D 元变异有牙：①把 compare_versions 的补零逻辑改坏（不补零）→ 1.0 vs 1.0.0 应转非 same（证明判据锁住补零）；
    ②把 unknown 分支改成降级返回 same → 非法版本真值应转红。改的是加载后的模块副本，不碰真源。
  E 端到端：真 contracts 文件（本地 + 造一份远端）跑 CLI，验报告落盘 + 三态真输出。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MOD = os.path.join(REPO, '通用层', 'skills', 'skill-sync-check', 'scripts', 'skill_sync_check.py')
PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


spec = importlib.util.spec_from_file_location('skill_sync_check_mod', MOD)
M = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(M)
    loaded = True
except Exception as ex:
    loaded = False
    check('模块加载', False, repr(ex))

if loaded:
    # A 结构层
    for fn in ('parse_version', 'compare_versions', 'build_update_report', 'main'):
        check('A 有函数 %s' % fn, hasattr(M, fn))

    # B 版本比较层
    cv = M.compare_versions
    check('B 本地落后 → behind', cv('1.0.0', '1.1.0') == 'behind')
    check('B 本地超前 → ahead', cv('1.1.0', '1.0.0') == 'ahead')
    check('B 完全一致 → same', cv('2.8.0', '2.8.0') == 'same')
    check('B 补零等价 1.0==1.0.0 → same', cv('1.0', '1.0.0') == 'same')
    check('B 跨段 1.2>1.1.9 → ahead', cv('1.2', '1.1.9') == 'ahead')
    check('B 跨段 1.1.9<1.2 → behind', cv('1.1.9', '1.2') == 'behind')
    check('B v 前缀（市场 schema 版本）→ unknown', cv('v1', 'v2') == 'unknown')
    check('B 空串 → unknown', cv('', '1.0') == 'unknown')
    check('B 非字符串 → unknown', cv('1.0.0', 123) == 'unknown')
    check('B 带字母段 → unknown', cv('1.a.0', '1.0.0') == 'unknown')
    check('B 多段不等长补零 1.1.0.1>1.1.0 → ahead', cv('1.1.0.1', '1.1.0') == 'ahead')

    # C 报告层
    local = {'skills': {
        'a': {'version': '1.0.0'},  # 落后
        'b': {'version': '2.0.0'},  # 超前
        'c': {'version': '1.0.0'},  # 一致
        'd': {'version': 'v1'},     # 非法 → unknown
    }}
    remote = {'skills': {
        'a': {'version': '1.1.0'},
        'b': {'version': '1.0.0'},
        'c': {'version': '1.0.0'},
        'd': {'version': '2.0.0'},
        'e': {'version': '1.0.0'},  # 远端独有 → missing
    }}
    rep = M.build_update_report(local, remote)
    items = {it['skill']: it for it in rep['items']}
    check('C a 落后 behind', items['a']['status'] == 'behind', items.get('a'))
    check('C b 超前 ahead', items['b']['status'] == 'ahead', items.get('b'))
    check('C c 一致 same', items['c']['status'] == 'same', items.get('c'))
    check('C d 非法版本 unknown', items['d']['status'] == 'unknown', items.get('d'))
    check('C e 远端独有 missing', items['e']['status'] == 'missing', items.get('e'))
    s = rep['summary']
    check('C summary.total=5', s['total'] == 5, s)
    check('C summary 各态计数对', (s['behind'], s['ahead'], s['same'], s['unknown'], s['missing']) == (1, 1, 1, 1, 1), s)
    check('C 本地无 version 字段 → missing',
          M.build_update_report({'skills': {'x': {}}}, {'skills': {'x': {'version': '1.0'}}})['items'][0]['status'] == 'missing')
    check('C 非法契约（缺 skills）→ error + 空 items',
          M.build_update_report({}, {'skills': {}})['summary'].get('error') is not None)

    # D 元变异有牙（改加载副本，不碰真源）
    src = open(MOD, encoding='utf-8').read()
    # 变异①：破坏补零——把 width 对齐两行删掉，1.0 vs 1.0.0 变成短 tuple 直接比（(1,0)<(1,0,0) → behind，非 same）
    mut1 = src.replace("    width = max(len(a), len(b))\n    a = a + (0,) * (width - len(a))\n    b = b + (0,) * (width - len(b))\n", "", 1)
    check('D 变异①命中（删补零）', mut1 != src)
    if mut1 != src:
        ns1 = {'__name__': 'mut1'}
        exec(compile(mut1, 'mut1.py', 'exec'), ns1)
        m1 = ns1['compare_versions']
        check('D 变异①后 1.0 vs 1.0.0 不再 same（判据有牙）', m1('1.0', '1.0.0') != 'same', m1('1.0', '1.0.0'))
    # 变异②：把 unknown 降级为 same——非法版本应被真判据抓成 same（转红证明锁住 fail-closed）
    mut2 = src.replace("    except InvalidVersion:\n        return 'unknown'", "    except InvalidVersion:\n        return 'same'", 1)
    check('D 变异②命中（unknown→same）', mut2 != src)
    if mut2 != src:
        ns2 = {'__name__': 'mut2'}
        exec(compile(mut2, 'mut2.py', 'exec'), ns2)
        m2 = ns2['compare_versions']
        check('D 变异②后 v1 vs v2 变 same（判据有牙）', m2('v1', 'v2') == 'same', m2('v1', 'v2'))

    # E 端到端：真文件 + 造远端
    with tempfile.TemporaryDirectory() as td:
        lp = os.path.join(td, 'local.json')
        rp = os.path.join(td, 'remote.json')
        op = os.path.join(td, 'report.json')
        json.dump(local, open(lp, 'w', encoding='utf-8'), ensure_ascii=False)
        # 远端由真 contracts 派生：把 a 升版、删 c、加 e（模拟真实差异）
        json.dump(remote, open(rp, 'w', encoding='utf-8'), ensure_ascii=False)
        p = subprocess.run([sys.executable, MOD, '--local', lp, '--remote', rp, '--json-out', op],
                           capture_output=True, text=True)
        check('E CLI rc=0', p.returncode == 0, p.stderr[:200])
        if os.path.isfile(op):
            out = json.load(open(op, encoding='utf-8'))
            check('E 报告落盘 total=5', out['summary']['total'] == 5, out['summary'])
            check('E 报告含 behind=1', out['summary']['behind'] == 1, out['summary'])
        else:
            check('E 报告落盘', False, '未生成 %s' % op)
        # 真 contracts 自比（本地==本地，全 same，证明能喂真数据）
        real = os.path.join(REPO, 'verify', 'skill_contracts.json')
        p2 = subprocess.run([sys.executable, MOD, '--local', real, '--remote', real],
                            capture_output=True, text=True)
        check('E 真 contracts 自比 rc=0', p2.returncode == 0, p2.stderr[:200])
        if p2.returncode == 0:
            out2 = json.loads(p2.stdout)
            # 判据对象=真 contracts 的实际技能数（动态读，不硬编码——登记新技能后不误红，病15）
            real_count = len(json.load(open(real, encoding='utf-8')).get('skills', {}))
            check('E 真 contracts 自比全 same（%d 技能）' % real_count,
                  out2['summary']['same'] == out2['summary']['total'] == real_count, out2['summary'])

    # selftest
    p3 = subprocess.run([sys.executable, MOD, '--selftest'], capture_output=True, text=True)
    check('模块 --selftest OK', p3.returncode == 0 and 'OK' in p3.stdout, p3.stdout + p3.stderr)

print('\n结果：%s' % ('全部通过（%d 项）' % len(PASS) if not FAIL else '%d 项失败：%s' % (len(FAIL), ','.join(FAIL))))
sys.exit(1 if FAIL else 0)
