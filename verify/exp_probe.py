#!/usr/bin/env python3
"""经验闭环可观测探针（经验闭环 v2 · ②③观测 + ④回读）：一条命令回读四环状态，
解决用户「看不见、摸不着、不知道真闭环假闭环」的痛点。

四环读数（全部指回可核实落点，不报「分析过」当产出，B-02 三态）：
  ① 写（淬炼）：exp_entries 条数 / 有 evidence 占比（无 evidence = 假经验）
  ② 读（复用）：reuse_count>0 条数、last_hit 非空条数（= 真被引用过；0 = 死库存）
  ③ 进化：exp_entries 里 solidified=true 条数（= 固化成技能/判据的落点）
  ④ 呈现：next_anchor.py 注入段是否含「💡经验」标记（每轮可见的活体证据）

三态诚实：没有 exp_entries 键 = 「未淬炼」（不是 0 条经验）；有键但全 0 复用 =
「只写不用」红灯，不折叠成「通过」。

用法：
  python3 verify/exp_probe.py            # 回读四环状态（供 verify.sh 接电）
  python3 verify/exp_probe.py --selftest # 正反向自证
"""
import os
import sys
import json
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(ROOT, 'experience_recurrence.json')
ANCHOR = os.path.join(ROOT, 'hooks', 'next_anchor.py')
INJECT_MARK = '💡经验'


def _read_rec(path=REC):
    if not os.path.isfile(path):
        return None
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return None


def measure(rec=None, anchor_path=ANCHOR):
    """返回四环读数 dict + 状态灯。纯函数，便于 selftest 抄真实样本。"""
    d = rec if rec is not None else _read_rec()
    if d is None or 'exp_entries' not in (d or {}):
        return {'state': 'unbuilt', 'total': 0, 'with_evidence': 0,
                'reused': 0, 'hit': 0, 'solid': 0, 'present': False, 'lights': '⚪未淬炼'}

    es = d.get('exp_entries') or []
    total = len(es)
    with_ev = sum(1 for e in es if e.get('evidence'))
    reused = sum(1 for e in es if (e.get('reuse_count') or 0) > 0)
    hit = sum(1 for e in es if e.get('last_hit'))
    solid = sum(1 for e in es if e.get('solidified'))
    present = False
    if os.path.isfile(anchor_path):
        present = INJECT_MARK in open(anchor_path, encoding='utf-8').read()

    # 状态灯：写有落点才亮；读/进化为 0 如实报红（只写不用=死库存）
    w = '✓' if total > 0 and with_ev == total else ('⚠' if total else '⚪')
    r = '✓' if reused > 0 else '✗'
    g = '✓' if solid > 0 else '⚠'
    p = '✓' if present else '✗'
    return {'state': 'built', 'total': total, 'with_evidence': with_ev,
            'reused': reused, 'hit': hit, 'solid': solid, 'present': present,
            'lights': '写%s 读%s 进化%s 呈现%s' % (w, r, g, p)}


def _similar(a, b):
    """症状相似度：包含关系直接高分，否则中文子串/字符 2-gram 重叠（复用 sync_sop 思路）。"""
    a, b = (a or '').lower(), (b or '').lower()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.9
    # 提取中文/ASCII 词块
    import re as _re
    ta = set(_re.findall(r'[\u4e00-\u9fff]{2,}|[a-z0-9_]{3,}', a))
    tb = set(_re.findall(r'[\u4e00-\u9fff]{2,}|[a-z0-9_]{3,}', b))
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    if not inter:
        return 0.0
    # 查询覆盖率为主信号：用户输入的症状词若都被经验覆盖，即使经验很长也该命中
    coverage = len(inter) / len(ta)
    overlap = len(inter) / len(tb)
    return max(coverage * 0.9, overlap)


