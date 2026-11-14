#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程F-4 检查：交接摘要三项齐全 + 版本不过期

判据（B-07 的执行面）：
  ① 文件存在；
  ② 三个必载段齐全（当前主线 / 版本与位置 / 习惯快照指针）——缺一项就等于"只知道在哪、不知道在干啥"；
  ③ 写的版本号 == VERSION（**过期即红**：交接摘要写着旧版本，接手的人会按旧口径干活）；
  ④ 在 git 仓内时，"当前主线自检口径"那句还在（提醒接手的人先跑 verify）；
  ⑤ 账目三齐（B-14，v0.8.22 工程J）：待办账目段每条必须有 owner/next/due，
     且段内不得出现"待跟进/后续优化/有空再说"这类无主无期措辞——
     为什么查这个：交接最贵的成本不是"不知道版本"，是"看到一条没人认领的待办"。

只查"是否过期/是否缺项"，不查文字质量——那机器判不了（三态不标注就是骗自己）。
用法：python3 verify/tests/test_handoff.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
H = os.path.join(REPO, 'docs', 'handoff_latest.md')
FAIL, PASS = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + detail))


LEDGER_HEAD = '## 4. 待办账目'
BAN_WORDS = ('待跟进', '后续优化', '有空再说', '以后再说')

# B-07 的"接手动作"要落在三通道上：只写在 core-8 里，手机端（不读项目薄壳）就看不到；
# 只写在手机指令里，桌面/云端会话又不会读它。三处缺一，就有一种会话形态拿不到这个动作。
CHANNELS = (
    ('通用层/rules/core-8.md', 'core-8 真源'),
    ('能力层/tvbox/CODEBUDDY.md', '项目薄壳'),
    ('手机指令.md', '手机硬轨'),
)


def check_handoff_pointers():
    """三通道都必须写出"接手先读 handoff_latest.md"这个**动作**。

    ⚠️ 这是**存在性判据**：它只能证明"条款写在那儿"，不能证明"agent 真读了"。
    后者机器判不了（B-19：别拿无因果关系的代理指标冒充真判据），故此处只报"在位"。
    但它仍有价值：防止后续改动把这句话删掉而没人发现——这已发生过（B-05 口径、硬轨漏条）。

    判据自证第 5 例（2026-11-13）：首版只 grep 文件名 `handoff_latest.md`，结果手机指令
    第 69 行那句「交接账目在桌面 docs/handoff_latest.md 维护」（讲 B-14 为何不入硬轨的**理由**）
    把变异蹭成了假绿——删掉真正的动作条款，判据照样 ✓。改为要求「读」与文件名**同行且相邻**，
    把"提到文件"和"要求去读文件"区分开。
    """
    action = re.compile(r'(?:读|先读|第一动作)[^\n]{0,60}handoff_latest\.md'
                        r'|handoff_latest\.md[^\n]{0,60}(?:读|先读)')
    for rel, label in CHANNELS:
        p = os.path.join(REPO, rel)
        if not os.path.exists(p):
            check(f'接手条款·{label} 文件存在', False, rel)
            continue
        t = open(p, encoding='utf-8').read()
        check(f'接手条款·{label} 有"读摘要"动作句', bool(action.search(t)),
              '只提到文件名不算：该通道的会话不会因此先读交接摘要')


def check_ledger(body):
    """B-14 账目三齐：owner / next / due。空表也算三齐（0 条待办是合法状态）。"""
    if LEDGER_HEAD not in body:
        check('账目三齐：存在「待办账目」段', False,
              '缺段=未完事项无处登记（B-14）；段标题须为「## 4. 待办账目」')
        return
    check('账目三齐：存在「待办账目」段', True)
    seg = body.split(LEDGER_HEAD, 1)[1].split('\n## ', 1)[0]
    rows = [l.strip() for l in seg.splitlines() if l.strip().startswith('|')]
    if not rows:
        check('账目三齐：账目表存在', False, '段内没有表格')
        return
    header = [c.strip().lower() for c in rows[0].strip('|').split('|')]
    need = ('owner', 'next', 'due')
    miss = [k for k in need if not any(k in h for h in header)]
    check('账目三齐：表头含 owner / next / due', not miss, f'缺列 {miss}')
    data = [r for r in rows[1:] if not re.match(r'^\|[\s:\-|]+\|$', r)]
    bad = []
    for r in data:
        cols = [c.strip() for c in r.strip('|').split('|')]
        if len(cols) < 4 or any(not c for c in cols[-3:]):
            bad.append(r)
    check(f'账目三齐：{len(data)} 条待办三字段非空', not bad, f'缺字段：{bad[:2]}')

    # 分级（2026-11-14）：主次不分是实际发生过的病——5 条待办并排，分不出哪条是主线，
    # 于是每轮问"下一步做什么"时只能从池子里随手抓一条干，抓的就是 P2 杂务。
    # 判据只查"P0 有没有超过 1 条"，查不了"你选的那条对不对"——后者是人的事。
    lvl_i = next((i for i, h in enumerate(header) if '级别' in h), None)
    check('账目分级：表头含「级别」列', lvl_i is not None,
          '缺级别列=分不清主次（P0 主线 / P1 阻断 / P2 杂务）')
    if lvl_i is not None:
        p0 = []
        for r in data:
            cols = [c.strip() for c in r.strip('|').split('|')]
            if len(cols) > lvl_i and cols[lvl_i] == 'P0':
                p0.append(cols[1] if len(cols) > 1 else r)
        check('账目分级：P0 至多 1 条（主次不分即红）', len(p0) <= 1,
              f'当前 {len(p0)} 条 P0：{p0[:3]}')
    banned = [w for w in BAN_WORDS if w in seg]
    check('账目三齐：段内无「待跟进」类无主无期措辞', not banned, f'出现 {banned}')


def main():
    if not os.path.exists(H):
        check('docs/handoff_latest.md 存在', False, H)
        print('结果：0 ✓ / 1 ✗')
        return 1
    body = open(H, encoding='utf-8').read()
    check('文件存在', True)
    for key in ('当前主线', '版本与位置', '习惯快照指针'):
        check(f'必载段「{key}」', key in body)

    ver = ''
    try:
        ver = open(os.path.join(REPO, 'VERSION'), encoding='utf-8').read().strip().splitlines()[0]
    except Exception:
        pass
    m = re.search(r'版本[:：]\s*`?(\d+\.\d+\.\d+)', body)
    got = m.group(1) if m else ''
    check(f'版本号与 VERSION 一致（{got} vs {ver}）', bool(ver) and got == ver,
          '交接摘要过期：接手的人会按旧版本口径干活')

    check('含"先跑自检"的提醒', 'verify.sh' in body)
    check_handoff_pointers()
    check_ledger(body)
    print('结果：%d ✓ / %d ✗' % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
