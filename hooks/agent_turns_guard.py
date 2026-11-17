#!/usr/bin/env python3
# impl: B-11 S1  ← 派子任务带时限（缺 max_turns deny），孤儿闸归位
# agent_turns_guard.py —— 子任务时限闸（防卡死检查单·等待死另一半，v0.8.80）
# 挂 PreToolUse·Agent（install.sh 幂等注册；matcher 由 Agent|Task 收窄，见病15 第21例）。
# 防的卡死：派出的子代理无时限
# 跑飞（死循环/无限重试），主会话白等——B-11「派子任务必须带时限」的执行闸。
#
# 设计四条（自审过 docs/防卡死检查单.md 检查单 7 条）：
#   ① 管理动作豁免：带 max_turns 的调用恒放行——不拦任何已合规动作；
#   ② 逃生口在被锁实体可达的层：补上 max_turns 参数即可过，无状态无残留；
#   ③ 无死状态：纯输入校验，不落状态文件，天然不永久锁门；
#   ④ fail-open：任何异常 exit 0 放行——本闸绝不锁死派活通道。
#
# 判据：tool_name 为派活工具（Agent/Task）且缺 max_turns → deny，提示带时限（15–30 回合）。
# 对象判定用 tool_name 精确白名单（病15 第21例根因）：旧版用「tool_input 含 prompt 或
# description」当派活特征，而 TaskCreate/Update/Get 等记账工具也带 description，于是
# matcher Agent|Task 把它们路由进来后误拦——识别范围（字段特征）宽于对象范围（派活）。
# 字段名兼容：只认 tool_name 白名单；max_turns 缺失或显式 null 算缺。

import json
import sys


def deny_payload(reason):
    # 输出格式与 guard_cmd.py deny_payload 同构（正本入口，B-08）
    print(json.dumps({
        'hookSpecificOutput': {
            'permissionDecision': 'deny',
            'permissionDecisionReason': reason,
        }
    }, ensure_ascii=False))
    sys.exit(2)


def main():
    # --probe（病13 观测要件）：via=判定依据来源，hit=最近一次判定结果
    if '--probe' in sys.argv:
        print(json.dumps({'probe': True, 'via': 'tool_input.max_turns',
                          'hit': 'stateless（纯输入校验，无状态文件）'}, ensure_ascii=False))
        sys.exit(0)
    raw = sys.stdin.read() if not sys.stdin.isatty() else ''
    try:
        inp = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)  # 坏输入 fail-open
    ti = inp.get('tool_input') or {}
    if not isinstance(ti, dict):
        sys.exit(0)

    # ⓪ 对象范围限定（病15 第21例修复）：只校验真正的「派活调用」，判据是 tool_name
    #    精确白名单，不再用 tool_input 的 prompt/description 字段特征。旧特征把带
    #    description 的记账工具（TaskCreate/Update/Get/List）也算成派活并误拦——
    #    识别范围宽于对象范围。派活工具白名单：Agent（主）、Task（兼容平台别名）。
    #    其余工具即使平台误路由到本闸（如 Bash/其他）一律放行。
    SPAWN_TOOLS = ('Agent', 'Task')
    tool_name = inp.get('tool_name')
    if tool_name not in SPAWN_TOOLS:
        sys.exit(0)

    # ① 已合规：带 max_turns（含 0/数字）恒放行
    mt = ti.get('max_turns')
    if mt is not None:
        sys.exit(0)

    # ② 缺时限：deny（逃生口=补参数即可，会话侧可达）
    deny_payload(
        '防卡死闸（子任务时限）：派子代理（Agent/Task）未带 max_turns——子代理跑飞时'
        '主会话会无限白等（B-11：派子任务必须带时限）。补 max_turns（建议 15–30）后重发；'
        '探查型给小值（如 10），施工型给大值（如 30）。记账工具（TaskCreate 等）不受此闸。')
    sys.exit(0)


