#!/usr/bin/env python3
"""v0.8.64 方案v3：落地监测三面（M9 总览 / M10 薄弱 / M11 项目追踪）。
契约与既有 chk_* 一致：chk(target, cfg, ctx) -> {'status', 'items'}。
三态铁律：取不到/失败 → 白（无法判定），绝不装绿；数据源全部离线为主，census 一项可失败降级。
"""
import ast, datetime, glob, json, os, re, subprocess

TH = lambda ctx, k, dflt: (ctx.get('thresholds') or {}).get(k, dflt)


def _worst(ctx, sts):
    """聚合器：优先复用引擎 worst（单一真源），异常时本地降级实现（三态顺序一致）。"""
    f = ctx.get('worst')
    if f:
        return f(sts)
    order = ['green', 'yellow', 'red', 'unknown', 'pending']
    for k in ('red', 'unknown', 'yellow', 'pending', 'green'):
        if k in sts:
            return k
    return 'unknown'


def _repo(target, cfg):
    return cfg.get('repo') or target


def _ledger(repo):
    return os.path.join(repo, 'archive_ledger.json')


def _load_ledger_safe(repo):
    p = _ledger(repo)
    if not os.path.isfile(p):
        return 'missing', None, p
    try:
        d = json.load(open(p, encoding='utf-8'))
        if not isinstance(d, dict) or not isinstance(d.get('entries'), list):
            return 'corrupt', None, p
        return 'ok', d['entries'], p
    except Exception as e:
        return 'corrupt', repr(e), p


def chk_overview(target, cfg, ctx):
    """M9 总览面：520 整体情况（版本/技能/分片/落库回执/云端缝率）。"""
    items, sts = [], []
    repo = _repo(target, cfg)
    # 1) 版本
    vp = os.path.join(repo, 'VERSION')
    try:
        ver = open(vp, encoding='utf-8').read().strip()
        items.append({'t': f'【绿】520pro 版本 {ver}', 'e': 'VERSION 文件', 'c': '无需处置'})
        sts.append('green')
    except Exception as e:
        items.append({'t': '【白】VERSION 读取失败，无法判定', 'e': repr(e), 'c': '核对仓库完整性'})
        sts.append('unknown')
    # 2) 技能与分片
    skills = os.path.expanduser(cfg.get('install_root', '~/.codebuddy/skills'))
    n_skill = len([d for d in glob.glob(os.path.join(skills, '*',)) if os.path.isdir(d)])
    n_shard = 0
    for p in glob.glob(os.path.join(skills, '*', 'artifacts.json')):
        try:
            if isinstance(json.load(open(p, encoding='utf-8')).get('blueprint'), dict):
                n_shard += 1
        except Exception:
            pass
    if n_shard:
        items.append({'t': f'【绿】技能 {n_skill} 个 / 蓝图分片 {n_shard} 个（产出自动跟随）',
                      'e': skills, 'c': '无需处置'})
        sts.append('green')
    else:
        items.append({'t': '【黄】零蓝图分片——产出将落「未归类」', 'e': skills, 'c': '核对 artifacts.json 安装完整性'})
        sts.append('yellow')
    # 3) 落库回执（今日）
    st, entries, p = _load_ledger_safe(repo)
    today = datetime.date.today().isoformat()
    if st == 'ok':
        n_today = sum(1 for e in entries if (e.get('ts') or '')[:10] == today and e.get('result') == 'ok')
        items.append({'t': f'【绿】archive_ledger 今日落库回执 {n_today} 条', 'e': p, 'c': '无需处置'})
        sts.append('green')
    elif st == 'missing':
        items.append({'t': '【白】archive_ledger 缺失，落库对账无法判定', 'e': p, 'c': '跑方案 v3 步骤补建'})
        sts.append('unknown')
    else:
        items.append({'t': '【红】archive_ledger 损坏（数据基座塌陷 M-R58）', 'e': str(entries)[:120], 'c': '从 Git 恢复或修复 JSON'})
        sts.append('red')
    # 4) 云端缝率（census，可失败降级为无法判定）
    try:
        sh = cfg.get('space_hub', os.path.expanduser('~/.codebuddy/skills/space-hub/scripts/space_hub.py'))
        r = subprocess.run(['python3', sh, 'census'], capture_output=True, text=True, timeout=25)
        m = re.search(r'缝（无主）(\d+)（(\d+)%\）', r.stdout)
        if m:
            pct = int(m.group(2))
            if pct <= 20:
                items.append({'t': f'【绿】云端缝率 {pct}%（{m.group(1)} 个）', 'e': 'space-hub census', 'c': '无需处置'})
                sts.append('green')
            else:
                items.append({'t': f'【黄】云端缝率 {pct}%——归属治理欠账', 'e': 'space-hub census', 'c': '补 space_hub_zones.json 登记'})
                sts.append('yellow')
        else:
            items.append({'t': '【白】census 输出无缝率行，无法判定', 'e': r.stdout[-120:], 'c': '手跑 census 核查'})
            sts.append('unknown')
    except Exception as e:
        items.append({'t': '【白】census 调用失败（云端不可达/超时），无法判定', 'e': repr(e)[:120], 'c': '网络恢复后复跑'})
        sts.append('unknown')
    return {'status': _worst(ctx, sts), 'items': items}


