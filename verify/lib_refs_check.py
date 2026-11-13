#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_refs_check.py — 外部正本脚本引用对账（平台升级后指针失效的第一道闸）

为什么要单独一条检查:
  520 的技能大量复用平台 library 技能的脚本（`{LIB}/database/xxx.py`）。
  平台一改目录结构或改名，我们的调用全部变成运行时 FileNotFoundError，
  而自检看不见——因为自检只读我们自己的文件。

  2026-11-13 实测：12 类引用里 8 类已失配，横跨 10 个脚本（space-hub 与
  tvbox-core 两条主线），`database/` 整层调用全断。这不是孤例，是模式。

判据（三级，`--probe` 逐级加深）:
  L1 存在性：扫全仓 .py，抽出所有 `{LIB}/... .py` 引用，逐个 os.path.exists。
     失配时用 difflib 给出最近的同名候选，避免瞎猜新名字。
  L2 可执行性（`--probe`）：每个引用脚本真跑一次 `--help`，rc 必须 0，且输出不能是
     错误载荷（分发型脚本遇未知子命令是 rc=0 + `{"error": ... unknown api ...}`）。
     抓的是「文件在但 import 炸了 / 依赖没了 / argparse 重构了」——L1 全绿也照样能炸。
  L3 参数契约（`--probe`）：把**调用点**上的字面参数（`'--op'`、`'set-records'`、
     `'space.workspace.list-nodes'`）抽出来，逐个回查目标脚本 `--help` 里还在不在；
     `--help` 里写成 `{a,b,c}` 的才算枚举，`--limit 60` 这种数据不校验。
     抓的是「脚本还在、名字没改，但参数改名/枚举值删了」——这类最阴，L1/L2 都全绿。
     归账用 AST、按作用域算（脚本名走变量、参数在另一条语句拼 argv 时，正则截片段看不见）。

  为什么必须三级：2026-11-13 的教训是「查到了存在 ≠ 调得通」。只查存在性是
  静态猜测（B-02 三态里最差的一档），真跑一次才叫验证。

三态（B-02）:
  ✓ 全部存在（且 --probe 时：全部可执行、参数契约全对）
  · 无法判定 —— library 技能未安装 / 目标脚本无 --help 契约（不敢贸然执行）/ 超时
  ✗/⚠ 存在失配 或 探活失败 或 参数失配（带 `--strict` 才是 ✗ 且退出码 1，否则 ⚠ 退出码 0）

