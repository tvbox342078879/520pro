---
description: 编辑 master_config / 源清单类文件时注入的集成契约。仅命中 paths 才加载，不常驻。
alwaysApply: false
paths:
  - "**/master_config*.json"
  - "**/sources.json"
enabled: true
---

# 配置集成契约（tvbox.paths · 条件触发示例）

> ⚠️ **诚实标注**：本生态实测——**条件规则（`paths` 注入）在这套宿主上并不可靠**，可能完全不注入（368817 报告 `L2.cond`：编辑 docs 时"仅 CODEBUDDY.md 被注入"）。
> 因此本文件只是**示例与补充**，真正的兜底在 `.codebuddy/CODEBUDDY.md` 薄壳内的第二节。别把关键约束只放这里。

## 命中以下文件时执行

- `master_config.json` / `master_config.new.json`
- `sources.json` / `live_result.json`

## 契约

1. **结构不变**：`sites` / `lives` / `parses` / `rules` / `spider` 字段结构保持，只增删条目内容。
2. **幂等**：重复跑 `merge_config.py` 结果一致，不产生重复源。
3. **可回溯**：覆盖前保留上一版（`master_config.bak.json`），或在 git 中提交后再覆盖。
4. **口径一致**：源的 key 唯一、name 人读、api/url 二选一有值。
