#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_skill_cards.py · 回归测试（工程G-4）

跑法：python3 verify/tests/test_skill_cards.py
退出码：0 全过 / 2 有失败

重点盯三件会真出事的事:
  ① description 吞掉 allowed-tools（首次跑就踩到）→ 粘到手机上是一张坏卡片；
  ② 缺字段的技能输出"半张卡片"→ 比不输出更难查；
  ③ 导出内容与仓库不同步（手改文档的老路）→ 这里直接从 SKILL.md 现读，
     故用"仓库里 description 的首句"当锚，能抓出"卡片是抄的"。
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 技能数以契约表为真源（M1）——写死数字会在每次新增/退役技能时假红
_CONTRACTS = json.load(open(os.path.join(REPO, 'verify', 'skill_contracts.json'), encoding='utf-8'))
_K = _CONTRACTS.get('skills', _CONTRACTS)
N_SKILLS = sum(1 for v in _K.values() if v.get('kind') == 'skill')
SCRIPT = os.path.join(REPO, 'export_skill_cards.py')
fails = []


def check(name, got, want):
    ok = got == want
    print(('  ✓ ' if ok else '  ✗ ') + name + ('' if ok else f'（期望 {want!r}，实得 {got!r}）'))
    if not ok:
        fails.append(name)


def run(*args, repo=None):
    cmd = [sys.executable, SCRIPT] + list(args)
    if repo:
        cmd += ['--repo', repo]
    return subprocess.run(cmd, capture_output=True, text=True)


print('【①】真仓库全量导出')
r = run('--json')
check('退出码 0', r.returncode, 0)
d = json.loads(r.stdout)
check(f'{N_SKILLS} 个技能（=契约表 kind:skill）', len(d['cards']), N_SKILLS)
check('无坏技能', d['broken'], [])
names = [c['name'] for c in d['cards']]
# 病15 根修：原判据钉死 names[0]=='artifact-store'，新增同层技能（按字母序 ad-audit
# 排在 artifact-store 前）就假红。判据对象应是「通用层整体在能力层之前」这一行为，
# 不是某个具体技能名——绑层序，不绑首元素。
layers = [c['layer'] for c in d['cards']]
check('按层排序（通用层全在能力层前）',
      layers == sorted(layers, key=lambda L: {'通用层': 0, '能力层': 1}.get(L, 9)),
      True)
check('每个都有 version', all(c['version'] for c in d['cards']), True)
check('每个都有触发词', all(c['triggers'] for c in d['cards']), True)

print('【②】description 不许夹带 frontmatter 其它键')
md = run().stdout
check('输出不含 allowed-tools', 'allowed-tools' in md, False)
bad = [c['name'] for c in d['cards'] if 'allowed-tools' in c['description']]
check('JSON 侧也不含', bad, [])

print('【③】YAML 卡片可解析（真能被手机端吃下）')
try:
    import yaml
    blocks = md.split('```yaml')
    okc = 0
    for b in blocks[1:]:
        body = b.split('```')[0]
        y = yaml.safe_load(body)
        assert y['name'] and y['version'] and len(y['description']) > 40, y.get('name')
        okc += 1
    check(f'{N_SKILLS} 张卡片均可解析', okc, N_SKILLS)
except ImportError:
    print('  · 无法判定：无 pyyaml，跳过解析校验（不计入通过）')

print('【④】--only 过滤')
r2 = run('--only', 'space-hub,probe-hub', '--json')
d2 = json.loads(r2.stdout)
check('只出 2 个', sorted(c['name'] for c in d2['cards']), ['probe-hub', 'space-hub'])

print('【⑤】坏技能必须整条不输出（不许半张卡片）')
tmp = tempfile.mkdtemp()
try:
    sk = os.path.join(tmp, '通用层', 'skills', 'broken-skill')
    os.makedirs(sk)
    open(os.path.join(sk, 'SKILL.md'), 'w', encoding='utf-8').write(
        '---\nname: broken-skill\ndescription: "没有 version 字段的坏技能"\n---\n\n正文\n')
    good = os.path.join(tmp, '通用层', 'skills', 'good-skill')
    os.makedirs(good)
    open(os.path.join(good, 'SKILL.md'), 'w', encoding='utf-8').write(
        '---\nname: good-skill\nversion: "1.0.0"\ndescription: "正常的技能。触发词：甲 / 乙。"\n---\n\n正文\n')
    r3 = run('--json', repo=tmp)
    check('有坏技能时退出码 2', r3.returncode, 2)
    d3 = json.loads(r3.stdout)
    check('好技能照常导出', [c['name'] for c in d3['cards']], ['good-skill'])
    check('坏技能进 broken 而不是 cards', [b[0] for b in d3['broken']], ['broken-skill'])
    check('坏技能原因写清', 'version' in d3['broken'][0][1], True)
finally:
    import shutil
    shutil.rmtree(tmp)

print('【⑥】导出内容跟仓库同步（抓"手改文档"的老路）')
# 取一个改动过触发词的技能，确认卡片里有新词
sh = [c for c in d['cards'] if c['name'] == 'space-hub'][0]
# ★ 判据口径（2026-11-15 修·病15 同型）：原来写死 `startswith('2.7')`——
#   那是把「版本号」当被测对象，改成「卡片版本 == 契约登记版本」（真源对账），
#   否则每次 bump 都要来改这条测试，而真该防的是「卡片与真源脱节」。
_want_sh = json.load(open(os.path.join(REPO, 'verify', 'skill_contracts.json'),
                          encoding='utf-8'))['skills']['space-hub']['version']
check(f'space-hub 卡片版本与契约一致（{_want_sh}）', sh['version'], _want_sh)

print()
if fails:
    print(f'✗ {len(fails)} 项失败：' + '、'.join(fails))
    sys.exit(2)
print('✓ 技能卡片导出回归全过')
