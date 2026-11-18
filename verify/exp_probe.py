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
# 经验闭环 v3 步骤3（真源搬家）：运行时经验数据读写统一落用户级，跨项目/跨会话共享。
# 仓内 experience_recurrence.json 退为「版本化种子真源」（随 git 跨设备分发），
# install.sh 首次复制到用户级、已存在跳过（保护运行时累积的 reuse/retire 数据）。
# 用户级路径固定，不依赖 cwd / git root / last_repo——换仓不静默空转。
# CODEBUDDY_EXP_HOME 供判据隔离 mock（病15：判据识别范围须=对象范围）。
EXP_HOME = os.environ.get('CODEBUDDY_EXP_HOME') or os.path.join(
    os.path.expanduser('~'), '.codebuddy', 'experience')
SEED_REC = os.path.join(ROOT, 'experience_recurrence.json')  # 仓内种子（安装源/镜像）
SEED_MAP = os.path.join(ROOT, 'verify', '病号映射表.json')


def _live_path(seed):
    """用户级优先解析数据路径：用户级有该文件则用之，否则回退仓内种子。
    纯路径决策，不读文件内容；判据可 monkeypatch EXP_HOME + reload 做正反验证。"""
    name = os.path.basename(seed)
    live = os.path.join(EXP_HOME, name)
    if os.path.isfile(live):
        return live
    return seed


REC = _live_path(SEED_REC)   # 运行时真源（用户级优先）
ANCHOR = os.path.join(ROOT, 'hooks', 'next_anchor.py')
INJECT_MARK = '💡经验'

# 误报治理（经验闭环 v3 步骤1，用户五条遗漏④）：松散 match 对通用短词命中度虚高
# （实测"推送"因子串包含直接 0.9、"钩子"0.72），动作前拦会洪水。三道闸：
#   ① 短词（<4 字）禁用包含式 0.9，只认词块重叠且覆盖率达阈值；
#   ② 通用词黑名单（无区分度的技术高频词）不匹配；
#   ③ 拦截池只收「已验证」经验（solidified 或 reuse_count>0），死库存不拦人。
GENERIC_TERMS = frozenset(('推送', '钩子', '测试', '修复', '改文件', '同步', '检查', '验证',
                           'bump', '提交', '脚本', '文件', '方法', '字段', '版本', '代码',
                           'crash', 'error', 'bug', 'fix', 'test', 'docs', 'commit'))
MIN_QUERY_TOKENS = 4          # 低于此长度不接受包含式满分
VERIFIED_ONLY_IN_GATE = True  # gate 拦截池白名单：只收已验证经验（match 仍全池供提示）


def _is_generic(q):
    """查询是否为无区分度的通用词（整串命中黑名单即视为通用）。"""
    s = (q or '').strip().lower()
    return s in GENERIC_TERMS or len(s) <= 2


def _read_rec(path=None):
    path = path or REC
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
    """症状相似度：包含关系高分，但短词/通用词禁用包含式（误报治理步骤1）。

    原实现 `if a in b or b in a: return 0.9` 对"推送"这类单字词给满分，
    导致 50 条经验在动作前拦洪水。改为：查询是短词/通用词时只认词块重叠。
    """
    a, b = (a or '').lower(), (b or '').lower()
    if not a or not b:
        return 0.0
    import re as _re
    ta = set(_re.findall(r'[\u4e00-\u9fff]{2,}|[a-z0-9_]{3,}', a))
    tb = set(_re.findall(r'[\u4e00-\u9fff]{2,}|[a-z0-9_]{3,}', b))
    # 短词/通用词：禁用包含式，且要求词块重叠（无词块直接 0，不误报）
    if _is_generic(a):
        if not ta or not tb:
            return 0.0
        inter = ta & tb
        return (len(inter) / len(ta)) * 0.9 if inter else 0.0
    # 长查询：包含关系仍给高分（正常直达），但要求查询本身有区分度
    if a in b or b in a:
        return 0.9
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    if not inter:
        return 0.0
    # 查询覆盖率为主信号：用户输入的症状词若都被经验覆盖，即使经验很长也该命中
    coverage = len(inter) / len(ta)
    overlap = len(inter) / len(tb)
    return max(coverage * 0.9, overlap)


