# -*- coding: utf-8 -*-
"""模板库构建器（forgekit）—— 把复用件在**构建期**内联进单文件源。

## 为什么必须在构建期内联，而不是运行时 import

业内两条硬约束（kasas ADR 0001 + pypacker 实践）：

1. TVBox 壳装源时只吃**一个文件**。插件可以有依赖，但交付时必须打成单一入口。
   kasas 的原话大意：打包进来的 lodash 能排数组，但打不开 socket ——
   因为 socket API 根本不在包里。**能用到什么能力，由打包那一刻决定。**
2. 运行时动态加载（往 sys.modules 塞字符串再改写 import）坑太多：
   - `__package__` 在 `__main__` 下是 None，相对 import 直接
     `SystemError: Parent module '' not loaded`
   - 模块名冲突会覆盖真实模块（必须用唯一名）
   - 有些库依赖 `__file__`，动态模块没有这个属性
   - 清 sys.modules 不会更新已持有的引用
   这些坑在用户手机上全是黑屏/闪退，却没法远程排查。

所以本模块只做一件事：**读模板源文件 → 生成去掉注释/docstring 的纯代码 →
拼装成可直接粘贴进 build 产物的字符串**。产物里不留 import、不留运行时加载。

## 三道硬约束（都是踩过的）

- **只用标准库**：模板里只允许 `json` `re` 与 `urllib.parse`。
  壳的 Python 环境不一定有 requests/lxml；`base64` 一类可以引，但用不到就不引。
- **过体积门禁**：生成物必须能被 `forge_gate.gate_size` 判 PASS。
  注释、docstring、`__main__` 一律不落进产物。
- **语法可解析**：产物先 `ast.parse` 一遍再返回，语法错就不出包。
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '_template_src.py')

# 模板允许引用的标准库（白名单）。
# 为什么卡这么死：壳端 Python 可能没有第三方包，而 `socket`/`subprocess`
# 这类模块在源里根本不该出现（写源四门禁 + ai_ast 都会拦）。
ALLOWED_IMPORTS = {'json', 're', 'urllib.parse', 'urllib.request', 'base64',
                   'hashlib', 'time', 'random', 'math',
                   # Crypto 只允许出现在 try 里（有就快、没有就走纯 Python 兜底），
                   # 见 _check_optional_imports —— 不允许裸露的顶层 import。
                   'Crypto'}


# ═══════════════════════ 模板库清单 ═══════════════════════
# name → (说明, 需要的前置片段名列表, 是否需要 json/re 之类)
# 顺序即依赖顺序：后面的可以依赖前面的。
COMPONENTS = [
    ('flags', '线路名归一化别名表（33 项，含「优 酷」这类字间空格变体）', []),
    ('play_groups', 'r148 三数字模板选集：按 sid/nid 分组，避免把同集不同线路当多集', []),
    ('pic', 'r145 封面兜底：data-src → poster → background-image 等 8 级 + 占位图排除', []),
    ('inline', '内联首屏数据提取四件套（打分选片单，同分取条数多）', []),
    ('aes', '纯 Python AES-CBC 解密兜底（有 pycryptodome 时优先用它）', []),
]

# 方法名 → 所属片段（拼装时按需取）
METHODS = {
    'flags': ['_norm_flag', '_fix_url'],
    'play_groups': ['_play_groups', '_play_build'],
    'pic': ['_pic'],
    'inline': ['_json_block', '_inline_state', '_inline_arrays',
               '_inline_score', '_inline_walk', '_inline_items'],
    'aes': ['_aes_decrypt'],
}

# 顶层函数/常量 → 所属片段
TOPLEVEL = {
    'aes': ['_build_sbox', '_SBOX', '_INV', '_RCON', '_gmul', '_expand_key',
            '_decrypt_block', '_aes_cbc_decrypt'],
    'flags': ['FLAGS'],
    'pic': ['PIC_BAD', 'PIC_PAT'],
    'inline': ['STATE_KEYS', 'SCORE'],
    'play_groups': [],
}


# 片段 → 它需要的 import 行（原样抄模板源顶部的写法）
IMPORTS = {
    'flags': [],
    'play_groups': ['import re'],
    'pic': ['import re'],
    'inline': ['import json'],
    'aes': [],
}


# 片段 → 依赖的**模块级语句块**（形如 `for _i,_v in ...: _INV[_v]=_i` 这种赋值+循环）
# ★ 只有顶层 Assign 不够：`_INV` 的填充是靠一个模块级 for 循环完成的，
#   第一版只搬 `_INV = [0]*256`，搬来的是一张全 0 表 →
#   InvSubBytes 变成恒等映射 → 解密结果「看起来很有结构（正好等于 key）」
#   却完全不对。这类 bug 只有「拿独立库的密文反解」才抓得到。
MODULE_STMTS = {
    'aes': [('_INV', [ast.For])],
}


class TemplateError(Exception):
    pass


def _parse():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        raise TemplateError(f'模板源语法错误：{e}')
    return text, tree


def _strip_node(src_lines, node, keep_doc=False):
    """取一个顶层节点/方法的源码，去掉 docstring 与注释行。

    注意：这里**不能**用 `ast.unparse` 重排已有代码 —— 它会把
    `p ^ ((p<<1)&0xFF)` 重写成 `p ^ p << 1 & 255`，语义相等但可读性差一个档，
    而且会顺手丢掉所有常量表的行内说明。所以策略是：
      · 函数体：保留原文，只删注释行与 docstring 行
      · 只有确实需要清 docstring 的多行块，才退回 unparse
    这些代码最终是要**贴到给用户看的源文件里**的，可读性是硬要求。
    """
    seg = ast.get_source_segment('\n'.join(src_lines), node) or ''
    out = []
    in_doc = None
    for ln in seg.splitlines():
        s = ln.strip()
        if s.startswith('#'):
            continue
        # 单行 docstring：整行丢弃（函数/类首行）
        if in_doc is None and (s.startswith('"""') or s.startswith("'''")):
            q = s[:3]
            if s.count(q) >= 2 and len(s) > 3:
                continue                    # 单行闭合
            in_doc = q
            continue
        if in_doc:
            if in_doc in s:
                in_doc = None
            continue
        out.append(ln)
    txt = '\n'.join(out)
    if not txt.strip():
        return ''
    return _dedent(txt).strip('\n')


