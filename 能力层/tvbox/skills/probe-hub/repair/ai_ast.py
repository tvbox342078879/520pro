#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair/ai_ast.py —— LLM 补丁的 AST 能力层校验（S224·吸收 base(5) ai_ast）

**为什么需要它**（与 schema 契约的分工）：
  · `repair_result.schema.json` 管的是**格式**——补丁形状对不对；
  · 本模块管的是**能力**——补丁有没有偷偷给源加危险能力。
  两者互补：LLM 完全可能返回一个格式合法、但顺手 `import subprocess` 的补丁。

**基线豁免（学自壳，且我们认同这个设计）**：
  判据不是「有没有危险模块」，而是「**新增**了什么危险模块」。
  原代码本来就 `import socket`（直播源很常见）不算问题——一刀切禁掉会让修复直接不可行；
  只拦补丁"偷偷引入"的能力，既防后门又不阻断修复。
  同理：补丁**移除**危险模块永远是好事，不拦。

用法：
  python3 ai_ast.py <新源码> --old <旧源码>
  from repair.ai_ast import check; ok, kind, msg, line = check(new, old)
"""
from __future__ import annotations

import ast
import sys

# 白名单 53 个（照搬壳，可按需裁剪；明显是写源够用的那一套）
ALLOWED_MODULES = frozenset({
    'Crypto', 'base', 'base64', 'binascii', 'bs4', 'cachetools', 'calendar',
    'codecs', 'collections', 'copy', 'dataclasses', 'datetime', 'decimal',
    'enum', 'ext', 'fractions', 'functools', 'glob', 'gzip', 'hashlib', 'hmac',
    'html', 'htmlparse', 'io', 'itertools', 'json', 'logging', 'lxml', 'math',
    'operator', 'os', 'pyquery', 'queue', 'random', 're', 'requests', 'secrets',
    'statistics', 'string', 'struct', 'sys', 'tempfile', 'textwrap', 'threading',
    'time', 'traceback', 'typing', 'urllib', 'urllib3', 'uuid', 'warnings', 'zlib',
})

# 禁止 11 个：能起进程、能开原始套接字、能反序列化执行、能动态加载代码
BANNED_MODULES = frozenset({
    'ctypes', 'fcntl', 'importlib', 'multiprocessing', 'pickle', 'platform',
    'pty', 'shutil', 'signal', 'socket', 'subprocess',
})

# 禁止调用（属性名或函数名命中即算）。比壳更严一点：补上 eval/exec/compile。
BANNED_CALLS = frozenset({
    'eval', 'exec', 'compile', '__import__', 'system', 'popen', 'spawn',
    'fork', 'kill', 'remove', 'rmtree', 'unlink', 'chmod', 'chown',
})


def _top(module_name):
    """取模块顶层名：'requests.adapters' → 'requests'。"""
    return (module_name or '').split('.')[0]


def _collect_imports(tree):
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for al in n.names:
                mods.add(_top(al.name))
        elif isinstance(n, ast.ImportFrom):
            if n.level == 0 and n.module:      # 相对导入不算（层次不由这里管）
                mods.add(_top(n.module))
    return mods


def _call_name(node):
    """把调用表达式还原成点号名字：os.system(...) → 'os.system'。"""
    parts = []
    cur = node.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return '.'.join(reversed(parts))
    return ''


def _collect_calls(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = _call_name(n)
            if name:
                out.add(name)
    return out


def _parse(code):
    return ast.parse(code)


def check(new_code, old_code=''):
    """校验补丁后的源码。返回 (ok, kind, message, line)。

    kind: ''（通过）/ 'syntax'（语法错）/ 'import'（新增禁用或白名单外导入）/ 'danger'（新增禁用调用）
    line: 语法错时给行号，其余为 0
    """
    try:
        new_tree = _parse(new_code)
    except SyntaxError as e:
        return False, 'syntax', f'第 {e.lineno} 行语法错误：{e.msg}', e.lineno or 0
    except Exception as e:
        return False, 'syntax', f'无法解析：{type(e).__name__}: {e}', 0

    try:
        old_tree = _parse(old_code) if old_code and old_code.strip() else None
    except Exception:
        # 旧代码本身语法坏 → 不给基线豁免（从严），否则基线可以被人为污染来放行
        old_tree = None

    old_imports = _collect_imports(old_tree) if old_tree else set()
    old_calls = _collect_calls(old_tree) if old_tree else set()

    # ① 新增的禁用模块
    new_imports = _collect_imports(new_tree)
    banned = sorted((new_imports - old_imports) & BANNED_MODULES)
    if banned:
        return False, 'import', f'新增了禁止的导入模块：{", ".join(banned)}', 0

    # ② 新增的白名单外模块
    outside = sorted((new_imports - old_imports) - ALLOWED_MODULES - BANNED_MODULES)
    if outside:
        return False, 'import', f'新增了白名单外的导入模块：{", ".join(outside)}', 0

    # ③ 新增的禁用调用（只比末段名：os.system 与 system 同等对待）
    new_calls = _collect_calls(new_tree)
    def tails(names):
        return {n.rsplit('.', 1)[-1] for n in names}
    added_tails = tails(new_calls) - tails(old_calls)
    danger = sorted(added_tails & BANNED_CALLS)
    if danger:
        return False, 'danger', f'新增了禁止的调用：{", ".join(danger)}', 0

    return True, '', '', 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description='LLM 补丁 AST 能力层校验（基线豁免）')
    ap.add_argument('new_src')
    ap.add_argument('--old', default='', help='补丁前源码（提供则只拦增量）')
    a = ap.parse_args()
    new = open(a.new_src, encoding='utf-8').read()
    old = open(a.old, encoding='utf-8').read() if a.old else ''
    ok, kind, msg, line = check(new, old)
    if ok:
        print('✅ AST 校验通过（无新增危险能力）')
        return 0
    print(f'❌ [{kind}] {msg}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