def chk_weakness(target, cfg, ctx):
    """M10 薄弱面：遗留登记待办/超期、ledger pending、近期 bump 密度。"""
    items, sts = [], []
    repo = _repo(target, cfg)
    today = datetime.date.today()
    # 1) 遗留登记
    lp = os.path.join(repo, 'docs', '遗留登记.md')
    try:
        txt = open(lp, encoding='utf-8').read()
        n_open = txt.count('【待】')
        overdue = []
        for m in re.finditer(r'期限：(\d{4}-\d{2}-\d{2})', txt):
            try:
                if datetime.date.fromisoformat(m.group(1)) < today:
                    overdue.append(m.group(1))
            except ValueError:
                pass
        if overdue:
            items.append({'t': f'【红】遗留登记超期 {len(overdue)} 条 / 待办 {n_open} 条', 'e': '期限<' + today.isoformat() + ': ' + ', '.join(overdue[:4]), 'c': '逐条闭环或改期（B-14）'})
            sts.append('red')
        else:
            items.append({'t': f'【绿】遗留登记 {n_open} 条待办，0 超期', 'e': 'docs/遗留登记.md', 'c': '无需处置'})
            sts.append('green')
    except FileNotFoundError:
        items.append({'t': '【白】遗留登记文件缺失，无法判定', 'e': lp, 'c': '巡检司 M6 面数据源核对'})
        sts.append('unknown')
    # 2) ledger pending
    st, entries, p = _load_ledger_safe(repo)
    if st == 'ok':
        n_pend = sum(1 for e in entries if e.get('result') == 'pending')
        if n_pend > 10:
            items.append({'t': f'【黄】ledger pending {n_pend} 条——待归档欠账偏多', 'e': p, 'c': 'products --retry 补投或人工处置后销账'})
            sts.append('yellow')
        else:
            items.append({'t': f'【绿】ledger pending {n_pend} 条（含说明性欠账）', 'e': p, 'c': '无需处置'})
            sts.append('green')
    else:
        items.append({'t': '【白】ledger 不可读，pending 无法判定', 'e': str(entries)[:100], 'c': 'M9 已报，此处不重复'})
        sts.append('unknown')
    # 3) 近 3 天 bump 密度（改动活跃度提示）
    n_bump = 0
    for cl in glob.glob(os.path.join(repo, '**', 'CHANGELOG.md'), recursive=True):
        try:
            head = open(cl, encoding='utf-8').read(3000)
        except Exception:
            continue
        for m in re.finditer(r'^## v[\d.]+ — (\d{4}-\d{2}-\d{2})', head, re.M):
            try:
                if (today - datetime.date.fromisoformat(m.group(1))).days <= 3:
                    n_bump += 1
                    break
            except ValueError:
                pass
    items.append({'t': f'【绿】近 3 天 {n_bump} 个技能有版本 bump（活跃度事实行）', 'e': 'CHANGELOG 扫描', 'c': '活跃≠风险，供总览参考'})
    sts.append('green')
    return {'status': _worst(ctx, sts), 'items': items}


