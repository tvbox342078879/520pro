#!/usr/bin/env python3
"""v0.8.67 · 内容流触发源探测器（批3）：该产未产 → 欠账负账本。

背景（四轮漏检排查）：archive_ledger 只记「落了的」（正向账），漏落无影无踪——
01-方法论只有 1 件、版本台账断流 11 版，都是「触发源发生了、产出没发生、没人报红」。
本探测器把触发源机器可测化（git commit message / diff 路径 / VERSION），
与正向账对账，命中「该产未产」写欠账进 verify/delivery_debt.json；
ledger 出现对应回执即机器自动核销。

三态（B-02）：
  ✓ 绿  —— 全部触发源都有回执，或窗口内无触发源（无可判对象）
  ✗ 红  —— 存在该产未产欠账（或账本损坏，不折叠成绿）
  · 无法判定 —— content_sources / ledger 不可读，或 online 类流（离线不可判）

正向：造一条 Lesson 非空的 commit 无回执 → 出欠账；反向：Lesson=「无」/ 已有回执 → 零欠账。
（--selftest 用纯函数 probe_commit 造 4 个用例，不碰真实数据。）
"""
import json, os, re, subprocess, sys, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CS = os.path.join(REPO, 'verify', 'content_sources.json')
DEBT = os.path.join(REPO, 'verify', 'delivery_debt.json')
LEDGER = os.path.join(REPO, 'archive_ledger.json')


# ────────────────────────── 纯函数层（可单测，不碰磁盘） ──────────────────────────
def lesson_of(msg):
    """取 commit message 的 Lesson: 段（首个匹配行）。返回 (原文, 是否实质)。"""
    m = re.search(r'(?m)^Lesson:\s*(.*)$', msg or '')
    if not m:
        return '', False
    line = m.group(1).strip()
    if not line:
        return '', False
    if line.startswith('无'):
        return line, False          # 「无」或「无（…）」按 commit-msg 语义=没踩坑
    return line, True


def lesson_advisory(msg):
    """逃逸提示：Lesson 写「无」但括号里塞了实质内容（>15 字）→ 提示确认。
    机器只能提示不能断言（语义判断），故不计欠账。"""
    line, real = lesson_of(msg)
    if real or not line:
        return None
    m = re.match(r'无\s*[（(](.*)[）)]\s*$', line)
    if m and len(m.group(1).strip()) > 15:
        return f'Lesson 写「无」但括注 {len(m.group(1))} 字：「{m.group(1)[:50]}…」——确认是否应提炼方法论'
    return None


def _glob_hit(path, pattern):
    """极简 glob：支持 ** 与 *，用于 diff 路径匹配（不引第三方依赖）。"""
    rx = re.escape(pattern).replace(r'\*\*/', '(?:.*/)?').replace(r'\*', '[^/]*')
    return re.search('^' + rx + '$', path) is not None


def signal_hit(sig, commit):
    """单条 flow 的信号是否命中。返回 (hit, evidence)；不支持的 type 返回 (False, '')。"""
    t = sig.get('type')
    msg = commit.get('msg', '')
    paths = commit.get('paths') or []

    if t == 'lesson':
        line, real = lesson_of(msg)
        if sig.get('match') == 'nonempty':
            return (True, f'Lesson: {line[:80]}') if real else (False, '')
        if sig.get('match') == 'keyword':
            kws = sig.get('keywords') or []
            if real and any(k in line for k in kws):
                return True, f'Lesson 命中 {[k for k in kws if k in line]}: {line[:60]}'
            return False, ''
        return False, ''

    if t == 'message':
        for group in sig.get('all_of') or []:
            if not any(k in msg for k in group):
                return False, ''
        return True, 'message 命中 ' + str([g[0] for g in (sig.get('all_of') or [])])

    if t == 'diff_paths':
        pat = sig.get('glob', '')
        flt = sig.get('path_filter') or []
        hits = [p for p in paths
                if (_glob_hit(p, pat) or p.endswith(pat))
                and (not flt or any(x in p for x in flt))]
        return (True, f'改动文件: {hits[0]}' if hits else '') if hits else (False, '')

    if t == 'version_bump':
        v = commit.get('version')
        if v and v[0] != v[1]:
            return True, f'VERSION {v[0]} → {v[1]}'
        return False, ''

    return False, ''   # online / derived：离线不可判/派生，交给上层


