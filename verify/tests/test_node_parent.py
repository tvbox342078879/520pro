#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_node_parent 反查优先级 · 回归测试（工程G-2）

跑法：python3 verify/tests/test_node_parent.py
退出码：0 全过 / 2 有失败

为什么测这条：它只被 cmd_move 用（记录移动前原父位），但错了会让
「已在收件箱」被读成「不在箱」——2026-11-12 投两个测试库时实测踩到：
add 报成功、回读说不符，差点当成移动失败去重试（而重试 = 撞 B-10 的"换个写法重试同一道闸"）。
根因是 database 类型节点不在 root 的子节点枚举链上，全树遍历恒查不到。
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, '通用层', 'skills', 'space-hub', 'scripts'))
import space_hub as S  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print(('  ✓ ' if ok else '  ✗ ') + name + ('' if ok else f'（期望 {want!r}，实得 {got!r}）'))
    if not ok:
        fails.append(name)


def fake_space(parent_id, boom=False):
    def _f(api, **kw):
        if boom:
            raise RuntimeError('接口炸了')
        return {'data': {'node': {'id': kw.get('node_id'), 'parentId': parent_id}}}
    return _f


orig_space, orig_find = S._space, S._find_parent
try:
    print('【①】node-info 有 parentId → 用它，且不打扰遍历')
    S._space = fake_space('INBOX_ID')
    S._find_parent = lambda nid, skip_inbox=True: (_ for _ in ()).throw(AssertionError('不该走到遍历'))
    check('parentId 优先', S._node_parent('X'), 'INBOX_ID')

    print('【②】node-info 无 parentId（None/空）→ 退回遍历')
    S._space = fake_space(None)
    S._find_parent = lambda nid, skip_inbox=True: 'WALKED'
    check('空值退回遍历', S._node_parent('X'), 'WALKED')

    print('【③】node-info 炸了 → 仍退回遍历（不许整体崩）')
    S._space = fake_space(None, boom=True)
    check('异常退回遍历', S._node_parent('X'), 'WALKED')

    print('【④】两边都查不到 → 返回空串（调用方须显式报，不许当"根"）')
    S._find_parent = lambda nid, skip_inbox=True: ''
    check('都查不到返回空串', S._node_parent('X'), '')

    print('【⑤】遍历抛异常 → 也要返回空串而不是把异常抛给调用方')
    S._find_parent = lambda nid, skip_inbox=True: (_ for _ in ()).throw(RuntimeError('boom'))
    check('遍历异常不冒泡', S._node_parent('X'), '')
finally:
    S._space, S._find_parent = orig_space, orig_find

print('【⑥】还原后真接口仍可用（有网才跑，没网记无法判定）')
try:
    p = S._node_parent('WEDPaX82ZnTFOzyQlzu2QW')
    if p:
        check('真接口返回非空父节点', bool(p), True)
    else:
        print('  · 无法判定：真接口返回空（沙箱无网或节点已变），不计入通过')
except Exception as e:
    print(f'  · 无法判定：{e!r}')

print()
if fails:
    print(f'✗ {len(fails)} 项失败：' + '、'.join(fails))
    sys.exit(2)
print('✓ _node_parent 回归全过')
