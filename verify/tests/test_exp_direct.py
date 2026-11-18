#!/usr/bin/env python3
"""机制判据：踩坑→能力→直达（exp_direct）闭环。

验证三件事（真阳性/真阴性/无法判定，B-02）：
  ① 数据：exp_entries 带 fixed_path + symptom 字段（命中才有解法可直达）
  ② 查询：exp_probe.match(symptom) 命中返回 fixed_path，不命中返回 None
  ③ 呈现：注入含「💡经验命中」但不报脏落点、注入≠复用（假账已除）
  ④ 闸口：exp_probe.gate() 真调用才记账，命中返 B-10 三字段（reason/target/method）

先红后绿：改动前本文件应 FAIL。
"""
import os
import sys
import json
import inspect
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
    # 从根修后：非空 fixed_path 必须均指可执行(.py/.sh)真实文件——放行 .md/.json 是旧漏洞
    check('非空 fixed_path 均为可信可执行(.py/.sh)真实文件',
          all(e['fixed_path'].endswith(('.py', '.sh')) and
              os.path.isfile(os.path.join(ROOT, e['fixed_path']))
              for e in with_fp))
except Exception as ex:
    check('exp_entries 有 fixed_path 字段（命中可直达）', False)
    print('    err=%r' % ex)

# ② 查询层：match(symptom) 命中/不命中
try:
    import exp_probe
    check('exp_probe 有 match(symptom) 直达查询接口', hasattr(exp_probe, 'match'))
    if hasattr(exp_probe, 'match'):
        # 从根修后落点可刻意缺省：命中必返经验，fixed_path 要么可执行(.py/.sh)要么空
        hit = exp_probe.match('白名单判据用子串匹配 FIELDS 坏实现假绿', rec=rec)
        _fp_ok = bool(hit) and (not hit.get('fixed_path') or
                                hit['fixed_path'].endswith(('.py', '.sh')))
        check('命中症状返回经验（落点可执行或缺省）', bool(hit) and _fp_ok)
        miss = exp_probe.match('完全无关的量子 berry 相位', rec=rec)
        check('不相关症状不误命中（真阴性）', not miss)
except Exception as ex:
    check('exp_probe 有 match(symptom) 直达查询接口', False)
    print('    err=%r' % ex)

# ③ 呈现层：注入段含「💡经验命中」（不再报脏落点），且注入≠复用——注入瞬间不得记账
try:
    anchor = open(os.path.join(ROOT, 'hooks', 'next_anchor.py'), encoding='utf-8').read()
    check('next_anchor 注入段含「💡经验命中」', '💡经验命中' in anchor)
    # 假账判据：注入段不得在注入瞬间调 hit()（把"看到"当"用了"）
    # 病15 防护：切片必须用注释锚点的完整区段，不能用变量名 split（会切到定义与循环之间，假绿）
    _seg = anchor.split('经验闭环 v3')[1].split('经验注入失败')[0] if '经验闭环 v3' in anchor else ''
    check('注入瞬间不记账（假账已除，注入≠复用）',
          '_ep.match' in _seg and 'hit(' not in _seg)
except Exception as ex:
    check('next_anchor 注入段含「💡经验命中」', False)
    print('    err=%r' % ex)

# ④ 闸口层：exp_probe.gate() 显式硬闸接口——真调用才记账 + B-10 三字段
try:
    import exp_probe as _ep
    check('exp_probe 有 gate() 显式闸口接口', hasattr(_ep, 'gate'))
    if hasattr(_ep, 'gate'):
        # 真阳性：命中症状应返回正门三字段（reason/target/method）
        g = _ep.gate('白名单判据用子串匹配 FIELDS 坏实现假绿', rec=rec, commit=False)
        check('gate 命中返 B-10 三字段 reason/target/method',
              bool(g) and all(k in g for k in ('reason', 'target', 'method')))
        check('gate.target 指回真落点（可执行或 evidence 锚点）',
              bool(g) and (g.get('fixed_path') or
                           str(g.get('target', '')).startswith('evidence:')))
        # 真阴性：无关症状不误命中
        gm = _ep.gate('完全无关的量子 berry 相位', rec=rec, commit=False)
        check('gate 不相关症状不误命中（真阴性）', not gm)
        # 假账分离：gate(commit=False) 不写账，match 是只读查询
        check('gate 只读模式不改 reuse_count（commit=False）',
              hasattr(_ep, 'gate') and 'commit' in str(inspect.signature(_ep.gate)))
except Exception as ex:
    check('exp_probe 有 gate() 显式闸口接口', False)
    print('    err=%r' % ex)

