#!/usr/bin/env python3
"""经验淬炼器（经验闭环 v2 · ①淬炼）：把实战中「踩的坑」与「解法」从已有真源自动派生为
可复用的结构化经验条目，写入 experience_recurrence.json 的 exp_entries 键。

真源纪律（M1/M2）：不新建经验池文件。内容真源仍是：
  - docs/通病台账.md（坑的表现/修法/机制落点）
  - commit message 的 Lesson:/Reuse: trailers（实战解法，指回 commit）
本脚本只派生「索引视图」，每条 evidence 指回 commit 短 sha 或台账病号，可随时 --rebuild 重建。

反稀释闸（M-R148 完成态凭落点 / M-R29 留痕只增不撤污染分母）：
  - 只认带可核实落点的材料：Lesson 形如「病N（第K次）」必须能在台账核到该病号；
    Reuse 必须含「新建 0」或具体复用路径即视为有落点。
  - 无落点的 Lesson（如「无」）不派生；纯叙述不派生。
  - 幂等：evidence（commit sha + 类型）相同不重复入池。

用法：
  python3 verify/exp_distill.py --apply     # 派生并写回 exp_entries
  python3 verify/exp_distill.py --status    # 只读回读当前 exp_entries 统计
  python3 verify/exp_distill.py --selftest  # 正反向自证（含反稀释/幂等）
"""
import os
import re
import sys
import json
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(ROOT, 'experience_recurrence.json')
LEDGER = os.path.join(ROOT, 'docs', '通病台账.md')
MAP = os.path.join(ROOT, 'verify', '病号映射表.json')
SHA_RE = re.compile(r'\b[0-9a-f]{7,40}\b')
DIS_RE = re.compile(r'病(\d+)（第\s*\d+\s*次）|新病：')


def _git(*args):
    try:
        r = subprocess.run(['git', '-C', ROOT] + list(args),
                           capture_output=True, text=True, timeout=30)
        return r.stdout if r.returncode == 0 else ''
    except Exception:
        return ''


def _trailers():
    """从最近 60 条 commit 提取 Lesson/Reuse（实战解法真源）。

    用完整 %B 而非 trailers:valueonly——后者会丢掉键名，无法区分 Lesson 与 Reuse
    （病15 识别范围≠对象范围：valueonly 输出只有值，按 startswith('Lesson:') 解析必 0 命中）。
    """
    raw = _git('log', '-60', '--format=%H%x1f%B%x1e')
    out = []
    for block in raw.split('\x1e'):
        if '\x1f' not in block:
            continue
        sha, body = block.split('\x1f', 1)
        sha = sha.strip()
        if not SHA_RE.fullmatch(sha):
            continue
        for line in body.splitlines():
            m = re.match(r'^(Lesson|Reuse)\s*[:：]\s*(.*)$', line.strip())
            if not m:
                continue
            kind, text = m.group(1).lower(), m.group(2).strip()
            if text and text != '无':
                out.append({'sha': sha[:7], 'kind': kind, 'text': text})
    return out


def _ledger_diseases():
    """台账里已登记的病号集合（反稀释：Lesson 记的病必须在台账核到）。"""
    if not os.path.isfile(LEDGER):
        return set()
    txt = open(LEDGER, encoding='utf-8').read()
    return set('病' + m for m in re.findall(r'病(\d+)\s*[··]', txt))


def _has_landing(item, diseases):
    """可核实落点判据（对象范围=能指回真源，不是文本里出现字）。"""
    if item['kind'] == 'lesson':
        m = DIS_RE.search(item['text'])
        # 「无」/纯叙述无落点；记病且台账核得到才算；新病须有 commit sha 兜底
        if m:
            if m.group(1) and ('病' + m.group(1)) in diseases:
                return True
            if m.group(0).startswith('新病'):
                return True
        return False
    # reuse：含「新建 0」或扩展/复用既有路径即算有落点
    return bool(re.search(r'新建\s*0|扩展|复用|\.py|\.md|\.json', item['text']))


def _solid_diseases():
    """③进化固化集：映射表里 destination=闸化 的病号=已固化成闸/判据（可核实落点）。"""
    if not os.path.isfile(MAP):
        return set()
    try:
        mp = json.load(open(MAP, encoding='utf-8'))
        return set(d['id'] for d in mp.get('diseases', [])
                   if d.get('destination') == '闸化' and d.get('status') == 'active')
    except Exception:
        return set()


# ── 直达机制（踩坑→能力→直达）：给经验条目装「症状 + 解法落点」──────────────
# 设计：symptom 从 Lesson/Reuse 文本抽关键症状词；fixed_path 从该 commit 的真实改动
# 文件取第一处代码/文档落点（指回真源，不是编的）。两者都由 derive 自动派生，
# 命中时 exp_probe.match(symptom) 直接带出 fixed_path —— 第二次不用重查。
_FP_EXT = ('.py', '.md', '.sh', '.json')


