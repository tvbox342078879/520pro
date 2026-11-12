#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""terminology_check.py —— 口径机检（core-8 元规则 M4/M5 的可机检部分）

为什么有这个脚本：core-8 元规则 M5 写的是「改真源后同步所有指针点；跑通才算完成
（断链 / 词表误用 / 编号越界 / 复制条款四类须全绿）」，skill-evolution 的 SKILL.md 也写着
「收尾跑 verify/terminology_check.py（C5）」——但 2026-11-12 实查发现**这个脚本根本不存在**，
属于规则被引用、入口是空的（文档断链）。

本脚本做**能可靠机检的三类**，宁可少判也不误判（误报一多，人就会整体忽略它）：

  ① 编号越界：core-8 里 B-01…B-10、M1…M7 必须连续、不重号、不跳号（M4）
  ② 引用断链：文档中明确指向**本仓内**的路径（verify/ 通用层/ 能力层/ docs/ 开头），
     文件不存在即报（M2/M5）
  ③ 规则↔验证器互引（E10）：verify/rule_map.json 与 core-8 双向一致；machine 项的锚点
     必须真实存在（防实现漂移后映射还在假装有效）；manual 项必须写清怎么问，且不计为通过

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
EXEMPT = {
    'scripts/activity_log.json':
        '运行时生成（probe.py 首次采样时创建，A_LOG=SELF_DIR/activity_log.json）；本机私产不入 git',
    'verify/model_handover.py':
        'README 在描述**旧仓 tvbox-eco** 原版换机司的断言依赖，不是引用本仓文件',
}

SCAN_EXT = ('.md',)
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.codebuddy'}   # .codebuddy 是部署产物

results = []


def rec(cid, level, msg):
    results.append((cid, level, msg))


def read(p):
    try:
        return open(p, encoding='utf-8', errors='ignore').read()
    except Exception:
        return ''


def check_numbering(repo):
    """M4：core-8 的 9 条必须带 B-01…B-09 标注，且序号与编号一一对应、不跳不重。

    为什么这样查：这个生态到处引用「B-05 零明文凭证」「B-02 三态诚实」，
    但 2026-11-12 实查发现真源正文只有 1…9 数字序号、**没有 B-xx 标注**——
    即 M4 声明的编号命名空间在真源里找不到落点（引用成了悬空标签）。故本判据同时查两件：
      ① 条数与 B 编号连续；② 第 n 条必须标 B-0n（序号与编号不许错位）。
    """
    p = os.path.join(repo, '通用层', 'rules', 'core-8.md')
    if not os.path.exists(p):
        rec('T1', '·', '未找到 通用层/rules/core-8.md——编号无法判定（不算通过）')
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
        rec('T4', '·', '未找到 core-8.md——规则↔验证器映射无法判定')
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
        print('✓ 口径机检通过（编号连续、引用无断链、规则↔验证器双向一致）')
    return 0 if not any(l == '✗' for _, l, _ in results) else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
