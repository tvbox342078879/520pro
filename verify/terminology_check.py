#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""terminology_check.py —— 口径机检（core-8 元规则 M4/M5 的可机检部分）

为什么有这个脚本：core-8 元规则 M5 写的是「改真源后同步所有指针点；跑通才算完成
（断链 / 词表误用 / 编号越界 / 复制条款四类须全绿）」，skill-evolution 的 SKILL.md 也写着
「收尾跑 verify/terminology_check.py（C5）」——但 2026-11-12 实查发现**这个脚本根本不存在**，
属于规则被引用、入口是空的（文档断链）。

本脚本做**能可靠机检的四类**，宁可少判也不误判（误报一多，人就会整体忽略它）：

  ① 编号越界：core-8 里 B-01…B-16、M1…M7 必须连续、不重号、不跳号（M4）
  ② 引用断链：文档中明确指向**本仓内**的路径（verify/ 通用层/ 能力层/ docs/ 开头），
     文件不存在即报（M2/M5）
  ③ 规则↔验证器互引（E10）：verify/rule_map.json 与 core-8 双向一致；machine 项的锚点
     必须真实存在（防实现漂移后映射还在假装有效）；manual 项必须写清怎么问，且不计为通过
  ④ 保留域前缀（F-8）：规则真源里出现的 `X-NN` 编号，前缀必须是 M4 登记的 B / M-R / V，
     否则就是自造了一个没人定义过的标签
  ⑤ 账目-落点一致性（T6，v0.8.82 增量）：交接册（handoff）把某对象记「无法判定/未实测」，
     但检查单/实证记录里同一对象已「已实证」——按 B-14「账目与落点冲突以落点为准」，
     账目必须回写，否则读 handoff 的人以为还没做。只配**受控话题词**，不扫全文
     "无法判定"（那会把三态诚实记录、历史档案全算成罪，病15 识别范围≠对象范围）。
  ⑥ 矩阵-真源强度对账（T7，v0.8.82 增量）：软规则硬化矩阵的「当前强度」是手写中文，
     rule_map.strength 是机器真源，两边会随扩展脱钩（实测 B-11 真源 S1、矩阵仍写 S6）。
     T7 要求：rule_map 有强度登记的规则，矩阵当前强度列至少要出现其中一档；脱钩即红。
     只认行首 `| B-` 规则行第 4 列，不扫全文（病15 精确锚定）。

**故意不做的**（做不好会误报，留给人工/其他工具）：
  - 词表语义误用（M3）：需要理解上下文，关键词匹配必然误报
  - 复制条款判定（M2 的"是否抄了全文"）：形似不等于违规，无法机检
  - 安装后路径（~/.codebuddy/…、$HOME/…）：那是部署目标，不是本仓文件
  - 目标项目路径（.codebuddy/CODEBUDDY.md）：那是装到别人项目里的壳，本仓没有是对的

用法:
  python3 verify/terminology_check.py [--repo <仓库根>] [--json]