def _dedent(s):
    lines = s.splitlines()
    pad = None
    for ln in lines:
        if ln.strip():
            n = len(ln) - len(ln.lstrip())
            pad = n if pad is None else min(pad, n)
    if not pad:
        return s
    return '\n'.join(ln[pad:] if ln.strip() else '' for ln in lines)


def _imports_of(text):
    mods = set()
    for n in ast.walk(ast.parse(text)):
        if isinstance(n, ast.Import):
            for a in n.names:
                mods.add(a.name.split('.')[0])
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                mods.add(n.module.split('.')[0])
    return mods


def build(components=None, *, indent=4):
    """→ (code, meta)。

    code 是可直接粘进源文件的顶层代码块（含 class 内的改用 `indent` 缩进版）。
    meta 记录每个片段的行数，方便排查体积。
    """
    want = list(components or [c[0] for c in COMPONENTS])
    bad = [w for w in want if w not in dict((c[0], 1) for c in COMPONENTS)]
    if bad:
        raise TemplateError(f'未知片段：{bad}（可选 {[c[0] for c in COMPONENTS]}）')

    src, tree = _parse()
    lines = src.splitlines()

    top_nodes, method_nodes, mixin = {}, {}, None
    module_stmts = {}          # 目标名 → 相关的模块级语句（For 等）
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name == 'Mixin':
            mixin = n
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_nodes[m.name] = m
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign)):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        top_nodes[t.id] = n
            else:
                top_nodes[n.name] = n
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            top_nodes[n.target.id] = n
        elif isinstance(n, (ast.For, ast.If)):
            # 记录它写到/读到了哪些顶层名字。
            # ★ 必须同时看 Store 和 Load：`for _i, _v in enumerate(_SBOX): _INV[_v] = _i`
            #   写进去的是 `_INV[_v]`（Subscript，不是 Name），唯一出现 `_INV` 的地方
            #   是 Load。只认 Store 的话这条语句根本挂不到 `_INV` 名下，被静默丢弃。
            for sub in ast.walk(n):
                if isinstance(sub, ast.Name):
                    module_stmts.setdefault(sub.id, []).append(n)

    need_methods, need_top, need_imports = [], [], []
    for part in want:
        need_methods += [m for m in METHODS[part] if m not in need_methods]
        need_top += [t for t in TOPLEVEL[part] if t not in need_top]
        # ★ 每个片段自己声明的 import 也要带上。
        #   第一版只搬「方法 + 含常量的赋值」，漏了模板顶部的 import json/re ——
        #   产物 ast.parse 能过（语法合法），一 exec 就 NameError: name 're' is not defined。
        #   壳端表现是「源一加载就报错」，且报的是模板内部的行号，极难归因。
        for im in IMPORTS.get(part, []):
            if im not in need_imports:
                need_imports.append(im)
    # 片段之间的隐式依赖：_aes_decrypt 不依赖别的，_pic 只用 PIC_*，
    # inline 的四件套互相调用（_inline_items→_inline_state/_inline_walk）
    if 'inline' in want:
        for m in METHODS['inline']:
            if m not in need_methods:
                need_methods.append(m)

    missing = [m for m in need_methods if m not in method_nodes]
    if missing:
        raise TemplateError(f'模板里找不到方法：{missing}')

    out_top = []
    for t in need_top:
        if t not in top_nodes:
            raise TemplateError(f'模板里找不到顶层定义：{t}')
        out_top.append(_strip_node(lines, top_nodes[t]))
    out_top = _reorder(out_top, need_top, want)

    # 模块级填充语句：必须紧跟在它为赋值的那行后面（保持源码里的先后关系）
    stmt_of = {}
    for part in want:
        for target, kinds in MODULE_STMTS.get(part, []):
            if target not in need_top:
                continue
            for st in module_stmts.get(target, []):
                if type(st) not in kinds:
                    continue
                if st in stmt_of.setdefault(target, []):
                    continue
                stmt_of[target].append(st)
    if stmt_of:
        merged = []
        for txt in out_top:
            merged.append(txt)
            first = txt.split('\n', 1)[0].split('=')[0].strip()
            for st in stmt_of.get(first, []):
                body_txt = _strip_node(lines, st)
                if body_txt:
                    merged.append(body_txt)
        out_top = merged

    out_methods = [_strip_node(lines, method_nodes[m]) for m in need_methods]
    cls = ['class ForgeMixin(object):']
    for m in out_methods:
        for ln in m.splitlines():
            cls.append((' ' * indent + ln) if ln.strip() else '')
        cls.append('')

    head = '\n'.join(sorted(set(need_imports))) if need_imports else ''
    body = '\n\n'.join(out_top + ['\n'.join(cls).rstrip()])
    code = (head + '\n\n' + body).strip('\n') + '\n'

    mods = _imports_of(code)
    extra = sorted(mods - ALLOWED_IMPORTS)
    if extra:
        raise TemplateError(f'模板引了白名单外的模块：{extra}（源端可能没有这些包）')
    _check_optional_imports(code, tree)

    try:
        ast.parse(code)
    except SyntaxError as e:
        raise TemplateError(f'生成物语法错误：{e}\n---\n{code[:800]}')

    meta = {
        'components': want,
        'lines': len(code.splitlines()),
        'bytes': len(code.encode('utf-8')),
        'imports': sorted(mods),
        'methods': need_methods,
        'toplevel': need_top,
    }
    return code, meta