def chk_projects(target, cfg, ctx):
    """M11 项目面：逐技能版本/最近变更/最近落库回执——具体项目落地追踪。"""
    items, sts = [], []
    repo = _repo(target, cfg)
    st, entries, _p = _load_ledger_safe(repo)
    yd = TH(ctx, 'stale_yellow_days', 14)
    rd = TH(ctx, 'stale_red_days', 30)
    today = datetime.date.today()
    proj = cfg.get('projects') or [
        ('探源司', '能力层/tvbox/skills/probe-hub'),
        ('整包坊', '能力层/tvbox/skills/tvbox-pipeline'),
        ('库务司', '通用层/skills/space-hub'),
        ('巡检司', '通用层/skills/inspect-hub'),
        ('学习工坊', '通用层/skills/learn-hub'),
    ]
    for name, rel in proj:
        base = os.path.join(repo, rel)
        sk = os.path.join(base, 'SKILL.md')
        cl = os.path.join(base, 'CHANGELOG.md')
        ver, last, last_day = '', '', None
        try:
            m = re.search(r'^version:\s*"?([^"\n]+)"?', open(sk, encoding='utf-8').read(6000), re.M)
            ver = (m.group(1) if m else '?').strip()
        except Exception:
            pass
        try:
            # 病15 第29例：旧正则只认 `## vX — YYYY-MM-DD`（日期紧跟破折号），探源司写
            # `## v1.28.9 — 描述（2026-11-15）`（日期在尾括号）→ 首4000字无合规行、更旧的
            # 合规行被 read(4000) 截断 → 误报「无法判定」。放宽为：取首条 `## vX` 行，
            # 日期在行内任意位置（紧跟破折号或尾括号均可），读 8000 字；只取首条=最新。
            head = open(cl, encoding='utf-8').read(8000)
            hm = re.search(r'^## (v[\d.]+)[^\n]*', head, re.M)
            if hm:
                dm = re.search(r'(\d{4}-\d{2}-\d{2})', hm.group(0))
                if dm:
                    last, last_day = hm.group(1), datetime.date.fromisoformat(dm.group(1))
        except Exception:
            pass
        if not last_day:
            items.append({'t': f'【白】{name}：版本 {ver or "取不到"}，最近变更无法判定', 'e': rel, 'c': '核对 CHANGELOG'})
            sts.append('unknown')
            continue
        days = (today - last_day).days
        # ledger 里该技能最近回执
        last_ok = ''
        if st == 'ok':
            for e in reversed(entries):
                if e.get('result') == 'ok' and name in json.dumps(e, ensure_ascii=False):
                    last_ok = (e.get('ts') or '')[:10]
                    break
        if days >= rd:
            items.append({'t': f'【红】{name} v{ver}：最近变更 {last}（{days} 天前）≥ {rd} 天停更', 'e': rel, 'c': '确认是否需要保鲜或宣布冻结'})
            sts.append('red')
        elif days >= yd:
            items.append({'t': f'【黄】{name} v{ver}：最近变更 {last}（{days} 天前）', 'e': rel, 'c': '观察新鲜度'})
            sts.append('yellow')
        else:
            items.append({'t': f'【绿】{name} v{ver}：最近变更 {last}（{days} 天前）｜最近落库回执 {last_ok or "无"}',
                          'e': rel, 'c': '无需处置'})
            sts.append('green')
    return {'status': _worst(ctx, sts), 'items': items}


# ── v0.8.73 闸化登记实证（M12 经验门 yellow 机制级消解）──────────────────
# 背景：判4 原只读 experience_recurrence.counters，病15 count=7 就永远报
#   「须升【阻】或闸化」yellow，即使该病早已闸化（词边界+8形态 selftest）。
# 真源纪律：experience_recurrence.json 是 hook 机器记账、doc 明写「AI 不手工记账」，
#   改 count/status 消黄 = 洗绿，禁止。正解是让判据采信「已闸化登记」并实证落点。
# 病15 同型坑（识别范围≠对象范围）：若只扫「出现 --selftest 字样」会把注释/
#   docstring/示例当落点（gate_scan.py 第6例镜像）；收严成「只认整行精确锚点」
#   又漏掉别的真实写法。这里用 ast 结构化节点识别——注释/docstring 造不出
#   FunctionDef/Call 节点，天然排除；五种后接写法全覆盖（见 gate_experience --selftest）。