# ⑤ 硬闸层：PreToolUse 拦截 reason 自动带出固化经验的 target 落点（机器喂正门，不靠翻台账）
try:
    sys.path.insert(0, os.path.join(ROOT, 'hooks'))
    import guard_cmd as _gc
    check('guard_cmd 有 gate_target() 落点解析接口', hasattr(_gc, 'gate_target'))
    if hasattr(_gc, 'gate_target'):
        # 真阳性：G5（有 guard_rules 映射→病15→固化经验）应带出判据文件落点
        # 落点格式 "文件#规则id"，取 # 前的文件部分做存在性校验
        _t = _gc.gate_target('G5')
        check('gate_target(G5) 带出真实存在的判据文件',
              bool(_t) and os.path.isfile(os.path.join(ROOT, _t.split('#')[0])))
        # 精确性（本阶段升级）：落点须带该规则专属锚点，不是所有规则同一个裸文件名
        _t2 = _gc.gate_target('G1')
        check('gate_target 按规则带出专属锚点（非全规则同一裸名）',
              bool(_t2) and _t2 != _t and 'G1' in _t2)
        # 拦截 reason 里确实含这个落点（不是只在独立函数里算出来却没接进 reason）
        _payload = _gc.deny_payload({'id': 'G5', 'why': 'test', 'fix': 'testfix'})
        _reason = _payload['hookSpecificOutput']['permissionDecisionReason']
        check('deny_payload.reason 自动含 target 落点（机器喂正门）',
              bool(_t) and os.path.isfile(os.path.join(ROOT, _t.split('#')[0])) and _t in _reason)
        # 真阴性：无 guard_rules 映射的规则不硬塞落点（避免病15 式误带）
        _tn = _gc.gate_target('G-NOMAP-TEST')
        check('无映射规则不误带落点（真阴性）', not _tn)
except Exception as ex:
    check('guard_cmd 有 gate_target() 落点解析接口', False)
    print('    err=%r' % ex)

# ⑥ 落点源统一：注入层不报脏 fixed_path，唯一落点真源是 gate_target(规则id)
try:
    import exp_probe as _ep6
    anchor = open(os.path.join(ROOT, 'hooks', 'next_anchor.py'), encoding='utf-8').read()
    _seg = anchor.split('经验闭环 v3')[1].split('经验注入失败')[0] if '经验闭环 v3' in anchor else ''
    # 注入段不得把 match 的 fixed_path 当落点拼进消息（实测 48/49 是账本/文档脏落点）
    check('💡注入段不拼脏 fixed_path 落点',
          "_hit['fixed_path']" not in _seg and '证据' in _seg)
    # landing() 只接 rule_id，不接 evidence（证据路已实证不可信，废除）
    check('landing 落点真源只接 rule_id（evidence 路已废）',
          'evidence' not in str(inspect.signature(_ep6.landing)))
except Exception as ex:
    check('💡注入段不拼脏 fixed_path 落点', False)
    print('    err=%r' % ex)

# ⑦ 派生层：fixed_path 从根修——只认「commit 改动 ∩ 可执行(.py/.sh) ∩ 与症状词块重合」，无合格则不写
try:
    import exp_distill as _ed7
    _src7 = inspect.getsource(_ed7)
    check('_FP_EXT 仅含可执行(.py/.sh)，无账本/文档(.json/.md)',
          "_FP_EXT = ('.py', '.sh')" in _src7 or
          ("_FP_EXT" in _src7 and "'.json'" not in _src7.split('_FP_EXT')[1].split('\n')[0]))
    check('_fixed_path 无「退化取文本路径」脏落点分支',
          're.search' not in inspect.getsource(_ed7._fixed_path))
    # 真阳性：d86604d 症状含 pan/parse，其 commit 改动含可执行且与症状重合的文件
    _fp7 = _ed7._fixed_path('d86604d', 'pan.py 的 pan_parse_share_ex 白名单子串假绿')
    check('_fixed_path 返回可执行(.py/.sh)真实文件',
          bool(_fp7) and _fp7.endswith(('.py', '.sh')) and
          os.path.isfile(os.path.join(ROOT, _fp7)))
    # 真阴性：症状词块与改动文件全不重合 → 不写落点（缺省），杜绝脏落点
    _fp7n = _ed7._fixed_path('d86604d', '量子 Berry 相位 完全无关')
    check('_fixed_path 无重合不写落点（真阴性/缺省）', not _fp7n)
    # derive 不再用旧的脏 fixed_path 兜底（old.get('fixed_path') or ...）
    # 剥注释后检查（病15 防护：裸字符串会把注释字面量当代码，假红/假绿）
    _derive_code = '\n'.join(l for l in inspect.getsource(_ed7.derive).splitlines()
                             if not l.strip().startswith('#'))
    check('derive 不保留旧脏 fixed_path（old 兜底已除）',
          "old.get('fixed_path')" not in _derive_code)
except Exception as ex:
    check('_fixed_path 从根修（可执行+词块重合+缺省）', False)
    print('    err=%r' % ex)

# ⑧ 完成判据：真实经验库里 fixed_path 为空或均指 .py/.sh 真实文件
try:
    es8 = json.load(open(os.path.join(ROOT, 'experience_recurrence.json'), encoding='utf-8')).get('exp_entries') or []
    _bad8 = [e for e in es8 if e.get('fixed_path') and
             not (e['fixed_path'].endswith(('.py', '.sh')) and
                  os.path.isfile(os.path.join(ROOT, e['fixed_path'])))]
    check('exp_entries 里 fixed_path 为空或均指 .py/.sh 真实文件（无脏落点）', not _bad8)
