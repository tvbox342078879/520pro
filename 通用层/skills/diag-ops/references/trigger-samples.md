# diag-ops 触发样本集

> **判据真源**：`SKILL.md`（能力/边界）。本文件只放样本。
> **登记**：`verify/skill_contracts.json` → `trigger_samples`；C6 机检 T≥8/N≥6/B≥3。

## T 组 · 应触发（T≥8）

### T01
- Prompt：`进程重启后任务卡在下载中，怎么恢复`
- 为什么该触发：53 启动对账是本技能核心
- 预期第一动作：读 SKILL 正门 → reconcile_tasks() → queued/running 收敛 paused
- 不许：逐条手动改状态、改入参

### T02
- Prompt：`启动对账要幂等吗`
- 为什么该触发：幂等是本技能设计要点
- 预期第一动作：reconcile_tasks() 重复跑 changed=0
- 不许：重复启动把已暂停任务又改一遍

### T03
- Prompt：`崩溃日志存在哪里，文件名什么格式`
- 为什么该触发：3 崩溃现场命名是本技能能力②
- 预期第一动作：capture_crash() → crash_<毫秒>.txt
- 不许：随便起文件名

### T04
- Prompt：`导出最近3份崩溃报告加 logcat 尾部`
- 为什么该触发：LogExporter 导出窗口是本技能能力
- 预期第一动作：export_diag(recent_n=3, tail_lines=30000)
- 不许：把全部历史报告都导出

### T05
- Prompt：`日志里的 token 和手机号脱敏一下`
- 为什么该触发：48 日志脱敏是本技能能力③
- 预期第一动作：redact() → <redacted> + hits
- 不许：打印原始 token

### T06
- Prompt：`新增一条脱敏规则要改主流程吗`
- 为什么该触发：规则表驱动是本技能设计
- 预期第一动作：说明往 REDACT_RULES 加一条，redact 主流程不动
- 不许：每个调用点各写一套 replace

### T07
- Prompt：`崩溃报告为空能导出吗`
- 为什么该触发：无内容→skipped 三态诚实
- 预期第一动作：export_diag([], logcat='') → status=skipped
- 不许：空报告硬造一份

### T08
- Prompt：`脱敏正则写错了会怎样`
- 为什么该触发：改坏规则→unknown 不静默
- 预期第一动作：redact(rules=[坏正则]) → status=unknown
- 不许：正则崩了还返回原文本当成功

## N 组 · 不应触发（N≥6）

### N01
- Prompt：`把网盘文件转存下来`
- 不应触发原因：转存业务
- 应归谁：learn-hub pan.py / transfer-poll

### N02
- Prompt：`把 cookie 加密存到本地`
- 不应触发原因：凭证加密存储
- 应归谁：cred-vault

### N03
- Prompt：`解析这个网盘链接的提取码`
- 不应触发原因：链接解析
- 应归谁：share-parser

### N04
- Prompt：`校验技能包签名`
- 不应触发原因：市场包校验
- 应归谁：market-verify

### N05
- Prompt：`探测直链是否被拦`
- 不应触发原因：下载探测
- 应归谁：download-probe

### N06
- Prompt：`推送到远端 main`
- 不应触发原因：git 推送
- 应归谁：push-safe

## B 组 · 边界样本（B≥3）

### B01
- 场景：对账输入含 status=9（非 queued/running/paused）
- 边界判定：状态9 不动，不误收敛；changed 只数 1/0
- 依据：只认 INTERRUPTED_STATES=(0,1)

### B02
- 场景：日志无任何敏感串
- 边界判定：status=skipped（不是 ok 硬报命中）
- 依据：三态诚实

### B03
- 场景：崩溃报告7份，注入 recent_n=1
- 边界判定：只导最近1份（窗口可注入真生效）
- 依据：export_diag 参数驱动，非硬编码3
