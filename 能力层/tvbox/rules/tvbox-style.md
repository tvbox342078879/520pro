---
description: TVBox 能力层常驻规则（项目级 alwaysApply）。约束测活/集成的执行纪律，防止模型手搓 curl 或篡改主配置结构。
alwaysApply: true
enabled: true
---

# TVBox 工作纪律（tvbox-style · 常驻）

> 本文件部署到目标项目 `.codebuddy/rules/tvbox-style.md`，字段 `alwaysApply:true` 常驻（原生加载）。
> 与 `.codebuddy/CODEBUDDY.md` 薄壳**叠加**：薄壳保证"触发即路由"，本文件保证"执行守纪律"。

## 1. 执行纪律（硬约束）

1. **只走脚本，不手搓**：测活一律用 `.codebuddy/scripts/check_live.py`（并发线程池），**禁止手动逐条 curl**。
2. **只过滤、不改结构**：`merge_config.py` 只剔除失效源，主配置字段结构保持不变，幂等可重跑。
3. **结果落盘复用**：`sources.json` / `live_result.json` / `master_config.new.json` 落盘，下次可跳过已测活部分。
4. **不编造源**：仓库地址、主配置路径从**项目内实际文件**读取，不凭记忆编 `xxx/yyy` 之外的地址。

## 2. 触发即执行（与薄壳同口径）

提到 `TVBox / 测活 / 直播源 / 站点源 / 配置源 / 线路 / 订阅源` 时，按
`collect_repos.py → check_live.py → merge_config.py` 顺序执行，汇报"存活 N / 失效 M"。

## 3. 不可逆动作闸（无 hook 的补偿）

本生态**不押 hook**，删除/覆盖类动作在脚本内做保护：覆盖主配置前先确认 `master_config.json` 可重建（或已 git 跟踪），
不直接 `rm` 用户源文件。需要"删除前确认"的场景，先打印将删除清单再等用户确认。
