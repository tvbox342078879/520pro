#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_live.py —— 批量测活 TVBox 线路（直播源 lives / 站点源 sites）。
特性：并发（线程池）、超时可控、结果落盘复用，不依赖第三方库。
模型只负责调用本脚本，不要手动一条条 curl。
"""
import sys
import json
import ssl
import urllib.request
import urllib.error
import concurrent.futures as cf

# 关闭证书校验（很多源是自签/过期证书），按需保留
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

TIMEOUT = 8
WORKERS = 20


def probe(url: str):
    try:
        req = urllib.request.Request(
            url, method="GET",
            headers={"User-Agent": "Mozilla/5.0 (TVBox)"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            _ = r.read(4096)  # 只读头部，足够判断存活
            return url, r.status
    except Exception:
        return url, 0


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "sources.json"
    with open(src, encoding="utf-8") as f:
        urls = json.load(f)
    if isinstance(urls, dict):
        urls = urls.get("alive") or urls.get("urls") or []

    alive, dead = [], []
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for url, st in ex.map(probe, urls):
            (alive if 0 < st < 400 else dead).append(url)

    with open("live_result.json", "w", encoding="utf-8") as f:
        json.dump({"alive": alive, "dead": dead}, f,
                  ensure_ascii=False, indent=2)
    print(f"存活 {len(alive)}  失效 {len(dead)}  → live_result.json")


if __name__ == "__main__":
    main()
