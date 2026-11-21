# skill-sync-check 触发样本集

> **判据真源**：`SKILL.md`（能力/边界）。本文件只放样本。
> **登记**：`verify/skill_contracts.json` → `trigger_samples`；C6 机检 T≥8/N≥6/B≥3。

## T 组 · 应触发（T≥8）

### T01
- Prompt：`本地技能和远端差多少`
- 为什么该触发：本地 vs 远端版本对比是本技能核心
- 预期第一动作：读 SKILL 正门 → `skill_sync_check.py --help` → 喂本地/远端 contracts → 四态报告
- 不许：自己拼版本号字符串比较

### T02
- Prompt：`查一下哪些技能要更新`
- 为什么该触发：behind 态（本地落后该更新）是本技能主场
- 预期第一动作：build_update_report() → 筛 status=behind
- 不许：把 ahead/missing 也算成要更新

### T03
- Prompt：`达标晋升能不能同步`
- 为什么该触发：原文明确"查更新"是达标晋升同步的前置能力
- 预期第一动作：说明本技能先能查出谁落后，自动同步是下一步（诚实边界）
- 不许：冒称本技能会自动同步/触网拉列表

### T04
- Prompt：`market-verify 是 v1，contracts 登记 v2，能不能升`
- 为什么该触发：版本比较判定（behind/ahead）
- 预期第一动作：compare_versions('v1','v2') → unknown（v 前缀是市场 schema 版本，归 market-verify）
- 不许：硬判成可升级

### T05
- Prompt：`1.0 和 1.0.0 算不算同一个版本`
- 为什么该触发：补零等价是本技能比较口径
- 预期第一动作：compare_versions('1.0','1.0.0') → same
- 不许：段数不同就判不等

### T06
- Prompt：`给我两个 skill_contracts.json 对比版本`
- 为什么该触发：喂真契约文件出报告是本技能交付
- 预期第一动作：`--local a.json --remote b.json` → summary + items
- 不许：只读一个文件就下结论

### T07
- Prompt：`远端多了一个本地没有的技能，什么情况`
- 为什么该触发：missing 态（一侧独有）是本技能四态之一
- 预期第一动作：build_update_report → status=missing，标注无法判定谁新
- 不许：把 missing 当成 behind 让你去更新

### T08
- Prompt：`版本号写成 1.a.0 能比吗`
- 为什么该触发：非法版本 fail-closed 是三态诚实要求
- 预期第一动作：compare_versions → unknown，不硬判
- 不许：把非法版本折叠成 0 或某版本

## N 组 · 不应触发（N≥6）

### N01
- Prompt：`校验这个技能包的 sha256 和签名`
- 不应触发原因：包完整性校验，版本对比不碰摘要/签名
- 应归谁：market-verify

### N02
- Prompt：`这个插件公钥在撤销表里吗`
- 不应触发原因：撤销表查询
- 应归谁：market-verify

### N03
- Prompt：`把技能自动更新到最新版`
- 不应触发原因：本技能只读不触网、不自动更新
- 应归谁：bootstrap（git pull）/ 下一步的同步能力

### N04
- Prompt：`从 GitHub 拉取技能列表`
- 不应触发原因：触网拉列表是下一步，本技能只喂文件
- 应归谁：machine-bootstrap 的 raw_sync

### N05
- Prompt：`安装失败怎么回滚`
- 不应触发原因：回滚决策
- 应归谁：market-verify（rollback_to_previous）

### N06
- Prompt：`把这几笔推送到远端 main`
- 不应触发原因：git 推送
- 应归谁：push-safe

## B 组 · 边界样本（B≥3）

### B01
- 场景：本地 `1.2`，远端 `1.1.9`（段数不同且逐段有大小）
- 边界判定：逐段比较，1.2 > 1.1.9 → ahead
- 依据：compare_versions 逐段比，缺段补 0

### B02
- 场景：版本串 `v1`/`v2`（带字母前缀）
- 边界判定：unknown（那是市场 schema 版本对象，不混用）
- 依据：M3 受控词表——技能版本=点分数字，市场 schema=v+序号，两个对象

### B03
- 场景：远端 contracts 缺 skills 段 / 某技能缺 version 字段
- 边界判定：缺 skills 段 → error + 空 items；缺 version → missing
- 依据：三态诚实，字段缺失无法判定，不硬造版本
