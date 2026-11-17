#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_scan.py — 病10 / 病13 的落地判据（2026-11-14，取代台账里的"暂无判据"）

为什么在：两道病之前只有文字病历没有机器判据（verify.sh 全绿 ≠ 这两道被守着）。
- 病10 中文路径转义：`git diff --cached --name-only` / `ls-files` 不带
  `-c core.quotepath=false` 时，非 ASCII 文件名被转义成 `"docs/\346..."`，
  与中文字面量比对永远 False——闸静默放行（假绿）或断言假红。
- 病13 通道末端未验：钩子跑了/命中了/打印了都不算数，必须能自证「到了末端」。
  平台钩子（install.sh 注册到 settings.json 的）必须自带 `--probe` 快照，
  且快照含 `hit` 与 `via`——没有它，「生效与否」永远记无法判定。

判据（可造违例 / 能拦下 / 改坏会溜过，三件套见 verify/tests/test_gate_scan.py）：
- quotepath：扫 hooks/ verify/ scripts/ install.sh verify.sh（*.sh *.py），
  行内出现 `git ... diff --cached | diff --name-only | diff --numstat | ls-files`
  调用而同行无 `core.quotepath=false` → 红。豁免：注释行。
- hook-probe：从 install.sh 提取 `cp "$ROOT/hooks/X" "$HOME/.codebuddy/hooks/"`
  注册的平台钩子，逐个检查脚本含 `--probe`、`hit`、`via` → 缺任一即红。
- hook-registered（v0.8.59，补病13 的另一半）：hook-probe 只管「脚本合不合格」，
  不管「这个脚本到底被挂到哪个事件上」。脚本 cp 到盘上但事件段没注册 = 文件在、
  钩子不跑，而 cp 那一行仍在 install.sh 里，闸照样全绿。
  故从 install.sh 静态提取「变量 → 事件」「脚本 → 变量」两层绑定，得到
  {脚本: [事件]}，再与 `~/.codebuddy/settings.json` 的 hooks 实况对账：
  声明要挂、实际没有 → 红。settings.json 不存在 → 记「不适用」（不判通过，B-02 三态）。
- case-count（v0.8.59）：测试汇总行第一实参必须 `N[0]` 由 check() 自增。
  写死字面量或 `len(x)+N` 偏移估算即红——报出的例数是假的，等于没有用例计数。
- impl-reconcile（v0.8.62，补「登记强度 ≠ 实物强度」）：rule_map 的 `strength`
  与代码里的 `# impl: B-xx Sn` 自报标记双向对账。虚标（machine 无 strength）/
  漏登（实物有标记、映射没写）/ 过期登记 / 写了没挂 / 字段是编的，五种都红。
  首版正则只要求「出现标记」，把本文件 docstring 里的示例行也算成了落点（病15 第 6 例），
  现要求整行注释。
- orphan-guard（v0.8.82 增量，补「有闸没登记」的反向盲区）：impl-reconcile 只查
  「谁声称守、谁真的标了守」，查不了「装了个钩子到用户机器、却没有任何规则认领它」。
  从 install.sh 提取 cp 到用户级的独立钩子（排除被别的钩子 import 的依赖库），逐个要求
  有 `# impl: B-xx Sn` 标记或 rule_map 点名；两者都无即红（改坏了没有判据会红）。
  病15 精确锚定：对象=install.sh 真实 cp 的独立钩子，不扫 hooks/ 全目录的杂项脚本。

