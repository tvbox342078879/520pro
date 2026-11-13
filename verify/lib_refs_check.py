#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_refs_check.py — 外部正本脚本引用对账（平台升级后指针失效的第一道闸）

为什么要单独一条检查:
  520 的技能大量复用平台 library 技能的脚本（`{LIB}/database/xxx.py`）。
  平台一改目录结构或改名，我们的调用全部变成运行时 FileNotFoundError，
  而自检看不见——因为自检只读我们自己的文件。

  2026-11-13 实测：12 类引用里 8 类已失配，横跨 10 个脚本（space-hub 与
  tvbox-core 两条主线），`database/` 整层调用全断。这不是孤例，是模式。

判据:
  扫全仓 .py，抽出所有 `{LIB}/... .py` 引用，逐个 os.path.exists。
  失配时用 difflib 给出最近的同名候选，避免瞎猜新名字。

三态（B-02）:
  ✓ 全部存在
  · 无法判定 —— library 技能未安装（本机无此依赖，不是我们的错）
  ✗ 存在失配 —— 引用写了、文件没了，调用必炸

退出码: 0=全通 / 1=有失配 / 2=无法判定
"""
import difflib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.expanduser('~/.codebuddy/skills/library')
PAT = re.compile(r'\{LIB\}/([A-Za-z0-9_/]+\.py)')
# 间接入口：脚本名以字符串常量传给 `_run_lib(...)` 一类转发函数，路径在函数内部
# 才与 LIB 拼接 —— 上面的 PAT 只看 `{LIB}/` 字面量，对这类写法是**瞎的**。
# 2026-11-13 实测：core.py:688/719、preflight.py:40 三处指着已消失的
# batch_update_database_records.py / batch_delete_database_records.py /
# get_database_schema.py，第一版检查器 0 命中（B-15 模式级盲区，不是孤例）。
# 已知仍扫不到的：run.py:54 把变量转发给 _run_lib（静态不可判，登记在文档里）。
PAT_INDIRECT = re.compile(r"""(?:_run_lib|api)\(\s*['"]([A-Za-z0-9_/]+\.py)['"]""")
PATTERNS = (PAT, PAT_INDIRECT)
SKIP_DIRS = {'__pycache__', '.git', 'node_modules'}


def collect_refs():
    refs = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith('.py'):
                continue
            full = os.path.join(dirpath, name)
            if os.path.abspath(full) == os.path.abspath(__file__):
                continue                       # 不拿自己的文档示例当引用
            try:
                text = open(full, encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            hits = []
            for pat in PATTERNS:
                hits += [(m.group(1), m.start()) for m in pat.finditer(text)]
            for rel, pos in sorted(hits, key=lambda x: x[1]):
                line = text[:pos].count('\n') + 1
                refs.setdefault(rel, []).append(f'{os.path.relpath(full, ROOT)}:{line}')
    return refs


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


def main():
    strict = '--strict' in sys.argv[1:]
    if not os.path.isdir(LIB):
        print(f'  · 无法判定：library 技能未安装（{LIB} 不存在），本机不校验外部引用')
        return 2

    refs = collect_refs()
    if not refs:
        print('  ✓ 全仓无 {LIB} 引用（不需要校验）')
        return 0

    lib_files = all_lib_scripts()
    basenames = {os.path.basename(p): p for p in lib_files}
    missing = {}
    for rel, sites in sorted(refs.items()):
        if os.path.exists(os.path.join(LIB, rel)):
            continue
        missing[rel] = sites

    total = len(refs)
    ok_n = total - len(missing)
    if not missing:
        print(f'  ✓ 外部正本引用全部有效（{ok_n}/{total} 类，共 {sum(len(v) for v in refs.values())} 处）')
        return 0

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
    if strict:
        return 1
    print('     （warn 级：日常自检不阻断；发布前 `--strict` 会红。已登记 docs/遗留登记.md）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