退出码: 0 全绿 / 2 有红项（豁免项按 M7 登记后照常 0）
"""
import os
import re
import sys
import json

DEFAULT_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 引用断链只查这几类前缀：它们**只能**是本仓内文件（其他前缀多半是部署路径/通配/外部仓）
REPO_PREFIXES = ('verify/', '通用层/', '能力层/', 'docs/', 'scripts/', '手机指令', 'bootstrap.sh')

# 豁免：确实"运行时生成""属别的仓""有意不建"的路径，**必须写理由**（M7 有意例外登记）。
# 判据：写不出理由的就不该豁免——要么是断链（去修），要么是判据假阳（去改判据）。
_RUNTIME_REASON = ('运行时生成/本机私产：install.sh 的 RUNTIME_FILES 明示不随分发；'
                   '干净 clone 里不存在是正常的，不是断链（2026-11-12 干净仓自检暴露）')
EXEMPT = {
    'scripts/activity_log.json':
        '运行时生成（probe.py 首次采样时创建，A_LOG=SELF_DIR/activity_log.json）；本机私产不入 git',
    'verify/model_handover.py':
        'README 在描述**旧仓 tvbox-eco** 原版换机司的断言依赖，不是引用本仓文件',
    'findings_history.json': _RUNTIME_REASON,
    'monitors.json': _RUNTIME_REASON,
    'space_hub_state.json': _RUNTIME_REASON,
    'monitor_targets.json': _RUNTIME_REASON,
    'monitor_domains.json': _RUNTIME_REASON,
    'monitor_pubsources.json': _RUNTIME_REASON,
    'dead_repos.json': _RUNTIME_REASON,
    'shellcrack_cands.json': _RUNTIME_REASON,
    'docs/巡检/dashboard.html':
        '巡检司面板产物（inspect-hub 运行时渲染生成，不入 git；面板缺了是"没跑过"，不是引用错）',
}

SCAN_EXT = ('.md',)
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.codebuddy'}   # .codebuddy 是部署产物
# M7 有意例外（W7-B）：capability_63/v4_skills 是从 MilkCode APK 解出的**上游第三方
# 只读原文资产**（63 域技能正文），不是本仓自有维护文档。其中的引用（如
# seagull-social-eng/SKILL.md 引用 upstream 本就缺失的 person_osint.py）属上游原文
# 既有缺陷，按原样归档、不修改（改了就不是一手真源）。病15：本判据对象是「本仓自有
# 文档的引用完整性」，识别范围不该覆盖只读原文资产。正文自身的完整性由 core.body_ok
# 的 bytes/sha256 逐条对账保证（manifest 为锚），不靠本 T3 断链判据。
SKIP_DIRS |= {'v4_skills'}

results = []


def rec(cid, level, msg):
    results.append((cid, level, msg))


def read(p):
    try:
        return open(p, encoding='utf-8', errors='ignore').read()
    except Exception:
        return ''


def check_numbering(repo):
    """M4：core-8 的每条都必须带 B-xx 标注，且序号与编号一一对应、不跳不重（条数随真源走，不写死）。

    为什么这样查：这个生态到处引用「B-05 零明文凭证」「B-02 三态诚实」，
    但 2026-11-12 实查发现真源正文只有 1…9 数字序号、**没有 B-xx 标注**——
    即 M4 声明的编号命名空间在真源里找不到落点（引用成了悬空标签）。故本判据同时查两件：
      ① 条数与 B 编号连续；② 第 n 条必须标 B-0n（序号与编号不许错位）。
    """
    p = os.path.join(repo, '通用层', 'rules', 'core-8.md')
    if not os.path.exists(p):
        # v0.8.36：规则目录在、core-8 没了 = 真源丢失（✗，这是真问题）；
        # 整个规则目录不在 = lite 形状/不是完整仓（·，不该管）。
        # 原先一律记 '·'，等于把「真源被删」和「这个仓本来就没有」折叠进同一个数。
        if os.path.isdir(os.path.dirname(p)):
            rec('T1', '✗', '通用层/rules/ 存在但 core-8.md 缺失——真源丢失，编号无从校验')
        else:
            rec('T1', '·', '通用层/rules/ 不存在——lite 形状无规则真源，不适用')
        return
    t = read(p)
    # 只认正文条款行："1. **B-01 语言**：" 或（缺标注时）"1. **语言**："
    rows = re.findall(r'(?m)^(\d+)\.\s+\*\*(B-\d{2})?\s*([^*]*?)\*\*', t)
    if not rows:
        rec('T1', '·', 'core-8 内未识别到编号条款——无法判定')
        return
    nums = [int(r[0]) for r in rows]
    no_tag = [str(r[0]) for r in rows if not r[1]]
    bs = [r[1] for r in rows if r[1]]
    problems = []
    if nums != list(range(1, len(nums) + 1)):
        problems.append(f'序号不连续/不从 1 起：{nums}')
    if no_tag:
        problems.append(f'缺 B-xx 标注的条款：第 {", ".join(no_tag)} 条')
    if bs:
        expect = [f'B-{i:02d}' for i in range(1, len(bs) + 1)]
        if bs != expect:
            problems.append(f'B 编号与序号错位/跳号：{bs}')
    if problems:
        rec('T1', '✗', '；'.join(problems) + '（M4 禁跳号、禁悬空标签）')
    else:
        rec('T1', '✓', f'B 编号连续且与序号对齐 B-01…B-{len(bs):02d}（共 {len(bs)} 条）')
    # M1…M7：只认行首的 "**M1 xxx**"，避免把 M-R60 之类混进来
    ms = sorted({int(m) for m in re.findall(r'(?m)^-\s+\*\*M(\d+)\s', t)})
    if ms:
        want = list(range(1, max(ms) + 1))
        missing = [f'M{i}' for i in want if i not in ms]
        if missing:
            rec('T2', '✗', f'元规则编号跳号：缺 {", ".join(missing)}（M4 禁跳号）')
        else:
            rec('T2', '✓', f'元规则编号连续 M1…M{max(ms)}（共 {len(ms)} 条）')
    else:
        rec('T2', '·', 'core-8 内未发现 M1…M7 条目——无法判定')


def iter_docs(repo):
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(SCAN_EXT):
                yield os.path.join(root, f)


def doc_base(repo, p):
    """文档里相对路径的解析基准：最近的含 SKILL.md 的目录（技能根），退仓根。

    为什么必须这样：技能文档写 `scripts/learn.py` 指的是**技能内**的脚本，
    按仓根解析会全判断链（实测 91 条里七成是这么来的假阳）。
    """
    cur = os.path.dirname(p)
    repo_abs = os.path.abspath(repo)
    while os.path.abspath(cur).startswith(repo_abs):
        # SKILL.md 是技能标志；manifest.json 是 lib 类（如 tvbox-core）的标志——
        # 少了后半个判断，lib 内的 `scripts/core.py` 会被按仓根解析而全判断链。
        if os.path.exists(os.path.join(cur, 'SKILL.md')) or os.path.exists(os.path.join(cur, 'manifest.json')):
            return cur
        if os.path.abspath(cur) == repo_abs:
            break
        cur = os.path.dirname(cur)
    return repo


def check_links(repo):
    """M2/M5：文档里引用本仓内路径但文件不存在 = 断链。

    实现要点：
      - 反引号里常带命令前缀（`python3 verify/xxx.py`），故在反引号内容里搜子串；
      - 相对路径按「技能根 → 仓根」两级解析；
      - **CHANGELOG 不查**：那是历史档案，记的是当时的文件（删了/改名了是正常演化）；
      - 带 `#锚点` 剥掉锚点再判；带 `::` 的是"文件::函数"，取前半。
    """
    pref = '(?:verify|通用层|能力层|docs|scripts|渠道层)/'
    inner = re.compile(r'(?:^|[\s=:（(])((?:' + pref + r'|bootstrap\.sh|手机指令\.md)[^\s`）)，。；、]*)')
    tick = re.compile(r'`([^`\n]+)`')
    bad = {}
    checked = 0
    for p in iter_docs(repo):
        name = os.path.basename(p)
        if name.startswith('CHANGELOG') or name.startswith('TEST') or name.startswith('阶段测试卡'):
            continue                       # 历史档案/测试记录不查（避免拿今天的目录结构审历史）
        rel_doc = os.path.relpath(p, repo).replace('\\', '/')
        base = doc_base(repo, p)
        for ln, line in enumerate(read(p).splitlines(), 1):
            for tm in tick.finditer(line):
                for mm in inner.finditer(tm.group(1)):
                    path = mm.group(1).rstrip('.,;:）)】」')
                    if any(ch in path for ch in ('*', '?', '~', '$', '{', '}')):
                        continue          # 通配/变量，无法静态判定
                    if 'xxx' in path:
                        continue          # 文档里的占位写法
                    if path.endswith('/') or (path.count('/') == 0 and not path.endswith(('.sh', '.md'))):
                        continue          # 目录引用 / 裸命令名
                    if not re.search(r'\.[A-Za-z0-9]{1,6}$', path.rsplit('/', 1)[-1]):
                        continue          # 末段没扩展名 = 命令语法（如 `verify/list/classify/audit`），不是路径
                    path = path.split('::')[0].split('#')[0].rstrip('/')
                    # 豁免按**后缀**匹配：同一个运行时文件，文档里可能写成技能内相对路径
                    # （scripts/x.json）也可能写成仓内全路径，两种都要认。
                    if not path or path in EXEMPT or any(path.endswith(k) for k in EXEMPT):
                        continue
                    checked += 1
                    if not (os.path.exists(os.path.join(base, path))
                            or os.path.exists(os.path.join(repo, path))):
                        bad.setdefault(path, []).append(f'{rel_doc}:{ln}')
    if bad:
        detail = '；'.join(f'{k}（{v[0]} 等 {len(v)} 处）' for k, v in list(bad.items())[:8])
        rec('T3', '✗', f'引用断链 {len(bad)} 个：{detail}')
    else:
        rec('T3', '✓', f'引用无断链（查了 {checked} 处仓内路径引用）')


def check_rule_map(repo):
    """T4（E10）：规则 ↔ 验证器**双向互引**——规则说它有判据，判据真的存在。

    为什么要有：core-8 每条都写着"必须做 X"，但在此之前**没有任何入口能验证 X**；
    规则与验证器各写各的，改了一边另一边照样绿（假绿）。本项查四件事：
      ① 映射表与 core-8 的 B-xx 集合完全一致（多一条少一条都红）；
      ② core-8 每条尾注 `｜验证 V-xxx`，且与映射表的 verify_id 一致（双向）；
      ③ machine 项的 check 文件存在，且 anchor 字符串在该文件里真的出现（防锚点漂移）；
      ④ manual 项必须写明 how（怎么问才算做到），**但不计为机检通过**（三态不折叠）。

    只查"入口在不在、指得对不对"，不查"行为有没有发生"——后者机器判不了。
    """
    c8 = os.path.join(repo, '通用层', 'rules', 'core-8.md')
    rmp = os.path.join(repo, 'verify', 'rule_map.json')
    if not os.path.exists(c8):
        if os.path.isdir(os.path.dirname(c8)):
            rec('T4', '✗', '通用层/rules/ 存在但 core-8.md 缺失——真源丢失，规则映射无从校验')
        else:
            rec('T4', '·', '通用层/rules/ 不存在——lite 形状无规则真源，不适用')
        return
    if not os.path.exists(rmp):
        rec('T4', '✗', 'verify/rule_map.json 缺失（每条规则都声称有验证入口，但映射表不存在）')
        return
    try:
        rmap = json.load(open(rmp, encoding='utf-8')).get('rules') or {}
    except Exception as e:
        rec('T4', '✗', f'rule_map.json 无法解析（{type(e).__name__}）——映射等于没有')
        return
    t = read(c8)
    rows = re.findall(r'(?m)^\d+\.\s+\*\*(B-\d{2})[^*]*\*\*(.*)$', t)
    core = {}
    for bid, rest in rows:
        m = re.search(r'｜验证\s*(V-[A-Za-z0-9-]+)', rest)
        core[bid] = m.group(1) if m else None
    problems = []
    only_core = sorted(set(core) - set(rmap))
    only_map = sorted(set(rmap) - set(core))
    if only_core:
        problems.append(f'规则无映射：{", ".join(only_core)}')
    if only_map:
        problems.append(f'映射无规则：{", ".join(only_map)}')
    # 规则预算：只增不减是 178 条的成因。旧生态 active 153 条 + retired 28 条 + deprecated 6 条，
    # 退役了也没从正文拿掉，最后没人读得完。这里给个硬顶：超了必须先退役一条再进新的。
    BUDGET = 20
    if len(core) > BUDGET:
        problems.append(f'core-8 已有 {len(core)} 条，超过预算 {BUDGET} 条——'
                        f'新增规则必须先退役一条（B 号不复用），否则正文会一路膨胀到没人读完')
    no_tag = [k for k, v in core.items() if not v]
    if no_tag:
        problems.append(f'规则缺「｜验证 V-xxx」尾注：{", ".join(no_tag)}')
    seen = {}
    machine = manual = 0
    for bid in sorted(set(core) & set(rmap)):
        r = rmap[bid] or {}
        vid = (r.get('verify_id') or '').strip()
        if not vid:
            problems.append(f'{bid} 缺 verify_id')
            continue
        if vid in seen:
            problems.append(f'verify_id 重号：{vid}（{seen[vid]} 与 {bid}）')
        seen[vid] = bid
        if core.get(bid) and core[bid] != vid:
            problems.append(f'{bid} 尾注 {core[bid]} ≠ 映射 {vid}')
        kind = r.get('kind')
        if kind == 'machine':
            machine += 1
            cp = r.get('check') or ''
            anchor = r.get('anchor') or ''
            fp = os.path.join(repo, cp)
            if not cp or not os.path.exists(fp):
                problems.append(f'{bid} 指向的验证文件不存在：{cp or "(空)"}')
            elif not anchor or anchor not in read(fp):
                problems.append(f'{bid} 锚点「{anchor}」在 {cp} 里找不到（实现已漂移，映射过期）')
        elif kind == 'manual':
            manual += 1
            if not (r.get('how') or '').strip():
                problems.append(f'{bid} 标 manual 但没写 how（怎么问才算做到）')
        else:
            problems.append(f'{bid} 的 kind 必须是 machine 或 manual（当前 {kind!r}）')
    if problems:
        rec('T4', '✗', '规则↔验证器互引断裂：' + '；'.join(problems[:6])
            + (f'（共 {len(problems)} 处）' if len(problems) > 6 else ''))
    else:
        rec('T4', '✓', f'规则↔验证器双向一致：{len(core)} 条规则 = {machine} 条机检 + '
                       f'{manual} 条人工判据（人工项**不算机检通过**，只保证口径可交接）')


def check_reserved_prefix(repo):
    """T5（F-8）：保留域前缀——规则文件里出现的 `X-NN` 编号，前缀必须已登记。

    M4 声明了命名空间（B-01…B-16 / V-xxx / M-R### / §x / 第 x 章 / 20.x.y / M1…M7）。
    但"声明"不等于"拦住"：谁都能在规则里新造一个 `C-01`，然后引用它，看着很正规，
    实际没有任何地方定义它——这就是悬空标签的温床。

    本项只扫**规则真源**（core-8 与 rule_map），不扫业务文档：
    业务文档里的 `S169`/`P018` 是阶段/提案编号，有自己的体系，硬管必然误报。
    """
    paths = [os.path.join(repo, '通用层', 'rules', 'core-8.md'),
             os.path.join(repo, 'verify', 'rule_map.json')]
    allowed = {'B', 'M-R', 'V'}          # M4 登记的数字型前缀
    seen, bad = {}, []
    for p in paths:
        if not os.path.exists(p):
            continue
        rel = os.path.relpath(p, repo).replace('\\', '/')
        for ln, line in enumerate(read(p).splitlines(), 1):
            for m in re.finditer(r'\b([A-Z]{1,3}(?:-[A-Z])?)-\d{1,3}\b', line):
                pre = m.group(1)
                seen[pre] = seen.get(pre, 0) + 1
                if pre not in allowed:
                    bad.append(f'{rel}:{ln} 的 {m.group(0)}')
    if not seen:
        rec('T5', '·', '规则文件里未识别到编号前缀——无法判定')
    elif bad:
        rec('T5', '✗', f'未登记的编号前缀 {len(bad)} 处（M4 只允许 B/M-R/V）：'
                       + '；'.join(bad[:5]))
    else:
        rec('T5', '✓', f'保留域前缀合规（{"/".join(sorted(seen))}，共 {sum(seen.values())} 处）')


# T6 受控话题：只登记「交接册曾记未决、实证文件后来覆盖了」的对象。
# 新增话题必须同时给 handoff 侧未决文件与 evidence 侧实证文件，缺一不算配对（病15）。
LEDGER_TOPICS = {
    'block=true': ('docs/handoff_latest.md', 'docs/防卡死检查单.md'),
    'task_wait_guard': ('docs/handoff_latest.md', 'docs/防卡死检查单.md'),
    'agent_turns_guard': ('docs/handoff_latest.md', 'docs/防卡死检查单.md'),
}
UNDECIDED = ('无法判定', '未实测', '无法实证', '本会话无法')
PROVEN = ('已实证', '已实测', '真拦', '实测中')
# 回写注记：handoff 行里出现任一，说明「旧记未决、现已实证」已被显式覆盖，不再报冲突
WRITTEN_BACK = ('已实证', '已回写', '已纠偏', '→已', '回写')


def check_ledger_evidence(repo):
    """T6：交接册记未决、实证文件已实证的同一对象 → 红（逼回写，B-14 以落点为准）。

    为什么用受控话题而不是扫全文：文档里合法的「无法判定」很多（三态记录、历史
    档案、本会话边界），全扫必然误报（病15 识别范围宽于对象范围）。只查显式登记的
    「曾未决→已实证」对象，命中才报，且报出两边行号供回写。
    """
    pairs = 0
    for topic, (ledger_rel, ev_rel) in LEDGER_TOPICS.items():
        lp, ep = os.path.join(repo, ledger_rel), os.path.join(repo, ev_rel)
        if not (os.path.isfile(lp) and os.path.isfile(ep)):
            continue
        pairs += 1
        ledger_lines = [(n, ln) for n, ln in enumerate(read(lp).splitlines(), 1)
                        if topic in ln and any(w in ln for w in UNDECIDED)]
        ev_lines = [(n, ln) for n, ln in enumerate(read(ep).splitlines(), 1)
                    if topic in ln and any(w in ln for w in PROVEN)]
        for ln_no, ln in ledger_lines:
            if any(w in ln for w in WRITTEN_BACK):
                continue  # 已显式回写
            if ev_lines:
                ev_at = ', '.join('%s:%d' % (ev_rel, n) for n, _ in ev_lines[:2])
                rec('T6', '✗', '账目-落点冲突：话题「%s」在 %s:%d 记未决，但 %s 已实证——'
                    '按 B-14 以落点为准回写交接册'
                    % (topic, ledger_rel, ln_no, ev_at))
    if not pairs:
        rec('T6', '·', '受控话题的两份文档都不在——账目-落点一致性不适用')
    elif not any(c == 'T6' and l == '✗' for c, l, _ in results):
        rec('T6', '✓', '账目-落点一致：%d 个受控话题无「记未决但已实证」冲突'
            % pairs)


def check_matrix_strength(repo):
    """T7：软规则硬化矩阵「当前强度」vs rule_map.strength 双向对账（M2 真源唯一）。

    矩阵是给人读的中文说明，rule_map 是机器真源；两边各自手写会脱钩。T7 只做
    一个可靠判断：rule_map 登记了某档强度的规则，矩阵当前强度列必须至少体现其中
    一档（不要求全等——矩阵常只写最高档，rule_map 记多档是合法的）。
    对象范围：只认行首 `| B-xx |` 表格行的第 4 列，不扫正文里的 S 字样（病15）。
    """
    mp = os.path.join(repo, 'docs', '软规则硬化矩阵.md')
    rmp = os.path.join(repo, 'verify', 'rule_map.json')
    if not (os.path.isfile(mp) and os.path.isfile(rmp)):
        rec('T7', '·', '矩阵或 rule_map 不在——强度对账不适用')
        return
    try:
        R = json.load(open(rmp, encoding='utf-8')).get('rules') or {}
    except Exception:
        rec('T7', '·', 'rule_map 无法解析——强度对账不适用')
        return
    mat = {}
    for ln, line in enumerate(read(mp).splitlines(), 1):
        if not line.startswith('| B-'):
            continue
        cells = [c.strip() for c in line.split('|')]
        if len(cells) < 5:
            continue
        bid = cells[1]
        cur = cells[4]
        mat[bid] = (set(re.findall(r'S(\d)', cur)), ln)
    if not mat:
        rec('T7', '·', '矩阵里没有 `| B-xx |` 规则行——强度对账不适用')
        return
    bad = []
    checked = 0
    for bid, r in R.items():
        truth = set((r.get('strength') or {}).keys())  # {'S1', 'S5', ...}
        if not truth:
            continue
        checked += 1
        if bid not in mat:
            bad.append(f'{bid} 在 rule_map 有强度 {sorted(truth)}，矩阵里没有该规则行')
            continue
        shown, ln = mat[bid]
        truth_n = {s.lstrip('S') for s in truth}
        if not (truth_n & shown):
            bad.append(f'{bid}:{ln} 矩阵当前强度写 S{"/S".join(sorted(shown)) or "无"}，'
                       f'rule_map 已登记 {"/".join(sorted(truth))}——矩阵过期，回真源对齐')
    if bad:
        rec('T7', '✗', '矩阵-真源强度脱钩：' + '；'.join(bad[:5])
            + (f'（共 {len(bad)} 处）' if len(bad) > 5 else ''))
    else:
        rec('T7', '✓', f'矩阵强度与真源对齐：{checked} 条有强度登记的规则当前强度均有体现')


def main(argv):
    repo = DEFAULT_REPO
    as_json = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--repo':
            repo = argv[i + 1]; i += 2
        elif a == '--json':
            as_json = True; i += 1
        elif a in ('-h', '--help'):
            print(__doc__); return 0
        else:
            print(f'未知参数: {a}'); return 1
    check_numbering(repo)
    check_links(repo)
    check_rule_map(repo)
    check_reserved_prefix(repo)
    check_ledger_evidence(repo)
    check_matrix_strength(repo)
    if as_json:
        print(json.dumps([{'id': c, 'level': l, 'msg': m} for c, l, m in results],
                         ensure_ascii=False, indent=2))
    else:
        print(f'【口径机检】repo={repo}')
        icon = {'✓': '✓', '✗': '✗', '·': '·'}
        for cid, level, msg in results:
            print(f'  {icon[level]} [{cid}] {msg}')
        fails = sum(1 for _, l, _ in results if l == '✗')
        skips = sum(1 for _, l, _ in results if l == '·')
        print(f'\n结果：{len(results) - fails - skips} ✓ ｜ {fails} ✗ ｜ {skips} ·（无法判定）')
        if fails:
            print('✗ 有口径问题（断链→回真源补文件或改指针；跳号→按 M4 补号）')
            return 2
        print('✓ 口径机检通过（编号连续、引用无断链、规则↔验证器一致、前缀合规）')
    return 0 if not any(l == '✗' for _, l, _ in results) else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