def _fixed_path(sha, text):
    """解法落点：优先取该 commit 改动的真实文件（可核实），退化取文本里的路径。"""
    changed = [l.strip() for l in _git('show', '--name-only', '--format=', sha).splitlines()
               if l.strip().endswith(_FP_EXT)]
    if changed:
        return changed[0]
    m = re.search(r'[\w/.\-]+\.(?:py|md|sh|json)', text)
    return m.group() if m else ''


def _symptom(text):
    """症状词：去「病N（第K次）：」前缀，取前 60 字作匹配键（含坑的识别特征）。"""
    s = re.sub(r'^病\d+（第\s*\d+\s*次）[：:]?\s*', '', text)
    s = re.sub(r'^(新病[：:])?', '', s)
    return s[:60]


def derive(repo=ROOT):
    """派生经验条目列表（不写盘）。每条 evidence 唯一，幂等。

    ③进化：旧条目若已 --hit/固化，重派生时保留其复用态（幂等不洗掉实战命中）。
    """
    diseases = _ledger_diseases()
    solid = _solid_diseases()
    seen = set()
    entries = []
    prior = {e.get('evidence'): e for e in (_load_rec().get('exp_entries') or [])}
    for it in _trailers():
        if not _has_landing(it, diseases):
            continue
        ev = '%s:%s' % (it['sha'], it['kind'])
        if ev in seen:
            continue
        seen.add(ev)
        old = prior.get(ev) or {}
        m = DIS_RE.search(it['text'])
        dis = ('病' + m.group(1)) if (m and m.group(1)) else None
        entries.append({
            'id': 'EXP-%s-%s' % (it['sha'], it['kind'][:1]),
            'kind': it['kind'],
            'source_commit': it['sha'],
            'text': it['text'][:180],
            'evidence': ev,
            'reuse_count': old.get('reuse_count', 0),   # 保留实战命中，重派生不洗绿
            'last_hit': old.get('last_hit'),
            'solidified': bool(old.get('solidified')) or (dis in solid) if dis else bool(old.get('solidified')),
            # 直达机制：症状 + 解法落点（命中即带出，第二次不用重查）
            'symptom': old.get('symptom') or _symptom(it['text']),
            'fixed_path': old.get('fixed_path') or _fixed_path(it['sha'], it['text']),
        })
    return entries


def hit(evidence):
    """②复用正门：模型真采用某经验后显式回写 reuse_count+1 / last_hit。

    注入≠复用——不自动计命中，必须显式调用，否则 67 条全变假绿。"""
    rec = _load_rec()
    es = rec.get('exp_entries') or []
    now = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
    for e in es:
        if e.get('evidence') == evidence:
            e['reuse_count'] = (e.get('reuse_count') or 0) + 1
            e['last_hit'] = now
            tmp = REC + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
            os.replace(tmp, REC)
            return True
    return False


def _load_rec():
    if os.path.isfile(REC):
        return json.load(open(REC, encoding='utf-8'))
    return {'counters': {}, 'direction_cases': []}


def apply():
    """派生并原子写回 exp_entries（幂等：重派生覆盖，不重复膨胀）。"""
    rec = _load_rec()
    entries = derive()
    rec['exp_entries'] = entries
    rec['exp_meta'] = {'derived_by': 'exp_distill.py', 'total': len(entries)}
    tmp = REC + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, REC)
    return len(entries)


def status():
    rec = _load_rec()
    es = rec.get('exp_entries') or []
    lessons = sum(1 for e in es if e.get('kind') == 'lesson')
    reuses = sum(1 for e in es if e.get('kind') == 'reuse')
    print('[exp-distill] 经验条目 %d 条：坑/解法教训 %d / 复用方法 %d' % (len(es), lessons, reuses))
    print('[exp-distill] 真源：docs/通病台账.md + git Lesson:/Reuse: trailers（本键为可重建视图）')
    return 0


_KIND_L = 'lesson'
_KIND_R = 'reuse'


