---
name: tvbox-config-sync
description: >-
  更新/测活/集成 TVBox（电视盒子）配置：搜集配置仓库、整理直播源(lives)与站点源(sites)、
  并发测活线路、把存活源重新集成进主配置。触发词：TVBox、电视盒子、测活、直播源、
  站点源、配置源、线路、订阅源、更新tvbox配置。用户提到这些时自动调用本技能，
  用脚本执行，不要手动逐条 curl、不要手动改 JSON。
---

# TVBox 配置同步技能（520pro 用户级版）

## 何时使用
用户提到 TVBox / 电视盒子 / 测活线路 / 直播源 / 站点源 / 配置源 / 更新订阅 时，
**自动**按下列流程执行。目标：让"搜集仓库→测活→重新集成"全自动，模型只调脚本。

## 脚本位置（自动适配两种安装）
本技能可能装在 **用户级** `~/.codebuddy/skills/`（推荐，可路由），也可能装在**项目级** `.codebuddy/skills/`。
执行前先定位脚本目录（按顺序取第一个存在的）：

```bash
if [ -d "$HOME/.codebuddy/scripts" ]; then SCRIPT_DIR="$HOME/.codebuddy/scripts"; else SCRIPT_DIR=".codebuddy/scripts"; fi
```

## 执行流程（严格顺序）
1. `python3 "$SCRIPT_DIR/collect_repos.py"`  → 拉仓库、抽源，得 `sources.json`
2. `python3 "$SCRIPT_DIR/check_live.py" sources.json` → 并发测活，得 `live_result.json`
3. `python3 "$SCRIPT_DIR/merge_config.py"` → 过滤失效源，得 `master_config.new.json`
4. 汇报：`存活 N / 失效 M → master_config.new.json`，**输出精简，不堆过程**。

> 若项目根没有 `master_config.json`，先：
> `cp "$HOME/.codebuddy/tvbox/master_config.example.json" master_config.json`（或项目内 `.codebuddy/tvbox/master_config.example.json`），再让用户填源。

## 约束
- 测活走并发脚本，**禁止手动一条条 curl**。
- 主配置字段结构保持不变，只过滤失效源（幂等）。
- 结果文件落盘复用，下次可跳过已测活部分。
- 指定仓库名或 "all" 时，仅处理对应仓库（改 `collect_repos.py` 的 `REPOS` 或传参）。
- **重活可脱离子会话**：本流程步骤多，可派 `tvbox-agent` 子代理执行，避免主会话被日志刷屏。

## 无法判定时
脚本报错 / 超时 / 无输出 → 记「无法判定」，报清楚卡在哪一步，不臆造"成功"。
