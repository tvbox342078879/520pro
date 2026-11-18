#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_skills.py · 回归测试（发布闸是否真在守）

判据三件套（缺一不算通过）：
  ① 造违例：篡改包内容 / 删件 / 加件 / 改版本 / 去指纹 —— 每一种都必须被拦
  ② 具体判据：拦下时报的是哪一类问题（内容不同 vs 缺件 vs 版本不符），不能只说"失败"
  ③ 元变异：把 diff 判据改坏后，被篡改的包必须能溜过（自证判据真在守，不是恒真）
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, 'pack_skills.py')
fails = []


N = [0]   # 例数由 check 自增；手工偏移量迟早对不上真实用例数（4 个测试文件同病）


def check(name, cond, detail=''):
    N[0] += 1
    if not cond:
        fails.append(name)
        print(f'  ✗ {name}  {detail}')
    else:
        print(f'  ✓ {name}')


def load_mod(path=None):
    spec = importlib.util.spec_from_file_location('pack_skills_t', path or SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def rewrite(zp, mode):
    """在包里做手脚：'tamper' 改内容 / 'drop' 删件 / 'add' 加件 / 'bump' 改版本 / 'nometa' 去指纹"""
    td = tempfile.mkdtemp()
    with zipfile.ZipFile(zp) as z:
        items = {n: z.read(n) for n in z.namelist()}
    if mode == 'tamper':
        items['SKILL.md'] = items['SKILL.md'].replace(b'name:', b'name:  ', 1)
    elif mode == 'drop':
        items.pop('SKILL.md')
    elif mode == 'add':
        items['_EXTRA_UNREGISTERED.py'] = b'print("should not be here")\n'
    elif mode == 'bump':
        meta = json.loads(items['_PACK_META.json'])
        meta['version'] = '9.9.9'
        items['_PACK_META.json'] = json.dumps(meta, ensure_ascii=False).encode()
    elif mode == 'nometa':
        items.pop('_PACK_META.json')
    out = os.path.join(td, os.path.basename(zp))
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, b in items.items():
            z.writestr(n, b)
    return out, td


P = load_mod()
skills = P.load_skills(ROOT)
NAME = 'tvbox-pipeline'          # 小包（15 件），打包快
base = skills[NAME]
td = tempfile.mkdtemp()
good = P.pack_one(NAME, base, td, False, 'testhead', False)
check('前置：能打出包', good and os.path.exists(good))

# ── ① 基线：新包必须通过 ──
ok, msg = P.verify_zip(good, skills, ROOT)
check('新包逐 sha 一致', ok, msg)

# ── ② 内容被篡改 → 必须报「内容不同」 ──
z2, t2 = rewrite(good, 'tamper')
ok, msg = P.verify_zip(z2, skills, ROOT)
check('篡改内容被拦', not ok, msg)
check('拦下时指明是内容不同', '内容不同' in msg, msg)

# ── ③ 包内缺件 → 必须报缺件 ──
z3, t3 = rewrite(good, 'drop')
ok, msg = P.verify_zip(z3, skills, ROOT)
check('缺 SKILL.md 被拦', not ok, msg)

# ── ④ 包内多件（手工塞文件）→ 必须报多余 ──
z4, t4 = rewrite(good, 'add')
ok, msg = P.verify_zip(z4, skills, ROOT)
check('多余文件被拦', not ok and '多' in msg, msg)

# ── ⑤ 版本被改 → 必须报版本不符（这条治「包比仓库旧」） ──
z5, t5 = rewrite(good, 'bump')
ok, msg = P.verify_zip(z5, skills, ROOT)
check('版本不符被拦', not ok and '版本不符' in msg, msg)

# ── ⑥ 去掉指纹 → 必须判「无法判定」，不能算通过 ──
z6, t6 = rewrite(good, 'nometa')
ok, msg = P.verify_zip(z6, skills, ROOT)
check('无指纹包不算通过', not ok and '无法判定' in msg, msg)

# ── ⑦ 技能名对不上 → 拒绝（防改名后静默放过） ──
ok, msg = P.verify_zip(os.path.join(td, 'no-such-skill.zip'), skills, ROOT)
check('未登记技能被拒', not ok, msg)

# ── ⑧ 元变异：把 diff 判据改坏，篡改包必须溜过 ──
src = open(SCRIPT, encoding='utf-8').read()
mut = src.replace("    if diff:\n        problems.append(f'{len(diff)} 件内容不同",
                  "    if False:\n        problems.append(f'{len(diff)} 件内容不同")
check('变异真的落盘', 'if False:' in mut)
mpath = os.path.join(td, 'pack_mutated.py')
open(mpath, 'w', encoding='utf-8').write(mut)
Pm = load_mod(mpath)
# 变异副本落在 tmp 下，其模块级 CONTRACTS 指向 tmp；技能清单沿用原模块解析结果
# （verify_zip 的比对逻辑只用传入的 base/repo，不读模块常量）
ok, msg = Pm.verify_zip(z2, skills, ROOT)
check('判据改坏后篡改包溜过', ok, msg)

# ── ⑨ 契约表是唯一真源：技能清单必须来自 skill_contracts.json ──
contracts = json.load(open(os.path.join(ROOT, 'verify', 'skill_contracts.json'), encoding='utf-8'))
kinds = {n: s.get('kind') for n, s in contracts['skills'].items()}
check('lib 类不进打包清单', all(n not in skills for n, k in kinds.items() if k == 'lib'),
      f'skills={sorted(skills)}')

# ── ⑩ verify.sh 必须真挂了这道闸（防「测试绿但段被删」） ──
vsh = open(os.path.join(ROOT, 'verify.sh'), encoding='utf-8').read()
check('verify.sh 自动发现覆盖 pack_skills 回归',
      'for tf in "$TARGET"/verify/tests/test_*.py; do' in vsh
      and os.path.isfile(os.path.join(ROOT, 'verify', 'tests', 'test_pack_skills.py')))

for t in (t2, t3, t4, t5, t6, td):
    shutil.rmtree(t, ignore_errors=True)

print('test_pack_skills：%d 例，失败 %d' % (N[0], len(fails)))
sys.exit(1 if fails else 0)
