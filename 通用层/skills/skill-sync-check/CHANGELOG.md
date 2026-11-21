## v1.0.0 — 2026-11-21
- 云取借鉴第 4 条"查更新"（`PluginUpdateChecker`）的 520 对应物：技能版本清单对比，回答"本地技能 vs 远端差多少"，是"达标晋升能不能同步"的前置能力。
- 薄壳 `scripts/skill_sync_check.py` 纯标准库实现：`parse_version()` 点分数字版本归一化 + `compare_versions()` 逐段比较（behind/ahead/same/unknown）+ `build_update_report()` 双契约四态报告 + CLI（`--local/--remote/--json-out/--selftest`）。
- 判据 `verify/tests/test_skill_sync_check.py` 34/0：结构层 + 版本比较层（补零等价/跨段/非法 fail-closed）+ 报告层（四态+missing+summary 计数）+ 元变异有牙（删补零→1.0 vs 1.0.0 转非 same、unknown 降级 same→非法版本转红）+ 端到端（真 contracts 文件自比全 same 20 技能 + 造差异报告落盘）。
- 触发样本 T8/N6/B3 在册；C9 前置 / C10 词桥 / C11 工具白名单对齐。
- 证据等级：dex 类名实证（`MarketClient`/`PluginUpdateChecker`/`sourceMirror` 机制存在，方法体未 dump），原始诉求见 transcript L2565 第 4 条清单原文（原 57 条 `session.jsonl:65888` 已删不可恢复）。
