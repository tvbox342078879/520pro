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

STATE = os.path.expanduser('~/.codebuddy/hooks/.next_anchor_state')


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


def verdict(state, rule):
    """从整份 state 取 probe 判指定规则；无 probe 返回 unknown。"""
    probe = (state or {}).get('probe') or {}
    return (b07_trace if rule == 'B-07' else b03_trace if rule == 'B-03'
            else lambda _: 'unknown')(probe)


def cli():
    import sys
    if len(sys.argv) < 2 or sys.argv[1] not in ('B-07', 'B-03'):
        print('用法：python3 rule_trace.py <B-07|B-03> [--state PATH]')
        return 2
    rule = sys.argv[1]
    path = None
    if '--state' in sys.argv:
        path = sys.argv[sys.argv.index('--state') + 1]
    st = load_state(path)
    v = verdict(st, rule)
    probe = st.get('probe') or {}
    print('%s 执行留痕：%s（probe.event=%s, via=%s）'
          % (rule, v, probe.get('event'), probe.get('via')))
    # 三态出口：真阳性 0 / 真阴性 1 / 无法判定 2（不折叠成通过）
    return {'true': 0, 'false': 1, 'unknown': 2}[v]


if __name__ == '__main__':
    raise SystemExit(cli())
