#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""景门（M4）文档一致 · 回归测试（工程G-2）

跑法：python3 verify/tests/test_docsync.py
退出码：0 全过 / 2 有失败

这面 2026-11-12 大改过一次，改动理由值得留在这里：
  旧判据 = 登记册写死的 declared 常量 vs 代码计数。代码加个子命令、没人记得改登记册，
  这面就永久红。实测 space-hub 登记 14、代码实际 19 —— 连续几轮巡检都红着，
  而人一习惯"这面老是红"，真吹牛就被淹了。**假红的价值等于零，还倒扣信任。**
  新判据 = 文档现读 vs 代码现读，两边都是集合，能说出"多哪个/少哪个"。
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, '通用层', 'skills', 'inspect-hub', 'scripts'))
import inspect_hub as H  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print(('  ✓ ' if ok else '  ✗ ') + name + ('' if ok else f'（期望 {want!r}，实得 {got!r}）'))
    if not ok:
        fails.append(name)


def cfg():
    import json
    reg = json.load(open(os.path.join(REPO, '通用层', 'skills', 'inspect-hub',
                                      'scripts', 'inspect_registry.json'), encoding='utf-8'))
    for g in reg['gates']:
        if g['id'] == 'M4':
            return g['config']
    raise AssertionError('登记册里没有 M4')


def run():
    r = H.chk_docsync(REPO, cfg(), {})
    return r['status'], [i['t'] for i in r['items']]


print('【正例】真仓库两技能文档与代码对得上')
st, ts = run()
check('状态 green', st, 'green')
# 两种绿口径不同，别混：列全的报"一致"，不列全的必须把"未列 N 条不判"写进标题
check('probe-hub 绿（写"未列 N 条不判"）',
      any('probe-hub' in t and '都存在' in t and '不判' in t for t in ts), True)
check('space-hub 绿（写"一致"）',
      any('space-hub' in t and '一致' in t for t in ts), True)

DOC = os.path.join(REPO, '通用层', 'skills', 'space-hub', 'SKILL.md')
bak = open(DOC, encoding='utf-8').read()

print('【反例①】文档写了个不存在的命令 → 红（吹牛）')
try:
    open(DOC, 'w', encoding='utf-8').write(
        bak.replace('python3 space_hub.py inbox',
                    'python3 space_hub.py inbox\npython3 space_hub.py fakecmd', 1))
    st, ts = run()
    check('判红', st, 'red')
    check('点名写的是 fakecmd', any('fakecmd' in t for t in ts), True)
finally:
    open(DOC, 'w', encoding='utf-8').write(bak)

print('【反例②】代码加了子命令但文档不写 → 黄（check_missing=true 时）')
PY = os.path.join(REPO, '通用层', 'skills', 'space-hub', 'scripts', 'space_hub.py')
pbak = open(PY, encoding='utf-8').read()
try:
    open(PY, 'w', encoding='utf-8').write(
        pbak.replace("    sub.add_parser('inbox')", "    sub.add_parser('inbox')\n    sub.add_parser('shadowcmd')", 1))
    st, ts = run()
    check('判黄', st, 'yellow')
    check('点名写的是 shadowcmd', any('shadowcmd' in t for t in ts), True)
finally:
    open(PY, 'w', encoding='utf-8').write(pbak)

print('【反例③】抽样为空 → 无法判定（不许说"一致"）')
tmp = tempfile.mkdtemp()
try:
    for d in ('通用层/skills/space-hub', '通用层/skills/space-hub/scripts'):
        os.makedirs(os.path.join(tmp, d))
    open(os.path.join(tmp, '通用层/skills/space-hub/SKILL.md'), 'w', encoding='utf-8').write('# 空文档，无命令\n')
    open(os.path.join(tmp, '通用层/skills/space-hub/scripts/space_hub.py'), 'w', encoding='utf-8').write('x = 1\n')
    c = {'declarations': [x for x in cfg()['declarations'] if x['skill'] == 'space-hub']}
    r = H.chk_docsync(tmp, c, {})
    check('判 unknown', r['status'], 'unknown')
finally:
    shutil.rmtree(tmp)

print('【恢复】真仓库回到 green')
check('恢复后 green', run()[0], 'green')

print()
if fails:
    print(f'✗ {len(fails)} 项失败：' + '、'.join(fails))
    sys.exit(2)
print('✓ 景门回归全过')