def match(symptom, rec=None, threshold=0.34, verified_only=False):
    """②直达查询：症状命中经验 → 返回 {id,text,fixed_path,score}，不命中返回 None。

    真源=experience_recurrence.json 的 exp_entries（fixed_path 由 exp_distill 派生，
    指回真实 commit 改动文件）。命中后调 exp_distill.hit(evidence) 记复用，注入层带出落点。

    verified_only=True（gate 用）：拦截池只收已验证经验——solidified 或 reuse_count>0，
    且未 retired（退役）。死库存（reuse_count=0 且未固化）不进拦截池，避免拿没实战
    验证过的经验拦人（误报治理步骤1）。match 默认 False 供注入层全池提示。
    """
    d = rec if rec is not None else _read_rec()
    if not d or 'exp_entries' not in d:
        return None
    best = None
    for e in d.get('exp_entries') or []:
        if verified_only:
            if e.get('retired'):
                continue
            if not (e.get('solidified') or (e.get('reuse_count') or 0) > 0):
                continue
        # 命中靠症状/text 相似度，不以 fixed_path 为门槛（病：从根修后 27 条
        # 落点故意缺省，若拿 fixed_path 当准入会把所有缺省经验误排除→命中链塌）。
        # fixed_path 只是可选附带信息：有就带出，无则空串（注入层本就不报落点）。
        score = max(_similar(symptom, e.get('symptom')),
                    _similar(symptom, e.get('text')) * 0.8)
        if score >= threshold and (best is None or score > best['score']):
            best = {'id': e.get('id'), 'text': e.get('text'),
                    'fixed_path': e.get('fixed_path') or '', 'evidence': e.get('evidence'),
                    'score': round(score, 3)}
    return best


def landing(rule_id=None):
    """落点真源（唯一）：PreToolUse 拦截时按规则给出可执行判据落点。

    为什么只接 rule_id、不接 evidence（实测取证，病15 反面）：
      · exp_entries.fixed_path 由 exp_distill 从 commit 改动文件盲目派生，
        实测 49 条里 48 条是 .json/.md（账本/清单/文档），0 条可执行代码——
        喂给模型当"修复落点"全是脏的，比不报更糟。
      · 因此注入层（💡直达）**不报落点**，只报"经验命中+证据+走闸提示"；
        唯一可信落点是拦截时按规则走 guard_cmd.gate_target 的判据文件锚点。
    无 rule_id 或异常 → None（不误报）。
    """
    if rule_id:
        try:
            sys.path.insert(0, os.path.join(ROOT, 'hooks'))
            import guard_cmd
            return guard_cmd.gate_target(rule_id)
        except Exception:
            return None
    return None


def gate(symptom, rec=None, threshold=0.34, commit=True, force=False):
    """动作前显式闸口：命中已固化经验 → 返回正门三字段，未命中返回 None。

    与 match() 的区别（这正是"注入≠复用"的机制落点）：
      · match() 只读查询，供注入层"提示"用，不记账——注入瞬间记账=假账（病：看到当用了）。
      · gate() 是模型/流程**真要去用**某经验时的显式闸口，命中才调 exp_distill.hit() 记真复用。
    commit=False 供判据做真阳性/真阴性验证，不污染账本。

    误报治理（步骤1）：默认 verified_only=True——死库存/退役经验不进拦截池。
    force=True 绕过白名单（全池匹配），但记 force_hit 留痕（B-10 显式绕行留审计）。

    返回 B-10 三字段：reason（为何命中）/ target（正门落点=fixed_path）/ method（怎么用）。
    """
    hit = match(symptom, rec=rec, threshold=threshold, verified_only=not force)
    if not hit:
        return None
    if commit:
        try:
            import exp_distill
            exp_distill.hit(hit['evidence'])
            if force:
                exp_distill.force_hit(hit['evidence'])
        except Exception:
            pass  # 记账失败不阻断闸口本身（fail-open 但 match 已给出落点）
    fp = hit.get('fixed_path') or ''
    # 落点缺省时，target 降级为证据锚点（sha:kind）——它指回可核实的 commit，
    # 不是脏"落点"，模型据此 git show 即得经验原文，比喂 MANIFEST.json 强。
    target = fp or ('evidence:' + (hit.get('evidence') or hit['id']))
    return {
        'id': hit['id'],
        'reason': '命中已固化经验 %s（据 %s，命中度 %s）' % (
            hit['id'], hit.get('evidence', ''), hit.get('score', '')),
        'target': target,
        'method': ('动作前先读 target 落点（%s）' % fp + '，按既有固化做法执行，勿重试已踩过的错') if fp
                  else '无可执行落点，按经验文本与证据（%s）自行核实后执行，勿重试已踩过的错' % target,
        'fixed_path': fp,  # 原字段：空=刻意缺省，非空=可执行(.py/.sh)真实文件
        'evidence': hit.get('evidence'),
        'score': hit.get('score'),
    }


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