def _check_optional_imports(code, tree):
    """可选依赖（Crypto）只许出现在 try 里。

    为什么这条必须机器查：`import Crypto` 写在函数顶层时，羊壳没有 pycryptodome
    会直接 ModuleNotFoundError，**整个源在 import 阶段就挂**——症状是「源加载失败」
    而不是「解密失败」，用户根本没法归因。这类坑在陷阱库 G 组排第一条。
    正确写法只有一种：

        try:
            from Crypto.Cipher import AES
        except ImportError:
            走纯 Python 兜底

    所以这里做的是「Crypto 的每次 import 都必须有一个 except ImportError 的父 try」。
    """
    trees = [tree]
    # 产物是重新拼的，用产物重新 parse 一遍，查的是真正会交付的代码
    try:
        trees = [ast.parse(code)]
    except SyntaxError:
        pass
    for t in trees:
        for node in ast.walk(t):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            names = [a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import) \
                else [(node.module or '').split('.')[0]]
            if 'Crypto' not in names:
                continue
            guarded = False
            for anc in ast.walk(t):
                if not isinstance(anc, ast.Try):
                    continue
                if node not in [x for b in anc.body for x in ast.walk(b)]:
                    continue
                for h in anc.handlers:
                    if h.type is None:
                        guarded = True
                    elif isinstance(h.type, ast.Name) and h.type.id == 'ImportError':
                        guarded = True
                    elif isinstance(h.type, ast.Attribute) and h.type.attr in ('ImportError', 'ModuleNotFoundError'):
                        guarded = True
                if guarded:
                    break
            if not guarded:
                raise TemplateError(
                    '模板里存在未被 try/except ImportError 保护的 Crypto import'
                    f'（第 {getattr(node, "lineno", "?")} 行）——没有该库的壳会整源加载失败')