def selftest():
    fails = []

    # 反稀释正向：记病且台账核得到 → 有落点
    ok_item = {'sha': 'abcdef1', 'kind': _KIND_L, 'text': '病15（第14次）：识别范围宽于对象范围'}
    if not _has_landing(ok_item, {'病15'}):
        fails.append('反稀释正向：台账核得到的病号被误判无落点')
    # 反稀释反向1：['无'] 故事 无落点
    if _has_landing({'sha': 'abcdef2', 'kind': _KIND_L, 'text': '无'}, {'病15'}):
        fails.append('反稀释反向：Lesson=无 被误判有落点')
    # 反稀释反向2：台账核不到的病号 → 无落点（病15 深度：识别范围=对象范围）
    if _has_landing({'sha': 'abcdef3', 'kind': _KIND_L, 'text': '病99（第1次）：瞎编'}, {'病15'}):
        fails.append('反稀释反向：台账无此病号被误判有落点')
    # 反稀释反向3：纯叙述 reuse 无路径 → 无落点
    if _has_landing({'sha': 'abcdef4', 'kind': _KIND_R, 'text': '随便写写'}, set()):
        fails.append('反稀释反向：无路径 reuse 被误判有落点')

    # 幂等 + 落点：在临时仓造 git 真 commit，验派生条目 evidence 唯一、可重建
    td = tempfile.mkdtemp()
    subprocess.run(['git', '-C', td, 'init', '-q'], capture_output=True)
    subprocess.run(['git', '-C', td, 'config', 'user.email', 't@t'], capture_output=True)
    subprocess.run(['git', '-C', td, 'config', 'user.name', 't'], capture_output=True)
    open(os.path.join(td, 'f'), 'w').write('x')
    subprocess.run(['git', '-C', td, 'add', 'f'], capture_output=True)
    msg = ('feat: t\n\nLesson: 病15（第14次）：测试落点\n'
           'Reuse: 扩展既有件，新建 0\n')
    subprocess.run(['git', '-C', td, 'commit', '-q', '-m', msg], capture_output=True)
    os.makedirs(os.path.join(td, 'docs'), exist_ok=True)

    real_root = None
    try:
        # derive 用全局 ROOT，这里用 monkeypatch 指向临时仓验真链路
        global ROOT, REC, LEDGER
        real_root, real_rec, real_ledger = ROOT, REC, LEDGER
        ROOT = td
        REC = os.path.join(td, 'experience_recurrence.json')
        LEDGER = os.path.join(td, 'docs', '通病台账.md')
        open(LEDGER, 'w', encoding='utf-8').write('## 病15 · 判据\n| 实例 | 病15 · 测试 |\n')
        es = derive()
        lessons = [e for e in es if e['kind'] == _KIND_L]
        reuses = [e for e in es if e['kind'] == _KIND_R]
        if len(lessons) != 1:
            fails.append('真链路派生：lesson 条目数应为 1，实为 %d' % len(lessons))
        if len(reuses) != 1:
            fails.append('真链路派生：reuse 条目数应为 1，实为 %d' % len(reuses))
        if any(not e.get('evidence') for e in es):
            fails.append('派生条目缺 evidence')
        n = apply()
        if n != len(es):
            fails.append('apply 写回数与派生数不一致')
        # 幂等：再 apply 一次，evidence 集合不变、条目数不膨胀
        apply()
        rec = json.load(open(REC, encoding='utf-8'))
        if len(rec.get('exp_entries') or []) != len(es):
            fails.append('幂等失败：二次 apply 后条目数膨胀')

        # ②复用 reverse：未命中前 reuse_count=0；命中后 +1 且重派生不洗掉
        ev0 = rec['exp_entries'][0]['evidence']
        if rec['exp_entries'][0].get('reuse_count', 0) != 0:
            fails.append('复用反向：未命中条目 reuse_count 非 0')
        if not hit(ev0):
            fails.append('复用正门：命中已知 evidence 返回失败')
        rec2 = json.load(open(REC, encoding='utf-8'))
        hit_e = next(e for e in rec2['exp_entries'] if e['evidence'] == ev0)
        if hit_e['reuse_count'] != 1 or not hit_e.get('last_hit'):
            fails.append('复用正门：命中后 reuse_count/last_hit 未写')
        apply()  # 重派生
        rec3 = json.load(open(REC, encoding='utf-8'))
        hit_e3 = next(e for e in rec3['exp_entries'] if e['evidence'] == ev0)
        if hit_e3['reuse_count'] != 1:
            fails.append('幂等洗绿：重派生把实战命中 reuse_count 洗回 0')
        if hit('nonexistent-evidence'):
            fails.append('复用反向：不存在的 evidence 不应命中')
    finally:
        ROOT, REC, LEDGER = real_root, real_rec, real_ledger

    if fails:
        for f in fails:
            print('  ✗', f)
        return 1
    print('  ✓ 反稀释 4 类 + 真链路派生 + 幂等重建 + 复用命中/抗洗绿全过')
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    if '--apply' in sys.argv:
        print('[exp-distill] 已派生 %d 条经验入 exp_entries' % apply())
    elif '--hit' in sys.argv:
        i = sys.argv.index('--hit')
        if i + 1 < len(sys.argv):
            ok = hit(sys.argv[i + 1])
            print('[exp-distill] 复用命中 %s：%s' % (sys.argv[i + 1], '已记' if ok else '无此经验'))
            sys.exit(0 if ok else 1)
        print('[exp-distill] 用法：--hit <evidence>')
        sys.exit(1)
    elif '--status' in sys.argv:
        sys.exit(status())
    else:
        sys.exit(status())
