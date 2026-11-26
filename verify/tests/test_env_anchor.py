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
# 起点仓 clone 原落在 artifact 产物区（易失，清理即失，本机曾被清空）——改用临时自足 fixture：
# 判据语义不变（env_anchor 从合法仓根读三字段身份），去掉对易失路径的机制依赖（S-02）。
with tempfile.TemporaryDirectory() as _origin_root:
    with open(os.path.join(_origin_root, 'ENV_ID.json'), 'w', encoding='utf-8') as _f:
        json.dump({'env_id': 'tvbox-eco-origin', 'role': '起点仓·规则策源',
                   'version': '1.0.0', 'repo': 'tvbox-eco'}, _f)
    for label, root in [
        ('520pro 源仓', ROOT),
        ('新生态', '/workspace/新生态'),
        ('起点仓(临时fixture)', _origin_root),
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

print('── 非 git 工作区：带 ENV_ID.json 的目录作合法 root + 读 PROGRESS.md 锚点（防「看不了进度」回归）──')
with tempfile.TemporaryDirectory() as _ng:
    with open(os.path.join(_ng, 'ENV_ID.json'), 'w', encoding='utf-8') as _f:
        json.dump({'env_id': 'netdisk-app-dev', 'role': '网盘助手', 'version': 'P0.39'}, _f)
    with open(os.path.join(_ng, 'PROGRESS.md'), 'w', encoding='utf-8') as _f:
        _f.write('# 进度\n\n## 下一步\nNext: 真机验证12平台APK — 起点：d19a696b — 完成判据：用户截图确认\n')
    _p = {'via': 'none'}
    _root = na._resolve_root({}, _ng, '', _p)
    ck('非git仓+身份锚→cwd-env定位', _root == os.path.normpath(_ng) and _p.get('via') == 'cwd-env', _p)
    ck('非git仓未打unaligned', _p.get('unaligned') is not True, _p)
    _line = na._next_line(_root)
    ck('非git仓读PROGRESS.md的Next', '真机验证12平台APK' in _line, _line)
    with tempfile.TemporaryDirectory() as _empty:
        _p2 = {'via': 'none'}
        na._resolve_root({}, _empty, '', _p2)
        ck('无身份锚仍落none不误认', _p2.get('via') == 'none', _p2)

print('── 容器根回退：cwd=/workspace 类容器扫一级子目录定位非 git 工作区（防「看不了进度」二次回归）──')
with tempfile.TemporaryDirectory() as _container:
    # 候选1：非 git + ENV_ID + PROGRESS.md（netdisk-app 型，三级回退唯一漏掉的类型）
    _app = os.path.join(_container, 'netdisk-app')
    os.mkdir(_app)
    with open(os.path.join(_app, 'ENV_ID.json'), 'w', encoding='utf-8') as _f:
        json.dump({'env_id': 'netdisk-app-dev', 'role': '网盘助手', 'version': 'P0.39'}, _f)
    with open(os.path.join(_app, 'PROGRESS.md'), 'w', encoding='utf-8') as _f:
        _f.write('## 下一步\nNext: 容器根真机验证12平台APK — 起点：d19a696b — 完成判据：截图确认\n')
    # 候选2：git 仓 + ENV_ID，无 PROGRESS（520pro 型，须被此级跳过——进度走 commit）
    _gitrepo = os.path.join(_container, '520pro')
    os.mkdir(_gitrepo)
    subprocess.run(['git', 'init', '-q', _gitrepo], check=True)
    with open(os.path.join(_gitrepo, 'ENV_ID.json'), 'w', encoding='utf-8') as _f:
        json.dump({'env_id': '520pro-main', 'role': '源仓', 'version': '0.8.89'}, _f)
    _p3 = {'via': 'none'}
    _root3 = na._resolve_root({}, _container, '', _p3)
    ck('容器根定位到非git工作区', _root3 == os.path.normpath(_app) and _p3.get('via') == 'cwd-child-progress', _p3)
    ck('容器根命中未打unaligned', _p3.get('unaligned') is not True, _p3)
    ck('容器根读到PROGRESS锚点', '容器根真机验证12平台APK' in na._next_line(_root3), na._next_line(_root3))
    # 多命中：再加一个非 git+ENV_ID+PROGRESS 子目录 → 打歧义标记，不臆测
    _app2 = os.path.join(_container, 'other-app')
    os.mkdir(_app2)
    with open(os.path.join(_app2, 'ENV_ID.json'), 'w', encoding='utf-8') as _f:
        json.dump({'env_id': 'other-dev', 'role': '其他', 'version': '1.0'}, _f)
    with open(os.path.join(_app2, 'PROGRESS.md'), 'w', encoding='utf-8') as _f:
        _f.write('Next: 别的进度\n')
    _p4 = {'via': 'none'}
    na._resolve_root({}, _container, '', _p4)
    ck('多命中打child_ambiguous不臆测', len(_p4.get('child_ambiguous', [])) == 2 and _p4.get('via') != 'cwd-child-progress', _p4)

print('── 单元：last_repo 回退打标（纯函数级）──')
_saved = na._read_state()
_probe = {'via': 'none'}
try:
    with tempfile.TemporaryDirectory() as _empty2:
        na._resolve_root({'last_repo': ROOT}, _empty2, '', _probe)
    # 空目录非仓、command 空 → 落到 last_repo 分支
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
# 活场景（本轮实证用户对话 cwd=/workspace）：应注入 netdisk-app 的进度锚点，
# 不是 520pro 的「推送两笔」，且不打「身份未对齐」。
if os.path.isdir('/workspace/netdisk-app'):
    ctx3, rc3 = run_hook('UserPromptSubmit', '/workspace')
    ck('容器根/workspace 注入netdisk-app进度', '真机验证' in ctx3 and 'netdisk-app' in ctx3, ctx3[:300])
    ck('容器根/workspace 不再串520pro推送', '推送' not in ctx3.split('下一步')[0][:200], ctx3[:200])
    ck('容器根/workspace 不打身份未对齐', '身份未对齐' not in ctx3, ctx3[:300])

print('\n结果：%s' % ('全部通过' if not fails else str(len(fails)) + ' 项失败：' + ','.join(fails)))
sys.exit(0 if not fails else 2)