def _closed(folder, flow, commit, ledger_rows):
    """核销判定：ledger 有 result=ok、target 前缀命中、ts>=commit 日期 的行，
    **且回执能指回这条 commit**——否则同夹里别人的回执会把账误销掉（实测踩到：
    d8b5b6a 的方法论欠账被 01 夹「自愈演示」旧回执误判为已还）。
      · F09 / close_match=version：回执须含 VERSION bump 目标版本（本身就是本 commit 引入的）
      · close_match=msg_version（F04）：回执须含**本 commit 短 sha 或本次 bump 目标版本**。
        ★ 病15 第 13 例横向复发（2026-11-15 W2）：旧实现用「message 里任一 x.y.z 版本号」
          当核销凭据，而提交信息会写承接版本（承接 v0.8.75）、范式版本（v0.8.4）、
          技能版本（1.1.0）——实测命中 artifact-store v1.1.0 的**他人回执**，把 foundry
          的 F04 静默销掉。核销凭据必须能指回本 commit，不能用 message 全量版本号。
      · 其余：回执须含 commit 短 sha（无源内容判据的口径：event_ref 必须指向 commit）
    """
    day = (commit.get('date') or '')[:10]
    fid = flow.get('id', '')
    cm = flow.get('close_match', '')
    sha = (commit.get('short') or '')[:7]
    ver = commit.get('version') or (None, None)
    want_ver = ver[1] if (fid == 'F09' or cm == 'version') else None
    bumped = ver[1] if (ver[0] != ver[1] and ver[1]) else None
    # msg_version 的锚 = 本 commit 短 sha 或本次 bump 目标版本（二选一即指回本 commit）
    msg_anchors = [a for a in (sha, bumped) if a] if cm == 'msg_version' else []
    for e in ledger_rows:
        if e.get('result') != 'ok':
            continue
        tgt = (e.get('target') or '')
        if not tgt.startswith(folder):
            continue
        if day and (e.get('ts') or '')[:10] < day:
            continue
        blob = json.dumps(e, ensure_ascii=False)
        if want_ver:
            if want_ver not in blob:
                continue
        elif msg_anchors:
            if not any(a in blob for a in msg_anchors):
                continue
        elif sha:
            if sha not in blob:
                continue
        return e
    return None


def probe_commit(commit, flows, ledger_rows):
    """单 commit 探测。返回 (debts, advices)；debts 元素为待入账的欠账 dict。"""
    debts, advices = [], []
    for f in flows:
        if f.get('probe') not in ('debt', 'advisory'):
            continue
        hit, ev = signal_hit(f.get('signal') or {}, commit)
        if not hit:
            continue
        if f.get('probe') == 'advisory':
            advices.append({'flow': f['id'], 'commit': commit.get('short', ''),
                            'text': f'{f["folder"].split("/")[-1]}: {ev}'})
            continue
        closed = _closed(f['folder'], f, commit, ledger_rows)
        if closed:
            continue
        debts.append({
            'id': f'D-{commit.get("short", "")[:7]}-{f["id"]}',
            'flow': f['id'], 'folder': f['folder'],
            'commit': commit.get('short', ''), 'commit_date': commit.get('date', ''),
            # v0.8.81 修：原只 F09 写当版版本 → F11 账 target_version 空，核销重判反推 version=(None,None)
            # 退化成「回执须含本 commit sha」→ 提交前落报告永远销不上（D-3e457d1-F11 实测）。
            # 凡 version_bump 信号流都必须落当版版本，核销凭据才成立。
            'target_version': ((commit.get('version') or (None, None))[1] or '')
                              if (f.get('signal') or {}).get('type') == 'version_bump' else '',
            'title': (commit.get('msg', '').splitlines() or [''])[0][:80],
            'expect': f.get('action', ''), 'evidence': ev[:160],
            'status': 'open', 'age_commits': 0,
            'first_seen': datetime.date.today().isoformat(),
            'closed_by': '', 'waived_until': '', 'note': '',
        })
    adv = lesson_advisory(commit.get('msg', ''))
    if adv:
        advices.append({'flow': 'lesson-escape', 'commit': commit.get('short', ''), 'text': adv})
    return debts, advices


