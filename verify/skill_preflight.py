#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方案落点机器核验闸（零期闸1，2026-11-19）。

背景（病15 第23次，2026-11-19 实犯）：写「云取57条落地方案」时凭记忆写了两个
不存在的落点——`verify/secret_scan.py`（真身在仓根）与
`learn-hub/artifacts.json` 的 TERRITORY 字段（真身在 SKILL.md §4.3）。
靠"下次注意"没用（同一型已复发 23 次），故固化成机器判据：
方案/契约常引用的关键落点是**一张可机检的表**，路径或锚点串漂移即红。

真源：本文件 ANCHORS 表（M1）。加落点只加一行，不改检查逻辑。
用法：
  python3 verify/skill_preflight.py --repo /workspace/520pro     # 核验
  python3 verify/skill_preflight.py --selftest                    # 正反自证
"""
import argparse
import os
import sys

# 关键落点登记：(逻辑名, 相对仓库路径, 必须出现的锚点串)
# 每条都对应一次"凭记忆写错"或"做一半会红"的真实教训。
ANCHORS = [
    ("密钥扫描真身在仓根(不在verify/)", "secret_scan.py", "CRED_NAMES"),
    ("判据自动发现在位(闸2后)", "verify.sh", 'for tf in "$TARGET"/verify/tests/test_*.py; do'),
    ("扩展回归判据节", "verify.sh", "扩展回归（v0.8.18"),
    ("契约表头项数(已纠六项→十项)", "verify/skill_contract_check.py", "十项检查：C1"),
    ("契约C4版本检查器", "verify/skill_contract_check.py", "check_version"),
    ("责任田真在SKILL.md §4.3(不在artifacts.json)", "通用层/skills/learn-hub/SKILL.md", "4.3"),
    ("凭证名单双真源对账", "hooks/guard_cmd.py", "CRED_BASENAMES"),
    ("precommit④真跑verify", "hooks/pre-commit", "repo-only"),
    ("prepush仓库闸", "hooks/pre-push", "仓库自检"),
]

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if detail and not cond else ""))


def verify_repo(repo):
    print("── 方案落点逐条核验 ──")
    for label, rel, needle in ANCHORS:
        p = os.path.join(repo, rel)
        exists = os.path.isfile(p)
        if not exists:
            check(label, False, f"文件不存在：{rel}")
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        check(label, needle in txt, f"{rel} 未含锚点串「{needle}」")
    return not FAIL


def selftest():
    """正反自证：真锚点全过；把路径/锚点改坏必须红。"""
    import tempfile
    print("── 正向：临时仓放齐锚点应全绿 ──")
    with tempfile.TemporaryDirectory() as d:
        for _, rel, needle in ANCHORS:
            fp = os.path.join(d, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(f"// seed\n{needle}\n")
        PASS.clear(); FAIL.clear()
        ok = verify_repo(d)
        check("selftest 正向全绿", ok and not FAIL and len(PASS) == len(ANCHORS))

    print("── 反向：锚点串被改掉必须红 ──")
    with tempfile.TemporaryDirectory() as d:
        # 只放第一个锚点，但锚点串故意写错 → 必须 FAIL
        label, rel, needle = ANCHORS[0]
        fp = os.path.join(d, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write("// 故意不含锚点串\nWRONG_NEEDLE\n")
        PASS.clear(); FAIL.clear()
        ok = verify_repo(d)
        check("selftest 反向(锚点漂移)转红", (not ok) and len(FAIL) == len(ANCHORS))

    # 反向2：文件缺失
    with tempfile.TemporaryDirectory() as d:
        PASS.clear(); FAIL.clear()
        ok = verify_repo(d)  # 空仓 → 全部文件缺失
        check("selftest 反向(文件全缺)转红", (not ok) and len(FAIL) == len(ANCHORS))

    return not FAIL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        ok = selftest()
    else:
        ok = verify_repo(a.repo)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
