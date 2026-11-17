#!/usr/bin/env python3
"""build_rail_check.py — 施工纪律 S 段真源 ↔ 手机指令硬轨 的对账判据（离线）。

为什么要有（S-02 机制解决，不打补丁）：
  施工纪律真源化（S-01…S-09）后，曾出现"真源改了但手机端/云端副本没同步"的假闭环——
  因为 core-8 的 B 段有 hard-rail 对账（改了会红），S 段却没有任何对账（改了静默）。
  本判据把 S 段接进同一条链：施工纪律.md 改 → 这里红 → 逼一次「进硬轨」的决定 →
  提交时 pre-commit 同步云端 doc → verify 新鲜度绿。

判据（比 B 段多一层正文核对，防"注释写对了、正文没落地"的假对账）：
  ① 不重不漏：build-rail 登记的 S 编号 == 施工纪律.md 的 S 编号全集
  ② 必入清单：手机端踩了当场出事的条（S-04 简洁 / S-07 素材为准）不能豁免
  ③ 正文标记：粘贴区正文必须出现每条 S 编号的 `S-0n` 标记

出口码：0=OK / 1=FAIL（红）/ 2=OPT（无法判定，不冒充绿也不冒充红）。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SLA_REL = os.path.join('通用层', 'rules', '施工纪律.md')
MOB_REL = '手机指令.md'
START_MARK = '## 【粘贴区 · 从下一行开始复制】'
END_MARK = '**【粘贴区 结束】**'
RAIL_TAG = 'build-rail'
MUST = {'S-04', 'S-07'}  # 手机端最容易踩、踩了当场出事：简洁输出 / 素材为准


def s_ids(sla_text):
    """施工纪律.md 里的 S 编号全集（只认 `N. **S-nn ...` 的条款行）。"""
    return set(re.findall(r'(?m)^\s*\d+\.\s+\*\*(S-[0-9]{2})', sla_text))


def rail_ids(mob_text, tag):
    """手机指令.md 里某条登记注释的 S 编号集合；注释不存在返回 None。"""
    m = re.search(r'<!--\s*%s\s*:\s*([^>]*?)-->' % tag, mob_text)
    if not m:
        return None
    return set(re.findall(r'S-[0-9]{2}', m.group(1)))


def paste(mob_text):
    """取粘贴区正文（两标记之间），剥掉 HTML 注释行——登记注释里的 S 编号
    不算正文标记（否则注释写对、正文没落也会假绿，正是病15 的识别范围陷阱）。"""
    i = mob_text.find(START_MARK)
    if i < 0:
        raise ValueError('找不到粘贴区起始标记')
    body = mob_text[i + len(START_MARK):]
    j = body.find(END_MARK)
    if j < 0:
        raise ValueError('找不到粘贴区结束标记')
    lines = [ln for ln in body[:j].split('\n') if not ln.strip().startswith('<!--')]
    return '\n'.join(lines)


def check(sla_text, mob_text):
    """返回 (status, probs)：status ∈ OK / FAIL / OPT。"""
    alls = s_ids(sla_text)
    if not alls:
        return 'OPT', ['施工纪律.md 未识别到 S 编号——对账无法判定']
    rail = rail_ids(mob_text, RAIL_TAG)
    if rail is None:
        return 'FAIL', ['手机指令.md 缺 build-rail 登记注释——S 段放没放全无从判断']

    probs = []
    ghost = rail - alls
    if ghost:
        probs.append('登记了施工纪律里不存在的编号 %s（写错或 S 段已删条）'
                     % '、'.join(sorted(ghost)))
    miss = alls - rail
    if miss:
        probs.append('施工纪律有但手机硬轨没登记：%s（改了真源忘同步手机端）'
                     % '、'.join(sorted(miss)))
    lack = MUST - rail
    if lack:
        probs.append('必入清单缺：%s（手机端踩了当场出事，不能漏）'
                     % '、'.join(sorted(lack)))

    try:
        body_ids = set(re.findall(r'S-[0-9]{2}', paste(mob_text)))
    except ValueError as e:
        return 'OPT', ['粘贴区不可读：%s' % e]
    bodymiss = alls - body_ids
    if bodymiss:
        probs.append('注释登记了但粘贴区正文缺标记：%s（假对账：只改注释没落正文）'
                     % '、'.join(sorted(bodymiss)))

    if probs:
        return 'FAIL', probs
    return 'OK', ['%d 条 S 编号登记齐全、正文标记齐全，不重不漏' % len(alls)]


def main():
    repo = ROOT
    if '--repo' in sys.argv:
        repo = sys.argv[sys.argv.index('--repo') + 1]
    sla_p = os.path.join(repo, SLA_REL)
    mob_p = os.path.join(repo, MOB_REL)
    try:
        sla = open(sla_p, encoding='utf-8').read()
        mob = open(mob_p, encoding='utf-8').read()
    except Exception as e:
        print('OPT  读文件失败：%s' % e)
        return 2
    status, probs = check(sla, mob)
    if status == 'OK':
        print('OK   ' + probs[0])
        return 0
    if status == 'OPT':
        print('OPT  ' + probs[0])
        return 2
    print('FAIL ' + '；'.join(probs))
    return 1


if __name__ == '__main__':
    sys.exit(main())