def _reorder(items, names, want):
    """顶层定义按**真实依赖**排序，不按「常量先/函数后」的粗规则。

    ★ 第一版用的是「所有赋值排前面」，结果 `_SBOX = _build_sbox()` 跑到了
      `def _build_sbox` 前面 —— 语法能过、ast.parse 也能过，但一 exec 就
      `NameError: name '_build_sbox' is not defined`。这种 bug 只有真跑才抓得到，
      所以本模块的 `selftest()` 一定要 exec 一遍，不许只 parse。
    """
    order = []
    for part in want:
        for t in TOPLEVEL.get(part, []):
            if t in names and t not in order:
                order.append(t)
    for t in names:
        if t not in order:
            order.append(t)

    txt_of = dict(zip(names, items))
    # 依赖收集：某段代码里引用到的、属于本批的其它名字
    deps = {}
    for name, txt in txt_of.items():
        used = set()
        try:
            for n in ast.walk(ast.parse(txt)):
                if isinstance(n, ast.Name):
                    used.add(n.id)
                elif isinstance(n, ast.Attribute):
                    pass
        except SyntaxError:
            pass
        deps[name] = {u for u in used if u in txt_of and u != name}

    out, done, visiting = [], set(), set()

    def visit(n):
        if n in done:
            return
        if n in visiting:
            # 循环依赖不该出现在模板里；真出现就保持原序，交给 exec 自检去报
            return
        visiting.add(n)
        for d in sorted(deps.get(n, ())):
            visit(d)
        visiting.discard(n)
        if n not in done:
            done.add(n)
            out.append(txt_of[n])

    for n in order:
        visit(n)
    return out


