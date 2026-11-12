#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程E 正反向测试：space_hub 拒收契约（不联网，全 mock）"""
import io
import json
import os
import sys
import types
import contextlib

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, '通用层', 'skills', 'space-hub', 'scripts'))
import space_hub as s  # noqa: E402

FAIL = []
PASS = []


def run(node_title, kids, force=False, reason='', move_ok=True):
    """跑一次 cmd_add，返回 (rc, stdout)"""
    s.load_state = lambda: {'inbox': 'INBOX', 'items': [], 'audit': []}
    s.save_state = lambda d: None
    s._audit_force = lambda *a: None
    s._find_parent = lambda nid: 'ORIGIN'
    s._kids = lambda nid: kids
    s._space = lambda method, **kw: (
        {'data': {'node': {'title': node_title, 'kind': 'folder', 'id': kw.get('node_id')}}}
        if method.endswith('node-info') else ({'data': {}} if move_ok else {'error': 'boom'}))
    a = types.SimpleNamespace(node='X1', reason=reason, force=force)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = s.cmd_add(a)
    return rc, buf.getvalue()


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + detail))


def payload_of(out):
    for line in out.splitlines():
        if line.strip().startswith('↳ '):
            return json.loads(line.strip()[2:])
    return None


print('【1】非空容器 → 拒收 + 三元组')
rc, out = run('普通夹', [{'id': 'a'}, {'id': 'b'}])
p = payload_of(out)
check('rc=4', rc == 4, f'rc={rc}')
check('error=guard_nonempty_container', (p or {}).get('error') == 'guard_nonempty_container', str(p))
check('四字段齐全', bool(p) and all(k in p and p[k] for k in ('error', 'reason', 'target', 'method')), str(p))

print('【2】空夹但名字像库 → 不同机器码（可分支）')
rc, out = run('数据源总库', [])
p2 = payload_of(out)
check('rc=4', rc == 4, f'rc={rc}')
check('error=guard_container_like_name', (p2 or {}).get('error') == 'guard_container_like_name', str(p2))
check('target 指向 classify 备选', 'classify' in (p2 or {}).get('method', ''), str(p2))

print('【3】正常情况下不误拦')
rc, out = run('一份旧报告.md', [])
check('rc=0', rc == 0, f'rc={rc}')
check('无拒收 JSON', payload_of(out) is None, out)

print('【4】失败路径也带机器码')
rc, out = run('一份旧报告.md', [], move_ok=False)
p4 = payload_of(out)
check('rc=3（登记但未移动）', rc == 3, f'rc={rc}')
check('error=move_rejected', (p4 or {}).get('error') == 'move_rejected', str(p4))

print('\n结果：%d ✓ / %d ✗' % (len(PASS), len(FAIL)))
sys.exit(0 if not FAIL else 1)
