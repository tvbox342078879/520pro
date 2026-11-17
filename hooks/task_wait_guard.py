#!/usr/bin/env python3
# task_wait_guard.py —— 会话层等待闸（防卡死检查单·等待死，v0.8.79）
# 挂 PreToolUse·TaskOutput（install.sh 幂等注册）。防的卡死：会话对同一后台任务
# 反复 block=true 前台死等（B-11 的执行闸——禁轮询从规则文字变成拦截）。
#
# 设计四条（自审过 docs/防卡死检查单.md 检查单 7 条）：
#   ① 管理动作豁免：block=false（非阻塞读取）恒放行，且顺带清该任务计数。
#   ② 逃生口在被锁实体可达的层：只拦「重复阻塞等待」，非阻塞路径永远开着。
#   ③ 死状态自动过期：计数记录 >1h 清零，不永久锁门。
#   ④ fail-open：任何异常 exit 0 放行——本闸绝不重演 deny-all 自锁。
#
# 阈值：同一 task_id 连续第 3 次 block=true → deny；第 1/2 次放行（合法等待）。
# 状态文件可用环境变量 _TASKWAIT_STATE 重定向（测试隔离用），默认 /tmp/_520_taskwait.json。

import json
import os
import sys
import time

STATE = os.environ.get('_TASKWAIT_STATE', '/tmp/_520_taskwait.json')
DENY_AT = 3          # 第 3 次阻塞等待拒绝
EXPIRE_SEC = 3600    # 计数化石过期：>1h 未再等待即重置


def _load():
    try:
        with open(STATE, encoding='utf-8') as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {}
        # 化石清理：过期条目直接删除（检查单第 4 条：死状态自动过期）
        now = time.time()
        return {k: v for k, v in d.items()
                if isinstance(v, dict) and now - float(v.get('ts', 0)) <= EXPIRE_SEC}
    except Exception:
        return {}


def _save(d):
    try:
        with open(STATE, 'w', encoding='utf-8') as f:
            json.dump(d, f)
    except Exception:
        pass  # 状态写不进去=闸失忆=放行，不升级成故障


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
    # --probe（病13 观测要件）：报告状态文件实况——hit=当前有等待账的任务及次数，via=判定依据来源
    if '--probe' in sys.argv:
        d = _load()
        print(json.dumps({'probe': True, 'via': 'state:' + STATE,
                          'hit': {k: int(v.get('count', 0)) for k, v in d.items()
                                  if int(v.get('count', 0)) > 0}}, ensure_ascii=False))
        sys.exit(0)
    raw = sys.stdin.read() if not sys.stdin.isatty() else ''
    try:
        inp = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)  # 坏输入 fail-open
    ti = inp.get('tool_input') or {}
    if not isinstance(ti, dict):
        sys.exit(0)
    task_id = str(ti.get('task_id') or '')
    if not task_id:
        sys.exit(0)  # 无 task_id 无法对账，放行不误伤

    d = _load()
    rec = d.get(task_id) or {'count': 0, 'ts': 0}

    # ① 非阻塞读取：恒放行 + 清计数（健康行为，重置等待账）
    if ti.get('block') is not True:
        if task_id in d:
            d.pop(task_id, None)
            _save(d)
        sys.exit(0)

    # ② 阻塞等待：计数 +1
    rec['count'] = int(rec.get('count', 0)) + 1
    rec['ts'] = time.time()
    d[task_id] = rec
    _save(d)

    if rec['count'] >= DENY_AT:
        deny_payload(
            '防卡死闸（等待死）：任务 %s 已连续 %d 次 block=true 前台等待——'
            '禁轮询（B-11）。改 block=false 立即返回（非阻塞），等完成通知到了再取；'
            '非阻塞读取会自动清本闸计数。' % (task_id, rec['count']))
    sys.exit(0)  # 第 1/2 次：合法等待，放行


def selftest():
    """双向自测（检查单第 7 条）：违规拦得住、合规不误拦 + 元变异证判据有牙。"""
    import tempfile
    results = []

    def case(name, cond):
        results.append((name, bool(cond)))

    with tempfile.TemporaryDirectory() as td:
        st = os.path.join(td, 'st.json')
        # 子进程经 env _TASKWAIT_STATE 隔离状态，本进程常量无需重读
        os.environ['_TASKWAIT_STATE'] = st

        def run(payload):
            p = __import__('subprocess').run(
                [sys.executable, __file__], input=json.dumps(payload),
                capture_output=True, text=True, env=dict(os.environ, _TASKWAIT_STATE=st))
            return p.returncode, p.stdout

        # 1. block=false 非阻塞放行
        rc, _ = run({'tool_name': 'TaskOutput', 'tool_input': {'task_id': 't1', 'block': False}})
        case('非阻塞放行(rc=0)', rc == 0)
        # 2. 阻塞第 1、2 次放行
        rc1, _ = run({'tool_input': {'task_id': 't2', 'block': True}})
        rc2, _ = run({'tool_input': {'task_id': 't2', 'block': True}})
        case('阻塞1/2次放行', rc1 == 0 and rc2 == 0)
        # 3. 第 3 次 deny（exit 2 + deny JSON）
        rc3, out3 = run({'tool_input': {'task_id': 't2', 'block': True}})
        ok_json = 'deny' in (out3 or '')
        case('第3次deny(irc=2+deny)', rc3 == 2 and ok_json)
        # 4. 非阻塞读取清计数后，再次阻塞从 1 数起
        run({'tool_input': {'task_id': 't2', 'block': False}})
        rc4, _ = run({'tool_input': {'task_id': 't2', 'block': True}})
        case('非阻塞清账后再等放行', rc4 == 0)
        # 5. 化石过期：伪造 1h 前的旧账，第 3 次不应 deny
        d = json.load(open(st, encoding='utf-8')) if os.path.exists(st) else {}
        d['t3'] = {'count': 2, 'ts': time.time() - 3700}
        json.dump(d, open(st, 'w', encoding='utf-8'))
        rc5, _ = run({'tool_input': {'task_id': 't3', 'block': True}})
        case('化石过期重置放行', rc5 == 0)
        # 6. 坏输入 fail-open
        p = __import__('subprocess').run(
            [sys.executable, __file__], input='not-json{{',
            capture_output=True, text=True, env=dict(os.environ, _TASKWAIT_STATE=st))
        case('坏输入fail-open', p.returncode == 0)

        # 7. 元变异：阈值 3→2 时原第 2 次就该 deny（证判据贴着阈值，不是恒绿）
        src = open(__file__, encoding='utf-8').read()
        mut = src.replace("rec['count'] >= DENY_AT", "rec['count'] >= 2", 1)
        assert mut != src, '变异点不存在'
        mpath = os.path.join(td, 'mut.py')
        open(mpath, 'w', encoding='utf-8').write(mut)
        st2 = os.path.join(td, 'st2.json')
        run2 = lambda payload: __import__('subprocess').run(
            [sys.executable, mpath], input=json.dumps(payload), capture_output=True,
            text=True, env=dict(os.environ, _TASKWAIT_STATE=st2)).returncode
        run2({'tool_input': {'task_id': 'm1', 'block': True}})
        rc_m2 = run2({'tool_input': {'task_id': 'm1', 'block': True}})
        case('元变异:阈值2时第2次deny', rc_m2 == 2)

    npass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(('  ✓ ' if ok else '  ✗ ') + name)
    print('selftest: %d/%d' % (npass, len(results)))
    sys.exit(0 if npass == len(results) else 1)


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        try:
            main()
        except Exception:
            sys.exit(0)  # ④ fail-open：闸自身故障绝不锁会话
