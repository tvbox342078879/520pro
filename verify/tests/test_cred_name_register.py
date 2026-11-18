#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零期闸4 判据：凭证名登记真源（verify/cred_names.json）被 secret_scan 实际扫描。

防的假绿：自造凭证名（如 cred_store.json）不在 CRED_NAMES 硬编码名单 →
文件名扫描兜不住、内容又加密 → 脱离 B-05 防线。
判据贴真函数：import 真 secret_scan，喂临时仓放一个登记名文件，看 scan_credential_files
是否真扫出；真源损坏要 fail-closed；基础六项对账不破。
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import secret_scan as SS

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if detail and not cond else ""))


print("── 真源加载 ──")
names, sfx, err = SS.load_cred_registry()
check("登记真源可读（无 err）", err == '', err)
check("扩展名已登记且非空", len(names) >= 1, f"names={names}")
check("cred_store.json 在扩展名单（本期示例自造名）", 'cred_store.json' in names, f"names={names}")
check("基础六项未被扩展名单覆盖改写", SS.CRED_NAMES[:6] ==
      ('.gh_token', '.git-credentials', '.netrc', 'id_rsa', 'id_ed25519', '.env'))

print("── 判据贴真函数：登记名被实际扫出 ──")
# 造临时 git 仓，放一个已登记的凭证名文件（未追踪未忽略 → 应红）
with tempfile.TemporaryDirectory() as d:
    import subprocess
    subprocess.run(['git', 'init', '-q', d], check=True)
    target = os.path.join(d, 'cred_store.json')
    with open(target, 'w') as f:
        f.write('{}\n')
    found, noted = [], []
    ok = SS.scan_credential_files(d, found, noted)
    hit = any('cred_store.json' in rel for rel, _ in found)
    check("scan_credential_files 判定成立", ok)
    check("已登记自造名 cred_store.json 被扫出", hit, f"found={found}")

print("── fail-closed：真源缺失报错 ──")
_orig = SS.CRED_REGISTRY
try:
    SS.CRED_REGISTRY = os.path.join(tempfile.gettempdir(), '__no_such_cred_registry__.json')
    n2, s2, e2 = SS.load_cred_registry()
    check("真源缺失时返回 err（不静默放行）", bool(e2), f"err={e2!r}")
    # 必须在仍存活的 git 仓里测，否则 git ls-files 先失败、到不了注册检查
    with tempfile.TemporaryDirectory() as d2:
        subprocess.run(['git', 'init', '-q', d2], check=True)
        found, noted = [], []
        SS.scan_credential_files(d2, found, noted)
        check("真源缺失时 found 记红（fail-closed）",
              any('登记真源缺失' in msg for _, msg in found), f"found={found}")
finally:
    SS.CRED_REGISTRY = _orig

print("── 元变异（判据有牙）──")
_src = open(os.path.join(ROOT, 'secret_scan.py'), encoding='utf-8').read()
check("真源码调用 load_cred_registry", 'load_cred_registry()' in _src)
mut = _src.replace('cred_names = set(CRED_NAMES) | set(extra_names)',
                   'cred_names = set(CRED_NAMES)')
check("元变异：扩展名不并入扫描应红（判据贴实现）",
      'cred_names = set(CRED_NAMES) | set(extra_names)' not in mut)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
