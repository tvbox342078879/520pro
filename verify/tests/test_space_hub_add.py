#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cmd_add「回执≠回读」闭环 · 回归测试（2026-11-13 空间重置实战教训）

跑法：python3 verify/tests/test_space_hub_add.py
退出码：0 全过 / 2 有失败

为什么测这三条（实战实锤，不是假想）：
  ① 幂等短路无回读——第一轮投递全败（收件箱夹被删，服务端 12607），
    失败项也进了登记册；重建收件箱后重投 49 项全部撞旧短路 return 0，
    回执「成功 32」、回读落地 0。修法：命中后回读核实，过期记录清掉放行重投。
  ② 移动回执成功 ≠ 落地——add 一直只看回执，cmd_move 早有 readback_mismatch
    先例却没对齐。修法：回执成功后回读收件箱一层，确有节点才算真落地。
  ③ 分页截断——服务端单页实测上限 50，_nodes_or_none 单页读 >单页容器漏读
    （顶层 130 项实测漏 81 项）。修法：offset 翻页到底，「失败→None」语义不变。
"""
import argparse
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, '通用层', 'skills', 'space-hub', 'scripts'))
import space_hub as S  # noqa: E402

fails = []
INBOX = 'INBOX_ID'
NODE = 'NODE_ID'


def check(name, got, want):
    ok = got == want
    print(('  ✓ ' if ok else '  ✗ ') + name + ('' if ok else f'（期望 {want!r}，实得 {got!r}）'))
    if not ok:
        fails.append(name)


def make_state(items):
    """临时登记册（load_state/save_state 全走 S.STATE）。"""
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    json.dump({'inbox': INBOX, 'items': items}, open(path, 'w', encoding='utf-8'))
    return path


def mock_space(landing, move_error=None, top_pages=None):
    """按 api 分发的 _space 替身。

    landing=True：move-node 回执成功时自动把 NODE 加进收件箱一层（模拟真实落地），
                  落地回读才能看到它；landing=False 模拟「回执成功但没落地」。
    top_pages：list-nodes parent='' 的分页序列 [(page, hasMore), ...]。
    """
    calls = {'move': 0, 'top_page': 0, 'inbox_read': 0}
    state = {'inbox_kids': []}

    def _f(api, **kw):
        if api == 'space.workspace.node-info':
            return {'data': {'node': {'id': kw.get('node_id'), 'title': '测试节点', 'kind': 'doc'}}}
        if api == 'space.workspace.move-node':
            calls['move'] += 1
            if move_error:
                return {'error': move_error}
            if landing:
                state['inbox_kids'] = [{'id': kw.get('node_id'), 'kind': 'doc', 'title': '测试节点'}]
            return {'data': {'status': 'done'}}
        if api == 'space.workspace.list-nodes':
            if kw.get('parent_node_id') == INBOX:
                calls['inbox_read'] += 1
                return {'data': {'nodes': state['inbox_kids'], 'hasMore': False}}
            if top_pages is not None and kw.get('parent_node_id') == '':
                i = min(calls['top_page'], len(top_pages) - 1)
                calls['top_page'] += 1
                pages, more = top_pages[i]
                return {'data': {'nodes': pages, 'hasMore': more}}
            return {'data': {'nodes': [], 'hasMore': False}}
        return {'error': f'unexpected api {api}'}

    return _f, calls


def run_add(state_items, landing=True, move_error=None, top_pages=None, force=True):
    """跑一次 cmd_add，返回 (rc, calls, state_dict)。state 先读后删（写后回读的账本为准）。"""
    path = make_state(state_items)
    old_state, old_space, old_audit = S.STATE, S._space, S._audit_force
    S.STATE = path
    S._space, calls = mock_space(landing, move_error, top_pages)
    S._audit_force = lambda *a, **k: None
    try:
        rc = S.cmd_add(argparse.Namespace(node=NODE, reason='测试', force=force))
        st = json.load(open(path, encoding='utf-8'))
    finally:
        S.STATE, S._space, S._audit_force = old_state, old_space, old_audit
        if os.path.exists(path):
            os.unlink(path)
    return rc, calls, st


def main():
    ok_node = {'id': NODE, 'kind': 'doc', 'title': '测试节点'}

    print('【T1】分页：_nodes_or_none / _kids 翻页收全（>单页容器不漏）')
    page1 = [{'id': f'p1-{i}', 'kind': 'doc', 'title': f'n{i}'} for i in range(50)]
    page2 = [{'id': f'p2-{i}', 'kind': 'doc', 'title': f'm{i}'} for i in range(30)]
    old_space = S._space
    S._space, _, = mock_space(False, top_pages=[(page1, True), (page2, False)])
    try:
        got_none = S._nodes_or_none('')
    finally:
        S._space = old_space
    S._space, _ = mock_space(False, top_pages=[(page1, True), (page2, False)])
    try:
        got_kids = S._kids('')
    finally:
        S._space = old_space
    check('_nodes_or_none 收全 80 项', len(got_none or []), 80)
    check('_kids 收全 80 项', len(got_kids), 80)

    print('【T2】幂等命中但登记册过期（记录在、节点不在收件箱）→ 必须重投，不许 return 0')
    rc, calls, st = run_add([{'id': NODE, 'title': '旧记录', 'moved': False}], landing=True)
    check('过期登记 → 重投（move 被调用 1 次）', calls['move'], 1)
    check('重投后 rc=0（落地成功）', rc, 0)
    check('登记册已刷新为落地成功', (st['items'] or [{}])[0].get('moved'), True)

    print('【T3】真幂等（记录在、节点确在收件箱一层）→ return 0 且不再 move')
    calls = {'move': 0, 'inbox_read': 0}
    def _f3(api, **kw):
        if api == 'space.workspace.node-info':
            return {'data': {'node': {'id': NODE, 'title': '测试节点', 'kind': 'doc'}}}
        if api == 'space.workspace.move-node':
            calls['move'] += 1
            return {'data': {'status': 'done'}}
        if api == 'space.workspace.list-nodes' and kw.get('parent_node_id') == INBOX:
            calls['inbox_read'] += 1
            return {'data': {'nodes': [ok_node], 'hasMore': False}}
        return {'data': {'nodes': [], 'hasMore': False}}
    path = make_state([{'id': NODE, 'title': '已在箱', 'moved': True}])
    old_state, old_space, old_audit = S.STATE, S._space, S._audit_force
    S.STATE = path
    S._space = _f3
    S._audit_force = lambda *a, **k: None
    try:
        rc = S.cmd_add(argparse.Namespace(node=NODE, reason='测试', force=True))
        st = json.load(open(path, encoding='utf-8'))
    finally:
        S.STATE, S._space, S._audit_force = old_state, old_space, old_audit
        if os.path.exists(path):
            os.unlink(path)
    check('真幂等不再 move', calls['move'], 0)
    check('真幂等核实调用了收件箱回读', calls['inbox_read'], 1)
    check('真幂等 rc=0', rc, 0)
    check('原登记保留不动', len(st['items']), 1)

    print('【T4】移动回执成功但回读未落地 → 不当作成功（moved=False / rc=3）')
    rc, calls, st = run_add([], landing=False, move_error=None)
    check('回执成功但未落地 → rc=3', rc, 3)
    check('登记 moved=False', (st['items'] or [{}])[0].get('moved'), False)

    print('【T5】移动回执成功且回读落地 → 真成功（moved=True / rc=0）')
    rc, calls, st = run_add([], landing=True, move_error=None)
    check('回执+回读双确认 → rc=0', rc, 0)
    check('登记 moved=True', (st['items'] or [{}])[0].get('moved'), True)

    print('【T6】失败→None 语义不塌：_nodes_or_none 接口炸了返回 None（区别于真·空 []）')
    old_space = S._space
    def _boom(api, **kw):
        return {'error': 'boom'}
    S._space = _boom
    try:
        got = S._nodes_or_none('')
    finally:
        S._space = old_space
    check('接口失败 → None（不是 []）', got is None, True)

    print()
    if fails:
        print(f'✗ {len(fails)} 项失败：' + '、'.join(fails))
        sys.exit(2)
    print('✓ cmd_add「回执≠回读」回归全过')


if __name__ == '__main__':
    main()