def _selftest_landed(src, anchor=''):
    """ast 结构化实证：落点脚本确有 selftest 函数定义且接电（+可选判据锚点）。

    五种后接形态（真实 Python 写法）全覆盖：
      ① def selftest():          ② async def selftest():      ③ 方法/test_ 前缀
      ④ '--selftest' 字符串开关（argv/argparse）  ⑤ selftest() 调用出口（SystemExit/sys.exit/裸调用）
    反例天然排除：注释 `# def selftest()`、docstring 里的字样都不产生节点。
    返回 (landed: bool, reason: str)。
    """
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError) as ex:
        return False, f'落点脚本语法不可解析 {str(ex)[:30]}'
    defs, wired, invokes, nonempty = [], 0, 0, 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                ('selftest' in node.name.lower() or node.name.startswith('test_')):
            defs.append(node.name)
            body = [s for s in node.body
                    if not isinstance(s, ast.Pass)
                    and not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                             and isinstance(s.value.value, str))]   # 排除 docstring
            if body:
                nonempty += 1
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and '--selftest' in node.value:
            wired += 1
        if isinstance(node, ast.Call):
            fn = node.func
            nm = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else '')
            if nm == 'selftest':
                invokes += 1
    if not defs:
        return False, '落点脚本无 selftest 函数定义（注释/docstring 不算）'
    if not (wired or invokes):
        return False, 'selftest 未接电（无 --selftest 开关 / 调用出口）'
    if nonempty == 0:
        return False, 'selftest 是空壳（仅 pass/docstring）'
    if anchor:
        hit = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    ('selftest' in node.name.lower() or node.name.startswith('test_')):
                for i, s in enumerate(node.body):
                    if i == 0 and isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) \
                            and isinstance(s.value.value, str):
                        continue                                    # 跳过 docstring
                    for sub in ast.walk(s):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and anchor in sub.value:
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    break
        if not hit:
            return False, f'selftest 体内未见判据锚点 {anchor}（注释不算）'
    return True, f'def×{len(defs)}/非空×{nonempty}/开关×{wired}/调用×{invokes}' + \
                 (f'/锚点{anchor}命中' if anchor else '')


def _gate_landed(repo, gate):
    """实证一条「已闸化登记」：结构化字段 + 落点脚本存在 + selftest 真实落地。
    返回 (landed: bool, reason: str)。三态由调用方包装（取不到记无法判定，不折叠）。"""
    if not isinstance(gate, dict):
        return False, 'gate 非结构化登记'
    script = (gate.get('script') or '').strip()
    if not script:
        return False, 'gate 缺落点脚本'
    path = script if os.path.isabs(script) else os.path.join(repo, script)
    if not os.path.isfile(path):
        return False, f'落点脚本不存在 {script}'
    try:
        src = open(path, encoding='utf-8').read()
    except OSError as ex:
        return False, f'落点脚本不可读 {str(ex)[:40]}'
    return _selftest_landed(src, (gate.get('anchor') or '').strip())