def match(symptom, rec=None, threshold=0.34):
    """②直达查询：症状命中经验 → 返回 {id,text,fixed_path,score}，不命中返回 None。

    真源=experience_recurrence.json 的 exp_entries（fixed_path 由 exp_distill 派生，
    指回真实 commit 改动文件）。命中后调 exp_distill.hit(evidence) 记复用，注入层带出落点。
    """
    d = rec if rec is not None else _read_rec()
    if not d or 'exp_entries' not in d:
        return None
    best = None
    for e in d.get('exp_entries') or []:
        if not e.get('fixed_path'):
            continue
        score = max(_similar(symptom, e.get('symptom')),
                    _similar(symptom, e.get('text')) * 0.8)
        if score >= threshold and (best is None or score > best['score']):
            best = {'id': e.get('id'), 'text': e.get('text'),
                    'fixed_path': e['fixed_path'], 'evidence': e.get('evidence'),
                    'score': round(score, 3)}
    return best


def report(m=None):
    m = m or measure()
    print('[exp-probe] 经验闭环四环：%s' % m['lights'])
    if m['state'] == 'unbuilt':
        print('[exp-probe] 未淬炼——先跑 python3 verify/exp_distill.py --apply')
        return 0  # 未淬炼是「无法判定/未做」，不是失败，不折叠
    print('[exp-probe]   ①写 %d 条（有落点 %d）｜②读 复用 %d / 命中 %d｜③进化 固化 %d｜④呈现 %s'
          % (m['total'], m['with_evidence'], m['reused'], m['hit'], m['solid'],
             '在' if m['present'] else '缺'))
    if m['reused'] == 0:
        print('[exp-probe]   ⚠ 只写不用：%d 条经验 reuse_count 全 0（死库存，非通过）' % m['total'])
    return 0


def selftest():
    fails = []

    # 正向：抄真实结构（含 evidence + reuse_count>0 + solidified + 注入标记）
    td = tempfile.mkdtemp()
    anchor = os.path.join(td, 'next_anchor.py')
    open(anchor, 'w', encoding='utf-8').write('msg += "💡经验 %s"')
    good = {'exp_entries': [
        {'evidence': 'abc:lesson', 'reuse_count': 2, 'last_hit': '2026-11-15', 'solidified': True},
        {'evidence': 'def:reuse', 'reuse_count': 1, 'last_hit': '2026-11-14', 'solidified': False},
    ]}
    m = measure(good, anchor)
    if not (m['state'] == 'built' and m['total'] == 2 and m['reused'] == 2
            and m['hit'] == 2 and m['solid'] == 1 and m['present']):
        fails.append('正向：真闭环读数不全绿 → %s' % m)

    # 反向1：只写不用（全 0 复用）→ 读灯必须红，不能洗绿
    dead = {'exp_entries': [{'evidence': 'x:lesson', 'reuse_count': 0,
                             'last_hit': None, 'solidified': False}]}
    m2 = measure(dead, anchor)
    if '读✗' not in m2['lights']:
        fails.append('反向1：全 0 复用未报读红（死库存被洗绿）')

    # 反向2：无 evidence 的假经验 → 写灯不能绿
    fake = {'exp_entries': [{'reuse_count': 1, 'last_hit': 'x', 'solidified': True}]}
    m3 = measure(fake, anchor)
    if '写⚪' not in m3['lights'] and '写⚠' not in m3['lights']:
        fails.append('反向2：无 evidence 假经验写灯误绿')

    # 反向3：未淬炼（无键）→ 必须报 unbuilt，不折叠成 0 条
    if measure({'counters': {}}, anchor)['state'] != 'unbuilt':
        fails.append('反向3：无 exp_entries 键未报未淬炼')

    # 反向4：注入段缺标记 → 呈现灯必须红
    anchor2 = os.path.join(td, 'na2.py')
    open(anchor2, 'w', encoding='utf-8').write('msg = "no inject"')
    if measure(good, anchor2)['present']:
        fails.append('反向4：注入段缺标记却报已呈现')

    if fails:
        for f in fails:
            print('  ✗', f)
        return 1
    print('  ✓ 四环正向 + 4 类反向（死库存/假经验/未淬炼/缺呈现）全过')
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(report())
