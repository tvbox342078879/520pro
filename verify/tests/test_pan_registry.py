#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_pan_registry.py — pan-registry 单一真源判据（云取借鉴第 10 条：adapter 统一底座）。

病15 防御核心：判据识别范围 = 对象范围。第 10 条的验收标准是"新增网盘只改一处、
两技能主流程零改"，所以判据必须喂真注册表 + 真两技能，证明三件事：
  A 结构层：注册表 lib 三件齐 + 四类投影函数可调用。
  B 单一真源层：两技能模块级表 == 注册表投影（不是各自写死的表）。
  C 有牙层（元变异）：
    ① 改注册表 PLATFORMS 加一条 → share-parser 认得新平台、transfer-poll 认得新间隔；
    ② 删注册表一条 → 两技能同步失去该平台（删一处即全局生效，反证非硬编码）；
    ③ 两技能源码里不再含写死的平台表字面量（识别范围=对象范围）。
  全部用临时副本改注册表、不污染真源，改完还原。
"""
import importlib.util
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
REG_DIR = os.path.join(REPO, '通用层', 'skills', 'pan-registry', 'scripts')
REG = os.path.join(REG_DIR, 'registry.py')
SP = os.path.join(REPO, '通用层', 'skills', 'share-parser', 'scripts', 'share_parser.py')
TP = os.path.join(REPO, '通用层', 'skills', 'transfer-poll', 'scripts', 'transfer_poll.py')

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── A 结构层 ──
for f in ('registry.py',):
    check('A 注册表正门存在 %s' % f, os.path.isfile(os.path.join(REG_DIR, f)))
reg = load(REG, 'reg_mod')
for fn in ('platform_names', 'share_rules', 'expire_codes', 'poll_intervals',
           'progress_texts', 'default_poll_ms', 'default_progress_text'):
    check('A 投影函数可调用 %s' % fn, callable(getattr(reg, fn, None)))
check('A 在册 8 家平台', len(reg.platform_names()) == 8, reg.platform_names())

# ── B 单一真源层：两技能模块表 == 注册表投影 ──
sp = load(SP, 'sp_mod')
tp = load(TP, 'tp_mod')
check('B share-parser 规则表 == 注册表投影',
      [r[0] for r in sp.PLATFORM_RULES] == [r[0] for r in reg.share_rules()])
check('B share-parser 有效期表 == 注册表投影', sp.EXPIRE_CODES == reg.expire_codes())
check('B transfer-poll 间隔表 == 注册表投影', tp.POLL_INTERVAL_MS == reg.poll_intervals())
check('B transfer-poll 文案表 == 注册表投影', tp.TEXT_IN_PROGRESS == reg.progress_texts())
check('B transfer-poll 默认文案 == 注册表默认', tp.DEFAULT_PROGRESS_TEXT == reg.default_progress_text())

# ── C① 元变异：加一条 → 两技能同步认得 ──
with tempfile.TemporaryDirectory() as td:
    # 复制整个 pan-registry 到临时目录，改它的注册表，让两技能从临时副本 import。
    fake_dir = os.path.join(td, 'pan-registry', 'scripts')
    os.makedirs(fake_dir)
    shutil.copy(os.path.join(REG_DIR, 'registry.py'), os.path.join(fake_dir, 'registry.py'))
    fake_reg = os.path.join(fake_dir, 'registry.py')
    src = open(fake_reg, encoding='utf-8').read()
    # 在 PLATFORMS 列表开头插一条假平台 pitest。
    inject = ("    {'name': 'pitest',\n"
              "     'share_pattern': r'pitest\\.example\\.com/s/([A-Za-z0-9]+)', 'share_group': 1,\n"
              "     'poll_ms': 321, 'progress_text': 'pitest 处理中'},\n")
    src2 = src.replace('PLATFORMS = [\n', 'PLATFORMS = [\n' + inject, 1)
    open(fake_reg, 'w', encoding='utf-8').write(src2)
    # 在临时 skills 根下建两技能 scripts，复制脚本，使 parents[2] 指向临时 skills 根 → 读假注册表。
    fake_skills = os.path.dirname(os.path.dirname(fake_dir))  # td
    for name, real in (('share-parser', SP), ('transfer-poll', TP)):
        d = os.path.join(fake_skills, name, 'scripts')
        os.makedirs(d, exist_ok=True)
        shutil.copy(real, os.path.join(d, os.path.basename(real)))
    # 关键：清 sys.modules 缓存，否则假技能 import registry 拿到首次缓存的真模块（病15 判据对象没对准）。
    sys.modules.pop('registry', None)
    sp2 = load(os.path.join(fake_skills, 'share-parser', 'scripts', 'share_parser.py'), 'sp_fake')
    sys.modules.pop('registry', None)
    tp2 = load(os.path.join(fake_skills, 'transfer-poll', 'scripts', 'transfer_poll.py'), 'tp_fake')
    parsed = sp2.parse_share('https://pitest.example.com/s/a1b2 提取码：z9y8')
    check('C① 加一条 → share-parser 认得新平台', parsed.get('platform') == 'pitest', parsed)
    check('C① 加一条 → share-parser 认得新 share_id', parsed.get('share_id') == 'a1b2', parsed)
    check('C① 加一条 → transfer-poll 认得新间隔', tp2.poll_interval('pitest') == 321,
          tp2.POLL_INTERVAL_MS)
    pend = tp2.classify_task('running', platform='pitest')
    check('C① 加一条 → transfer-poll 认得新文案', pend.get('text') == 'pitest 处理中', pend)

# ── C② 元变异：删一条 → 两技能同步失去 ──
with tempfile.TemporaryDirectory() as td:
    fake_dir = os.path.join(td, 'pan-registry', 'scripts')
    os.makedirs(fake_dir)
    shutil.copy(REG, os.path.join(fake_dir, 'registry.py'))
    fake_reg = os.path.join(fake_dir, 'registry.py')
    src = open(fake_reg, encoding='utf-8').read()
    # 删掉 quark 整条：从 "{'name': 'quark'" 那行起，到下一个 "{'name':" 行或 "]" 行止。
    lines = src.splitlines(keepends=True)
    out, skipping = [], False
    for ln in lines:
        if "'name': 'quark'" in ln:
            skipping = True
            continue
        if skipping and ("'name':" in ln or ln.lstrip().startswith(']')):
            skipping = False
        if not skipping:
            out.append(ln)
    src2 = ''.join(out)
    open(fake_reg, 'w', encoding='utf-8').write(src2)
    fake_skills = td
    for name, real in (('share-parser', SP), ('transfer-poll', TP)):
        d = os.path.join(fake_skills, name, 'scripts')
        os.makedirs(d, exist_ok=True)
        shutil.copy(real, os.path.join(d, os.path.basename(real)))
    sys.modules.pop('registry', None)
    sp3 = load(os.path.join(fake_skills, 'share-parser', 'scripts', 'share_parser.py'), 'sp_del')
    sys.modules.pop('registry', None)
    tp3 = load(os.path.join(fake_skills, 'transfer-poll', 'scripts', 'transfer_poll.py'), 'tp_del')
    gone = sp3.parse_share('https://pan.quark.cn/s/abc123')
    check('C② 删一条 → share-parser 失去该平台', gone.get('status') == 'no_match', gone)
    check('C② 删一条 → transfer-poll 失去该间隔', tp3.poll_interval('quark') == tp3.DEFAULT_INTERVAL_MS,
          tp3.POLL_INTERVAL_MS)

# ── C③ 识别范围=对象范围：两技能源码无写死平台表 ──
sp_src = open(SP, encoding='utf-8').read()
tp_src = open(TP, encoding='utf-8').read()
check('C③ share-parser 无写死 PLATFORM_RULES 字面量', 'PLATFORM_RULES = [' not in sp_src)
check('C③ transfer-poll 无写死间隔表字面量', "POLL_INTERVAL_MS = {'" not in tp_src)
check('C③ transfer-poll 无写死文案表字面量', "TEXT_IN_PROGRESS = {" not in tp_src)

print('\n=== test_pan_registry: %d✓ / %d✗ ===' % (len(PASS), len(FAIL)))
if FAIL:
    for f in FAIL:
        print('  FAILED:', f)
    raise SystemExit(1)
print('ALL PASS')