退出码: 0=全通（含 warn 级） / 1=有失配且带 --strict / 2=无法判定
"""
import ast
import difflib
import os
import re
import subprocess
import sys

# 环境变量只为测试用（verify/tests/test_lib_refs_probe.py 造假的 LIB 与假的仓），
# 生产路径永远是下面这两个默认值。
ROOT = os.environ.get('LIB_REFS_ROOT') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.environ.get('LIB_REFS_LIB') or os.path.expanduser('~/.codebuddy/skills/library')
# 前缀不止 `{LIB}` 一种：tvbox-core 用 `{core.LIB}/database/xxx.py`（属性访问写法）。
# 2026-11-13 实测：只认 `{LIB}/` 时，5 个已断的调用点（backfill_system 3 + build 2）
# 全部静默漏过，而自检照样全绿——**闸只认一种拼写，就等于没闸**。
PAT = re.compile(r'\{(?:[A-Za-z_][A-Za-z0-9_]*\.)?LIB\}/([A-Za-z0-9_/]+\.py)')
# 间接入口：脚本名以字符串常量传给 `_run_lib(...)` 一类转发函数，路径在函数内部
# 才与 LIB 拼接 —— 上面的 PAT 只看 `{LIB}/` 字面量，对这类写法是**瞎的**。
# 2026-11-13 实测：core.py:688/719、preflight.py:40 三处指着已消失的
# batch_update_database_records.py / batch_delete_database_records.py /
# get_database_schema.py，第一版检查器 0 命中（B-15 模式级盲区，不是孤例）。
# 已知仍扫不到的：run.py:54 把变量转发给 _run_lib（静态不可判，登记在文档里）。
PAT_INDIRECT = re.compile(r"""(?:_run_lib|api)\(\s*['"]([A-Za-z0-9_/]+\.py)['"]""")
PATTERNS = (PAT, PAT_INDIRECT)
SKIP_DIRS = {'__pycache__', '.git', 'node_modules'}
# 不扫 verify/tests/：里面的「调用点」是夹具里的**字符串常量**（造给 --probe 回归用的
# 假脚本名、假参数），不是真调用。第一版没排除，`--probe` 当场把夹具里的
# `no_cli.py`、`'--limit','60'` 当成本仓的真实引用报红——检查器吃了自己的测试数据。
# 判据：真调用只在 通用层/ 与 能力层/ 的生产脚本里。
SKIP_REL_PREFIXES = ('verify/tests/',)
# ── L3 用的两种常量形态 ─────────────────────────────────────────────────────
REL_RE = re.compile(r'^(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py$')      # 'database/db_edit.py'
# f'{LIB}/database/db_query.py' 拆成 JoinedStr 后，路径片段是 Constant('/database/db_query.py')。
# 直接读这个常量，别用 ast.get_source_segment——后者每次都把全文重切一遍行，
# 实测 3069 次调用烧掉 82 秒（本检查器剩下 3 秒），是纯 CPU 自残。
PART_RE = re.compile(r'^/((?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py)')
DOT_RE = re.compile(r'^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_-]*)+$')    # 'space.workspace.list-nodes'


def _walk_scope(node):
    """遍历一个作用域，但**不下钻**嵌套的函数/Lambda——参数归属按作用域算，
    下钻会把内层函数的参数错记到外层引用的账上。"""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(cur))


def _params_in(node):
    """一个节点子树里的字面参数：(flags, dots, pairs)。不认脚本名，只管参数本身。"""
    flags, dots, pairs = set(), set(), []
    for sub in [node, *_walk_scope(node)]:      # 含根节点：调用自己的实参表也要配对
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            v = sub.value
            if v.startswith('--'):
                flags.add(v)
            elif REL_RE.match(v):
                pass                  # 脚本名，不是参数也不是子命令
            elif DOT_RE.match(v):
                dots.add(v)
        if isinstance(sub, (ast.List, ast.Tuple, ast.Call)):
            elts = sub.args if isinstance(sub, ast.Call) else sub.elts
            for a, b in zip(elts, elts[1:]):
                if (isinstance(a, ast.Constant) and isinstance(b, ast.Constant)
                        and isinstance(a.value, str) and a.value.startswith('--')
                        and isinstance(b.value, str)):
                    pairs.append((a.value, b.value))
    return flags, dots, pairs


