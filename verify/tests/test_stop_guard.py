#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stop_guard.py · 回归测试（B-13 完成态凭落点，Stop 拽回）

判据三件套：
  ① 造违例：宣称完成且零落点证据 → 必须拽回（stdout 出 JSON decision:block）
  ② 具体判据：判定理由要写清是「无证据」还是「否定语境豁免」
  ③ 元变异：清空断言词表后，同样的违例必须溜过（自证判据真在守）

另加三条"接得上"的检查：
  ④ stop_hook_active 为真必须放行（平台重入，防死循环）
  ⑤ 同 session 连续拽回达上限后放行并留痕（判据写坏也不能卡死会话）
  ⑥ settings.json 真的注册了 stop_guard.py（写了没挂 = 等于没写）
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(ROOT, 'hooks')
GUARD = os.path.join(HOOKS, 'stop_guard.py')
fails = []


N = [0]   # 例数由 check 自增；手工偏移量迟早对不上真实用例数（4 个测试文件同病）


def check(name, cond, detail=''):
    N[0] += 1
    if not cond:
        fails.append(name)
        print(f'  ✗ {name}  {detail}')
    else:
        print(f'  ✓ {name}')


def load(path, modname='sg'):
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = load(GUARD)

# 违例样例在运行时拼接，避免本文件被其它闸静态扫成违例样本
DONE = '已' + '完成'
ALLPASS = '全部' + '通过'

# ── ① 造违例：断言 + 零证据 → 必须拽回 ──
bad = [
    (f'{DONE}修复。', '最短断言'),
    (f'{ALLPASS}，可以收工了。', '全部通过'),
    ('搞定了，你看下。', '口语断言'),
    (f'{DONE}，三处都改好了，放心。', '断言 + 空口保证'),
]
for text, why in bad:
    d, reason = S.judge(text)
    check(f'拽回：{why}', d is True, f'实际={d}（{reason}）')

# ── ② 放行：有落点证据 / 否定语境 / 过程描述 ──
good = [
    (f'{DONE}，提交 6ed5df1', '有 sha'),
    (f'{DONE}，bash verify.sh → 0 ✗ / 2 ·（rc=0）', '有判据输出'),
    (f'已修复，改的是 hooks/stop_guard.py:118', '有文件:行号'),
    ('未完成，因为没有权限。', '否定语境'),
    ('无法验证，环境不可达。', '否定词开场'),
    ('这个函数完成了数据加载功能。', '过程描述不是任务断言'),
    ('39 例 0 失败', '只有判据无断言'),
    ('', '空消息'),
]
for text, why in good:
    d, reason = S.judge(text)
    check(f'放行：{why}', d is False, f'实际拽回（{reason}）')

# ── ③ 元变异：清空断言词表后，违例必须溜过 ──
src = open(GUARD, encoding='utf-8').read()
mut = re.sub(r'^ASSERT_PATS = \[.*?^\]', 'ASSERT_PATS = []', src, flags=re.S | re.M)
check('变异真的落盘', 'ASSERT_PATS = []' in mut)
td = tempfile.mkdtemp()
mp = os.path.join(td, 'stop_guard_mut.py')
open(mp, 'w', encoding='utf-8').write(mut)
Sm = load(mp, 'sg_mut')
d, _ = Sm.judge(f'{DONE}修复。')
check('断言表清空后违例溜过（判据不是恒真）', d is False, f'实际={d}')

# ── ④ stop_hook_active 放行（防死循环）──
r = subprocess.run(['python3', GUARD], input=json.dumps(
    {'session_id': 't-active', 'stop_hook_active': True,
     'last_assistant_message': f'{DONE}修复。'}), capture_output=True, text=True)
check('stop_hook_active=true 时放行', r.returncode == 0, f'rc={r.returncode}')

# ── ⑤ 连续拽回达上限后放行并留痕 ──
sid = 't-max-retry'
# 先清历史计数：判据把状态写在 ~/.codebuddy/hooks/.stop_guard_state，
# 不清就会「第二次跑测试必红」——pre-commit 每次跑，等于每次都在给自己挖坑
_st = S._read_state()
_st.pop(sid, None)
S._write_state(_st)
payload = json.dumps({'session_id': sid, 'stop_hook_active': False,
                      'last_assistant_message': f'{DONE}修复。'})
res = []
for _ in range(S.MAX_RETRY + 2):
    p = subprocess.run(['python3', GUARD], input=payload,
                       capture_output=True, text=True)
    try:
        blk = json.loads(p.stdout.strip() or '{}').get('decision') == 'block'
    except Exception:
        blk = False
    res.append((p.returncode, blk, p.stderr.strip()[:40]))