诚实边界：行级扫描，多行 subprocess 列表会漏报——多行调用须写在同一行，
或在本文件附近登记豁免理由（M7）。impl-reconcile 只对账「谁声称守、谁真的标了守」，
不判「行为有没有发生」；后者看 proven_by 的实测记录，本闸只统计条数不判红（没测≠错，也不等于通过）。
退出码 0 全绿 / 2 有红。
"""
import json
import os
import re
import sys

CALL = re.compile(
    r'\bgit\b.*\b(diff --cached|diff --name-only|diff --numstat|ls-files)\b')
QUOTEPATH = 'core.quotepath=false'
SCAN_DIRS = ('hooks', 'verify', 'scripts')
SCAN_FILES = ('install.sh', 'verify.sh')
SCAN_EXT = ('.sh', '.py')
CP_HOOK = re.compile(
    r'cp\s+"\$ROOT/hooks/([\w.-]+\.(?:py|sh))"\s+"\$HOME/\.codebuddy/hooks/')
# install.sh 的合并段形状（真源，不在这里复制脚本名单——那是 M2 明令禁止的）：
#   cmds3 = [h.get('command', '') for e in d['hooks']['Stop'] for h in e.get('hooks', [])]
#   if not any('stop_guard.py' in c for c in cmds3):
EVENT_OF_VAR = re.compile(
    r"(cmds\d*)\s*=\s*\[h\.get\('command',\s*''\)\s*for\s+e\s+in\s+d\['hooks'\]\['(\w+)'\]")
SCRIPT_OF_VAR = re.compile(
    r"any\('([\w.-]+\.(?:py|sh))'\s+in\s+c\s+for\s+c\s+in\s+(cmds\d*)\)")


def scan_lines(root):
    """yield (文件相对路径, 行号, 行内容)，只扫声明范围内。"""
    targets = []
    for d in SCAN_DIRS:
        p = os.path.join(root, d)
        if not os.path.isdir(p):
            continue
        for base, _, files in os.walk(p):
            for f in files:
                if f.endswith(SCAN_EXT) and not f.startswith('test_gate'):
                    targets.append(os.path.join(base, f))
    for f in SCAN_FILES:
        p = os.path.join(root, f)
        if os.path.isfile(p):
            targets.append(p)
    for path in targets:
        rel = os.path.relpath(path, root)
        if os.path.basename(path) == os.path.basename(__file__):
            continue  # 自指豁免（病1 先例 is_self_sample_line）：本文件的 docstring/报错文案含模式串，无真实 git 调用
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                for i, line in enumerate(fh, 1):
                    yield rel, i, line.rstrip('\n')
        except OSError:
            pass


def gate_quotepath(root, settings=None):
    reds = []
    for rel, i, line in scan_lines(root):
        if line.lstrip().startswith('#'):
            continue
        if CALL.search(line) and QUOTEPATH not in line:
            reds.append('%s:%d 裸 git diff/ls-files（病10）： %s' % (rel, i, line.strip()[:100]))
    return reds


def _imported_by_other(root, name):
    """该脚本是否被 hooks/ 下别的脚本 import（= 依赖库，不是独立注册的钩子）。

    v0.8.55 起区分这两类：guard_cmd.py 是被 next_anchor import 的守卫逻辑，
    自身不维护 state，观测由 next_anchor 的 probe['via']（+guard:G1）承担。
    旧判据把「cp 到 hooks 目录的所有脚本」一律当作注册钩子，于是对库也要求
    --probe/hit/via，必然误红——判据错在归类，不在被测对象，故改判据。
    """
    stem = name[:-3] if name.endswith('.py') else name
    hdir = os.path.join(root, 'hooks')
    for other in os.listdir(hdir):
        if other == name or not other.endswith('.py'):
            continue
        body = open(os.path.join(hdir, other), encoding='utf-8', errors='ignore').read()
        if re.search(r'^\s*import\s+%s\b' % re.escape(stem), body, re.M) \
           or re.search(r'^\s*from\s+%s\s+import\b' % re.escape(stem), body, re.M):
            return True
    return False


# 测试汇总行的「例数」实参：必须是 N[0]（check 自增），不许写死或靠偏移估算。
# 病12 复发实证：4 个测试文件全部写死，真实例数分别为 22/13/38/20，而写的是 14/12/「+22」/「+8」。
CASE_ARG = re.compile(r"例，失败\s*%d'\s*%\s*\(\s*([^,]*)")


def gate_case_count(root, settings=None):
    """测试例数不许写死（病12 复发型）：写死的数字不会随用例增删而变，最终报的是假数。"""
    reds = []
    tdir = os.path.join(root, 'verify', 'tests')
    if not os.path.isdir(tdir):
        return reds
    for f in sorted(os.listdir(tdir)):
        if not (f.startswith('test_') and f.endswith('.py')):
            continue
        p = os.path.join(tdir, f)
        try:
            lines = open(p, encoding='utf-8', errors='ignore').readlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith('#'):
                continue
            m = CASE_ARG.search(line)
            if not m:
                continue
            arg = m.group(1).strip()
            if arg != 'N[0]':
                reds.append('verify/tests/%s:%d 例数写死或靠偏移估算（%s）——用例增删后必失真（病12）'
                            % (f, i, arg))
    return reds


def declared_events(install_text):
    """从 install.sh 提取 {钩子脚本: [事件名...]}（两层绑定：变量→事件、脚本→变量）。

    返回空 dict 表示「提不出绑定」——此时不能当全绿，要红（否则删掉合并段即可绕过）。
    """
    var2ev = dict(EVENT_OF_VAR.findall(install_text))
    out = {}
    for script, var in SCRIPT_OF_VAR.findall(install_text):
        ev = var2ev.get(var)
        if not ev:
            continue
        out.setdefault(script, [])
        if ev not in out[script]:
            out[script].append(ev)
    return out


def gate_hook_registered(root, settings=None):
    """安装态对账：install.sh 声明「脚本 X 挂事件 E」，settings.json 里必须真有。

    为什么必须单独一道：hook-probe 只看脚本自身有没有 --probe，脚本合格但没挂上，
    钩子一次都不会跑——这正是「写了没挂 = 等于没写」。cp 那行还在，闸就一直是绿的。
    三态：一致 → []（绿）；声明了没挂 → 红；settings.json 不在本机 → 「·」不适用。
    """
    inst = os.path.join(root, 'install.sh')
    try:
        text = open(inst, encoding='utf-8', errors='ignore').read()
    except OSError:
        return [('✗', 'install.sh 不可读，无法提取事件绑定（病13）')]
    decl = declared_events(text)
    if not decl:
        return [('✗', 'install.sh 里提取不到「脚本→事件」绑定——删掉合并段即可绕过本闸，'
                       '判据失效（病13）')]

    sp = settings or os.path.join(os.path.expanduser('~'), '.codebuddy', 'settings.json')
    if not os.path.isfile(sp):
        return [('·', '本机无 %s，安装态对账不适用（不判通过）' % sp)]
    try:
        cfg = json.load(open(sp, encoding='utf-8'))
    except Exception as e:
        return [('✗', 'settings.json 解析失败，钩子生效与否无法判定：%r' % e)]

    hooks = cfg.get('hooks') or {}
    reds = []
    for script, events in sorted(decl.items()):
        for ev in events:
            cs = [h.get('command', '') for e in (hooks.get(ev) or []) for h in e.get('hooks', [])]
            if not any(script in c for c in cs):
                reds.append(('✗', '%s 声明挂 hooks.%s，但 settings.json 里没有——'
                                  '脚本在盘上却不生效（重跑 install.sh）' % (script, ev)))
    return reds


def gate_hook_probe(root, settings=None):
    reds = []
    inst = os.path.join(root, 'install.sh')
    try:
        text = open(inst, encoding='utf-8', errors='ignore').read()
    except OSError:
        return ['install.sh 不可读，无法提取平台钩子清单（病13）']
    hooks = sorted(set(CP_HOOK.findall(text)))
    if not hooks:
        return ['install.sh 里提取不到平台钩子注册（cp "$ROOT/hooks/..." "$HOME/.codebuddy/hooks/"）']
    for name in hooks:
        p = os.path.join(root, 'hooks', name)
        if not os.path.isfile(p):
            reds.append('hooks/%s 被 install.sh 注册但文件不存在（病13）' % name)
            continue
        if _imported_by_other(root, name):
            # 依赖库：不要求自带 --probe，但必须真的被引用（防孤儿脚本静默失效）
            body = open(p, encoding='utf-8', errors='ignore').read()
            if not body.strip():
                reds.append('hooks/%s 是空文件却被安装（病13）' % name)
            continue
        body = open(p, encoding='utf-8', errors='ignore').read()
        missing = [k for k in ('--probe', 'hit', 'via') if k not in body]
        if missing:
            reds.append('hooks/%s 缺观测要件 %s（病13：无法判定生效与否）' % (name, '/'.join(missing)))
    return reds


IMPL_RE = re.compile(r'(?m)^[ \t]*#[ \t]*impl:[ \t]*(B-\d{2})[ \t]+(S\d)')


def collect_impl(root):
    """收集实物自报标记 `# impl: B-xx Sn` → {B-xx: {Sn: [相对路径, ...]}}。

    为什么让实物自报、而不是让闸去搜 "B-13" 字样：说明性引用与真实实现
    在文本上长得一样，扫字样必然把文档注释也当成实现——病15 家族
    （识别范围 ≠ 对象范围）。标记是显式声明，写的人负责，闸只对账。

    收严过一版：首版正则只要求「出现 # impl: B-xx Sn」，结果把本文件 docstring
    里的示例行也算成了「B-13 在 gate_scan.py 有实现」，凭空多出一处落点（上线首跑
    即踩，病15 第 6 例）。现要求**整行注释**（行首 `#`，前面只许空白），
    行内提到标记不算——这也符合「标记是声明，不是描述」的约定。
    """
    out = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in ('.git', '__pycache__', 'node_modules', '.venv', 'archive')]
        for f in files:
            # pre-push 是 git 钩子（无扩展名），与 commit-msg/pre-commit 同类——
            # 它写 # impl: 标记必须被收集，否则标记成了没人认的死声明（病15 家族）。
            if not (f.endswith('.py') or f.endswith('.sh')
                    or f in ('commit-msg', 'pre-commit', 'pre-push')):
                continue
            p = os.path.join(dirpath, f)
            try:
                t = open(p, encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            rel = os.path.relpath(p, root)
            for bid, lv in IMPL_RE.findall(t):
                out.setdefault(bid, {}).setdefault(lv, []).append(rel)
    return out


def gate_impl_reconcile(root, settings=None):
    """rule_map 的「声称强度」与实物的「自报强度」双向对账。

    查五种断裂：
      ① kind=machine 却 strength 为空 —— 机器判据无从谈起（B-02 的原始形态）
      ② 登记了强度，但全仓找不到该规则的 impl 标记 —— 写了没挂
      ③ 实物有某等级、映射没登记 —— 漏登（B-13 的原始形态）
      ④ 映射登记某等级、实物没有 —— 过期登记（改小或退役后忘了改表）
      ⑤ strength 点名的文件里没有对应标记 —— 字段是编的

    不判「行为有没有发生」：那要靠 proven_by 的实测记录，本闸只统计条数、不判红
    （没测过不等于错，但也不等于通过 —— B-02 三态不折叠）。
    """
    rmp = os.path.join(root, 'verify', 'rule_map.json')
    if not os.path.isfile(rmp):
        return [('·', 'verify/rule_map.json 不存在——无映射可比对')]
    try:
        R = json.load(open(rmp, encoding='utf-8')).get('rules') or {}
    except Exception as e:
        return [('✗', 'rule_map.json 无法解析（%s）——映射等于没有' % type(e).__name__)]
    if not R:
        return [('·', 'rule_map.rules 为空——还没有任何规则登记')]

    impl = collect_impl(root)
    items = []
    for bid in sorted(R):
        r = R[bid] or {}
        declared = set((r.get('strength') or {}).keys())
        actual = set((impl.get(bid) or {}).keys())
        kind = r.get('kind')
        if kind == 'machine' and not declared:
            items.append(('✗', '%s 标 machine 但 strength 为空——机器判据无从谈起，是虚标' % bid))
        if declared and not actual:
            items.append(('✗', '%s 登记 %s，全仓却找不到 `# impl: %s S*` 标记——写了没挂'
                          % (bid, sorted(declared), bid)))
        for lv in sorted(actual - declared):
            items.append(('✗', '%s 实物自报 %s（%s），映射未登记——漏登'
                          % (bid, lv, ', '.join(sorted(impl[bid][lv])[:2]))))
        for lv in sorted(declared - actual):
            items.append(('✗', '%s 映射登记 %s，实物无该等级标记——过期登记' % (bid, lv)))
        # ⑤ strength 里点名的文件，必须真的带该等级标记
        for lv, ref in (r.get('strength') or {}).items():
            if not ref:
                continue
            fn = ref.split('#')[0].strip()
            hit = impl.get(bid, {}).get(lv) or []
            if fn and fn not in hit:
                items.append(('✗', '%s 的 %s 指向 %s，但该文件里没有 `# impl: %s %s`'
                              % (bid, lv, fn, bid, lv)))
    if items:
        return items

    # 全绿时也给一条统计，不假装「全绿 = 都实测过」
    proven = sum(1 for b in R
                 if ((R[b].get('proven_by') or {}).get('got') or '').strip()
                 and '未实测' not in ((R[b].get('proven_by') or {}).get('got') or ''))
    return [('·', '强度对账全对：%d 条有实测记录 / %d 条无（无实测≠通过，只是没测过）'
             % (proven, len(R) - proven))]


def gate_orphan_guard(root, settings=None):
    """反向核：install.sh 注册到用户机器的独立钩子，必须有规则归属。

    impl-reconcile 是「从 rule_map 出发查实物」，本闸是反方向「从实物（已注册钩子）
    出发查 rule_map」——补上「装了钩子却没人认领」的盲区。这类孤儿闸改坏了，
    没有任何 strength/impl 对账会红，等于装了个没人守的守卫（假闭环）。

    对象范围（病15 精确锚定）：install.sh 里 `cp "$ROOT/hooks/X" "$HOME/.codebuddy/hooks/"`
    的脚本，且排除被别的钩子 import 的依赖库（如 guard_cmd 被 next_anchor import，
    归属由引用方承担，不单独要求标记）。不扫 hooks/ 目录全部 .py——那是识别范围
    宽于对象范围，会把测试用的临时脚本、未安装的存货也算成孤儿。

    归属判定（两条任一即可，避免误伤）：
      ① 脚本内有整行 `# impl: B-xx Sn` 标记；
      ② rule_map 的 impl 数组或 strength 点名了该文件。
    """
    rmp = os.path.join(root, 'verify', 'rule_map.json')
    if not os.path.isfile(rmp):
        return [('·', 'rule_map.json 不存在——孤儿闸反向核无映射可比，不适用')]
    try:
        R = json.load(open(rmp, encoding='utf-8')).get('rules') or {}
    except Exception as e:
        return [('✗', 'rule_map.json 无法解析（%s）——孤儿闸反向核失效' % type(e).__name__)]

    inst = os.path.join(root, 'install.sh')
    try:
        text = open(inst, encoding='utf-8', errors='ignore').read()
    except OSError:
        return [('✗', 'install.sh 不可读，无法提取注册钩子清单（孤儿闸反向核）')]
    hooks = sorted(set(CP_HOOK.findall(text)))
    if not hooks:
        return [('✗', 'install.sh 提取不到 cp 注册钩子——删掉 cp 行即可绕过本闸，判据失效')]

    # 归属②：rule_map 的 impl/strength 点名过的文件集合
    named = set()
    for r in R.values():
        r = r or {}
        for f in (r.get('impl') or []):
            named.add(f.replace('\\', '/'))
        for ref in (r.get('strength') or {}).values():
            if ref:
                named.add(ref.split('#')[0].strip().replace('\\', '/'))

    # 归属①：全仓 # impl: 标记（复用 collect_impl，整行注释口径一致）
    impl = collect_impl(root)

    reds = []
    for name in hooks:
        rel = 'hooks/' + name
        if _imported_by_other(root, name):
            continue  # 依赖库：归属由引用方承担（guard_cmd 先例）
        stem = name[:-3] if name.endswith('.py') else name
        # ② rule_map 点名（整路径或文件名）
        if rel in named or name in named or any(p.endswith('/' + name) for p in named):
            continue
        # ① 实物标记（脚本内有 # impl: 整行）
        if any(any(os.path.basename(p) == name for p in paths)
               for levels in impl.values() for paths in levels.values()):
            continue
        reds.append(('✗', '%s 已注册到用户机器，但无 `# impl:` 标记、rule_map 也未点名——'
                          '孤儿闸：改坏了没有任何判据会红（S5 变更闸本应守它）' % rel))
    if not reds:
        return [('·', '孤儿闸反向核全对：%d 个已注册独立钩子都有规则归属'
                 % sum(1 for n in hooks if not _imported_by_other(root, n)))]
    return reds


GATES = {'quotepath': gate_quotepath, 'hook-probe': gate_hook_probe,
         'hook-registered': gate_hook_registered, 'case-count': gate_case_count,
         'impl-reconcile': gate_impl_reconcile, 'orphan-guard': gate_orphan_guard}


def main():
    args = sys.argv[1:]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gates = list(GATES)
    settings = None
    while args:
        a = args.pop(0)
        if a == '--root':
            root = args.pop(0)
        elif a == '--gate':
            gates = [args.pop(0)]
        elif a == '--settings':
            settings = args.pop(0)
        else:
            print('未知参数 %s（支持 --root DIR / --gate %s / --settings PATH）'
                  % (a, '|'.join(GATES)))
            return 2
    all_reds = []
    n_note = 0
    for g in gates:
        if g not in GATES:
            print('✗ 未知 gate：%s' % g)
            return 2
        items = GATES[g](root, settings)
        # 允许闸返回 ('✗'|'·', msg)：· 是「不适用」，既不判通过也不判失败（B-02 三态不折叠）
        items = [it if isinstance(it, tuple) else ('✗', it) for it in items]
        for kind, msg in items:
            print('  %s [%s] %s' % (kind, g, msg))
        if not items:
            print('  ✓ [%s] 全绿' % g)
        all_reds += [m for k, m in items if k == '✗']
        n_note += sum(1 for k, _ in items if k == '·')
    print('gate_scan：%d gate / %d 红 / %d 不适用' % (len(gates), len(all_reds), n_note))
    return 2 if all_reds else 0


if __name__ == '__main__':
    sys.exit(main())
