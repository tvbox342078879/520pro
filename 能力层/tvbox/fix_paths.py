#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_paths.py —— 把探源司系列脚本里硬编码的 /root/.codebuddy 改成
                os.path.expanduser('~/.codebuddy')，跨机器可用。

背景：probe.py / core.py 等写死
    _sys.path.insert(0, '/root/.codebuddy/skills/tvbox-source-hub/scripts')
非 root 用户 / Windows / 换机后全部失效。

【关键】不能简单正则替换！很多路径出现在多行字符串隐式拼接里，例如：
    ('...覆盖写入 '
     '/root/.codebuddy/.baidu_cookie（权限 600）')
一旦把中间那段换成函数调用，'a' 'b' f() 就变成非法语法。
所以本脚本用 tokenize 逐 token 判断：
  · 只处理 STRING token，且其值【以】/root/.codebuddy 开头（真路径常量，不是文案）
  · 前后相邻 token 不得是 STRING（排除隐式拼接）
  · 跳过 f-string / 注释 / docstring

用法：python3 fix_paths.py <skills_root>
"""
import io
import os
import sys
import tokenize

TARGET = '/root/.codebuddy'
NEW = "os.path.expanduser('~/.codebuddy"


def _tok_is_other_string(tok):
    return tok is not None and tok.type == tokenize.STRING


def fix_source(src: str):
    """返回 (新源码, 替换处数)。用 tokenize 精确定位。"""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError):
        return src, 0

    # 过滤掉注释/NL/缩进等，保留有意义的 token 用于邻接判断
    skip = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
            tokenize.COMMENT, tokenize.ENCODING}
    meaningful = [t for t in toks if t.type not in skip]

    idx_of = {id(t): i for i, t in enumerate(meaningful)}

    edits = []   # (start, end, replacement)
    n = 0
    for t in meaningful:
        if t.type != tokenize.STRING:
            continue
        raw = t.string
        if raw.startswith(('f"', "f'", 'F"', "F'")):
            continue                      # f-string 不动
        # 取字符串值
        try:
            val = eval(raw, {'__builtins__': {}})   # 仅字面量，安全
        except Exception:
            continue
        if not isinstance(val, str) or not val.startswith(TARGET):
            continue                      # 只认“以路径开头”的字面量
        # 邻接检查：前后若紧挨 STRING，则是隐式拼接，跳过
        i = idx_of.get(id(t))
        prev_t = meaningful[i - 1] if i and i - 1 >= 0 else None
        next_t = meaningful[i + 1] if i is not None and i + 1 < len(meaningful) else None
        if _tok_is_other_string(prev_t) or _tok_is_other_string(next_t):
            continue

        rest = val[len(TARGET):]          # 例如 /skills/xxx
        quote = "'" if "'''" not in raw else "'''"
        repl = NEW + rest + quote + ")"
        # token 可能跨行（三引号），用 start/end 定位覆盖行内即可
        edits.append((t.start, t.end, repl))
        n += 1

    if not edits:
        return src, 0

    lines = src.splitlines(keepends=True)
    # 从后往前改，避免偏移错乱
    for (srow, scol), (erow, ecol), repl in sorted(edits, reverse=True):
        if srow == erow:
            li = srow - 1
            lines[li] = lines[li][:scol] + repl + lines[li][ecol:]
        # 跨行字符串（罕见）跳过，避免破坏结构
    return ''.join(lines), n


def ensure_import_os(src: str) -> str:
    if 'os.path.expanduser' not in src:
        return src
    # 已有 import os 的形式
    stripped = src
    if '\nimport os' in stripped or stripped.startswith('import os'):
        return src
    if '\nfrom os import' in stripped or stripped.startswith('from os import'):
        return src
    # 插到 shebang / coding 之后
    lines = src.splitlines(keepends=True)
    pos = 0
    for i, ln in enumerate(lines[:6]):
        s = ln.strip()
        if s.startswith('#!') or 'coding' in s or s == '':
            pos = i + 1
        else:
            break
    lines.insert(pos, 'import os  # fix_paths.py 注入（路径跨机器适配）\n')
    return ''.join(lines)


def main():
    if len(sys.argv) < 2:
        print('用法: python3 fix_paths.py <skills_root>')
        sys.exit(2)
    root = os.path.expanduser(sys.argv[1])
    if not os.path.isdir(root):
        print(f'✗ 目录不存在: {root}')
        sys.exit(2)

    total_files = total_hits = 0
    for dirpath, _dn, filenames in os.walk(root):
        if '__pycache__' in dirpath:
            continue
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            p = os.path.join(dirpath, fn)
            try:
                src = open(p, encoding='utf-8').read()
            except (UnicodeDecodeError, OSError):
                continue
            if TARGET not in src:
                continue
            new, n = fix_source(src)
            if n:
                new = ensure_import_os(new)
                open(p, 'w', encoding='utf-8').write(new)
                total_files += 1
                total_hits += n
                print(f'  修正 {n:2d} 处  {os.path.relpath(p, root)}')

    print(f'✓ 完成：{total_files} 个文件，{total_hits} 处路径已改为 ~/.codebuddy')
    if not total_files:
        print('  （无独立路径字面量，或已处理过）')


if __name__ == '__main__':
    main()
