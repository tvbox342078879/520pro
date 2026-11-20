#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parallel_guard.py — B-04「并行纪律」执行层：能并行的必须并行，不许一条一条等。

## 来源与适配（实证，非照搬）
判据与拦截逻辑移植自另一环境的 parallel_guard.py（实测文档见资料库
`机制_1120_并行实现与源码实测.md`，node LG1GY8VbjVAEW8T8xc18AM）：
  · 判据从「时间窗猜」改为「transcript 里数 messageId 实数」——同批并发共享同一 messageId；
    实测 conversationRequestId 虚高 94.5%、generation_id 零区分度、messageId 4.2% 为真判据。
  · BLOCK_LADDER 累进收紧（只清零不累计 → 193 次全停在阈值 5，等于门没牙）。
  · 两类依赖豁免（写后跑 / 读上一步输出），避免合法串行被误伤（M-R113 噪音化）。

## 520 特有适配（关键差异，别丢）
1. **state 按 session_id 隔离**：原版用固定路径 `.parallel_state.json`，520 是多会话环境，
   多会话共写会互相清零（病15：识别范围≠对象范围）。本版按 sid 分文件。
2. **session_id 取自 PreToolUse payload**（实测 payload 含 session_id，见本仓探针记录）；
   取不到落 'default'，不猜、不拦。
3. **hook_heartbeat 为 noop**：520 当前无心跳账，`_beat` 保留接口但静默失败；
   将来接心跳账时无需改判据逻辑。

## 放行（fail-open，钩子永不阻塞调用方）
  · PARALLEL_GUARD_OFF=1 / CODEBUDDY_SESSION_TYPE=automation
  · 读不到 transcript / 找不到当前批次 → unknown 放行（取不到 ≠ 违规）
  · 非阻塞锁：拿不到锁跳过本轮统计，绝不阻塞
  · 工具不在 CONCURRENCY_SAFE（Edit/Write 等有写冲突风险）→ 不拦（但仍参与计数）