check('前 MAX_RETRY 次拽回', all(rc == 0 and b for rc, b, _ in res[:S.MAX_RETRY]),
      f'实际={res[:S.MAX_RETRY]}')
check('达上限后放行', all(rc == 0 and not b for rc, b, _ in res[S.MAX_RETRY:]),
      f'实际={res[S.MAX_RETRY:]}')
# 协议：实测 exit 2 + stderr 拽不回，只有 JSON decision:block 能拽回。
# 这条防的是「以后有人好心把输出改回 exit 2」——那样钩子还在跑，但语义降级成事后可见。
check('拽回走 JSON decision:block（非 exit 2）',
      res[0][0] == 0 and res[0][1] and not res[0][2], f'实际={res[0]}')
st = json.load(open(S.STATE, encoding='utf-8'))
check('放行痕迹已登记', st.get(sid, {}).get('gave_up') is True, f'实际={st.get(sid)}')

# ── ⑥ 闸必须真的挂在执行路径上 ──
sp = os.path.expanduser('~/.codebuddy/settings.json')
regd = False
if os.path.exists(sp):
    try:
        d = json.load(open(sp, encoding='utf-8'))
        blob = json.dumps(d.get('hooks', {}).get('Stop', []), ensure_ascii=False)
        regd = 'stop_guard.py' in blob
    except Exception:
        regd = False
check('settings.json 注册了 stop_guard.py', regd, '写了没挂 = 等于没写')

# ── ⑦ L3 留痕拽回（真消费 next_anchor state，非只测纯函数）──
RT = load(os.path.join(ROOT, 'verify', 'rule_trace.py'), 'rt_l3')


def mk_state(b03_via, b07_via, confirmed=None):
    """造隔离 state：按事件分槽 + 可选消解证据。"""
    d = {'probe_by_event': {
        'UserPromptSubmit': {'event': 'UserPromptSubmit', 'via': b03_via, 'root': '/x'},
        'SessionStart': {'event': 'SessionStart', 'via': b07_via},
    }}
    if confirmed:
        d['confirmed'] = confirmed
    td = tempfile.mkdtemp()
    fp = os.path.join(td, 'anchor_state.json')
    json.dump(d, open(fp, 'w', encoding='utf-8'))
    return fp


# 真阴性未消解 → 拽回（B-03 last_repo + B-07 no-handoff）
fp_bad = mk_state('last_repo', 'session-start+no-handoff')
deny_t, bad = S.judge_trace(fp_bad)
check('L3 留痕真阴性未消解→拽回', deny_t is True, f'bad={bad}')
check('L3 拽回规则含 B-03', 'B-03' in bad, f'bad={bad}')
check('L3 拽回规则含 B-07', 'B-07' in bad, f'bad={bad}')

# 病15 反向：已 confirm 消解（补做了行为）→ 不误拦
fp_ok = mk_state('last_repo', 'session-start+no-handoff',
                 confirmed={'B-03': {'proof': '手工 cat ENV_ID.json', 'ts': 1},
                            'B-07': {'proof': '手工读 handoff_latest.md', 'ts': 1}})
deny_ok, bad_ok = S.judge_trace(fp_ok)
check('L3 病15反向：已消解不误拦（识别范围≠对象范围）', deny_ok is False, f'bad={bad_ok}')

# 真阳性 → 不拦（真做了行为）
fp_true = mk_state('cwd', 'session-start+handoff')
check('L3 真阳性不拦', S.judge_trace(fp_true)[0] is False)

# unknown（无对应事件槽，回退旧 probe=PreToolUse）→ 不冒充红
fp_unk = os.path.join(tempfile.mkdtemp(), 'minimal.json')
json.dump({'probe': {'event': 'PreToolUse', 'via': 'command'}}, open(fp_unk, 'w', encoding='utf-8'))
check('L3 unknown 不冒充红', S.judge_trace(fp_unk)[0] is False)

# 元变异：清空 EV_OF 后留痕判据失效 → 真阴性样本溜过（自证判据真在守）
sg_src = open(GUARD, encoding='utf-8').read()
sd = tempfile.mkdtemp()
sgp = os.path.join(sd, 'sg_noimpl.py')
# 把 judge_trace 换成恒放行，验证「是这段代码在拦」而非环境巧合
mut = sg_src.replace("    bad = [r for r in ('B-07', 'B-03') if rt.unresolved(st, r)]",
                     "    bad = []  # MUT: 拿掉留痕判据")
