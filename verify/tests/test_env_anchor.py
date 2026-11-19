#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据 L1 环境身份锚：next_anchor.env_anchor 读真 ENV_ID.json + 注入接线。

病15 防线：判据对象=真函数读真文件 + 真跑 hook 子进程看 additionalContext，
不查源码字符串存在（"env_id 字样在文件里"不算数）。
三元变异：去 env_anchor 函数 / 去注入接线 / 去回退打标，各自判据须转红。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(ROOT, 'hooks', 'next_anchor.py')

spec = importlib.util.spec_from_file_location('next_anchor', ENGINE)
na = importlib.util.module_from_spec(spec)
spec.loader.exec_module(na)

fails = []


def ck(label, cond, detail=''):
    ok = bool(cond)
    print(('  ✓ ' if ok else '  ✗ ') + label + ('' if ok else '  ← ' + str(detail)))
    if not ok:
        fails.append(label)


print('── 正向：真函数读真仓 ENV_ID.json ──')
for label, root in [
    ('520pro 源仓', ROOT),
    ('新生态', '/workspace/新生态'),
    ('tvbox-eco 起点仓', '/root/.codebuddy/artifact/2f8a7d30-9c21-4f0b-1d64-1139ab417000/tvbox-eco'),
]:
    a = na.env_anchor(root)
    ck(label + ' 读出身份', bool(a) and a.get('env_id', '').endswith(('main', 'dev', 'origin')),
       a)
    if a:
        ck(label + ' 三字段齐全', all(a.get(k) for k in ('env_id', 'role', 'version')), a)
        ck(label + ' 自报句含 env_id', a['env_id'] in na.env_anchor_line(a))

print('── 反向：缺失/损坏/字段不全一律 None（不伪造身份）──')
with tempfile.TemporaryDirectory() as td:
    ck('空目录返回 None', na.env_anchor(td) is None)
    with open(os.path.join(td, 'ENV_ID.json'), 'w') as f:
        f.write('not json{')
    ck('损坏 JSON 返回 None', na.env_anchor(td) is None)
    with open(os.path.join(td, 'ENV_ID.json'), 'w') as f:
        json.dump({'env_id': 'x', 'role': 'y'}, f)
    ck('缺 version 返回 None', na.env_anchor(td) is None)
    with open(os.path.join(td, 'ENV_ID.json'), 'w') as f:
        json.dump({'env_id': '  ', 'role': 'y', 'version': 'z'}, f)
    ck('空 env_id 返回 None', na.env_anchor(td) is None)
    with open(os.path.join(td, 'ENV_ID.json'), 'w') as f:
        json.dump(['not', 'dict'], f)
    ck('非 dict 返回 None', na.env_anchor(td) is None)
ck('env_anchor_line(None) 返回空串', na.env_anchor_line(None) == '')

print('── 单元：last_repo 回退打标（纯函数级）──')
_saved = na._read_state()
_probe = {'via': 'none'}
try:
    na._resolve_root({'last_repo': ROOT}, '/tmp', '', _probe)
    # /tmp 非仓、command 空 → 落到 last_repo 分支
    ck('回退命中打 unaligned', _probe.get('via') == 'last_repo' and _probe.get('unaligned') is True,
       _probe)
finally:
    if 'unaligned' in na.__dict__:
        pass

print('── 端到端：真跑 hook 看注入接线（防「函数对/没接线」假绿）──')


def run_hook(event, cwd):
    payload = json.dumps({'hook_event_name': event, 'prompt': '继续', 'cwd': cwd},
                         ensure_ascii=False)
    try:
        p = subprocess.run([sys.executable, ENGINE], input=payload, text=True,
                           capture_output=True, timeout=30, cwd=cwd)
        out = json.loads(p.stdout)
        return out.get('hookSpecificOutput', {}).get('additionalContext', ''), p.returncode
    except Exception as e:
        return '__ERR__' + str(e), -1


# SessionStart：根目录传本仓（git 仓），应注入 handoff 段 + 身份自报
ctx, rc = run_hook('SessionStart', ROOT)
ck('SessionStart 注入身份自报', '🪪 环境身份' in ctx and '520pro-main' in ctx, ctx[:200])
ck('SessionStart rc=0', rc == 0, rc)
# UserPromptSubmit：本仓有 Next（HEAD commit 带 Next:），应注入锚点 + 身份
ctx2, rc2 = run_hook('UserPromptSubmit', ROOT)
ck('UserPromptSubmit 注入身份自报', '🪪 环境身份' in ctx2 and '520pro-main' in ctx2, ctx2[:200])
ck('UserPromptSubmit rc=0', rc2 == 0, rc2)

print('\n结果：%s' % ('全部通过' if not fails else str(len(fails)) + ' 项失败：' + ','.join(fails)))
sys.exit(0 if not fails else 2)
