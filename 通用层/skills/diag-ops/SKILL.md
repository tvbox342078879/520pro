---
name: diag-ops
description: "当用户说「重启后任务卡住怎么办」「崩溃日志在哪」「导出最近几份崩溃报告」「日志里的 token/手机号脱敏一下」「启动对账怎么做」时使用本技能。诊断运维三件套（云取 53+3+48 借鉴·纯 Python 标准库）：①启动对账——进程重启把 queued(0)/running(1) 一条 SQL 幂等收敛为 paused(2)，杜绝僵尸任务；②崩溃现场——crash_<毫秒>.txt + DiagLog.recordCrash + LogExporter 最近3份各截16384字+logcat末3万行；③日志脱敏——正则表 token/密码/手机号→<redacted>，规则可注入。正门：scripts/diag_ops.py。不要用于：任务转存本身(归 transfer-poll)、凭证加密存储(归 cred-vault)、网盘解析(归 share-parser)。触发词：启动对账 / 僵尸任务 / 崩溃日志 / crash文件 / 日志导出 / 日志脱敏 / LogRedactor / 中断任务恢复。"
version: "1.0.0"
allowed-tools: Read,Grep,Glob,Bash,Write,Edit
---

> **语言铁律**：全程简体中文，切模型/压缩/新会话不回退。

# diag-ops（诊断运维三件套）

> **定位**：把云取借鉴点 53（启动中断任务状态对账）+ 3（崩溃现场抓取与导出）+ 48（日志脱敏）封成独立薄壳技能。

## 1. 何时用
- 进程重启后要收敛上次遗留的 queued/running 任务为 paused。
- 要给崩溃现场落一份可诊断的记录，并导出最近若干份 + logcat 尾部。
- 要在输出日志前把 token / 密码 / 手机号等敏感串脱敏。

## 2. 正门与自省
**先读本技能 + `scripts/diag_ops.py --help`，不许看见脚本就直接跑。**
- 正门：`scripts/diag_ops.py`（薄壳，标准库独立实现）。
- 判据：`verify/tests/test_diag_ops.py`（真样本喂函数 + 元变异有牙）。
- 三态：`ok` / `skipped` / `unknown` 分开；对账幂等（重复跑 changed=0），不改入参。

## 3. 能力边界
- 只做**诊断与收敛**：对账产新任务表、崩溃产元信息、脱敏产文本——不真的写盘、不触网、不执行任务。
- 真实落盘/调度归调用方；脱敏规则表 `REDACT_RULES` 可注入，新增规则加一条不动主流程。
- 状态常量/导出窗口可注入（`reconcile_tasks`/`export_diag` 参数），判据此验表驱动。

## 4. 交付
- `reconcile_tasks(tasks)` → `{status, changed, tasks}`（三态 + 幂等）。
- `capture_crash(...)` → `{status, file, ...}`；`export_diag(...)` → `{status, reports, logcat_tail}`。
- `redact(text, rules=None)` → `{status, text, hits, redacted}`。

## 5. 证据等级（B-02 三态诚实）
- **53 方法体实证**：`/tmp/yunget_round4_ops.txt:34-37` SQL 原文 + `r4_diag.txt:862` recoverInterruptedTasks 启动调用——最扎实的一项。
- **3/48 DEX 类名实证 + 转录归纳**：classes4 `CrashHandler.kt`/`CrashActivity.kt`、classes5 `DiagLog.kt`/`LogExporter.kt`/`LogRedactor.kt`；具体窗口常量（最近3份/16384字/3万行）来自会话转录归纳，方法体未 dump。
- 原 57 条清单（`session.jsonl:65888`）已删不可恢复，编号按内容特征匹配，机制重建非逐字节还原——不冒称完整复刻原 APK。