# impl: B-04 S1   ← PreToolUse·Bash 已注册（C 步）；messageId 实数判单发 + 会话隔离 + 依赖豁免
"""
import fcntl
import json
import os
import re
import sys
import time

THRESHOLD = 5            # 连续 5 批单发 → 拦
TAIL_BYTES = 256 * 1024  # 只读 transcript 尾部这么多字节
BLOCK_LADDER = 2         # 每被拦一次，阈值降这么多
MIN_THRESHOLD = 2        # 阈值下限
STATE_DIR = os.environ.get('PARALLEL_STATE_DIR') or '/root/.codebuddy/hooks'
CONCURRENCY_SAFE = {'Bash', 'Read', 'Glob', 'Grep', 'WebFetch', 'WebSearch',
                    'TaskGet', 'TaskList'}


def _threshold_for(blocks):
    """按已拦次数算出本次应使用的阈值。"""
    return max(MIN_THRESHOLD, THRESHOLD - BLOCK_LADDER * int(blocks or 0))


def _state_for(sid):
    """state 按会话隔离：单测可用 PARALLEL_STATE 覆盖，生产按 sid 分文件。"""
    override = os.environ.get('PARALLEL_STATE')
    if override:
        return override
    safe = re.sub(r'[^A-Za-z0-9_-]', '', str(sid))[-40:] or 'default'
    return os.path.join(STATE_DIR, '.parallel_state_%s.json' % safe)


def _load(state):
    try:
        return json.load(open(state, encoding='utf-8'))
    except Exception:
        return {'solo': 0, 'mid': ''}


def _save(state, d):
    try:
        tmp = state + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, state)
    except Exception:
        pass


def _tail_records(path, max_bytes=TAIL_BYTES):
    """读 JSONL 尾部，返回可解析记录列表（顺序为文件顺序）。只读尾部，丢截断首行。"""
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            raw = f.read().decode('utf-8', 'ignore')
    except Exception:
        return []
    lines = raw.split('\n')
    if start > 0:
        lines = lines[1:]
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith('{'):
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _is_dependent_chain(recs):
    """本条 Bash 读取上一条命令刚写过的文件 → 合法串行（依赖链），不记 solo。"""
    try:
        fcs = [r for r in recs if r.get('type') == 'function_call']
        if len(fcs) < 2:
            return False
        cur = fcs[-1]
        if cur.get('name') != 'Bash':
            return False
        try:
            cmd = str(json.loads(cur.get('arguments') or '{}').get('command') or '')
        except Exception:
            return False
        if not cmd:
            return False
        prev = fcs[-2]
        written = []
        try:
            prev_args = json.loads(prev.get('arguments') or '{}')
        except Exception:
            prev_args = {}
        if prev.get('name') in ('Write', 'Edit', 'MultiEdit'):
            fp = str(prev_args.get('file_path') or '')
            if fp:
                written.append(fp)
        elif prev.get('name') == 'Bash':
            pcmd = str(prev_args.get('command') or '')
            written += re.findall(r'>{1,2}\s*([^\s;|&]+)', pcmd)
            written += re.findall(r'(?:-o|--output)[\s=]+([^\s;|&]+)', pcmd)
        for fp in written:
            fp = fp.strip().strip('"\'')
            if not fp or len(fp) < 4:
                continue
            base = os.path.basename(fp)
            if fp in cmd or (len(base) >= 4 and base in cmd):
                return True
        return False
    except Exception:
        return False


def _is_write_run_chain(recs):
    """当前批唯一调用是 Bash，且命令引用最近一次 Write/Edit 的文件 → 写后跑链，不记 solo。"""
    try:
        fcs = [r for r in recs if r.get('type') == 'function_call']
        if len(fcs) < 2:
            return False
        cur = fcs[-1]
        if cur.get('name') != 'Bash':
            return False
        try:
            cmd = str(json.loads(cur.get('arguments') or '{}').get('command') or '')
        except Exception:
            return False
        if not cmd:
            return False
        for r in reversed(fcs[:-1]):
            if r.get('name') in ('Write', 'Edit'):
                try:
                    fp = str(json.loads(r.get('arguments') or '{}').get('file_path') or '')
                except Exception:
                    return False
                if not fp:
                    return False
                base = os.path.basename(fp)
                return base in cmd or fp in cmd
        return False
    except Exception:
        return False


def _current_batch(path):
    """从 transcript 找「当前这一批」的调用数 → (messageId, 本批调用数)。取不到 → (None, 0)。"""
    recs = _tail_records(path)
    if not recs:
        return None, 0
    last_mid = None
    for d in reversed(recs):
        if d.get('type') == 'function_call':
            last_mid = ((d.get('providerData') or {}).get('messageId'))
            break
    if not last_mid:
        return None, 0
    n = 0
    for d in recs:
        if d.get('type') != 'function_call':
            continue
        if ((d.get('providerData') or {}).get('messageId')) == last_mid:
            n += 1
    return last_mid, n


def _beat(payload=None, blocked=False, missed=False):
    """可观测性钩子：写心跳账（v0.8.89 填实，原 noop）。

    import 失败 / 账本写失败一律静默——心跳账是可观测性，绝不能反噬拦截主逻辑。
    """
    try:
        import hook_heartbeat
        hook_heartbeat.beat_from_payload(payload, 'parallel_guard.py',
                                         blocked=blocked, missed=missed)
    except Exception:
        pass


def main():
    # --probe（病13 观测要件）：报本会话并行闸实况——hit=是否真拦过(blocks>0)，
    # via=判定来源(state 路径 + messageId 判据)。让"闸到底生效没有"可自证，
    # 不靠"装了脚本"这种口头承诺。无 state 时 hit=false，三态分清（没拦过≠没生效，
    # 需配合 via 指向的 state 是否在更新判断）。
    if '--probe' in sys.argv:
        probe_sid = 'default'
        if '--sid' in sys.argv:
            try:
                probe_sid = sys.argv[sys.argv.index('--sid') + 1]
            except (IndexError, ValueError):
                pass
        ps = _state_for(probe_sid)
        pd = _load(ps)
        print(json.dumps({
            'event': 'PreToolUse/Bash',
            'hit': int(pd.get('blocks') or 0) > 0,
            'via': 'transcript.messageId + state:' + ps,
            'solo': int(pd.get('solo') or 0),
            'blocks': int(pd.get('blocks') or 0),
            'mid': pd.get('mid', ''),
        }, ensure_ascii=False))
        return 0
    if os.environ.get('PARALLEL_GUARD_OFF') == '1':
        return 0
    if os.environ.get('CODEBUDDY_SESSION_TYPE') == 'automation':
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get('tool_name') or ''
    tp = payload.get('transcript_path') or ''
    sid = payload.get('session_id') or 'default'
    state = _state_for(sid)
    lock = state + '.lock'

    # 非阻塞锁：拿不到就放行（绝不阻塞调用方）
    lf = None
    locked = False
    try:
        lf = open(lock, 'a+')
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
    except Exception:
        locked = False

    hit = False
    solo = 0
    _blocks_now = 0
    if locked:
        try:
            d = _load(state)
            mid, n = _current_batch(tp) if tp else (None, 0)
            prev_mid = d.get('mid') or ''

            # 新批且单条：先判依赖豁免，命中则合法串行放行
            if mid and mid != prev_mid and n == 1:
                if _is_write_run_chain(_tail_records(tp) if tp else []) or \
                        _is_dependent_chain(_tail_records(tp) if tp else []):
                    d['mid'] = mid
                    _save(state, d)
                    return 0

            if mid and mid == prev_mid:
                pass                      # 同一批后续调用，不重复记账
            elif mid:
                if n >= 2:
                    d['solo'] = 0         # 并行 → 打断惯性
                    d['blocks'] = max(0, int(d.get('blocks') or 0) - 1)  # 退一格，不清零
                else:
                    d['solo'] = int(d.get('solo') or 0) + 1
                d['mid'] = mid
            # mid 为空（transcript 读不到）→ 不猜、不记账、不拦

            solo = int(d.get('solo') or 0)
            thr = _threshold_for(d.get('blocks'))
            hit = solo >= thr and tool in CONCURRENCY_SAFE
            if hit:
                d['solo'] = 0
                d['blocks'] = int(d.get('blocks') or 0) + 1
                d['last_block_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
                _blocks_now = d['blocks']
            _save(state, d)
        finally:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
                lf.close()
            except Exception:
                pass
    elif lf:
        try:
            lf.close()
        except Exception:
            pass

    if hit:
        print('🛑 拦截：已经连续 %d 批「只发一个工具调用、等回来、再发一个」.' % solo,
              file=sys.stderr)
        print('   B-04：能并行的必须并行；判断标准——后一条参数是否依赖前一条输出？',
              file=sys.stderr)
        print('   判据：transcript 的 messageId 实数（不用时间窗猜）', file=sys.stderr)
        if _blocks_now >= 2:
            print('   ⚠️ 本轮第 %d 次被拦——阈值已收紧到 %d 批（下限 %d）.'
                  % (_blocks_now, _threshold_for(_blocks_now), MIN_THRESHOLD), file=sys.stderr)
        print('   ① 挑出「参数不依赖前一步输出」的动作；', file=sys.stderr)
        print('   ② 下一条消息里一次性并发发出（同一消息多个工具调用块）。', file=sys.stderr)
        _beat(payload, True)
        return 2
    _beat(payload)
    return 0


if __name__ == '__main__':
    sys.exit(main())