def ast_units(text, path_rel):
    """抽「脚本 → 字面参数」的关联，返回 (units, ambiguous_scope_count)。

    两级归账，先精确后兜底：
      ① 调用级：某次调用的子树里只出现一个正本、且带字面参数 → 直接记在它头上。
         例：`api('space_api.py', 'space.workspace.list-nodes', '--space-id', S)`
      ② 函数级兜底：脚本名与参数**分在两条语句**时（`argv=['--ask',x]` 然后
         `_db_call(_DB_QUERY, argv)`），调用级一条都归不上；此时若整个函数只引用
         一个正本，就把函数内的字面参数记给它。
     都不成立（函数里引用了两个及以上正本、参数又不在调用级）→ 计数报出，不硬猜。

    为什么非这么干：2026-11-13 变异实测，按「正则截一条调用表达式」抽参数时，
    把 db_query 的 `--ask` 改名成 `--query`，space_hub/core/backfill_jar 三处
    包装函数全绿（假阴性）——片段版看不见 argv 在别处拼。
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], 0

    name_map = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            tgt = [t.id for t in targets if isinstance(t, ast.Name)]
            rels = _rels(node.value, {})
            if len(tgt) == 1 and len(rels) == 1:
                name_map[tgt[0]] = next(iter(rels))

    scopes = [n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not scopes:
        scopes = [tree]
    units, ambiguous = [], 0
    for sc in scopes:
        rels, flags, dots, pairs = set(), set(), set(), []
        call_units = []
        for node in _walk_scope(sc):
            rels |= _rels(node, name_map)
            if isinstance(node, ast.Call):
                c_rels = _call_rels(node, name_map)
                if len(c_rels) == 1:
                    f, d, p = _params_in(node)
                    if f or d:
                        call_units.append({'rel': next(iter(c_rels)),
                                           'site': f'{path_rel}:{node.lineno}',
                                           'flags': f, 'pairs': p, 'dots': d})
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if v.startswith('--'):
                    flags.add(v)
                elif REL_RE.match(v):
                    pass
                elif DOT_RE.match(v):
                    dots.add(v)
            if isinstance(node, (ast.List, ast.Tuple, ast.Call)):
                elts = node.args if isinstance(node, ast.Call) else node.elts
                for a, b in zip(elts, elts[1:]):
                    if (isinstance(a, ast.Constant) and isinstance(b, ast.Constant)
                            and isinstance(a.value, str) and a.value.startswith('--')
                            and isinstance(b.value, str)):
                        pairs.append((a.value, b.value))

        if not rels:
            continue
        covered = {u['rel'] for u in call_units}
        if len(rels) == 1:
            only = next(iter(rels))
            if only not in covered:
                call_units.append({'rel': only, 'site': f'{path_rel}:{sc.lineno}',
                                   'flags': flags, 'pairs': pairs, 'dots': dots})
            units.extend(call_units)
        elif call_units:
            # 一个函数里调了两个正本，但每处调用自己带参数 → 仍能分别归账
            units.extend(call_units)
            if len(rels - covered) > 0 and (flags or dots):
                ambiguous += 1
        else:
            ambiguous += 1
    return units, ambiguous


def _call_rels(call, name_map):
    """一次调用的实参里出现的正本脚本（只看这一层调用，不下钻到别的调用）。"""
    out = set()
    for a in list(call.args) + [k.value for k in call.keywords]:
        if isinstance(a, ast.Starred):
            a = a.value
        out |= _rels(a, name_map)
    return out


def _rels(node, name_map):
    """一个 AST 节点里出现的正本脚本相对路径（f-string 片段 / 常量 / 已绑定变量）。"""
    out = set()
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                m = PART_RE.match(part.value)
                if m:
                    out.add(m.group(1))
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        if REL_RE.match(node.value):
            out.add(node.value)
    elif isinstance(node, ast.Name) and node.id in name_map:
        out.add(name_map[node.id])
    return out


def collect_refs():
    """返回 (l1, units, ambiguous)。
    l1        = {rel: [site...]}      —— 正则扫出的引用点，管「文件在不在」（L1）
    units     = [{rel, site, flags, pairs, dots}] —— AST 按作用域归的账，管「调得通不通」（L3）
    ambiguous = 作用域里出现 ≥2 个正本的处数（L3 主动放弃归账的地方，必须报数）"""
    refs, units, ambiguous = {}, [], 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith('.py'):
                continue
            full = os.path.join(dirpath, name)
            if os.path.abspath(full) == os.path.abspath(__file__):
                continue                       # 不拿自己的文档示例当引用
            relpath = os.path.relpath(full, ROOT)
            if relpath.startswith(SKIP_REL_PREFIXES):
                continue                       # 测试夹具不是调用点
            try:
                text = open(full, encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            hits = []
            for pat in PATTERNS:
                hits += [(m.group(1), m.start()) for m in pat.finditer(text)]
            for rel, pos in sorted(hits, key=lambda x: x[1]):
                line = text[:pos].count('\n') + 1
                refs.setdefault(rel, []).append(f'{relpath}:{line}')
            u, amb = ast_units(text, relpath)
            ambiguous += amb
            for e in u:
                if os.path.exists(os.path.join(LIB, e['rel'])):
                    units.append(e)
    return refs, _dedupe_units(units), ambiguous


def _dedupe_units(units):
    seen, out = set(), []
    for u in units:
        key = (u['rel'], u['site'])
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def all_lib_scripts():
    out = []
    if not os.path.isdir(LIB):
        return out
    for dirpath, dirnames, filenames in os.walk(LIB):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith('.py'):
                out.append(os.path.relpath(os.path.join(dirpath, name), LIB))
    return out


# ── L2/L3：探针段 ────────────────────────────────────────────────────────────
HELP_TIMEOUT = 20
# 只对「自己声明了 CLI 契约」的脚本跑 --help：没有 argparse/click 的脚本
# 收到 --help 会当成普通参数照跑主逻辑，探活反而变成副作用（B-05 式事故）。
HAS_CLI = re.compile(r'\bargparse\b|\badd_argument\b|\bclick\b|\bfire\.Fire\b')
# 只有 --help 里写成 `--op {a,b,c}` 的才算枚举；`--limit 60` 这种是数据不是枚举，
# 早期版本把它当枚举查，当场造出 2 条假阳性（link.py:624/637）——判据必须认 choices。
PAT_CHOICES = re.compile(r'(--[A-Za-z][A-Za-z0-9-]*)\s+\{([^}]*)\}')


def choices_of(help_text):
    return {flag: {v.strip() for v in vals.split(',') if v.strip()}
            for flag, vals in PAT_CHOICES.findall(help_text)}


def run_help(path, *extra):
    """真跑 `<脚本> [子命令] --help`。返回 (verdict, text_or_detail)。"""
    argv = [sys.executable, path, *extra, '--help']
    try:
        r = subprocess.run(argv, cwd=os.path.dirname(path) or '.',
                           capture_output=True, text=True, timeout=HELP_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 'unknown', f'`--help` 超时（>{HELP_TIMEOUT}s）'
    except OSError as e:
        return 'fail', f'起不了进程: {e}'
    if r.returncode != 0:
        lines = (r.stderr or r.stdout or '').strip().splitlines()
        tail = ' | '.join(lines[-2:])[:180] if lines else '（无输出）'
        return 'fail', f'rc={r.returncode}: {tail}'
    text = r.stdout + r.stderr
    # 退出码不够用：真平台的分发型脚本（space_api.py）遇到不存在的 api 是
    # rc=0 + stdout 吐 `{"error": "code=INVALID_PARAMS; msg=unknown api: ..."}`
    # （2026-11-13 实测）。只看 rc 会把「子命令被删」误判成「探活成功」。
    head = text.lstrip()
    if head.startswith('{"error"') or 'unknown api' in text.lower():
        return 'fail', f'返回错误载荷: {head.splitlines()[0][:160] if head else "（空）"}'
    return 'ok', text


def probe_script(path):
    """L2：脚本本身能不能跑起来（import / 依赖 / argparse 重构）。"""
    try:
        src = open(path, encoding='utf-8', errors='ignore').read()
    except OSError as e:
        return 'fail', f'读不到源码: {e}'
    if not HAS_CLI.search(src):
        return 'unknown', '源码无 argparse/click，不贸然执行'
    return run_help(path)


def help_text_of(path, rel, dot, cache):
    """取某个调用点的有效帮助文本：(verdict, text_or_detail)。
    带点子命令的（`space_api.py space.xxx.yyy`）必须走**子命令级** --help：
    顶层只列 api 名，不含该 api 的参数，拿顶层文本校验参数必然全红（假阳性）。"""
    if (rel, '') not in cache:
        cache[(rel, '')] = probe_script(path)      # L2：脚本本身先活着
    top = cache[(rel, '')]
    if top[0] != 'ok' or not dot:
        return top
    key = (rel, dot)
    if key not in cache:
        cache[key] = run_help(path, dot)
    return cache[key]


def contract_drift(unit, help_text):
    """一个作用域里的字面参数，逐个回查目标 --help。返回失配项列表。"""
    bad = []
    for flag in sorted(unit['flags']):
        if flag not in help_text:
            bad.append(flag)
    for name in sorted(unit['dots']):
        if name not in help_text:
            bad.append(name)
    choices = choices_of(help_text)
    for flag, val in unit['pairs']:
        allowed = choices.get(flag)
        if allowed and val not in allowed:
            bad.append(f'{flag} {val}')
    return bad


def _report_missing(missing, total, lib_files, basenames, strict):
    """L1 存在性失配清单（每类给出同目录候选，不瞎猜新名字）。"""
    n_sites = sum(len(v) for v in missing.values())
    print(f'  {"✗" if strict else "⚠"} 外部正本引用失配 {len(missing)}/{total} 类（{n_sites} 处调用）：')
    for rel, sites in missing.items():
        # 同目录清单比模糊猜名更准：database/ 一共就十来个脚本，人一眼能认
        sib_dir = os.path.dirname(rel)
        siblings = sorted({os.path.basename(p) for p in lib_files
                           if os.path.dirname(p) == sib_dir})
        if siblings:
            hint = f' → 同目录现有: {" ".join(siblings)}'
        else:
            base = os.path.basename(rel)
            cand = difflib.get_close_matches(base, list(basenames), n=2, cutoff=0.6)
            hint = f' → 疑似: {", ".join(basenames[c] for c in cand)}' if cand else ' → 同目录为空或不存在'
        print(f'     {rel}{hint}')
        for s in sites[:4]:
            print(f'       ↳ {s}')
        if len(sites) > 4:
            print(f'       ↳ …另 {len(sites) - 4} 处')
    print('     处置：确认新脚本的参数签名后再改调用点，别只改文件名（B-08 查正本入口）')


def _report_probe(refs, units, alive, ambiguous, strict):
    """L2 可执行性 + L3 参数契约。返回 (hard_bad, unknown)。

    L3 的账记在 unit（作用域）上，不记在 refs（正则命中行）上——理由见 ast_units。
    一个 unit 若有多个点号子命令，逐个探；子命令名本身就是第一道契约。"""
    cache, exec_bad, unknown = {}, [], []
    drift, dead_sub = [], []

    # L2：每个脚本先自证活得下来（import / 依赖 / argparse 重构都在这一层现形）
    for rel in alive:
        path = os.path.join(LIB, rel)
        v, t = help_text_of(path, rel, None, cache)
        if v == 'fail':
            exec_bad.append((rel, t))
        elif v == 'unknown':
            unknown.append((rel, t))

    # L3
    checked = 0
    for u in units:
        rel = u['rel']
        if rel not in alive:
            continue
        checked += 1
        path = os.path.join(LIB, rel)
        dots = u['dots']
        if not dots:
            if cache.get((rel, ''), ('', ''))[0] != 'ok':
                continue                       # 脚本没探通，已在 L2 报过
            for tok in contract_drift(u, cache[(rel, '')][1]):
                drift.append((rel, u['site'], tok))
            continue
        for dot in sorted(dots):
            v, t = help_text_of(path, rel, dot, cache)
            if v == 'fail':
                dead_sub.append((rel, dot, u['site'], t))
                continue
            if v == 'unknown':
                unknown.append((f'{rel} {dot}', t))
                continue
            for tok in contract_drift(u, t):
                drift.append((rel, u['site'], tok))

    # 同一作用域里若同时引用两个正本，参数归属静态分不清——报数，不硬猜
    mark = '✗' if strict else '⚠'     # 与 L1 同一条规矩：warn 级不阻断，strict 才红
    if exec_bad:
        print(f'  {mark} 探活失败 {len(exec_bad)} 个脚本（`--help` 都跑不通，调用必炸）：')
        for rel, detail in exec_bad:
            print(f'     {rel}  {detail}')
            for s in refs.get(rel, [])[:2]:
                print(f'       ↳ {s}')
    if dead_sub:
        print(f'  {mark} 子命令已不存在 {len(dead_sub)} 处：')
        for rel, dot, site, detail in dead_sub[:10]:
            print(f'     {rel} `{dot}`  {detail}')
            print(f'       ↳ {site}')
    if drift:
        print(f'  {mark} 参数契约失配 {len(drift)} 处（脚本在、名字在，参数名或枚举值变了）：')
        for rel, site, tok in drift[:10]:
            print(f'     {rel}  `{tok}` 不在 --help：{site}')
        if len(drift) > 10:
            print(f'     …另 {len(drift) - 10} 处')
    if unknown:
        seen, uniq = set(), []
        for rel, detail in unknown:
            if rel in seen:
                continue
            seen.add(rel)
            uniq.append((rel, detail))
        print(f'  · 无法判定 {len(uniq)} 项（未探通，不计入通过）：')
        for rel, detail in uniq:
            print(f'     {rel}  {detail}')

    hard = len(exec_bad) + len(dead_sub) + len(drift)
    if not hard and not unknown:
        n_scripts = sum(1 for k in cache if k[1] == '' and cache[k][0] == 'ok')
        print(f'  ✓ 探活全通（{n_scripts} 个脚本 `--help` rc=0，'
              f'{checked} 个调用作用域参数契约全对'
              + (f'；另有 {ambiguous} 个作用域引用多个正本，参数归属静态不可判' if ambiguous else '')
              + '）')
    return hard, len({r for r, _ in unknown})


def _refs_guess():
    """library 未安装时的轻量预扫：只跑正则，不起进程、不探活。

    为什么要有：未安装时若只说「未安装」，用户不知道该不该在意。
    报出「有 N 类引用正等着校验」才能判断这是欠账还是无事可做。
    只跑 collect_refs 的第一段（纯正则），成本是毫秒级。
    """
    try:
        refs, _units, _amb = collect_refs()
        return refs
    except Exception:
        return {}


def main():
    argv = sys.argv[1:]
    strict = '--strict' in argv
    probe = '--probe' in argv
    if not os.path.isdir(LIB):
        # v0.8.36：这是 PARTIAL（环境欠账，该装），不是 SKIP（结构性不适用）。
        # 两者原先都打 '·' 都返回 2，看输出分不清「我该去装一下」和「这本来就不该管」。
        print(f'  ◐ 环境欠账：library 技能未安装（{LIB} 不存在）——'
              f'装好 library 才能校验 {len(_refs_guess())} 类外部引用（本机不计通过）')
        return 2

    refs, units, ambiguous = collect_refs()
    if not refs:
        print('  ✓ 全仓无 {LIB} 引用（不需要校验）')
        return 0

    lib_files = all_lib_scripts()
    basenames = {os.path.basename(p): p for p in lib_files}
    total = len(refs)
    n_sites = sum(len(v) for v in refs.values())
    missing = {rel: sites for rel, sites in sorted(refs.items())
               if not os.path.exists(os.path.join(LIB, rel))}
    ok_n = total - len(missing)

    if not probe:
        if not missing:
            print(f'  ✓ 外部正本引用全部有效（{ok_n}/{total} 类，共 {n_sites} 处）')
            return 0
        _report_missing(missing, total, lib_files, basenames, strict)
        if strict:
            return 1
        print('     （warn 级：日常自检不阻断；发布前 `--strict` 会红。已登记 docs/遗留登记.md）')
        return 0

    # --probe：L1 报完继续往下探，两级证据分开列，不混成一句话
    if missing:
        _report_missing(missing, total, lib_files, basenames, strict)
    alive = [rel for rel in sorted(refs) if rel not in missing]
    bad, unknown = _report_probe(refs, units, alive, ambiguous, strict)

    if bad or missing:
        print('     处置：先 `python3 <新脚本> --help` 对签名，再改调用点（B-08 查正本入口）')
        if strict:
            return 1
        print('     （warn 级：日常自检不阻断；`--probe --strict` 发布前会红）')
        return 0
    if unknown:
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