# ────────────────────────── 磁盘层 ──────────────────────────
def _git(*args):
    r = subprocess.run(['git', '-C', REPO] + list(args), capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ''


def load_json(path, default=None):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return default


def save_json_atomic(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ★ 扫描游标放本地，不放受管账本（v0.8.69 修）：
#   游标是"这台机器扫到哪了"，不是账本事实。放 delivery_debt.json 里会形成一个必然的
#   差一格闭环——每次提交后扫描把游标推到该提交，于是账本文件**永远**比 HEAD 落后一格，
#   工作区永远脏一个文件，每轮都得多打一个"位点前移"的提交来收尾。
#   挪到 .git/ 下（本就不入版本库）后：账本只记事实，游标只在本地，提交后工作区干净。
#   迁移兼容：本地无游标时回退读账本里的旧 scan_state（老机器不会重复判历史）。
STATE_LOCAL = os.path.join(REPO, '.git', 'delivery_probe_state.json')


def _load_state(debt):
    """读游标。只认 last_sha / last_scan_ts 两个键——账本里那份 scan_state 已改成说明文字，
    整个 dict 拿来用会把说明文字当游标一起写回本地（首版就这么干了，本地文件里多出两行 doc）。"""
    keys = ('last_sha', 'last_scan_ts')
    try:
        s = json.load(open(STATE_LOCAL, encoding='utf-8'))
        if isinstance(s, dict) and s.get('last_sha'):
            return {k: v for k, v in s.items() if k in keys}
    except Exception:
        pass
    return {k: v for k, v in dict((debt or {}).get('scan_state') or {}).items() if k in keys}


def _save_state(state):
    try:
        save_json_atomic(STATE_LOCAL, state)
    except Exception as e:
        print(f'  · [delivery-probe] 无法判定：游标写盘失败（{type(e).__name__}）——本轮不推进位点，下次会重判同一批 commit')


def read_commits(limit=None, after_sha=None):
    """读 commit 列表（含 diff 路径与 VERSION 前后值）。after_sha 之后的所有 commit。

    ★2026-11-15 修（病15 第 11 例，本轮最大发现）：`git show --name-only` 默认
    `core.quotepath=true`，**中文路径会被转义成 `"\\350\\203\\275..."` 并加引号**。
    于是 glob 判据（`CHANGELOG.md` / `docs/通病台账.md` / `probe-hub/**/*.json`）
    对这些路径**永远不命中**——判据看着在工作（其它流照常），实则 5 条流整体失效：
    F03 生态总览 / F04 子项目演进 / F05 侦察资产 / F06 复盘与判例 / F08 落地监测。
    实测：bce02ae 改了 `能力层/.../CHANGELOG.md`，F04 命中结果为 False。
    本仓绝大多数路径含中文（`能力层/`、`通用层/`、`docs/通病台账.md`），
    等于探测器只对 `VERSION`/`MANIFEST.json` 这类纯 ASCII 路径有效。

    修法：显式 `-c core.quotepath=false`，让 git 输出原始 UTF-8 路径。
    这不是"改判据迁就数据"，是**让判据看到真实对象**（B-15 机制级修复）。
    """
    fmt = '--format=%h%x1f%H%x1f%ad%x1f%B%x1e'
    rng = f'{after_sha}..HEAD' if after_sha else f'-{limit or 40}'
    raw = _git('log', '--date=short', fmt, rng)
    out = []
    for chunk in raw.split('\x1e'):
        chunk = chunk.strip('\n')
        if not chunk:
            continue
        parts = chunk.split('\x1f')
        if len(parts) < 4:
            continue
        short, full, date, msg = parts[0], parts[1], parts[2], parts[3]
        # ★ quotepath=false：中文路径原样输出（否则 glob 判据对中文路径永不命中）
        paths = [p for p in _git('-c', 'core.quotepath=false', 'show', '--name-only',
                                 '--format=', short).splitlines() if p.strip()]
        v_new = _git('show', f'{short}:VERSION').strip()
        v_old = _git('show', f'{short}^:VERSION').strip() or v_new
        out.append({'short': short, 'full': full, 'date': date, 'msg': msg,
                    'paths': paths, 'version': (v_old, v_new) if v_new else None})
    out.reverse()   # 时间正序
    return out


def _probe_window(limit=40, flows=None, rows=None):
    """按 probe_commit 复算窗口内欠账（不写盘）。返回 (commits, debts)。"""
    cs = load_json(CS)
    led = load_json(LEDGER)
    if not cs or not led:
        return [], []
    fl = flows if flows is not None else [f for f in cs.get('flows', []) if f.get('probe') == 'debt']
    lr = rows if rows is not None else (led.get('entries', []) if isinstance(led, dict) else led)
    commits = read_commits(limit=limit, after_sha=None)
    out = []
    for c in commits:
        ds, _ = probe_commit(c, fl, lr)
        out.extend(ds)
    return commits, out


def audit(limit=40):
    """只读全量对账：列出窗口内「该产未产」的账，**不写账本**（--audit）。

    为什么要有这个模式（病15 第 11 例的出口）：判据修好那一轮，历史窗口会一次性
    浮现几十条旧账。没有只读对账口，处置只能靠临时脚本——口径与 probe_commit
    各写一份，改一处必漏一处（本仓已因「复制判据」栽过）。本模式复用同一套
    probe_commit，只打印不落盘；处置结论由 --backfill 入账 + --waive/真补决定。
    """
    commits, ds = _probe_window(limit)
    if not commits:
        print('  · [delivery-probe] 无法判定：content_sources / archive_ledger 不可读，或窗口无 commit')
        return 0
    debt = load_json(DEBT) or {}
    known = {d['id'] for d in debt.get('debts', [])}
    print(f'🔍 只读对账窗口：{len(commits)} 个 commit（{commits[0]["short"]}..{commits[-1]["short"]}）')
    new = 0
    for d in ds:
        flag = '' if d['id'] in known else '  ← 未入账'
        new += 0 if d['id'] in known else 1
        print(f'    {d["id"]:18s} {d["folder"].split("/")[-1]:12s} {d["commit"]} {d["title"][:40]}{flag}')
    print(f'--- 窗口内欠账合计: {len(ds)}（其中未入账 {new} 条）')
    print('    处置：入账后逐条决定「真补落库」或「--waive 显式豁免」——两条都不许不做就翻篇')
    return 0


def backfill(limit=40):
    """把窗口内「未入账」的旧账补进账本（--backfill）——只入账，不改状态。

    判据修正后必须做的事：修好判据的那次提交之前，历史窗口里的欠账是**判据盲区**
    造成的静默漏账，它们既不在账本里也没人处置。补记入账才会让它们出现在
    `--list` 上，进而被迫处置（真补 or 豁免），而不是随判据修正一起消失。
    """
    debt = load_json(DEBT)
    if not debt:
        print('  · [delivery-probe] 无法判定：delivery_debt.json 不可读')
        return 2
    commits, ds = _probe_window(limit)
    if not commits:
        print('  · [delivery-probe] 无法判定：content_sources / archive_ledger 不可读')
        return 0
    existing = {d['id']: d for d in debt.get('debts', [])}
    added = [d for d in ds if d['id'] not in existing]
    for d in added:
        d['note'] = '判据盲区补记（quotepath 修复后浮现的历史旧账，非本轮新增）'
        existing[d['id']] = d
    if added:
        debt['debts'] = sorted(existing.values(), key=lambda x: (x.get('commit_date', ''), x['id']))
        debt['updated'] = datetime.date.today().isoformat()
        save_json_atomic(DEBT, debt)
    print(f'📥 补记入账 {len(added)} 条（窗口 {len(commits)} 个 commit，欠账共 {len(ds)} 条）')
    for d in added:
        print(f'    + {d["id"]:18s} {d["folder"].split("/")[-1]:12s} {d["commit"]} {d["title"][:40]}')
    return 0


def _waive_check(status, until, why, today=None, max_days=90):
    """豁免校验（纯函数，供 selftest 正反向）。返回 (ok, 原因)。

    三道硬条件，缺一即拒——它们分别堵三种洗绿手法：
      · why 写"后续优化/待跟进"这类无主无期的话 → 豁免变成静默删除（B-14）
      · 不写期限 → 豁免变成永久绿（账本 schema 要求带期限，到期转 open）
      · 期限超上限 → 等于变相永久豁免
    """
    today = today or datetime.date.today()
    if status != 'open':
        return False, f'只有 open 账可豁免（当前 {status}）；已还的账不许改成豁免，那是改历史'
    why = (why or '').strip()
    if len(why) < 20:
        return False, f'理由需 ≥20 字且写实（当前 {len(why)} 字）：豁免不是"后续优化"这类无主无期条目'
    if not until:
        return False, '必须给 waived_until（YYYY-MM-DD）：无期限豁免=永久绿'
    try:
        d = datetime.date.fromisoformat(until)
    except Exception:
        return False, f'waived_until 不是合法日期：{until}'
    if d <= today:
        return False, f'waived_until {until} 不晚于今天——那不是豁免，是过期'
    if (d - today).days > max_days:
        return False, f'waived_until 超上限 {max_days} 天（{(d - today).days} 天）：变相永久豁免'
    return True, ''


def waive(ids, until, why, by='agent'):
    """显式豁免正门（三态里的 waived）：不静默删、不假称已还、到期自动转 open。

    为什么要有这个入口：账本 schema 声明三态，但此前只有 open/closed 两个产生
    通道——waived 只能手改 JSON，等于"模型手工记账"（违反本文件 _doc 的口径），
    实操里必然被绕过，或者被随手写成 closed 洗绿。
    """
    debt = load_json(DEBT)
    if not debt:
        print('  · [delivery-probe] 无法判定：delivery_debt.json 不可读')
        return 2
    rows = {d['id']: d for d in debt.get('debts', [])}
    maxd = (debt.get('thresholds') or {}).get('waive_max_days', 90)
    bad, done = [], []
    for i in ids:
        d = rows.get(i)
        if not d:
            bad.append((i, '账本无此 id（先 --audit 看真实 id，别猜）'))
            continue
        ok, msg = _waive_check(d.get('status', ''), until, why, max_days=maxd)
        if not ok:
            bad.append((i, msg))
            continue
        d['status'] = 'waived'
        d['waived_until'] = until
        d['waived_by'] = by
        d['waived_ts'] = datetime.datetime.now().isoformat(timespec='seconds')
        d['note'] = (d.get('note', '') + f'｜豁免至 {until}：{why.strip()}').strip('｜')
        done.append(i)
    if done:
        debt['updated'] = datetime.date.today().isoformat()
        save_json_atomic(DEBT, debt)
        print(f'🏷  已豁免 {len(done)} 条（至 {until}，到期 auto 转 open）：' + '，'.join(done))
    for i, m in bad:
        print(f'  ✗ {i}：{m}')
    return 2 if bad else 0


def scan(limit=None, quiet=False):
    cs = load_json(CS)
    led = load_json(LEDGER)
    debt = load_json(DEBT)
    if not cs or not led or not debt:
        print('  · [delivery-probe] 无法判定：content_sources / archive_ledger / delivery_debt 任一不可读')
        return 0
    flows = cs.get('flows', [])
    ledger_rows = led.get('entries', []) if isinstance(led, dict) else led
    state = _load_state(debt)
    after = state.get('last_sha') or None
    commits = read_commits(limit=limit or cs.get('probe', {}).get('window_commits', 40), after_sha=after)

    existing = {d['id']: d for d in debt.get('debts', [])}
    pre_open = {d['id'] for d in debt.get('debts', []) if d.get('status') == 'open'}
    added, advices = [], []
    for c in commits:
        ds, adv = probe_commit(c, flows, ledger_rows)
        for d in ds:
            if existing.get(d['id']):    # 幂等：同 flow+commit 不重复入账；已还的不重开
                continue
            existing[d['id']] = d
            added.append(d)
        advices.extend(adv)

    # 核销重判：**每次 scan 都跑**（回执可能在不扫新 commit 时补上）——机器销账，无需人工改状态
    just_closed = []
    for d in existing.values():
        if d.get('status') != 'open':
            continue
        fl = next((x for x in flows if x.get('id') == d['flow']), None) \
            or {'id': d['flow'], 'folder': d['folder']}
        # target_version 空（历史账）时从 evidence「VERSION a → b」取 b：判据修正后旧账能自动还，
        # 不必人工 waive/删账（机器核销优先于人手改状态）
        tv = d.get('target_version') or ''
        if not tv and fl.get('close_match') == 'version':
            m = re.search(r'VERSION\s*[\d.]+\s*→\s*([\d.]+)', d.get('evidence') or '')
            tv = m.group(1) if m else ''
        fake = {'short': d['commit'], 'date': d.get('commit_date', ''),
                'msg': d.get('evidence', ''),
                'version': (None, tv or None)}
        hit = _closed(d['folder'], fl, fake, ledger_rows)
        if hit:
            d['status'] = 'closed'
            d['closed_by'] = f'{hit.get("round", "?")} @ {hit.get("ts", "")[:10]}'
            d['note'] = (d.get('note', '') + '｜机器核销：ledger 回执已现').strip('｜')
            just_closed.append(d['id'])

    # 欠债不能躺着：扫描前就在的 open 账，按本轮新扫 commit 数增龄（新账从 0 起算）
    for did in pre_open:
        d = existing.get(did)
        if d and d.get('status') == 'open':
            d['age_commits'] = d.get('age_commits', 0) + len(commits)

    # 过期豁免自动转 open（防洗绿：豁免带期限，到期必须复检）
    today = datetime.date.today().isoformat()
    expired = []
    for d in existing.values():
        wu = d.get('waived_until') or ''
        if d.get('status') == 'waived' and wu and wu < today:
            d['status'] = 'open'
            d['note'] = (d.get('note', '') + f'｜豁免 {wu} 到期自动转 open').strip('｜')
            expired.append(d['id'])

    debt['debts'] = sorted(existing.values(), key=lambda x: (x.get('commit_date', ''), x['id']))
    if commits or just_closed or expired:   # 有变化才写盘（HEAD 未变时零扰动，不弄脏工作区）
        if commits:
            state['last_sha'] = commits[-1]['full']
        state['last_scan_ts'] = datetime.datetime.now().isoformat(timespec='seconds')
        _save_state(state)
        debt['updated'] = today
        save_json_atomic(DEBT, debt)

    open_ds = [d for d in debt['debts'] if d.get('status') == 'open']
    if not quiet:
        if commits:
            print(f'  扫描 {len(commits)} 个新 commit（{commits[0]["short"]}..{commits[-1]["short"]}）')
        elif not just_closed:
            print(f'  ✓ [delivery-probe] 无新 commit（上次扫到 {after[:7] if after else "—"}），无可判对象（绿）')
        print(f'  新增欠账 {len(added)} 条；当前 open {len(open_ds)} 条；'
              f'已豁免 {len([d for d in debt["debts"] if d.get("status") == "waived"])} 条'
              f'（到期自动转 open，不是永久绿）')
        for d in added:
            print(f'    + {d["id"]}  {d["folder"].split("/")[-1]}  ← {d["commit"]} {d["title"][:40]}')
        for a in advices:
            print(f'    ! 提示 {a["commit"]} {a["text"][:90]}')
        if just_closed:
            print(f'  ✓ 机器核销 {len(just_closed)} 条（ledger 回执已现）：' + '，'.join(just_closed))
        if open_ds:
            print('  ✗ [delivery-probe] 存在该产未产欠账（红）：')
            for d in open_ds:
                print(f'      {d["id"]}  龄 {d["age_commits"]} commit  {d["folder"]}  应为「{d["expect"][:30]}」')
            print('     修法：把该轮交付物经 space-hub archive 正门落库并写回执 → 重跑本探测器自动核销')
            return 2
        print('  ✓ [delivery-probe] 全部触发源均有落库回执（绿）')
    return 2 if open_ds else 0


def summary():
    """给 next_anchor / gate_experience 用的摘要（--json）。"""
    debt = load_json(DEBT) or {}
    rows = debt.get('debts', [])
    op = [d for d in rows if d.get('status') == 'open']
    return {'open': len(op), 'closed': len([d for d in rows if d.get('status') == 'closed']),
            'waived': len([d for d in rows if d.get('status') == 'waived']),
            'max_age': max([d.get('age_commits', 0) for d in op], default=0),
            'items': [{'id': d['id'], 'folder': d['folder'], 'commit': d['commit'],
                       'expect': d['expect'], 'age': d.get('age_commits', 0),
                       'title': d.get('title', '')[:60]} for d in op]}


def _ledger_has_report(ver, rows):
    """F11 纯函数：ledger 是否有 target=📦产物归档/文档 且 blob 含该版本号 的 ok 回执。"""
    for e in rows or []:
        if not isinstance(e, dict) or e.get('result') != 'ok':
            continue
        if not (e.get('target') or '').startswith('📦 产物归档/文档'):
            continue
        if ver and ver in json.dumps(e, ensure_ascii=False):
            return True
    return False


def precheck():
    """提交前预检（F11，v0.8.81）：本笔暂存含 VERSION 变更时，账本必须已有当版交付报告回执。

    供 hooks/commit-msg 调用——把「bump 那笔就必须有交付报告」的拦截点提到提交时。
    没有它时账本制只能事后探测（下一笔才报），用户仍得人盯一轮（2026-11-17 三次遭遇）。
    rc: 0=无要求或已满足；3=缺报告（commit-msg 据非零拒）。
    """
    import subprocess
    try:
        ver = open(os.path.join(REPO, 'VERSION'), encoding='utf-8').read().strip()
    except OSError:
        return 0
    try:
        staged = subprocess.run(
            ['git', '-c', 'core.quotepath=false', 'diff', '--cached', '--name-only'],
            cwd=REPO, capture_output=True, text=True, timeout=30).stdout.split()
    except Exception:
        return 0  # 无法判定 fail-open，账本制事后探测仍兜底
    if 'VERSION' not in staged:
        return 0
    try:
        led = json.load(open(LEDGER, encoding='utf-8'))
        rows = led.get('entries', []) if isinstance(led, dict) else led
    except Exception:
        print('  · [F11] 账本不可读，预检无法判定（不阻断；事后探测兜底）')
        return 0
    if _ledger_has_report(ver, rows):
        return 0
    print(f'  ✗ [F11] 本笔 bump {ver}，但账本无对应交付报告回执（📦 产物归档/文档，回执含版本号）')
    print('     → 先写交付报告（目标/交付物/实证/边界/遗留）经 space-hub archive 落库，再提交')
    return 3


def selftest():
    """正反向四用例（纯函数，不碰真实数据）。"""
    # 与真源同源（病15 第19例同族：判据环境里的对象清单手写必脱钩）：
    # 旧实现手写一份 flows 副本，F11 补 close_match 后副本没跟上 → 正向用例假红。
    # 改为直读 content_sources.json，真源改流 selftest 自动跟上，副本不再存在。
    flows = json.load(open(os.path.join(REPO, 'verify', 'content_sources.json'),
                           encoding='utf-8'))['flows']
    ok = True

    def case(name, commit, ledger, want_debts, want_adv=0):
        nonlocal ok
        ds, adv = probe_commit(commit, flows, ledger)
        got = len(ds)
        good = got == want_debts and len(adv) == want_adv
        ok = ok and good
        print(f'  {"✓" if good else "✗"} {name}：欠账 {got}（期望 {want_debts}）/ 提示 {len(adv)}（期望 {want_adv}）')
        for d in ds:
            print(f'      → {d["id"]} {d["folder"].split("/")[-1]}')

    print('── 正向①：Lesson 非空 + 无回执 → 必出欠账')
    case('踩坑文案无回执', {'short': 'aaa1111', 'date': '2026-11-15',
                          'msg': 'fix: x\n\nLesson: 病15(第8例) 判据识别范围过宽',
                          'paths': [], 'version': ('0.8.66', '0.8.66')}, [], 1)
    print('── 正向②：VERSION 变更 + 台账无该版本 → 必出欠账')
    case('版本bump无台账无报告', {'short': 'bbb2222', 'date': '2026-11-15', 'msg': 'v0.8.67 升级',
                          'paths': ['VERSION'], 'version': ('0.8.66', '0.8.67')}, [], 2)
    print('── 反向①：Lesson 写「无」 → 零欠账')
    case('无踩坑', {'short': 'ccc3333', 'date': '2026-11-15', 'msg': 'chore: y\n\nLesson: 无',
                  'paths': [], 'version': ('0.8.66', '0.8.66')}, [], 0)
    print('── 反向②：有对应落库回执 → 核销为零欠账')
    case('有回执', {'short': 'ddd4444', 'date': '2026-11-15',
                  'msg': 'fix: z\n\nLesson: 病15(第9例) 某坑', 'paths': [],
                  'version': ('0.8.66', '0.8.66')},
         [{'result': 'ok', 'target': '🧬 520进化论/01-方法论', 'ts': '2026-11-15T10:00:00',
           'event_ref': 'commit ddd4444'}], 0)
    print('── 反向③：回执早于 commit（旧账不能核销新账）→ 仍欠账')
    case('回执过期', {'short': 'eee5555', 'date': '2026-11-15',
                    'msg': 'fix: w\n\nLesson: 病15(第10例) 某坑', 'paths': [],
                    'version': ('0.8.66', '0.8.66')},
         [{'result': 'ok', 'target': '🧬 520进化论/01-方法论', 'ts': '2026-11-10T10:00:00',
           'event_ref': 'commit eee5555'}], 1)
    print('── 反向④：同夹同日但有回执不指向本 commit（他人回执误销）→ 仍欠账')
    case('他人回执', {'short': 'hhh8888', 'date': '2026-11-15',
                   'msg': 'fix: q\n\nLesson: 病15(第11例) 某坑', 'paths': [],
                   'version': ('0.8.66', '0.8.66')},
         [{'result': 'ok', 'target': '🧬 520进化论/01-方法论', 'ts': '2026-11-15T09:00:00',
           'event_ref': '自愈演示（无关 commit）'}], 1)
    print('── 提示①：Lesson 写「无」但括注实质 → 1 条提示、0 欠账')
    case('逃逸提示', {'short': 'fff6666', 'date': '2026-11-15',
                    'msg': 'chore: v\n\nLesson: 无（假正门属体检发现非踩坑，已订正登记并补四处清单）',
                    'paths': [], 'version': ('0.8.66', '0.8.66')}, [], 0, 1)
    print('── 正向③：台账回执不含目标版本号 → 不算核销（版本流专项）')
    case('台账版本不符且无报告', {'short': 'ggg7777', 'date': '2026-11-15', 'msg': 'v0.8.67 升级',
                       'paths': ['VERSION'], 'version': ('0.8.66', '0.8.67')},
         [{'result': 'ok', 'target': '🧬 520进化论/版本演化台账', 'ts': '2026-11-15T10:00:00',
           'note': '记了 0.8.66'}], 2)
    print('── F11 正向：bump + 台账齐但无交付报告 → 仅 F11 欠账')
    case('有台账无报告', {'short': 'iii9999', 'date': '2026-11-15', 'msg': 'v0.8.67 升级',
                     'paths': ['VERSION'], 'version': ('0.8.66', '0.8.67')},
         [{'result': 'ok', 'target': '🧬 520进化论/版本演化台账', 'ts': '2026-11-15T10:00:00',
           'note': '记了 0.8.67'}], 1)
    print('── F11 反向：bump + 台账 + 交付报告回执（含当版版本号）→ 零欠账')
    # 核销凭据＝当版版本号（close_match=version），非本 commit sha：
    # F11 要求提交前落报告，彼时 sha 尚未生成，用 sha 会成鸡生蛋死锁（D-3e457d1-F11 实测）。
    case('台账报告双齐', {'short': 'jjj0000', 'date': '2026-11-15', 'msg': 'v0.8.67 升级',
                     'paths': ['VERSION'], 'version': ('0.8.66', '0.8.67')},
         [{'result': 'ok', 'target': '🧬 520进化论/版本演化台账', 'ts': '2026-11-15T10:00:00',
           'note': '记了 0.8.67'},
          {'result': 'ok', 'target': '📦 产物归档/文档', 'ts': '2026-11-15T10:05:00',
           'event_ref': '交付报告 v0.8.67'}], 0)
    print('── F11 反向：报告版本不对（上一版）→ 仍欠账（他人/旧报告不核销）')
    case('他人报告', {'short': 'kkk1111', 'date': '2026-11-15', 'msg': 'v0.8.67 升级',
                   'paths': ['VERSION'], 'version': ('0.8.66', '0.8.67')},
         [{'result': 'ok', 'target': '🧬 520进化论/版本演化台账', 'ts': '2026-11-15T10:00:00',
           'note': '记了 0.8.67'},
          {'result': 'ok', 'target': '📦 产物归档/文档', 'ts': '2026-11-15T10:05:00',
           'event_ref': '交付报告 v0.8.66'}], 1)

    # ── F11 交付报告预检（纯函数两例，绕开 probe_commit 串扰）
    print('── F11 预检：账本回执须含当版版本号')
    _r1 = _ledger_has_report('0.8.81', [
        {'result': 'ok', 'target': '📦 产物归档/文档', 'event_ref': '报告 v0.8.81'}])
    ok = ok and _r1
    print(f'  {"✓" if _r1 else "✗"} F11预检-有报告放行（期望 True）')
    _r2 = _ledger_has_report('0.8.81', [
        {'result': 'ok', 'target': '📦 产物归档/文档', 'event_ref': '报告 v0.8.80'}])
    ok = ok and (not _r2)
    print(f'  {"✓" if not _r2 else "✗"} F11预检-版本不符不算数（期望 False）')
    _r3 = _ledger_has_report('0.8.81', [
        {'result': 'ok', 'target': '🧬 520进化论/01-方法论', 'event_ref': '报告 v0.8.81'}])
    ok = ok and (not _r3)
    print(f'  {"✓" if not _r3 else "✗"} F11预检-落错夹不算数（期望 False）')

    # ── 病15 第13例：msg_version 的核销凭据必须能指回本 commit（9 例正反向）
    #    直接测 _closed 纯函数，避开 probe_commit 里 F02/F09 串扰（识别范围=对象范围）。
    print('── 病15 第13例：msg_version 核销凭据须指回本 commit（9 例正反向）')
    f04f = '🧬 520进化论/03-子项目演进'
    f04 = {'id': 'F04', 'folder': f04f, 'close_match': 'msg_version'}
    w2 = {'short': 'j13aaa1xxx', 'date': '2026-11-15',
          'msg': ('v0.8.76 熔铸司 W2 引擎上提\n承接 W1（v0.8.75）；沿用 v0.8.4 范式；'
                  '版本四处对齐 1.1.0；VERSION 0.8.76'),
          'version': ('0.8.75', '0.8.76'),
          'paths': ['通用层/skills/foundry/CHANGELOG.md']}

    def L13(note, **kw):
        return dict({'result': 'ok', 'target': f04f, 'ts': '2026-11-15T20:10:00',
                     'event_ref': '他人 commit', 'note': note}, **kw)

    def ccase(name, ledger, want):
        nonlocal ok
        got = _closed(f04f, f04, w2, ledger) is not None
        good = got == want
        ok = ok and good
        print(f'  {"✓" if good else "✗"} {name}：核销 {got}（期望 {want}）')

    ccase('他人回执含技能版本 1.1.0（原始踩坑）', [L13('artifact-store v1.1.0 变更说明落库')], False)
    ccase('他人回执含承接版本 v0.8.75', [L13('承接 v0.8.75 说明')], False)
    ccase('他人回执含范式版本 v0.8.4', [L13('沿用 v0.8.4 范式')], False)
    ccase('他人回执只含无关版本 2.3.4', [L13('无关技能 2.3.4 落库')], False)
    ccase('本 commit 短 sha 可核销', [L13('演进说明落库 @ commit j13aaa1')], True)
    ccase('本次 bump 目标版本 0.8.76 可核销', [L13('foundry 演进说明 v0.8.76 落库')], True)
    ccase('result!=ok 不销', [L13('commit j13aaa1 落库', result='fail')], False)
    ccase('旧账不销新账', [L13('commit j13aaa1 落库', ts='2026-11-10T10:00:00')], False)
    ccase('回执 target 不命中', [L13('commit j13aaa1 落库', target='🧬 520进化论/别的夹')], False)

    print('── 正向④：豁免校验三条件齐备 → 放行')
    today = datetime.date.today()

    def wcase(name, status, until, why, want):
        nonlocal ok
        got, msg = _waive_check(status, until, why, today=today)
        good = got == want
        ok = ok and good
        print(f'  {"✓" if good else "✗"} {name}：{"放行" if got else "拒绝"}（期望 {"放行" if want else "拒绝"}）'
              + ('' if got else f' — {msg[:40]}'))

    wcase('理由充分+限期30天', 'open', (today + datetime.timedelta(days=30)).isoformat(),
          '判据盲区期的历史旧账，按不回溯原则不追补，留痕待复检', True)
    print('── 反向⑤：理由写「后续优化」→ 拒（无主无期，B-14）')
    wcase('理由空话', 'open', (today + datetime.timedelta(days=30)).isoformat(), '后续优化', False)
    print('── 反向⑥：不写期限 → 拒（否则=永久绿）')
    wcase('无期限', 'open', '', '判据盲区期的历史旧账，按不回溯原则不追补', False)
    print('── 反向⑦：期限已过/就是今天 → 拒')
    wcase('过期期限', 'open', today.isoformat(), '判据盲区期的历史旧账，按不回溯原则不追补', False)
    print('── 反向⑧：期限超上限 90 天 → 拒（变相永久）')
    wcase('超上限', 'open', (today + datetime.timedelta(days=200)).isoformat(),
          '判据盲区期的历史旧账，按不回溯原则不追补', False)
    print('── 反向⑨：已 closed 的账改成豁免 → 拒（那是改历史）')
    wcase('改历史', 'closed', (today + datetime.timedelta(days=30)).isoformat(),
          '判据盲区期的历史旧账，按不回溯原则不追补', False)

    print('✓ selftest 全通过（探测器活着，正反向皆如预期）' if ok
          else '✗ selftest 有失败——闸失灵，不许上线')
    return 0 if ok else 2


def selftest_quotepath():
    """病15 第 11 例的**回归用例**：直接拿真 git 输出验「中文路径能看见」。

    为什么必须走真 git：出问题的是 `read_commits` 取路径那一步（quotepath 转义），
    而 signal_hit 的用例喂的是**合成路径列表**——合成数据永远不含转义，
    所以原来那 8 个用例 100% 绿也照样漏掉 5 条流整体失效。判据的用例
    如果绕开了真实取值链路，等于没测（B-13 看落点不看断言）。
    """
    commits = read_commits(limit=20)
    paths = [p for c in commits for p in (c.get('paths') or [])]
    zh = [p for p in paths if any('\u4e00' <= ch <= '\u9fff' for ch in p)]
    # ★ 先判转义、再判样本：转义后的路径**不含汉字**（`"\350\203\275..."`），
    #   若先按「有汉字吗」判样本，回归会退化成"无法判定：未触及中文路径"——看着像没数据，
    #   实则正是 bug 本身。这是本条用例第一版的原样漏洞，反向实测（摘掉 quotepath=false）
    #   打出来的就是"无法判定"而不是红。判定顺序错 = 闸不判红（病15 第 11 例的套娃）。
    esc = [p for p in paths if p.startswith('"') or '\\3' in p]
    if esc:
        print(f'  ✗ quotepath 回归：{len(esc)} 条路径被转义，如 {esc[0][:40]}——中文路径判据会整体失明')
        return False
    if not paths:
        print('  · 无法判定：最近 20 个 commit 取不到路径（空仓或 git 不可用）')
        return None
    if not zh:
        print('  · 无法判定：最近 20 个 commit 未触及中文路径，本用例样本不足（不当绿）')
        return None
    print(f'  ✓ quotepath 回归：{len(zh)}/{len(paths)} 条中文路径原样可见（如 {zh[0][:50]}）')
    return True


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--selftest' in a:
        rc = selftest()
        qp = selftest_quotepath()
        if qp is False:
            rc = 2
        sys.exit(rc)
    if '--json' in a:
        print(json.dumps(summary(), ensure_ascii=False))
        sys.exit(0)
    if '--list' in a:
        s = summary()
        print(f"open {s['open']} / closed {s['closed']} / waived {s['waived']}  max_age {s['max_age']}")
        for d in s['items']:
            print(f"  {d['id']}  龄{d['age']}  {d['folder']}  ← {d['commit']}  {d['title']}")
        sys.exit(0)

    def _num(flag, default):
        return int(a[a.index(flag) + 1]) if flag in a else default

    if '--audit' in a:
        sys.exit(audit(_num('--audit', 40)))
    if '--backfill' in a:
        sys.exit(backfill(_num('--backfill', 40)))
    if '--precheck' in a:
        sys.exit(precheck())
    if '--waive' in a:
        ids, i = [], a.index('--waive') + 1
        while i < len(a) and not a[i].startswith('--'):
            ids.append(a[i])
            i += 1
        until = a[a.index('--until') + 1] if '--until' in a else ''
        why = a[a.index('--why') + 1] if '--why' in a else ''
        if not ids:
            print('  ✗ --waive 需要至少一个欠账 id（先 --list 看清单）')
            sys.exit(2)
        sys.exit(waive(ids, until, why))
    lim = None
    if '--commits' in a:
        lim = int(a[a.index('--commits') + 1])
    sys.exit(scan(limit=lim))
