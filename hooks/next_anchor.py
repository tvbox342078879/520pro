#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse 锚点钩子：Bash 调用前，把当前仓库上一轮提交的 `Next:` 打出来。

为什么要有：会话中途最容易忘的是「下一步是什么」。`verify.sh` 只在提交时打印，
中途没有任何必经点；`docs/钩子来源判定.md` 已实证平台支持 PreToolUse——
这是唯一能在「每个动作」粒度上带出锚点的位置。

铁律（三条，缺一条就不该装）：
  ① **永不拦截**：任何异常 / 非 Bash / 非 git 仓 → exit 0 静默，绝不挡工具调用；
  ② **节流**：同一仓库 15 分钟只提示一次，避免刷屏把上下文塞满；
  ③ **只读**：除自己的状态文件外不写任何东西。

定位仓库根的三级回退（2026-11-14 实测：Bash 工具 cwd 恒为 /workspace，
不随命令里的 cd 持久化；只认 payload.cwd 会让钩子在多仓工作区永久静默）：
  ① payload.cwd 自身是 git 仓 → 用它；
  ② 从 command 里解析最后一个 `cd <绝对路径>` / `git -C <绝对路径>` → 用它；
  ③ 都不中 → 用 state 里记的 last_repo（仅当它仍是 git 仓）。

状态文件：~/.codebuddy/hooks/.next_anchor_state
  {"repos": {仓库根: 最后打印时间}, "last_repo": 路径, "probe": 最后一次调用快照}
  旧版扁平格式 {仓库根: 时间} 读取时自动迁移。

自检：`python3 next_anchor.py --probe` 打印最后一次调用的 tool/cwd/root/via/hit，
用来区分「平台没调用钩子」与「调用了但没匹配上」——没有它，生效与否永远无法判定。
"""
import json
import os
import re
import subprocess
import sys
import time

STATE = os.path.expanduser('~/.codebuddy/hooks/.next_anchor_state')
THROTTLE_SEC = 15 * 60
MAX_STATE_KEYS = 50          # 状态文件有界，防无限增长
CMD_HEAD = 80                # probe 里只留命令开头，避免存整条长命令

EMPTY = {'repos': {}, 'last_repo': '', 'probe': {}}


def _read_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return dict(EMPTY)
    if not isinstance(d, dict):
        return dict(EMPTY)
    if 'repos' not in d:                                # 旧扁平格式迁移
        repos = {k: v for k, v in d.items() if isinstance(v, (int, float))}
        return {'repos': repos, 'last_repo': '', 'probe': {}}
    d.setdefault('repos', {})
    d.setdefault('last_repo', '')
    d.setdefault('probe', {})
    return d


def _write_state(d):
    try:
        repos = d.get('repos') or {}
        if len(repos) > MAX_STATE_KEYS:                 # 按时间留最近的
            keep = sorted(repos.items(), key=lambda kv: kv[1], reverse=True)[:MAX_STATE_KEYS]
            d['repos'] = dict(keep)
        tmp = STATE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        os.replace(tmp, STATE)                          # 原子替换（同 save_state 的做法）
    except Exception:
        pass


def _payload():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _repo_root(cwd):
    try:
        r = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _norm_abs(p):
    """只接受已存在的绝对路径（含 ~ 展开）。相对路径 / 命令替换 / 引号残留一律丢。"""
    p = (p or '').strip().strip('"').strip("'")
    if not p:
        return ''
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        return ''
    p = os.path.normpath(p)
    return p if os.path.isdir(p) else ''


def _cmd_candidates(command):
    """从命令文本里挖候选目录：cd 目标与 git -C 目标，取最后一次出现。"""
    if not command:
        return []
    out = []
    for pat in (r'(?<![\w.-])cd\s+([^\s;&|()]+)', r'\bgit\s+-C\s+([^\s;&|()]+)'):
        found = [_norm_abs(m) for m in re.findall(pat, command)]
        found = [p for p in found if p]
        if found:
            out.append(found[-1])
    return out


def _next_line(root):
    """取最近一条提交里以 Next: 开头的行（commit-msg 闸保证格式：做什么—起点—完成判据）。"""
    try:
        r = subprocess.run(['git', '-C', root, 'log', '-1', '--format=%B'],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith('Next: '):
                return line[6:].strip()
    except Exception:
        pass
    return ''


def _save(d, probe, hit=False):
    probe['hit'] = bool(hit)
    d['probe'] = probe
    _write_state(d)


def _resolve_root(d, cwd, command, probe):
    r = _repo_root(cwd)
    if r:
        probe['via'] = 'cwd'
        return r
    for cand in _cmd_candidates(command):
        r = _repo_root(cand)
        if r:
            probe['via'] = 'command'
            return r
    last = d.get('last_repo') or ''
    if last and os.path.isdir(last):
        r = _repo_root(last)
        if r:
            probe['via'] = 'last_repo'
            return r
    probe['via'] = 'none'
    return ''


def main():
    if '--probe' in sys.argv[1:]:
        p = _read_state().get('probe') or {}
        print(json.dumps(p, ensure_ascii=False, indent=2) if p else '（无调用记录）')
        return 0

    data = _payload()
    tool = data.get('tool_name') or data.get('toolName') or ''
    cwd = data.get('cwd') or data.get('workingDirectory') or os.getcwd()
    ti = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
    command = data.get('command') or ti.get('command') or ''

    d = _read_state()
    probe = {'ts': int(time.time()), 'tool': tool, 'cwd': cwd,
             'cmd': str(command)[:CMD_HEAD], 'root': '', 'via': 'none', 'hit': False}

    if tool and tool != 'Bash':                         # 只挂 Bash：Edit/Write 太频繁
        probe['via'] = 'skip-tool'
        _save(d, probe)
        return 0
    if not os.path.isdir(cwd):
        probe['via'] = 'bad-cwd'
        _save(d, probe)
        return 0

    root = _resolve_root(d, cwd, command, probe)
    probe['root'] = root
    if not root:
        _save(d, probe)
        return 0

    nxt = _next_line(root)
    if not nxt:
        probe['via'] += '+no-next'
        _save(d, probe)
        return 0
    if time.time() - float(d['repos'].get(root, 0) or 0) < THROTTLE_SEC:
        probe['via'] += '+throttled'
        _save(d, probe)
        return 0

    d['repos'][root] = time.time()
    d['last_repo'] = root
    _save(d, probe, hit=True)
    print('⏭ 上一轮 Next（%s）: %s' % (os.path.basename(root), nxt))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:                                   # 永不拦截：任何异常都放行
        sys.exit(0)