def chk_contentflow(target, cfg, ctx):
    """M12 内容流面（v0.8.64 经验闭环）：五判据+经验效果三指标。
    数据源全离线：archive_ledger / content_sources / experience_recurrence。
    原则：空夹不是病，供给信号已现而内容没落才是病；豁免必须显式带期限。"""
    import json as _json
    repo = _repo(target, cfg)
    items, sts = [], []
    LEDGER_EXEMPT_UNTIL = '2026-12-15'  # legacy 豁免显式登记（带期限，到期自动转红）

    led = _load_ledger_safe(repo)
    today = datetime.date.today()

    # 判1 账实脱节：ok 回执无 target
    if led[0] == 'ok':
        entries = led[1]
        no_target = [e for e in entries if e.get('result') == 'ok' and not (e.get('target') or '').strip()]
        # legacy 豁免显式可见（不是隐藏）：豁免条目数+期限列出
        if no_target and today.isoformat() <= LEDGER_EXEMPT_UNTIL:
            items.append({'s': 'yellow', 't': f'账实脱节(豁免中): {len(no_target)} 行无 target',
                          'e': f'legacy 豁免至 {LEDGER_EXEMPT_UNTIL}，到期未补即转红'})
            sts.append('yellow')
        elif no_target:
            items.append({'s': 'red', 't': f'账实脱节: {len(no_target)} 行 ok 回执无 target',
                          'e': '豁免已过期（2026-12-15），补 target 或显式续期'})
            sts.append('red')
        else:
            items.append({'s': 'green', 't': '账实脱节: 0', 'e': '全部 ok 回执带 target 落点'})

        # 判2 无源内容（event_ref；legacy 豁免同期限）
        LEGACY_ROUNDS = {'backfill-20261115', 'v1.28.5'}  # 上线前批次=legacy 豁免
        no_ref = [e for e in entries if e.get('result') == 'ok' and not (e.get('event_ref') or '').strip()
                  and e.get('round') not in LEGACY_ROUNDS]
        if no_ref:
            items.append({'s': 'red', 't': f'无源内容: {len(no_ref)} 条(新账)', 'e': '回执缺 event_ref(指向 commit/run)'})
            sts.append('red')
        else:
            items.append({'s': 'green', 't': '无源内容: 0(新账)', 'e': '2026-11-15 起回执均带 event_ref；存量 legacy 豁免至 ' + LEDGER_EXEMPT_UNTIL})
            sts.append('green')

        # 判3 内容流断路：供给信号已现而夹空（ledger target 代理）
        cs_path = os.path.join(repo, 'verify', 'content_sources.json')
        try:
            # v2.0.0：只判 kind=folder 的流（ledger 类流是云端库，无 doc 回执，判了必假红）
            flows = [f for f in _json.load(open(cs_path, encoding='utf-8')).get('flows', [])
                     if f.get('kind', 'folder') == 'folder']
            covered = set()
            for e in entries:
                if e.get('result') == 'ok' and e.get('target'):
                    for f in flows:
                        if e['target'].startswith(f['folder']):
                            covered.add(f['folder'])
            empty = [f['folder'].split('/')[-1] for f in flows if f['folder'] not in covered]
            if empty:
                items.append({'s': 'yellow', 't': f'内容流断路: {len(empty)}/{len(flows)} 夹无入库',
                              'e': '，'.join(empty) + '（供给源登记于 content_sources.json）'})
                sts.append('yellow')
            else:
                items.append({'s': 'green', 't': f'内容流: {len(flows)} 夹全有入库', 'e': ''})
                sts.append('green')
        except Exception as ex:
            items.append({'s': 'unknown', 't': 'content_sources 不可读', 'e': str(ex)[:80]})
            sts.append('unknown')
    else:
        items.append({'s': 'unknown', 't': 'archive_ledger 不可读', 'e': str(led[0])})
        sts.append('unknown')

    # 判4 经验复发（≥3 verify 黄）——v0.8.73：已闸化登记实证后不再报「须升【阻】或闸化」
    rec_path = os.path.join(repo, 'experience_recurrence.json')
    try:
        rec = _json.load(open(rec_path, encoding='utf-8'))
        hot = [(k, v.get('count', 0)) for k, v in rec.get('counters', {}).items()
               if v.get('count', 0) >= 3 and v.get('status', 'active') != 'retired']
        # 闸化登记：ctx 可注入 gate_registry（selftest 用，不污染真账本），否则读映射表
        reg = ctx.get('gate_registry') if ctx else None
        if reg is None:
            try:
                mp = _json.load(open(os.path.join(repo, 'verify', '病号映射表.json'), encoding='utf-8'))
                reg = {d.get('id'): d.get('gate') for d in mp.get('diseases', []) if d.get('gate')}
            except Exception:
                reg = {}
        gated, ungated, detail = [], [], []
        for k, n in hot:
            g = reg.get(k)
            if not g:
                ungated.append((k, n))
                detail.append(f'{k}: 无闸化登记')
                continue
            ok, why = _gate_landed(repo, g)
            (gated if ok else ungated).append((k, n))
            detail.append(f'{k}: {"已闸化(" + why + ")" if ok else "登记未落地(" + why + ")"}')
        if ungated:
            items.append({'s': 'yellow', 't': f'经验复发超限: {len(ungated)} 病号≥3次未闸化',
                          'e': '，'.join(f'{k}×{n}' for k, n in ungated) + '（须升【阻】或闸化）'})
            sts.append('yellow')
        elif gated:
            items.append({'s': 'green', 't': f'经验复发: {len(gated)} 病号≥3次已闸化',
                          'e': '；'.join(detail) + '｜落点脚本+selftest 实证，计数不洗绿'})
            sts.append('green')
        else:
            items.append({'s': 'green', 't': '经验复发: 无超限病号', 'e': '复发计数 hook 自动记账'})
            sts.append('green')
    except Exception:
        items.append({'s': 'unknown', 't': '复发计数不可读', 'e': 'experience_recurrence.json'})
        sts.append('unknown')

    # 经验效果三指标（消费判据：试错次数=拦截到放行尝试数；复发间隔；纠偏计数）
    try:
        rec = _json.load(open(rec_path, encoding='utf-8'))
        dc = rec.get('direction_cases', [])
        items.append({'s': 'green', 't': f'效果指标: 病号{len(rec.get("counters", {}))}个/方向纠偏{len(dc)}例',
                      'e': '试错次数与复发间隔随 hook 事件累积，目标试错≤1次'})
        sts.append('green')
    except Exception:
        pass

    return {'status': _worst(ctx, sts), 'items': items}


