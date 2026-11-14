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

诚实边界：行级扫描，多行 subprocess 列表会漏报——多行调用须写在同一行，
或在本文件附近登记豁免理由（M7）。退出码 0 全绿 / 2 有红。
"""
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


def gate_quotepath(root):
    reds = []
    for rel, i, line in scan_lines(root):
        if line.lstrip().startswith('#'):
            continue
        if CALL.search(line) and QUOTEPATH not in line:
            reds.append('%s:%d 裸 git diff/ls-files（病10）： %s' % (rel, i, line.strip()[:100]))
    return reds


def gate_hook_probe(root):
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
        body = open(p, encoding='utf-8', errors='ignore').read()
        missing = [k for k in ('--probe', 'hit', 'via') if k not in body]
        if missing:
            reds.append('hooks/%s 缺观测要件 %s（病13：无法判定生效与否）' % (name, '/'.join(missing)))
    return reds


GATES = {'quotepath': gate_quotepath, 'hook-probe': gate_hook_probe}


def main():
    args = sys.argv[1:]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gates = list(GATES)
    while args:
        a = args.pop(0)
        if a == '--root':
            root = args.pop(0)
        elif a == '--gate':
            gates = [args.pop(0)]
        else:
            print('未知参数 %s（支持 --root DIR / --gate quotepath|hook-probe）' % a)
            return 2
    all_reds = []
    for g in gates:
        if g not in GATES:
            print('✗ 未知 gate：%s' % g)
            return 2
        reds = GATES[g](root)
        for r in reds:
            print('  ✗ [%s] %s' % (g, r))
        if not reds:
            print('  ✓ [%s] 全绿' % g)
        all_reds += reds
    print('gate_scan：%d gate / %d 红' % (len(gates), len(all_reds)))
    return 2 if all_reds else 0


if __name__ == '__main__':
    sys.exit(main())