def selftest():
    """自检：构建 → exec → 跑行为断言。只 parse 不够，必须真跑（见 _reorder 注释）。"""
    import binascii
    fails = []

    def chk(name, cond, detail=''):
        print(f'[{"OK " if cond else "FAIL"}] {name}' + ('' if cond else f'  {detail}'))
        if not cond:
            fails.append(f'{name} {detail}')

    try:
        code, meta = build()
    except TemplateError as e:
        print(f'[FAIL] 构建失败：{e}')
        return 1
    chk('构建成功', True, f'{meta["lines"]}行/{meta["bytes"]}B')
    chk('体积 < 80KB（写源四门禁基线）', meta['bytes'] < 80 * 1024, f'{meta["bytes"]}B')

    # ① 不用 compile 也要 AST 能过
    import ast as _ast
    try:
        _ast.parse(code)
        chk('产物语法可解析', True)
    except SyntaxError as e:
        chk('产物语法可解析', False, str(e))
        return 1

    # ② 真跑：exec 到干净命名空间（模拟壳端 import 时执行顶层）
    ns = {}
    try:
        exec(compile(code, '<forgekit>', 'exec'), ns)      # noqa: S102
        chk('产物可 exec（顶层无未定义引用）', True)
    except Exception as e:                                  # noqa: BLE001
        chk('产物可 exec（顶层无未定义引用）', False, f'{type(e).__name__}: {e}')
        return 1

    M = ns.get('ForgeMixin')
    chk('ForgeMixin 存在', M is not None)
    if not M:
        return 1
    inst = M()
    inst.host = 'https://www.example.com'

    # ③ AES：用 pycryptodome 现算一个向量，两边必须一致
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        key = bytes(range(16))
        iv = bytes(range(16, 32))
        data = b'tvbox forgekit aes selftest'
        ct = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(data, 16))
        got = inst._aes_decrypt(ct, key, iv)
        chk('AES 与 pycryptodome 一致', got == data, got[:16])
    except ImportError:
        print('[SKIP] 无 pycryptodome，跳过 AES 交叉验证（纯 Python 版由 hls 侧另测）')

    # ④ 纯 Python AES 单块：用**独立库现算**的密文反解，避免写死向量抄错
    #    ★ 变量名不要用 k —— 上面 ③ 已经用 `key` 了没问题，但曾经误用 k
    #      导致「密文拿 key 的字节去解」，报出来的是 key 本身，白排查一轮。
    #      这类「测试自己写错」的失败比实现错更常见，测试里变量名要长且唯一。
    try:
        from Crypto.Cipher import AES
        aes_key = bytes.fromhex('2b7e151628aed2a6abf7158809cf4f3c')
        want_pt = bytes.fromhex('00112233445566778899aabbccddeeff')
        ecb_ct = AES.new(aes_key, AES.MODE_ECB).encrypt(want_pt)
        round_keys, n_rounds = ns['_expand_key'](aes_key)
        got_pt = ns['_decrypt_block'](ecb_ct, round_keys, n_rounds)
        chk('纯 Python AES 单块正确', got_pt == want_pt,
            f'得到 {got_pt.hex()}，期望 {want_pt.hex()}（密文由 pycryptodome ECB 生成）')
    except ImportError:
        print('[SKIP] 无 pycryptodome，纯 Python AES 无独立参照，跳过')
    except Exception as e:                                  # noqa: BLE001
        chk('纯 Python AES 单块正确', False, f'{type(e).__name__}: {e}')

    # ⑤ 内联提取：导航标签 vs 片单，必须选片单（同分取条数多的那条规则的实测场景）
    html = ('<html><script>window.APP_DATA = {"mods":{"text_link":['
            + ','.join('{"title":"标签%d","url":"/tag/%d"}' % (i, i) for i in range(20))
            + '],"video_list":['
            + ','.join('{"title":"片%d","m3u8":"https://cdn.x/%d.m3u8","thumbnail":"t%d.jpg"}'
                       % (i, i, i) for i in range(20))
            + ']}};</script></html>')
    items = inst._inline_items(html)
    chk('内联提取选片单而非导航', bool(items) and 'm3u8' in items[0],
        str(items[:1]))

    # ⑥ 封面兜底：占位图必须跳过
    chk('封面跳过占位图',
        inst._pic('<img src="/static/images/blank.gif" data-src="/u/real.jpg">')
        == 'https://www.example.com/u/real.jpg',
        inst._pic('<img src="/static/images/blank.gif" data-src="/u/real.jpg">'))
    chk('封面 // 补 https',
        inst._pic('data-original="//cdn.x/a.jpg"') == 'https://cdn.x/a.jpg')
    chk('封面 data: 丢弃', inst._pic('src="data:image/png;base64,xx"') == '')

    # ⑦ 线路分组：同集多 sid 不得算成多集（r148 的原始踩坑）
    html2 = ('<a href="/bofang/9-1-1.html">x</a><a href="/bofang/9-2-1.html">y</a>'
             '<a href="/bofang/9-3-1.html">z</a>')
    g = inst._play_groups(html2, r'href="(/bofang/\d+-(\d+)-(\d+)\.html)"')
    f2, u2 = inst._play_build(g, '线路')
    chk('单集多线路 → 每线路 1 集「正片」', u2.count('正片') == 3 and '第01集' not in u2,
        f'{f2} | {u2}')

    # ⑧ 线路名归一化：字间空格变体
    chk('线路名「优 酷」归一化', inst._norm_flag('优 酷') == 'youku',
        inst._norm_flag('优 酷'))
    chk('线路名「爱 奇 艺」归一化', inst._norm_flag('爱 奇 艺') == 'iqiyi')

    # ⑨ URL 补全
    chk('相对路径补全', inst._fix_url('https://a.com', 'x/y.jpg') == 'https://a.com/x/y.jpg')
    chk('协议相对补全', inst._fix_url('https://a.com', '//b.com/z') == 'https://b.com/z')

    print()
    if fails:
        print(f'✗ {len(fails)} 项失败')
        for f in fails:
            print('  -', f)
        return 1
    print('✓ 模板库全部自检通过')
    return 0


def hook_mixin(class_name='Spider', base='Spider', indent=4):
    """生成「已继承 ForgeMixin 的 Spider 类头」，供 forge 拼装时直接接进用户代码。

    用法：把 `class Spider(Spider):` 这一行整行替换成 hook_mixin() 的返回值，
    其余代码一个字不动。这样：
      · 用户源里已有的方法一个不丢（模板不覆盖业务逻辑）
      · 模板提供的方法通过 MRO 兜底（用户自己写了的优先，天然可覆盖）
      · 产物仍然是**单文件**，不需要 sys.path、不需要 sys.modules 注入

    LLM 常把 `class Spider(Spider):` 写成 `class Spider(Spider, object):` 或
    加了注释，故本函数返回的是「能配一个宽松正则用的文本」而不是行号替换。
    """
    return 'class %s(ForgeMixin, %s):' % (class_name, base)