except Exception as ex:
    check('exp_entries 无脏落点（完成判据）', False)
    print('    err=%r' % ex)

# ⑨ 窗口滚动保护：重派生不得丢窗口外"已真复用"的经验（否则洗掉实战命中）
try:
    import exp_distill as _ed9
    _asrc = inspect.getsource(_ed9.apply)
    check('apply 含窗口外复用条目回收逻辑',
          'recycled' in _asrc and 'reuse_count' in _asrc and 'last_hit' in _asrc)
    es9 = json.load(open(os.path.join(ROOT, 'experience_recurrence.json'), encoding='utf-8')).get('exp_entries') or []
    ev9 = {e.get('evidence') for e in es9}
    # 46fc914:lesson 是已被 git log -60 挤出、但 reuse_count=1 的真实复用条目
    check('窗口外已复用条目未被重派生洗掉（46fc914 回收）',
          '46fc914:lesson' in ev9 and
          any(e.get('evidence') == '46fc914:lesson' and (e.get('reuse_count') or 0) > 0 for e in es9))
except Exception as ex:
    check('apply 含窗口外复用条目回收逻辑', False)
    print('    err=%r' % ex)

# ⑩ 误报治理（步骤1）：通用短词不给包含式满分（原"推送"0.9→现不误报）
try:
    import exp_probe as _ep10
    check('通用短词误报治理：_similar("推送",长文本) < 0.34',
          _ep10._similar('推送', '推送到远端 main 的钩子脚本') < 0.34)
    check('通用词整串命中黑名单：_is_generic("推送")=True', _ep10._is_generic('推送'))
    check('有区分度长查询仍可包含式命中：_similar("支付回调验签","支付回调验签失败") >= 0.9',
          _ep10._similar('支付回调验签', '支付回调验签失败') >= 0.9)
except Exception as ex:
    check('通用短词误报治理', False)
    print('    err=%r' % ex)

# ⑪ 白名单：gate 只拦已验证经验，死库存不进拦截池（match 仍全池提示）
try:
    import exp_probe as _ep11
    _r11 = {'exp_entries': [
        {'id': 'E-dead', 'evidence': 'aaa:lesson', 'symptom': '记忆库断链', 'text': '记忆库断链',
         'reuse_count': 0, 'solidified': False},
        {'id': 'E-good', 'evidence': 'bbb:lesson', 'symptom': '支付回调验签', 'text': '支付回调验签',
         'reuse_count': 2, 'solidified': True}]}
    check('gate 死库存不拦（verified_only）',
          _ep11.gate('记忆库断链', rec=_r11, commit=False) is None)
    check('gate 已验证经验命中', _ep11.gate('支付回调验签', rec=_r11, commit=False) is not None)
    check('match 全池仍提示死库存（提示≠拦截）',
          _ep11.match('记忆库断链', rec=_r11) is not None)
except Exception as ex:
    check('gate 白名单', False)
    print('    err=%r' % ex)

# ⑫ force 绕行留痕：force=True 可命中死库存/退役，但记 force_hit
try:
    import exp_probe as _ep12, inspect as _ins12
    _r12 = {'exp_entries': [
        {'id': 'E-dead', 'evidence': 'aaa:lesson', 'symptom': '记忆库断链', 'text': '记忆库断链',
         'reuse_count': 0, 'solidified': False}]}
    check('gate(force=True) 可命中死库存',
          _ep12.gate('记忆库断链', rec=_r12, commit=False, force=True) is not None)
    check('exp_distill 有 force_hit 留痕函数', hasattr(__import__('exp_distill'), 'force_hit'))
    _fsrc = _ins12.getsource(__import__('exp_distill').force_hit)
    check('force_hit 记 force_count + force_last（显式绕行留审计）',
          'force_count' in _fsrc and 'force_last' in _fsrc)
except Exception as ex:
    check('force 绕行留痕', False)
    print('    err=%r' % ex)

# ⑬ 经验退役：retired 不进 gate，force 仍可取；重派生不洗掉退役态
try:
    import exp_probe as _ep13, exp_distill as _ed13, inspect as _ins13
    _r13 = {'exp_entries': [
        {'id': 'E-ret', 'evidence': 'ccc:lesson', 'symptom': '支付回调验签', 'text': '支付回调验签',
         'reuse_count': 2, 'solidified': True, 'retired': True}]}
    check('retired 经验不进 gate 拦截池',
          _ep13.gate('支付回调验签', rec=_r13, commit=False) is None)
    check('retired 经验 force 仍可取（留痕后可用）',
          _ep13.gate('支付回调验签', rec=_r13, commit=False, force=True) is not None)
    check('exp_distill 有 retire 退役正门', hasattr(_ed13, 'retire'))
    _dsrc = _ins13.getsource(_ed13.derive)
    check('derive 重派生保留 retired/force_count（不洗绿）',
          'retired' in _dsrc and 'force_count' in _dsrc)
except Exception as ex:
    check('经验退役', False)
    print('    err=%r' % ex)

print('\n%d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
