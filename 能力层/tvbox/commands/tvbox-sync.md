---
description: 一键更新 TVBox 配置：拉取仓库、并发测活线路、重新集成主配置
argument-hint: "[仓库名 或 'all']"
allowed-tools: Bash(python3:*), Bash(git:*), Read, Write
model: inherit
---

按 `tvbox-pipeline` 技能流程，用 $ARGUMENTS 指定的仓库（缺省 all）执行：
拉仓库 → 抽源 → 并发测活 → 集成主配置 → 汇报结果。

示例：
/tvbox-sync all
/tvbox-sync repoA