def hook(src, class_name='Spider', base='Spider', components=None):
    """把模板库内联进一份源，返回 (new_src, report)。

    做三件事，且**只做这三件**（不碰业务逻辑、不改缩进、不重排代码）：
      1. 去掉文件头 shebang / coding 行（部分壳对首行非注释有要求，也不占体积配额）
      2. 在 import 区之后插入模板库（import + 常量 + 顶层函数 + ForgeMixin 类）
      3. 把 `class Spider(Spider):` 改成 `class Spider(ForgeMixin, Spider):`

    任何一步判断不了，就**原样返回 + report 里写清楚**，不猜。
    """
    code, meta = build(components)
    rep = {'components': meta['components'], 'kit_lines': meta['lines'],
           'kit_bytes': meta['bytes'], 'changed': [], 'skipped': []}
    lines = (src or '').split('\n')
    head = [i for i, ln in enumerate(lines[:3])
            if ln.startswith('#!') or 'coding' in ln or 'encoding' in ln]

    tree = None
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        rep['skipped'].append(f'源码语法错误，不注入：{e}')
        return src, rep

    # 找最后一个顶层 import 的位置
    last_imp = -1
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            last_imp = max(last_imp, getattr(n, 'end_lineno', n.lineno))
        if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and getattr(n, 'name', '') == 'Spider':
            break

    cls_line = None
    already = False
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name == class_name:
            cls_line = n.lineno
            bases = [getattr(b, 'id', getattr(b, 'attr', '')) for b in n.bases]
            if 'ForgeMixin' in bases:
                already = True
            break
    if cls_line is None:
        rep['skipped'].append(f'找不到 class {class_name}，不注入（避免拼出跑不起来的源）')
        return src, rep

    # ★ 幂等：已经注入过就整体跳过。
    #   第一版只跳过「类头改写」，还是会再把 308 行模板插一遍 ——
    #   生成重复的 FLAGS/ForgeMixin 定义，体积白涨、行为还能被后一份覆盖。
    #   重复注入在流水线上极容易发生（build 重跑、批量脚本跑两遍）。
    if already or re.search(r'^class ForgeMixin\b', src, re.M):
        rep['skipped'].append('已内联过模板库（检测到 ForgeMixin），本次不做任何改动')
        return src, rep

    out = []
    for i, ln in enumerate(lines):
        if i in head:
            continue
        out.append(ln)
        if i + 1 == last_imp + 1 and last_imp >= 0:
            out.append('')
            out.append(code.rstrip('\n'))
            rep['changed'].append(f'在第 {i + 1} 行后插入模板库')
    # 类头改写（行号因插入而偏移，重新扫）
    for i, ln in enumerate(out):
        if ln.lstrip().startswith('class %s(' % class_name) and 'ForgeMixin' not in ln:
            stripped = ln.lstrip()
            ind = ln[:len(ln) - len(stripped)]
            out[i] = ind + hook_mixin(class_name, base)
            rep['changed'].append(f'第 {i + 1} 行：{ln.strip()} → {out[i].strip()}')
            break

    new_src = '\n'.join(out)
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        rep['skipped'].append(f'注入后语法错误，回退原文：{e}')
        return src, rep
    rep['bytes_delta'] = len(new_src.encode()) - len((src or '').encode())
    return new_src, rep


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    parts = None
    out = ''
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--only':
            parts = argv[i + 1].split(',')
            i += 2
            continue
        if a == '--out':
            out = argv[i + 1]
            i += 2
            continue
        if a in ('-h', '--help'):
            print('用法：forgekit/builder.py [--only flags,play_groups,pic,inline,aes] [--out x.py]')
            print('      forgekit/builder.py --selftest')
            print('片段：' + '；'.join(f'{c[0]}（{c[1]}）' for c in COMPONENTS))
            return 0
        if a == '--selftest':
            return selftest()
        i += 1
    try:
        code, meta = build(parts)
    except TemplateError as e:
        print(f'✗ {e}')
        return 1
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(code)
        print(f'✓ 写出 {out}')
    else:
        print(code)
    print(f'# {meta["lines"]} 行 / {meta["bytes"]} B / import {meta["imports"]}',
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
