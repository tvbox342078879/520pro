#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# impl: B-07 S5   ← SessionStart 读 handoff 行为留痕三态判据
# impl: B-03 S5   ← UserPromptSubmit 环境定位行为留痕三态判据
"""rule_trace.py — B-07/B-03「行为发生」三态判据（L2 高频人工判据硬化）。

为什么不是查源码字符串（病15 识别范围≠对象范围）：
  T4 只验「check 文件在 + anchor 字面出现」——那是入口存在，不是行为发生。
  本模块判据对象是**真 probe 快照**（next_anchor 落的执行留痕），喂样本判三态：
  - B-07：SessionStart 真读过 handoff → probe.via 含 '+handoff'
  - B-03：UserPromptSubmit 真定位到本仓（非 last_repo 猜）→ probe.via ∈ {cwd,command}

三态（B-02 不折叠）：
  真阳性 / 真阴性 / 无法判定（无对应事件留痕时如实 unknown，不冒充通过）。

诚实边界：这是「行为留痕在不在」的判据，不是「模型是否真的理解了 handoff/环境」——
后者机器判不了（test_handoff.py:47 自陈同一天花板）。留痕在 = 机制被触发过；
留痕缺 = 确定没触发（真阴性可用）。绝不用代理指标冒充「遵守」。
"""
import json
import os
import time

# 默认真 state；环境变量仅供端到端测试注入隔离 state（真实 hook 运行不设它，非绕过后门）
STATE = os.environ.get('NEXT_ANCHOR_STATE') or os.path.expanduser('~/.codebuddy/hooks/.next_anchor_state')

# L3：每条规则对应哪类事件槽（与 next_anchor 分槽写入一致）
EV_OF = {'B-07': 'SessionStart', 'B-03': 'UserPromptSubmit'}


def load_state(path=None):
    """读 state；缺失/损坏返回空 dict（无法判定，不伪造）。"""
    fp = path or STATE
    try:
        d = json.load(open(fp, encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def b07_trace(probe):
    """B-07 执行留痕三态：SessionStart 读 handoff 的 probe 是否显示成功。
    probe: dict（next_anchor 的一次调用快照）。返回 'true'/'false'/'unknown'。
    """
    if not isinstance(probe, dict):
        return 'unknown'
    if probe.get('event') != 'SessionStart':
        return 'unknown'                      # 本次留痕不是开机事件，判不了 B-07
    via = str(probe.get('via') or '')
    if '+no-handoff' in via:
        return 'false'                        # 开机了但没读到 handoff → 真阴性
    if 'session-start+handoff' in via or via.startswith('session-start') and '+handoff' in via:
        return 'true'                         # 开机且读到 → 真阳性
    if 'session-start' in via:
        return 'unknown'                      # 开机但 via 无 handoff 结论 → 无法判定
    return 'unknown'


def b03_trace(probe):
    """B-03 执行留痕三态：UserPromptSubmit 是否从 payload 明确定位到 git 仓。
    via=cwd/command = 真验环境；via=last_repo* = 回退猜仓（未真验）→ 真阴性。
    """
    if not isinstance(probe, dict):
        return 'unknown'
    if probe.get('event') != 'UserPromptSubmit':
        return 'unknown'
    via = str(probe.get('via') or '')
    root = probe.get('root') or ''
    if via in ('cwd', 'command'):
        return 'true' if root else 'unknown'  # 明确定位且拿到仓根
    if via.startswith('last_repo'):
        return 'false'                        # 回退猜仓 = 本轮没真验环境
    if via == 'none':
        return 'false'                        # 连仓都没定位到
    return 'unknown'


def _probe_for(state, rule):
    """L3：按事件槽取该规则该看的 probe；缺槽回退旧单一 probe（兼容旧 state / 旧测试）。"""
    st = state or {}
    by_ev = st.get('probe_by_event') or {}
    ev = EV_OF.get(rule)
    if ev and isinstance(by_ev.get(ev), dict):
        return by_ev[ev]
    return st.get('probe') or {}


def verdict(state, rule):
    """从整份 state 取该规则对应事件的 probe 判三态；无 probe 返回 unknown。"""
    probe = _probe_for(state, rule)
    return (b07_trace if rule == 'B-07' else b03_trace if rule == 'B-03'
            else lambda _: 'unknown')(probe)


def confirm(state, rule, proof, path=None):
    """对一条真阴性留痕写入「已消解」证据（evidence 必填，禁空戳—病15 反假绿）。

    消解 = 模型确实补做了行为（手工 cat ENV_ID / 读 handoff）并留下可核证据。
    写入 state['confirmed'][rule] = {proof, ts}；不伪造 probe 的 via。
    返回 (是否写入, 说明)。真阳性/unknown 无需消解，拒绝空 evidence。
    """
    if rule not in EV_OF:
        return False, '未知规则'
    proof = str(proof or '').strip()
    if not proof:
        return False, 'evidence 为空——拒绝无证据的空确认（病15 假绿）'
    st = state if isinstance(state, dict) else {}
    st.setdefault('confirmed', {})[rule] = {'proof': proof[:200], 'ts': int(time.time())}
    fp = path or STATE
    try:
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        json.dump(st, open(fp, 'w', encoding='utf-8'))
    except Exception as e:
        return False, '写入失败: %s' % e
    return True, '已消解 ' + rule


def unresolved(state, rule):
    """硬闸最终判据：verdict=false 且无 confirm 证据 → 需拽回。

    true（真做了）/ unknown（无法判定，B-02 不冒充）→ 不拦；
    false 但 confirmed[rule] 有非空 evidence → 已补做，放行（不误伤）。
    """
    v = verdict(state, rule)
    if v != 'false':
        return False
    cf = ((state or {}).get('confirmed') or {}).get(rule) or {}
    return not str(cf.get('proof') or '').strip()


def cli():
    import sys
    args = sys.argv[1:]
    path = None
    if '--state' in args:
        path = args[args.index('--state') + 1]
    st = load_state(path)

    # L3 硬闸入口：stop_guard 查「哪些规则留痕缺失且未消解」→ JSON 列表
    if args and args[0] == '--gate':
        bad = [r for r in ('B-07', 'B-03') if unresolved(st, r)]
        print(json.dumps({'block': bool(bad), 'rules': bad}, ensure_ascii=False))
        return 1 if bad else 0                       # 1=有未消解留痕缺口（闸门红）

    # L3 消解入口：被拽回后补做行为并给 evidence → 写入确认
    if args and args[0] == 'confirm':
        if len(args) < 3:
            print('用法：python3 rule_trace.py confirm <B-07|B-03> --proof "证据"')
            return 2
        rule = args[1]
        proof = args[args.index('--proof') + 1] if '--proof' in args else ''
        ok, msg = confirm(st, rule, proof, path)
        print(msg)
        return 0 if ok else 2

    if not args or args[0] not in ('B-07', 'B-03'):
        print('用法：python3 rule_trace.py <B-07|B-03> [--state PATH]'
              ' | --gate [--state PATH] | confirm <规则> --proof "证据"')
        return 2
    rule = args[0]
    v = verdict(st, rule)
    probe = _probe_for(st, rule)
    print('%s 执行留痕：%s（event=%s, via=%s, unresolve=%s）'
          % (rule, v, probe.get('event'), probe.get('via'), unresolved(st, rule)))
    # 三态出口：真阳性 0 / 真阴性 1 / 无法判定 2（不折叠成通过）
    return {'true': 0, 'false': 1, 'unknown': 2}[v]


if __name__ == '__main__':
    raise SystemExit(cli())
