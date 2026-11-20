#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hook_heartbeat.py —— 钩子自证账本：记「钩子拦过没有、拦了多少」。

## 定性（回答什么）
钩子装了，到底有没有真拦过？不靠模型自报（可随口伪造），靠钩子在拦截
那一刻自己落一笔机器账。这是可观测性基础设施，不是判据本身。

## 520 适配（与另一环境 M 体系的差异）
- 它的 .hook_heartbeat.json 记 5 个 PreToolUse 钩子的全局累计拦截数。
- 520 三点适配：① 按 session_id 记明细（多会话不混账，比 B-04 state 隔离
  更进一步：账本天然全局汇总 + 会话明细并存）；② 非阻塞锁 flock LOCK_NB
  （钩子是同步 PreToolUse，绝不能阻塞调用方——parallel_guard 坑2 实测卡死
  46s 的教训）；③ 原子写 tmp + os.replace（防半截 JSON）。

## 证据等级（B-02 三态诚实）
心跳账只证明「钩子自报拦过」，**不证明拦得对**。拦得对不对仍靠判据
（各钩 --probe 的 hit/via + verify/tests）。账本与判据配对才闭环，
单看账本把「拦过」说成「拦对」是 B-02 折叠，禁止。

## 接口
-beat(hook, blocked=, missed=, sid=)  记一笔，失败静默 fail-open
-snapshot(hook=, sid=)                 读账本快照（供 --probe / hook_ledger 用）
-python3 hook_heartbeat.py --probe     输出 JSON 含 hit/via/calls/missed/hooks
"""
import fcntl
import json
import os
import sys
import time


def _live_path():
    """账本路径：环境变量优先（测试隔离），否则用户级 hooks 目录。"""
    return (os.environ.get('HOOK_HEARTBEAT_STATE')
            or os.path.expanduser('~/.codebuddy/hooks/.hook_heartbeat.json'))


def _lock_path():
    return _live_path() + '.lock'


def _load():
    try:
        d = json.load(open(_live_path(), encoding='utf-8'))
        if not isinstance(d, dict):
            raise ValueError('not a dict')
        d.setdefault('hooks', {})
        return d
    except Exception:
        return {'hooks': {}, 'updated': ''}


def _save(d):
    """原子写：tmp + os.replace，避免钩子并发时写出半截 JSON。"""
    try:
        p = _live_path()
        tmp = p + '.tmp.%d' % os.getpid()
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def beat(hook, blocked=False, missed=False, sid=None):
    """记一笔心跳。blocked=本次真拦截；missed=本该拦却放行。

    fail-open：拿不到锁 / 路径不可写 / 任何异常 → 静默跳过，绝不阻塞调用方，
    绝不因记账失败让钩子崩（钩子是同步 PreToolUse，崩了会卡整条命令通道）。
    """
    lf = None
    try:
        lf = open(_lock_path(), 'a+')
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        try:
            if lf:
                lf.close()
        except Exception:
            pass
        return False
    try:
        d = _load()
        h = d['hooks'].setdefault(str(hook), {
            'calls': 0, 'blocked': 0, 'missed': 0, 'last_ts': '', 'sessions': {}})
        h['calls'] += 1
        if blocked:
            h['blocked'] += 1
        if missed:
            h['missed'] += 1
        h['last_ts'] = time.strftime('%Y-%m-%d %H:%M:%S')
        if sid:
            s = h['sessions'].setdefault(str(sid), {
                'calls': 0, 'blocked': 0, 'missed': 0})
            s['calls'] += 1
            if blocked:
                s['blocked'] += 1
            if missed:
                s['missed'] += 1
        d['updated'] = h['last_ts']
        return _save(d)
    except Exception:
        return False
    finally:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            lf.close()
        except Exception:
            pass


def beat_from_payload(payload, hook, blocked=False, missed=False):
    """从 hook payload 自动提 session_id 再记账——各钩接线的统一正门。

    payload 里 session_id 可能叫 session_id / sessionId；取不到就记全局账
    （sid=None → beat 跳过会话明细），不误伤、不阻塞。
    """
    sid = None
    if isinstance(payload, dict):
        sid = payload.get('session_id') or payload.get('sessionId')
    return beat(hook, blocked=blocked, missed=missed, sid=sid)


def snapshot(hook=None, sid=None):
    """读账本快照，供 --probe 与 verify/hook_ledger.py 用。失败返回空壳。"""
    d = _load()
    hooks = d.get('hooks', {})
    if hook:
        hooks = {k: v for k, v in hooks.items() if hook in k}
    if sid:
        hooks = {k: v for k, v in hooks.items()
                 if sid in (v.get('sessions') or {})}
    return hooks


def _probe(argv):
    hook = sid = None
    if '--hook' in argv:
        try:
            hook = argv[argv.index('--hook') + 1]
        except Exception:
            pass
    if '--sid' in argv:
        try:
            sid = argv[argv.index('--sid') + 1]
        except Exception:
            pass
    hooks = snapshot(hook, sid)
    if sid:
        # 指定 sid 时按会话明细汇总，避免把别的会话调用算进 filtered 快照
        def _sess(v, k):
            return int(((v.get('sessions') or {}).get(sid) or {}).get(k, 0))
        hit = sum(_sess(v, 'blocked') for v in hooks.values())
        calls = sum(_sess(v, 'calls') for v in hooks.values())
        missed = sum(_sess(v, 'missed') for v in hooks.values())
    else:
        hit = sum(int(v.get('blocked', 0)) for v in hooks.values())
        calls = sum(int(v.get('calls', 0)) for v in hooks.values())
        missed = sum(int(v.get('missed', 0)) for v in hooks.values())
    print(json.dumps({
        'hit': hit, 'via': 'hook_heartbeat.json', 'path': _live_path(),
        'calls': calls, 'missed': missed, 'hooks': hooks}, ensure_ascii=False))


if __name__ == '__main__':
    if '--probe' in sys.argv:
        _probe(sys.argv)
    # 无参 fail-open：不记账，避免误调用污染账本
    sys.exit(0)
