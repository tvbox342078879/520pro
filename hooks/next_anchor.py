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

状态文件：~/.codebuddy/hooks/.next_anchor_state（JSON: {仓库根: 最后打印时间}）
"""
import json
import os
import subprocess
import sys
import time

STATE = os.path.expanduser('~/.codebuddy/hooks/.next_anchor_state')
THROTTLE_SEC = 15 * 60
MAX_STATE_KEYS = 50          # 状态文件有界，防无限增长


def _read_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_state(d):
    try:
        if len(d) > MAX_STATE_KEYS:                     # 按时间留最近的
            keep = sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:MAX_STATE_KEYS]
            d = dict(keep)
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


def main():
    data = _payload()
    tool = data.get('tool_name') or data.get('toolName') or ''
    if tool and tool != 'Bash':                         # 只挂 Bash：Edit/Write 太频繁
        return 0
    cwd = data.get('cwd') or data.get('workingDirectory') or os.getcwd()
    if not os.path.isdir(cwd):
        return 0
    root = _repo_root(cwd)
    if not root:
        return 0
    nxt = _next_line(root)
    if not nxt:
        return 0
    st = _read_state()
    if time.time() - float(st.get(root, 0) or 0) < THROTTLE_SEC:
        return 0
    st[root] = time.time()
    _write_state(st)
    print('⏭ 上一轮 Next: ' + nxt)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:                                   # 永不拦截：任何异常都放行
        sys.exit(0)
