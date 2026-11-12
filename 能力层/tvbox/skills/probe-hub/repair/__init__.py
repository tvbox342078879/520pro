#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe-hub/repair —— 修源模块（S222·防腐层自包含设计）

设计决策（用户 2026-11-03 定案）：
  · 放进探源司板块（probe-hub）而非独立 skill——与 livecheck/死因分型强耦合，调用链最短；
  · **自包含**：本包不 import 上级 probe.py / livecheck 以外的模块（唯一例外：
    经 subprocess 或 sys.path 调 livecheck 的 death_cause——分型单一事实源，M-R38）；
  · 未来要独立出去 = 一条 `git mv repair/ <新skill>/`，因为对外契约全在 schemas/。

文件分工（按一次修复的时序）：
  recon.py     侦察站点结构 → 只在 rewrite 档用（S226）
  llm.py       修复通道（api 全自动 / host 两段式，无 Key 也能用）
  ai_ast.py    能力层闸门：只拦补丁**新增**的危险模块/调用（S224 基线豁免）
  engine.py    编排：checkup → route → drafts/apply 或 repair/rewrite
  schemas/     对外契约（checkup_report / repair_result）
  prompts/     策略提示词（_common 注入防御 + patch / rewrite）

三条贯穿全包的红线：
  · 没验证过就不许说 repaired（M-R136）—— 一律 verify_failed 或 not_applicable
  · 判不了就是「无法判定」，不折叠成 ok（M-R57/M-R60）
  · 侦察/证据不完整时**不生成**，宁可 aborted（编出来的源比坏源更难查）
"""
