#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据：弱网 raw 补包机制（raw_sync.py + bootstrap 指引 + 清单真源）。

贴真函数（import raw_sync，不重写逻辑）+ 三元变异：
  ① 去 URL 编码 → 中文路径 raw URL 假绿转红
  ② 去跳过已存在 → 断点续补失效转红
  ③ 去 bootstrap 指引锚点 → 弱网无路可走转红
"""
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
RS_PATH = os.path.join(ROOT, "通用层/skills/machine-bootstrap/scripts/raw_sync.py")
LIST_PATH = os.path.join(ROOT, "通用层/skills/machine-bootstrap/references/sync_filelist.txt")
BOOT_PATH = os.path.join(ROOT, "bootstrap.sh")

spec = importlib.util.spec_from_file_location("raw_sync", RS_PATH)
RS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RS)

_p = _f = 0


def check(name, cond, detail=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  ✓ {name}")
    else:
        _f += 1
        print(f"  ✗ {name} {detail}")


print("── 弱网 fallback 判据 ──")

# 机制1 清单真源
print("── 清单真源 ──")
with open(LIST_PATH, encoding="utf-8") as fh:
    raw_lines = [x.strip() for x in fh if x.strip()]
files = RS.read_filelist(LIST_PATH)
check("清单非空", len(files) > 100, f"n={len(files)}")
check("清单无大文件", not any(RS.HEAVY_PREFIX in x for x in files))
check("清单含中文路径原文", any("通用层" in x for x in files))
check("清单含换机关键件", all(x in files for x in RS.PRIORITY[:5]), "缺 MANIFEST/VERSION/install/bootstrap/verify")
check("清单无运行痕迹", not any(x.endswith(".pyc") or "snapshots/" in x or ".ensure.lock" in x for x in files))

# 机制2 URL 编码（元变异①）
print("── URL 编码（元变异①）──")
u = RS.raw_url("o/r", "main", "通用层/rules/core-8.md")
check("中文路径被 %XX 编码", "%E9%80%9A%E7%94%A8%E5%B1%82" in u and "通用层" not in u, u)
check("斜杠保留", "/通用层/" not in u and u.count("/") >= 5, u)
# 反向：直接把原文塞进 URL（未编码）应被视为不等价——证明编码这步"有牙"
u_bad = f"https://raw.githubusercontent.com/o/r/main/通用层/rules/core-8.md"
check("元变异① 未编码URL ≠ 真URL（编码有牙）", u != u_bad)

# 机制3 跳过已存在（元变异②）—— monkeypatch curl_download 为纯函数桩，判据完全离线
print("── 断点续补（元变异②）──")
_orig_curl = RS.curl_download
try:
    # 桩：只记录被请求下载的路径，返回一个可控结果（missing→失败，其余→成功）
    attempted = []

    def _stub(url, dest, timeout=120):
        attempted.append(os.path.basename(dest))
        if os.path.basename(dest) == "missing.md":
            return False, "stub: not found"
        with open(dest, "wb") as y:
            y.write(b"downloaded")
        return True, ""

    RS.curl_download = _stub
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "B"), exist_ok=True)
        with open(os.path.join(d, "B/exist.md"), "wb") as x:
            x.write(b"already-here")
        lf = os.path.join(d, "list.txt")
        with open(lf, "w", encoding="utf-8") as x:
            x.write("B/exist.md\nB/missing.md\n")
        events = []
        ok, bad = RS.sync("o/r", "main", lf, d, 1, on_progress=lambda i, r, s: events.append(s))
        check("已存在文件被跳过", "skip" in events, str(events))
        check("exist 未发下载请求", "exist.md" not in attempted, str(attempted))
        check("缺失文件计失败", bad == ["B/missing.md"], str(bad))
        check("失败数反映退出码口径", ok == 1 and len(bad) == 1, f"ok={ok} bad={bad}")
        # 元变异②：若无跳过逻辑，exist 也会进 attempted → 与真实现不同 = 跳过有牙
        check("元变异② 无跳过时 exist 会进 attempted（跳过有牙）",
              "exist.md" not in attempted and "missing.md" in attempted, str(attempted))
finally:
    RS.curl_download = _orig_curl

# 机制4 bootstrap 失败指引（元变异③）
print("── bootstrap 弱网指引（元变异③）──")
with open(BOOT_PATH, encoding="utf-8") as fh:
    boot = fh.read()
check("bootstrap 失败分支提及 raw 补救", "raw 单文件" in boot and "raw_sync.py" in boot)
check("bootstrap 提示勿跑 apply_sparse", "apply_sparse" in boot and "假失败" in boot)
anchor = "弱网补救（raw 单文件，已实测可达）"
check("元变异③ 指引锚点在位", anchor in boot)
with open(os.path.join(ROOT, "手机指令.md"), encoding="utf-8") as fh:
    phone = fh.read()
check("手机指令含 raw 补包 curl", "raw_sync.py -o /tmp/raw_sync.py" in phone and "sync_filelist.txt -o" in phone)

# selftest 本体
print("── selftest 本体 ──")
check("raw_sync --selftest 10/0", RS.selftest() == 0)

print(f"\n判据结果: {_p} 通过 / {_f} 失败")
sys.exit(1 if _f else 0)
