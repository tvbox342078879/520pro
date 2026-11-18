# push-safe 触发样本集

> **判据真源**：`SKILL.md`（能力/边界/顺序铁律）。本文件只放样本。
> **登记**：`verify/skill_contracts.json` → `trigger_samples`；C6 机检 T≥8/N≥6/B≥3。

## T 组 · 应触发（T≥8）

### T01
- Prompt：`把这几笔推送到远端 origin main`
- 为什么该触发：git 远端推送是本技能唯一正门场景
- 预期第一动作：先读 SKILL + hooks 头部 → 自检 verify 0✗ → 走 `git_push_safe.sh`（后台+落盘）
- 不许：裸 `git push`

### T02
- Prompt：`git 推送到 origin main，之前老卡`
- 为什么该触发：推送卡死是本技能专门处理（HTTP/2 切 SSH/退避重试）
- 预期第一动作：走正门脚本 → 失败报真因（网络/认证/pre-push）→ 终验远端 SHA 比对
- 不许：把退出码 0 当成功

### T03
- Prompt：`安全推送别裸推，推之前先自检`
- 为什么该触发：自检在前、推送在后是本技能铁律
- 预期第一动作：跑 verify --repo-only → commit-msg 五行齐 → 再推
- 不许：跳过自检直接推

### T04
- Prompt：`推送收口，上一笔 pre-push 报欠账`
- 为什么该触发：欠账 waive 留痕是本技能能力
- 预期第一动作：读 delivery_probe 正门 → 确认 connector 状态 → 显式 `--waive` 至约定日期
- 不许：静默忽略欠账洗绿

### T05
- Prompt：`推不上去，git 一直超时重试`
- 为什么该触发：网络抖动/重试耗尽属本技能诊断范围
- 预期第一动作：区分瞬时/认证错误 → 看正门日志 → 三态判定（成功/失败/无法判定）
- 不许：无脑重试认证错误

### T06
- Prompt：`HTTP2 卡死了，切 SSH over 443 怎么推`
- 为什么该触发：协议切换是正门脚本已固化能力
- 预期第一动作：读 hooks 头部依据 → 走正门 → 说明终验以远端比对为准
- 不许：自己手搓 git config 绕过

### T07
- Prompt：`推完怎么终验远端 SHA 比对，别只看 rc`
- 为什么该触发：终验口径（不看退出码看远端 SHA）是本技能核心教训
- 预期第一动作：`git ls-remote origin refs/heads/main` 与本地 `HEAD` 比对，给 `PUSH_VERIFIED`
- 不许：报 rc=0 就宣布成功

### T08
- Prompt：`把当前分支推到远端`
- 为什么该触发：常规推送也走正门
- 预期第一动作：读 hooks 头部 → 后台推 → 完成通知后非阻塞取 → 远端比对
- 不许：前台死等挂回合

## N 组 · 不应触发（N≥6）

### N01
- Prompt：`帮我把这几笔改动 commit 一下`
- 应归谁：git 常规（commit-msg 钩子约束），本技能只管远端推送
- 不许：本技能做本地提交

### N02
- Prompt：`从远端拉取最新代码`
- 应归谁：git pull（常规），非推送方向

### N03
- Prompt：`把分享链接里的资料存到网盘`
- 应归谁：learn-hub 的 pan.py save（网盘转存，非 git）

### N04
- Prompt：`帮我把文档推送到腾讯文档`
- 应归谁：mobile.tencentDocs.saveContent / 文档类工具（非 git 远端）

### N05
- Prompt：`这个 commit 怎么改 message`
- 应归谁：git 常规 amend（本地操作，且改 message 要谨慎）

### N06
- Prompt：`把代码 push 到我的私人 gitea`
- 应归谁：仍是 git 推送属本技能，但正门默认 origin/main——先确认 remote 名再走正门；非 origin 需显式指定

## B 组 · 边界样本（B≥3）

### B01
- `用户说"推一下图片到群里"→ 非 git，不触发`

### B02
- `问"git 历史怎么回退"→ 本地操作，不触发本技能`

### B03
- `推送已完成问"要不要删远端分支"→ 不可逆操作，本技能不擅自决定`