open(sgp, 'w', encoding='utf-8').write(mut)
Sm = load(sgp, 'sg_mut2')
check('L3 元变异：拿掉判据后真阴性溜过', Sm.judge_trace(fp_bad)[0] is False)

# 端到端：Stop payload + 环境变量注入隔离 state → stdout 出 JSON decision:block
# 必须先清本用例 sid（否则多次运行累积达 MAX_RETRY → gave_up 放行 → 假红，与用例⑤同病）
_sid_l3 = 't-l3-trace'
_stg = S._read_state()
_stg.pop(_sid_l3, None)
S._write_state(_stg)
env = dict(os.environ, NEXT_ANCHOR_STATE=fp_bad)
r = subprocess.run(['python3', GUARD], input=json.dumps(
    {'session_id': _sid_l3, 'stop_hook_active': False,
     'last_assistant_message': '部署好了。'}), capture_output=True, text=True, env=env)
try:
    blk = json.loads(r.stdout.strip() or '{}').get('decision') == 'block'
    reason = json.loads(r.stdout.strip() or '{}').get('reason', '')
except Exception:
    blk, reason = False, ''
check('L3 端到端：留痕缺失触发 decision:block', blk, f'rc={r.returncode}, out={r.stdout.strip()[:80]}')
check('L3 端到端：拽回文案指名规则', 'B-03' in reason and 'confirm' in reason, f'reason={reason[:80]}')

# ── ⑧ L4 B-18 溯源拽回（交付段缺计数对）──
DT = load(os.path.join(ROOT, 'verify', 'delivery_trace.py'), 'dt_l4')

DELIV_NO_COUNT = '交付物：报告一份。\n事实均指回文件与行号，已核实。'
DELIV_WITH_COUNT = '交付物：报告一份。\n事实 5 条有出处 / 1 条无出处（单列 ⚠️）。'
PROCESS_ONLY = '已完成，提交 sha 6ed5df1，rc=0。'
META_TALK = 'B-18 规则要求交付时报 N 条有出处 / M 条无出处两个数（这里讨论规则模板）。'

# 真阴性：交付段缺计数对 → judge_delivery 拽回
d18, _ = S.judge_delivery(DELIV_NO_COUNT)
check('L4 B-18 交付缺计数→拽回', d18 is True)

# 真阳性：计数对齐全 → 放行
d18ok, _ = S.judge_delivery(DELIV_WITH_COUNT)
check('L4 B-18 计数齐→放行', d18ok is False)

# 病15 反向：过程描述 / 元话语讨论模板 → 不误伤
check('L4 B-18 过程描述无交付段→放行', S.judge_delivery(PROCESS_ONLY)[0] is False)
check('L4 B-18 元话语讨论模板→放行（识别范围≠对象范围）',
      S.judge_delivery(META_TALK)[0] is False)

# 纯函数三态直测
check('L4 B-18 verify 真阴性', DT.verify(DELIV_NO_COUNT) == 'false')
check('L4 B-18 verify 真阳性', DT.verify(DELIV_WITH_COUNT) == 'true')
check('L4 B-18 verify unknown', DT.verify(PROCESS_ONLY) == 'unknown' and DT.verify('') == 'unknown')

# 元变异：把 unresolved 恒放行 → 真阴性溜过（自证判据在守）
dt_src = open(os.path.join(ROOT, 'verify', 'delivery_trace.py'), encoding='utf-8').read()
dtd = tempfile.mkdtemp()
dt_mut = dt_src.replace("    return verify(text) == 'false'", "    return False  # MUT: 拿掉计数判据")
dtp = os.path.join(dtd, 'delivery_trace_mut.py')
open(dtp, 'w', encoding='utf-8').write(dt_mut)
# judge_delivery 动态加载的是固定路径，这里直接测纯函数变异体验证判据非恒真
DTm = load(dtp, 'dt_mut')
check('L4 B-18 元变异：拿掉判据后真阴性溜过', DTm.unresolved(DELIV_NO_COUNT) is False)