# impl: B-15 S5 ← 痊愈机判：active→观察→retired 状态机由机器推进，不再手工标
def chk_cure(target, cfg, ctx):
    """M12-补 痊愈机判（v0.8.66）：扫 experience_recurrence.json 的 last_ts，
    跨 cure_rounds（默认10）个自然日无新复发自动降级：active→观察→retired。
    「轮」以自然日近似（每轮 verify.sh 至少跑一次的日子≈日），doc 真源见 experience_recurrence.json rules。
    机器直接原子写回状态（单进程闸内执行，os.replace 保证不写坏）；retired 病号自动移出注入池。"""
    import json as _json
    repo = _repo(target, cfg)
    items, sts = [], []
    rec_path = os.path.join(repo, 'experience_recurrence.json')
    if not os.path.isfile(rec_path):
        return {'status': 'unknown',
                'items': [{'s': 'unknown', 't': '复发计数不可读', 'e': 'experience_recurrence.json 缺失'}]}
    try:
        rec = _json.load(open(rec_path, encoding='utf-8'))
    except Exception as ex:
        return {'status': 'unknown',
                'items': [{'s': 'unknown', 't': '复发计数不可读（损坏不折叠）', 'e': str(ex)[:80]}]}
    rules = rec.get('rules', {})
    cure = int(rules.get('cure_rounds', 10))
    today = datetime.date.today()
    changed = []
    counters = rec.get('counters', {})
    for bid, c in counters.items():
        st = c.get('status', 'active')
        if st == 'retired':
            continue
        last = c.get('last_ts') or ''
        try:
            days = (today - datetime.date.fromisoformat(last)).days if last else None
        except ValueError:
            days = None
        if days is None:
            items.append({'s': 'unknown', 't': f'{bid} last_ts 缺失/损坏——不折叠为痊愈', 'e': str(last)[:20]})
            sts.append('unknown')
            continue
        if st == 'active' and days >= cure:
            c['status'] = '观察'
            changed.append(f'{bid} active→观察（{days}日无复发）')
        elif st == '观察' and days >= cure:
            c['status'] = 'retired'
            changed.append(f'{bid} 观察→retired（再{days}日无复发，移出注入池）')
    if changed:
        tmp = rec_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            _json.dump(rec, f, ensure_ascii=False, indent=1)
        os.replace(tmp, rec_path)
        items.append({'s': 'yellow', 't': f'痊愈机判降级 {len(changed)} 病号', 'e': '；'.join(changed)})
        sts.append('yellow')
    else:
        n_ret = len([1 for c in counters.values() if c.get('status') == 'retired'])
        items.append({'s': 'green', 't': f'痊愈机判: 无降级（病号{len(counters)}个/已retired {n_ret}）',
                      'e': f'机器判据：{cure} 自然日无复发自动降级'})
        sts.append('green')
    return {'status': _worst(ctx, sts), 'items': items}
