---
name: skill-sync-check
description: "当用户说「技能有没有新版」「本地技能和远端差多少」「查一下哪些技能要更新」「达标晋升能不能同步」时使用本技能。技能版本清单对比（云取 4+25 借鉴·纯 Python 标准库）。能力：①本地 vs 远端契约登记（skill_contracts.json）逐技能版本对比；②点分数字版本逐段比较（补零等价）；③四态报告——behind（本地落后该更新）/ahead（本地超前）/same（一致）/unknown（版本非法无法判定）/missing（一侧独有）。只读、不触网——远端清单由调用方喂文件（可从 git/raw 取后传入）。正门：scripts/skill_sync_check.py。不要用于：技能包完整性校验(归 market-verify)、凭证加密(归 cred-vault)、下载探测(归 download-probe)。触发词：技能版本对比 / 查更新 / 哪些技能要更新 / 本地远端版本差 / 达标晋升同步 / 技能落后。"
version: "1.0.0"
allowed-tools: Read,Grep,Glob,Bash
---

> **语言铁律**：全程简体中文，切模型/压缩/新会话不回退。

# skill-sync-check（技能版本清单对比·查更新）

> **定位**：云取借鉴第 4 条"查更新"（`PluginUpdateChecker`）的 520 对应物。它回答"本地技能版本 vs 远端差多少"，是"达标晋升能不能同步"的前置能力——先能查出谁落后，才谈得上同步。

## 1. 何时用
- 查本地技能是否落后远端、哪些需要更新。
- 对比两个契约登记（skill_contracts.json）的技能版本差异。
- 判断某技能本地超前（远端旧/本地未推）还是格式非法无法判定。

## 2. 正门与自省
**先读本技能 + `scripts/skill_sync_check.py --help`，不许自己拼版本比较逻辑。**
- 正门：`scripts/skill_sync_check.py --local <本地契约.json> --remote <远端契约.json>`；`--selftest` 自检。
- 判据：`verify/tests/test_skill_sync_check.py`（喂真函数看真输出 + 元变异有牙）。
- 远端清单获取：调用方先用 `git show origin/main:verify/skill_contracts.json > /tmp/remote_contracts.json`（或 raw_sync）取好，再传入；本工具不取网。

## 3. 能力边界
- **只读、不触网、不写任何文件**（`--json-out` 仅导出报告）。不自动更新、不装技能。
- 版本对象 = 点分数字（`1.1.0`/`1.28.9`）；带 v 前缀/字母的市场 schema 版本（`v1`）属 market-verify 的另一对象，本工具判 `unknown`，不混用（M3）。
- 四态 + missing 分开；版本串非法/字段缺 → unknown（fail-closed）；一侧独有 → missing（无法判定谁新）。

## 4. 交付
报告 JSON：`summary`（total + 各态计数）、`items`（`[{skill, local, remote, status}, ...]`），status ∈ behind/ahead/same/unknown/missing。

## 5. 证据等级（B-02 三态诚实）
原始诉求取自 transcript L2565 第 4 条清单原文（dex 类名 `MarketClient`/`PluginUpdateChecker`/`sourceMirror` 实证机制存在，方法体未 dump）。本技能只实现"查更新"一环——**不触网拉列表、不支持 sourceMirror 镜像源、不联动达标晋升自动同步**（这些是下一步，触网判据难做真阳性，不冒称已做）。