# 端到端：交付缺计数 + 隔离 state（B-03/B-07 均不拦）→ 只有 B-18 命中 → JSON decision:block
# 清 sid 防累积（沿 L3 教训）；并注入真阳 state，避免真实 state 的 B-03 回退先抢走 reason
_sid_l4 = 't-l4-delivery'
_stg = S._read_state()
_stg.pop(_sid_l4, None)
S._write_state(_stg)
fp_l4_anchor = mk_state('cwd', 'session-start+handoff')  # B-03/B-07 真阳 → judge_trace 放行
r = subprocess.run(['python3', GUARD], input=json.dumps(
    {'session_id': _sid_l4, 'stop_hook_active': False,
     'last_assistant_message': DELIV_NO_COUNT}),
    capture_output=True, text=True, env=dict(os.environ, NEXT_ANCHOR_STATE=fp_l4_anchor))
try:
    j = json.loads(r.stdout.strip() or '{}')
    blk, reason = j.get('decision') == 'block', j.get('reason', '')
except Exception:
    blk, reason = False, ''
check('L4 端到端：交付缺计数触发 decision:block', blk, f'rc={r.returncode}, out={r.stdout.strip()[:80]}')
check('L4 端到端：拽回文案指名 B-18 与计数模板',
      'B-18' in reason and '有出处' in reason and '无出处' in reason, f'reason={reason[:80]}')

# ── ⑨ L5 B-06 事实源拽回（状态断言无文件:行号引证）──
PT = load(os.path.join(ROOT, 'verify', 'premise_trace.py'), 'pt_l5')

PREMISE_NO_CITE = '结论：B-11 已退役，不用再查了。'          # 状态断言、无引证
PREMISE_WITH_CITE = 'B-11 已退役（见 docs/退役登记.md:42）。'  # 有引证
PREMISE_NEG = '该规则尚未退役，仍在使用。'                    # 否定语境
PREMISE_META = '规则原文举例「某规则已退役」——这是形态说明。'  # 元话语

# 真阴性：状态断言无引证 → judge_premise 拽回
check('L5 B-06 状态断言无引证→拽回', S.judge_premise(PREMISE_NO_CITE)[0] is True)
# 真阳性：带文件:行号引证 → 放行
check('L5 B-06 有引证→放行', S.judge_premise(PREMISE_WITH_CITE)[0] is False)
# 病15 反向：否定语境 / 元话语 / 过程描述 / B-13 域完成断言 → 不误伤
check('L5 B-06 否定语境→放行（识别范围≠对象范围）', S.judge_premise(PREMISE_NEG)[0] is False)
check('L5 B-06 元话语→放行', S.judge_premise(PREMISE_META)[0] is False)
check('L5 B-06 过程描述→放行', S.judge_premise('我查了仓库，然后改了脚本。')[0] is False)
check('L5 B-06 B-13完成断言→放行（对象域错开）',
      S.judge_premise('部署好了，提交 sha abc1234。')[0] is False)
# 纯函数三态直测
check('L5 B-06 verify 真阴性', PT.verify(PREMISE_NO_CITE) == 'false')
check('L5 B-06 verify 真阳性', PT.verify(PREMISE_WITH_CITE) == 'true')
check('L5 B-06 verify unknown',
      PT.verify(PREMISE_NEG) == 'unknown' and PT.verify('') == 'unknown')
# 元变异：把 unresolved 恒放行 → 真阴性溜过
pt_src = open(os.path.join(ROOT, 'verify', 'premise_trace.py'), encoding='utf-8').read()
ptd = tempfile.mkdtemp()
pt_mut = pt_src.replace("    return verify(text) == 'false'", "    return False  # MUT: 拿掉引证判据")
ptp = os.path.join(ptd, 'premise_trace_mut.py')
open(ptp, 'w', encoding='utf-8').write(pt_mut)
PTm = load(ptp, 'pt_mut')
check('L5 B-06 元变异：拿掉判据后真阴性溜过', PTm.unresolved(PREMISE_NO_CITE) is False)
# 端到端：状态断言无引证 + 隔离 state（B-03/B-07 真阳）+ 无交付段（B-18 放行）→ B-06 命中
_sid_l5 = 't-l5-premise'
_stg5 = S._read_state()
_stg5.pop(_sid_l5, None)
S._write_state(_stg5)
fp_l5_anchor = mk_state('cwd', 'session-start+handoff')
r = subprocess.run(['python3', GUARD], input=json.dumps(
    {'session_id': _sid_l5, 'stop_hook_active': False,
     'last_assistant_message': PREMISE_NO_CITE}),
    capture_output=True, text=True, env=dict(os.environ, NEXT_ANCHOR_STATE=fp_l5_anchor))
try:
    j = json.loads(r.stdout.strip() or '{}')
    blk, reason = j.get('decision') == 'block', j.get('reason', '')
except Exception:
    blk, reason = False, ''
