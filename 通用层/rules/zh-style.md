---
description: 项目级规则：项目专属契约 + §8 本地轻量纪律（防手机卡顿）。跨项目通用铁律（B-01…B-16）由用户级 base/rules/core-8.md 强制，本文件不重复。
alwaysApply: true
enabled: true
---

# 中文风格与输出纪律（zh-style）

> 本规则位于官方自动加载路径 `.codebuddy/rules/`，手机/云端任务必读。
> frontmatter 仅用官方 Memory 文档「规则控制字段」三项（`enabled` / `alwaysApply` / `paths`）；`description` 为人读元数据。官方字段表**无 `priority`**，本生态不设、不依赖（官方口径订正见 SOP 20.12.2）。
> 依据 SOP 第 16–20 章。与 `.codebuddy/CODEBUDDY.md` 薄壳**三通道叠加**，互为兜底。

## 0. 规则分层声明（三维度 · SOP 20.9）

> 通用铁律（B-01…B-16）的**唯一真源**是用户级 `base/rules/core-8.md`（装到 `~/.codebuddy/rules/` 后跨项目生效）。本文件是**项目级**规则，§1–7 不重复铁律全文、只留指针，换项目无需复制（去重复 + 省 context，呼应 20.7/20.8）。

| 维度 | 用户级基座 `base/rules/core-8.md` | 本文件 `.codebuddy/rules/zh-style.md` | 条件规则 `*.paths.md` | 台账 `docs/*.md` |
|---|---|---|---|---|
| 作用域 | 跨所有项目 | 仅本生态 | 仅本生态 | 不加载 |
| 触发 | `alwaysApply:true` 常驻 | `alwaysApply:true` 常驻 | `alwaysApply:false` + `paths` 命中才注入 | 不进 context |
| 内容 | 16 条通用铁律（B-01…B-16） | 项目专属契约 + §8 工程纪律 | 情境契约（如文档同步） | schema/去重/降级/owner/探针 |
| 强制力 | 软声明（三通道叠加） | 软声明 | 软声明 | — |

> 强制力梯度：`软声明 → config → permissions.deny → hook`。本生态**不押 hook**（手机不跑钩子，第 19 章），不可逆动作改在技能内设"删除前确认"闸。已弃用 tvbox-eco 的 `hot/warm/cold` 冷热分层，改由上表三维度决定加载。

## 1. 语言铁律（无条件全程中文）

1. → 见用户级 `core-8.md` `B-01`；**本文件不重复**。项目补充：本生态术语 `codebuddy-eco`、技能名、MANIFEST 字段保留英文原词。
2. → 见 `B-01`（切模型/压缩/新开/恢复会话不得回退英文）。

## 2. 判定三态诚实

3. → 见 `B-02`（真阳性 / 真阴性 / 无法判定）。
4. → 见 `B-02`（报错/超时/无输出/拦截一律"无法判定"）。项目补充：探针结果按三态记入巡检/普查记录（旧仓 rule-ledger 机制未随迁）。
5. → 见 `B-02`（"没查到" ≠ "没有"；三态语义不折叠）。

## 3. 先验环境

6. → 见 `B-03`（`pwd -P` + `git log --oneline -1` + `cat VERSION`）。项目补充：本生态真源标识见 `MANIFEST.json` 的 `ecosystem` / `version`。

## 4. 并行与纪律

7. → 见 `B-04`（独立并行、依赖串行、不臆测缺参）。项目补充：技能依赖图见 `MANIFEST.json` 的 `emits` / `depends_on`。

## 5. 唯一真源

8. → 见 `B-06`（仓库是真源、模型不是）。项目补充：本生态交付物含 `.codebuddy/` 全部治理文件与 `docs/`；Git 永久历史，本地检查点仅会话内撤销。

## 6. 安全红线

9. → 见 `B-05`（绝不写明文 token / 凭证）。项目补充：`machine-bootstrap` 的 `BOOTSTRAP_REPO` 走环境变量，不落盘。

