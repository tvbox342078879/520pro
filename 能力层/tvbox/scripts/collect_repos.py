#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_repos.py —— 拉取你搜集的各配置仓库（壳+配置源），抽取 sites/lives 源地址。
把仓库登记在下方 REPOS 字典里即可；克隆失败不影响其他仓库。
"""
import os
import json
import glob
import subprocess

# ===== 在这里登记你搜集的配置仓库 =====
REPOS = {
    "repoA": "https://github.com/xxx/tvbox-repoA",
    "repoB": "https://github.com/yyy/tvbox-repoB",
    # "repoC": "https://github.com/zzz/tvbox-repoC",
}
# =====================================
BASE = os.path.expanduser("~/tvbox_repos")


CLONE_TIMEOUT = 45  # 秒；超时即放弃该仓库，绝不无限等待


def pull(name: str, url: str) -> str:
    p = os.path.join(BASE, name)
    try:
        if os.path.exists(p):
            subprocess.run(["git", "-C", p, "pull", "--ff-only"],
                           check=False, capture_output=True, timeout=CLONE_TIMEOUT)
        else:
            os.makedirs(BASE, exist_ok=True)
            subprocess.run(["git", "clone", "--depth", "1", url, p],
                           check=False, capture_output=True, timeout=CLONE_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"[跳过] {name}：clone 超时（>{CLONE_TIMEOUT}s），网络或仓库不可达")
    except Exception as e:
        print(f"[跳过] {name}：{e}")
    return p


def main():
    urls = []
    for name, url in REPOS.items():
        # 占位地址直接跳过，避免无意义联网等待
        if any(t in url for t in ("/xxx/", "/yyy/", "/zzz/")):
            print(f"[跳过] {name}：占位地址未改（{url}），请编辑 REPOS 填真实仓库")
            continue
        p = pull(name, url)
        for f in glob.glob(os.path.join(p, "**", "*.json"), recursive=True):
            try:
                cfg = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            for s in cfg.get("sites", []):
                u = s.get("api") or s.get("url")
                if u:
                    urls.append(u)
            for l in cfg.get("lives", []):
                if l.get("url"):
                    urls.append(l["url"])

    urls = sorted(set(urls))
    with open("sources.json", "w", encoding="utf-8") as f:
        json.dump(urls, f, ensure_ascii=False, indent=2)
    print(f"抽取源 {len(urls)}  → sources.json")


if __name__ == "__main__":
    main()