check('L5 端到端：状态断言无引证触发 decision:block', blk,
      f'rc={r.returncode}, out={r.stdout.strip()[:80]}')
check('L5 端到端：拽回文案指名 B-06 与文件行号引证',
      'B-06' in reason and '行号' in reason, f'reason={reason[:80]}')

# ── ⑩ S 段施工纪律拽回（S-09 查证缺会话标记 / 派单缺中文约束）──
DT_S = load(os.path.join(ROOT, 'verify', 'discipline_trace.py'), 'dt_s')

# 真阴性：跨源查证完成态断言但无会话标记 → 拽回
CLAIM_NO_SCOPE = '全量查证结论如下：本次扫了仓库与资料库，共四条机检，证据略。'
CLAIM_WITH_SCOPE = '全量查证结论如下：见 会话.jsonl:65888，另核 verify/rule_map.json:12。'
# 派单段：派了子代理但 prompt 首句无中文约束
DISPATCH_NO_ZH = '派子代理去查：先看仓库结构，用 Explore 类型，任务如下……'
DISPATCH_WITH_ZH = '派子代理（全程简体中文）：先看仓库结构，用 Explore 类型……'

check('S-09 跨源查证缺会话标记→拽回', DT_S.verify(CLAIM_NO_SCOPE, 's09') == 'true')
check('S-09 有会话标记→放行', DT_S.verify(CLAIM_WITH_SCOPE, 's09') == 'false')
check('S-09 非查类断言→免疫（识别范围≠对象范围）',
      DT_S.verify('已完成，提交 sha abc1234。', 's09') == 'unknown')
check('S-09 空文本→unknown', DT_S.verify('', 's09') == 'unknown')
check('派单缺中文约束→拽回', DT_S.verify(DISPATCH_NO_ZH, 'dispatch') == 'true')
check('派单有中文约束→放行', DT_S.verify(DISPATCH_WITH_ZH, 'dispatch') == 'false')
check('派单无派单信号→免疫', DT_S.verify('查一下 git log。', 'dispatch') == 'unknown')

# judge_s_discipline 接线（端到端前先测函数）
check('judge_s_discipline 查证缺标记命中',
      S.judge_s_discipline(CLAIM_NO_SCOPE) == (True, 'S-09'))
check('judge_s_discipline 派单缺中文命中',
      S.judge_s_discipline(DISPATCH_NO_ZH) == (True, 'DISPATCH'))
check('judge_s_discipline 正常放行', S.judge_s_discipline(CLAIM_WITH_SCOPE) == (False, ''))

# 元变异：把 s09 的 verify 恒放行 → 真阴性溜过（自证判据在守）
s_src = open(os.path.join(ROOT, 'verify', 'discipline_trace.py'), encoding='utf-8').read()
sm_mut = s_src.replace("        return 'false' if _has_scope(text) else 'true'",
                       "        return 'false'  # MUT: 拿掉会话标记判据")
smp = os.path.join(tempfile.mkdtemp(), 'discipline_trace_mut.py')
open(smp, 'w', encoding='utf-8').write(sm_mut)
SMm = load(smp, 'dt_s_mut')
check('S-09 元变异：拿掉判据后真阴性溜过', SMm.verify(CLAIM_NO_SCOPE, 's09') == 'false')

# 端到端：跨源查证缺标记 + 隔离 state + 其余判据放行 → S 段命中
_sid_s = 't-s-discipline'
_sts = S._read_state()
_sts.pop(_sid_s, None)
S._write_state(_sts)
r = subprocess.run(['python3', GUARD], input=json.dumps(
    {'session_id': _sid_s, 'stop_hook_active': False,
     'last_assistant_message': CLAIM_NO_SCOPE}),
    capture_output=True, text=True, env=dict(os.environ, NEXT_ANCHOR_STATE=mk_state('cwd', 'session-start+handoff')))
try:
    js = json.loads(r.stdout.strip() or '{}')
    blk_s, reason_s = js.get('decision') == 'block', js.get('reason', '')
except Exception:
    blk_s, reason_s = False, ''
check('S 端到端：查证缺会话标记触发 decision:block', blk_s,
      f'rc={r.returncode}, out={r.stdout.strip()[:80]}')
check('S 端到端：拽回文案指名 S-09 与会话标记',
      'S-09' in reason_s and '会话' in reason_s, f'reason={reason_s[:80]}')

print('test_stop_guard：%d 例，失败 %d' % (N[0], len(fails)))
sys.exit(1 if fails else 0)