## 7. 输出形态

10. → 见 `B-01` 语言纪律。项目补充：本生态文档用 GitHub-flavored Markdown，表格/代码框优先，先结论后展开，避免流水账与冗余客套。

## 8. 本地轻量纪律（防手机卡顿）

> 依据官方一手资料（CodeBuddy Code **v2.51.0 发布说明** + CLI **Best Practices** + CLI **Memory 文档**）：
> 手机长期用变卡的根因是**上下文窗口快速填满 + 记忆/规则全量加载 + 本地数据堆积**，性能随之线性下降。
> 本条约束"加载体积"，与 `artifact-store`（本地轻量化总闸）协同。每条均标官方来源。
> **本节属运行时元纪律，保留项目级常驻、不做 `paths` 条件触发**（paths 只适合绑文件路径的情境契约，见 SOP 20.8.3 判断）；其落点经 SOP 20.7 批准，编号与引用保持稳定。

### 8.1 上下文窗口工程（官方 Best Practices 一等公民）

11. **`/clear` 纪律**：不相关任务之间**频繁**用它完全重置上下文窗口；同一会话纠错 ≥ 2 次即 `/clear` 重开（"干净会话 + 更好提示词 几乎总优于 堆积纠错的长会话"）。注 v2.163+ `/clear` 只清对话与执行状态，**保留**模型选择/上下文窗口/工具配置等会话设置。
12. **自动压缩 + `/compact`**：接近上限时自动压缩（保留代码与决策）；`/compact <指令>` 精细控制（如 `/compact focus on API changes`）；可在 CODEBUDDY.md 写"压缩时务必保留修改文件清单与测试命令"。
13. **Subagents 调研**：重调研/验证用 `.codebuddy/agents/` 子代理在**独立上下文**跑，主会话保持干净（官方："context is your fundamental constraint，subagents 是最强工具之一"）。避免"什么都塞一个会话"（Kitchen Sink）。

### 8.2 记忆按需加载（官方 v2.51.0 原生能力，优先于人工冷归档）

14. **记忆目录摘要**：v2.51.0 起系统提示词注入"记忆文件列表摘要（文件名/大小/修改日期/首行标题）"，AI **按需加载**，不再把所有记忆塞进上下文 → Token 消耗显著下降。**本生态不另建人工冷归档索引，直接用原生摘要。**
15. **记忆自动清理**：v2.51.0 起记忆文件**随会话历史清理一起清理，复用同一保留期配置**，`~/.codebuddy/memories/` 不再无限增长（用户侧：`/clear`、删除/归档旧会话即触发）。

### 8.3 记忆/规则分层与条件加载（官方 Memory 文档）

16. **四层记忆**：用户记忆 `~/.codebuddy/CODEBUDDY.md` / 用户规则 `~/.codebuddy/rules/` / 项目记忆 `./.codebuddy/CODEBUDDY.md` / 项目本地 `./CODEBUDDY.local.md`。**全部启动时自动加载** → 越精简越好。
17. **条件规则优先**：能用 `paths` 触发的（`alwaysApply:false` + `paths`），**不写 `alwaysApply:true` 全量注入**（如本规则中文铁律必须 alwaysApply；领域/TVBox 专属规则应改条件触发，本生态示范见 `.codebuddy/rules/docs.paths.md`）。
18. **临时关闭用 `enabled:false`**（完全不加载），不删文件也能减负。
19. **关闭向上递归查找**：`settings.json` 设 `"memory": { "parentDiscovery": false }` 或环境变量 `CODEBUDDY_DISABLE_PARENT_MEMORY=1`，防子目录会话继承上级甚至工作区外 CODEBUDDY.md，减少无关上下文。

### 8.4 上下文窗口常识

20. 默认 200K 窗口对绝大多数任务够用；**开到 1M 不会更聪明，只让每轮消耗成倍增加**——不盲目拉大窗口。