def selftest():
    """双向自测（检查单第 7 条）：违规拦得住、合规不误拦。"""
    import subprocess
    import tempfile
    results = []

    def case(name, cond):
        results.append((name, bool(cond)))

    with tempfile.TemporaryDirectory() as td:
        def run(payload):
            p = subprocess.run([sys.executable, __file__], input=json.dumps(payload),
                               capture_output=True, text=True,
                               env=dict(os.environ, HOME=td))
            return p.returncode, p.stdout

        rc1, _ = run({'tool_name': 'Agent', 'tool_input': {'prompt': 'x', 'max_turns': 25}})
        case('带 max_turns 放行', rc1 == 0)
        rc2, _ = run({'tool_name': 'Agent', 'tool_input': {'prompt': 'x', 'max_turns': 0}})
        case('max_turns=0 也是显式时限（放行）', rc2 == 0)
        rc3, out3 = run({'tool_name': 'Agent', 'tool_input': {'prompt': 'x'}})
        ok3 = rc3 == 2 and 'deny' in (out3 or '') and 'max_turns' in (out3 or '')
        case('缺 max_turns deny(irc=2+deny+提示补参)', ok3)
        rc4, _ = run({'tool_name': 'Agent', 'tool_input': {'prompt': 'x', 'max_turns': None}})
        case('显式 null 视为缺（deny）', rc4 == 2)
        p5 = subprocess.run([sys.executable, __file__], input='bad{{',
                            capture_output=True, text=True, env=dict(os.environ, HOME=td))
        case('坏输入 fail-open', p5.returncode == 0)
        rc6, _ = run({})
        case('空 payload 放行（不误伤非 Agent 调用）', rc6 == 0)
        rc6b, _ = run({'tool_name': 'Bash', 'tool_input': {'command': 'ls'}})
        case('Bash 形态 tool_input 放行（对象范围限定）', rc6b == 0)
        # 病15 第21例回归：记账工具带 description 不得被当派活误拦（旧版会 deny）
        for tgt in ('TaskCreate', 'TaskUpdate', 'TaskGet', 'TaskList', 'TaskOutput'):
            rcx, outx = run({'tool_name': tgt, 'tool_input': {
                'description': 'some task', 'subject': 'x'}})
            case('%s 带 description 无 max_turns 放行（误伤回归）' % tgt, rcx == 0)
        # 同一工具名缺失（None）——无法判定是不是派活，fail-open 放行而非误拦
        rcn, _ = run({'tool_input': {'prompt': 'x'}})
        case('tool_name 缺失放行（不误伤未知调用）', rcn == 0)
        # 元变异①：把 tool_name 白名单判据改回字段特征 → 记账工具误伤回归用例必须转红
        src = open(__file__, encoding='utf-8').read()
        mut0 = src.replace(
            "    if tool_name not in SPAWN_TOOLS:\n        sys.exit(0)",
            "    if 'prompt' not in ti and 'description' not in ti:\n        sys.exit(0)", 1)
        assert mut0 != src, '变异点0 不存在'
        m0 = td + '/mut0.py'
        open(m0, 'w', encoding='utf-8').write(mut0)
        p0 = subprocess.run([sys.executable, m0], input=json.dumps(
            {'tool_name': 'TaskCreate', 'tool_input': {'description': 'x'}}),
            capture_output=True, text=True, env=dict(os.environ, HOME=td))
        case('元变异:退回字段特征判据→TaskCreate 误伤回归红', p0.returncode == 2)
        # 元变异：合规放行分支改成 deny → 正向用例红（证判据贴着实现）
        src = open(__file__, encoding='utf-8').read()
        mut = src.replace("if mt is not None:\n        sys.exit(0)",
                          "if mt is not None:\n        sys.exit(2)", 1)
        assert mut != src, '变异点不存在'
        mpath = td + '/mut.py'
        open(mpath, 'w', encoding='utf-8').write(mut)
        p7 = subprocess.run([sys.executable, mpath], input=json.dumps(
            {'tool_name': 'Agent', 'tool_input': {'prompt': 'x', 'max_turns': 25}}),
            capture_output=True, text=True, env=dict(os.environ, HOME=td))
        case('元变异:合规路径被改死→正向红', p7.returncode != 0)

    npass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(('  ✓ ' if ok else '  ✗ ') + name)
    print('selftest: %d/%d' % (npass, len(results)))
    sys.exit(0 if npass == len(results) else 1)


if __name__ == '__main__':
    import os
    if '--selftest' in sys.argv:
        selftest()
    else:
        try:
            main()
        except Exception:
            sys.exit(0)  # ④ fail-open
