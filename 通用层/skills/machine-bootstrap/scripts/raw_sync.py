#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""raw_sync.py —— 弱网 raw 单文件补包器（换机司 fallback）。

场景：弱网下 git smart protocol（GnuTLS -110 / promisor blob 拉不到）clone 失败，
但 curl（OpenSSL 后端）对 raw.githubusercontent.com 的单文件下载可达。
本脚本按「逐文件清单」用 curl 逐个下载小文件，绕过被掐断的 git 通道。

设计（对齐 520 契约）：
- 单一真源：文件清单来自 git -c core.quotepath=false ls-files（排除 runtime_assets 大文件），
  随技能分发为 references/sync_filelist.txt；改真源须同步清单（判据守护）。
- 二进制大文件（capability_63/runtime_assets，约 200MB）不进清单——换机断言不查它们，
  弱网只搬文本真源（全仓约 1.2MB）。
- 跳过已存在非空文件 → 断点续补；中文路径 urllib.parse.quote 编码 → raw URL 可达。
- 每个文件失败重试 N 次；退出码 = 失败文件数（0 全成功）；零明文凭证（不读 token 值）。

用法：
  python3 raw_sync.py --repo <owner/repo> --list <filelist> --dest <dir> [--branch main] [--retries 5]
  python3 raw_sync.py --selftest
"""
import argparse
import os
import subprocess
import sys
import tempfile
import urllib.parse

RAW_BASE = "https://raw.githubusercontent.com"
# 换机断言必需、且用户弱网补包时最该先拿到的关键件（顺序=优先级，失败即早暴露）
PRIORITY = [
    "MANIFEST.json", "VERSION", "install.sh", "bootstrap.sh", "verify.sh",
    "secret_scan.py", "通用层/rules/core-8.md",
]
# 大文件前缀：整目录排除，不进弱网清单（与 filelist 生成口径一致）
HEAVY_PREFIX = "capability_63/runtime_assets"


def raw_url(repo, branch, rel):
    """拼 raw 下载 URL；中文/特殊字符按 UTF-8 编码，/ 保留为路径分隔。"""
    enc = urllib.parse.quote(rel, safe="/")
    return f"{RAW_BASE}/{repo}/{branch}/{enc}"


def read_filelist(path):
    """读逐文件清单，返回规范化相对路径列表（去空行/注释/去重/保序）。"""
    out, seen = [], set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("/"):
                continue
            if HEAVY_PREFIX in s or s in seen:
                continue
            seen.add(s)
            out.append(s)
    return out


def order_files(files):
    """关键件前置，其余按清单序；去重。"""
    head = [p for p in PRIORITY if p in files]
    rest = [p for p in files if p not in PRIORITY]
    return head + rest


def curl_download(url, dest, timeout=120):
    """单文件下载到 dest.tmp，成功后原子改名；返回 (ok, err)。"""
    tmp = dest + ".tmp"
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
    except OSError:
        pass
    try:
        r = subprocess.run(
            ["curl", "-fsSL", "--connect-timeout", "15", "--max-time", str(timeout),
             "--retry", "0", url, "-o", tmp],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout + 10,
        )
        if r.returncode != 0:
            return False, r.stderr.decode("utf-8", "replace").strip()[:160]
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            return False, "empty file"
        os.replace(tmp, dest)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:160]
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def sync(repo, branch, filelist, dest, retries, on_progress=None):
    """逐文件补包，返回 (ok_count, failed_paths)。"""
    files = order_files(read_filelist(filelist))
    ok, failed = 0, []
    for i, rel in enumerate(files, 1):
        target = os.path.join(dest, rel)
        if os.path.exists(target) and os.path.getsize(target) > 0:
            ok += 1
            if on_progress:
                on_progress(i, rel, "skip")
            continue
        url = raw_url(repo, branch, rel)
        good, err = False, ""
        for attempt in range(1, retries + 1):
            good, err = curl_download(url, target)
            if good:
                break
        if good:
            ok += 1
            if on_progress:
                on_progress(i, rel, "ok")
        else:
            failed.append(rel)
            if on_progress:
                on_progress(i, rel, f"FAIL({err})")
    return ok, failed


def selftest():
    """正反自检：URL 编码 / 清单解析 / 跳过已存在 / 大文件排除 / 排序 / 失败计数。"""
    passed = failed = 0

    def chk(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name} {detail}")

    print("── raw_sync selftest ──")
    # 1 URL 编码：中文路径 → %XX，/ 保留
    u = raw_url("tvbox342078879/520pro", "main", "通用层/skills/learn-hub/SKILL.md")
    chk("中文路径 UTF-8 编码", "%E9%80%9A%E7%94%A8%E5%B1%82" in u and "/通用层/" not in u, u)
    chk("URL 前缀正确", u.startswith("https://raw.githubusercontent.com/tvbox342078879/520pro/main/"), u)
    chk("斜杠保留为分隔", u.count("/") >= 6, u)

    # 2 清单解析：去空/注释/大文件/重复
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write("# 注释\n\nA.md\nB/中文.md\nA.md\n")
        tf.write("通用层/skills/foundry-core/assets/capability_63/runtime_assets/frida/bin\n")
        tf.write("/absolute/path\n")
        lst = tf.name
    fs = read_filelist(lst)
    chk("清单去重+去注释空行", fs == ["A.md", "B/中文.md"], str(fs))
    chk("大文件被排除", not any("runtime_assets" in x for x in fs))

    # 3 排序：PRIORITY 前置
    ordered = order_files(["B/中文.md", "MANIFEST.json", "VERSION", "A.md"])
    chk("关键件前置", ordered[:2] == ["MANIFEST.json", "VERSION"], str(ordered))
    chk("其余保序", ordered[2:] == ["B/中文.md", "A.md"], str(ordered))

    # 4 跳过已存在：造一个 dest 有 A.md，A.md 不该再下载
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "B"), exist_ok=True)
        with open(os.path.join(d, "B/中文.md"), "w", encoding="utf-8") as x:
            x.write("already")
        # 用 --repo 指向一个必然失败的地址，若跳过逻辑生效则只 B/中文.md 被跳过，其余失败
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf2:
            tf2.write("B/中文.md\nNEVER.md\n")
            lst2 = tf2.name
        events = []
        ok, bad = sync("no/such", "main", lst2, d, 1, on_progress=lambda i, r, s: events.append((r, s)))
        chk("已存在文件被跳过", any(r == "B/中文.md" and s == "skip" for r, s in events), str(events))
        chk("缺失文件计失败", bad == ["NEVER.md"], str(bad))
        chk("失败数反映在结果", ok == 1 and len(bad) == 1, f"ok={ok} bad={bad}")
        os.unlink(lst2)
    os.unlink(lst)

    print(f"selftest: {passed} 通过 / {failed} 失败")
    return 0 if failed == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="弱网 raw 单文件补包器")
    ap.add_argument("--repo", default="tvbox342078879/520pro", help="owner/repo")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--list", dest="filelist", help="逐文件清单路径")
    ap.add_argument("--dest", default=".", help="目标目录")
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.filelist or not os.path.exists(a.filelist):
        print("错误: 缺 --list 清单文件", file=sys.stderr)
        return 2
    ok, bad = sync(a.repo, a.branch, a.filelist, a.dest, a.retries)
    print(f"补包完成: OK={ok} FAIL={len(bad)}")
    for b in bad[:20]:
        print(f"  FAIL {b}", file=sys.stderr)
    return len(bad)


if __name__ == "__main__":
    sys.exit(main())
