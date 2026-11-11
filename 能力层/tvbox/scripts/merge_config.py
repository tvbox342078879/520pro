#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_config.py —— 只保留存活源，幂等集成进主配置 master_config.json。
不改动主配置字段结构，只过滤失效源；输出 master_config.new.json。
"""
import json

MASTER = "master_config.json"
LIVE = "live_result.json"
OUT = "master_config.new.json"


def main():
    with open(MASTER, encoding="utf-8") as f:
        master = json.load(f)
    with open(LIVE, encoding="utf-8") as f:
        live = json.load(f)

    alive = set(live.get("alive", []))
    master["sites"] = [
        s for s in master.get("sites", [])
        if (s.get("api") in alive) or (s.get("url") in alive)
    ]
    master["lives"] = [
        l for l in master.get("lives", [])
        if l.get("url") in alive
    ]

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)
    print(f"已生成 {OUT}（仅含存活源："
          f"sites {len(master['sites'])} / lives {len(master['lives'])}）")


if __name__ == "__main__":
    main()
