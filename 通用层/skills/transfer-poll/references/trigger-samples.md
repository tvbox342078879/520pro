# transfer-poll 触发样本集

> **判据真源**：`SKILL.md`（能力/边界）。本文件只放样本。
> **登记**：`verify/skill_contracts.json` → `trigger_samples`；C6 机检 T≥8/N≥6/B≥3。

## T 组 · 应触发（T≥8）

### T01
- Prompt：`转存任务轮询间隔多少`
- 为什么该触发：平台间隔常量表是本技能核心
- 预期第一动作：读 SKILL 正门 → `transfer_poll.py --help` → `--interval <平台>` → 报 ms
- 不许：自己猜一个固定间隔

### T02
- Prompt：`查一下这个 task_id 转存状态`
- 为什么该触发：task_id 状态判定是本技能主场
- 预期第一动作：`--status <state>` → classify_task() → 三态 + continue_polling
- 不许：把未知状态折叠成完成

### T03
- Prompt：`生成一个设备标识 deviceId`
- 为什么该触发：randomHex(32) 设备标识是本技能能力②
- 预期第一动作：`--device-id` → random_device_id() → 32 hex
- 不许：用固定写死的字符串

### T04
- Prompt：`算一下 div101 设备签名`
- 为什么该触发：div101.+MD5(SHA1) 签名是本技能能力②
- 预期第一动作：`--sign <id> --salt <盐>` → device_sign() → div101.+32hex
- 不许：编造一个固定盐当真

### T05
- Prompt：`光鸭转存轮询是多少毫秒`
- 为什么该触发：光鸭 750ms 常量是本技能实证点
- 预期第一动作：`--interval guangya` → 750
- 不许：和夸克的 1000ms 混为一谈

### T06
- Prompt：`夸克 task 状态是 running 还要继续查吗`
- 为什么该触发：pending 状态 continue_polling=true
- 预期第一动作：classify_task('running') → pending + 继续轮询文案
- 不许：报成 done

### T07
- Prompt：`这个状态是 failed，报什么文案`
- 为什么该触发：失败终态 + 用户可读文案
- 预期第一动作：classify_task('failed') → failed + TEXT_QUERY_FAILED/detail
- 不许：把 failed 当 pending 一直轮

### T08
- Prompt：`签名要带盐，盐我没给你别编`
- 为什么该触发：盐 DEX 未实证，必须调用方提供（三态诚实）
- 预期第一动作：说明盐由 `--salt` 提供，本技能不内置固定盐
- 不许：塞一个假盐冒充云取值

## N 组 · 不应触发（N≥6）

### N01
- Prompt：`把这个网盘文件真的转存到我的目录`
- 不应触发原因：真实转存操作
- 应归谁：learn-hub 的 pan.py（transfer）

### N02
- Prompt：`探测这个下载直链能不能续传`
- 不应触发原因：下载能力探测
- 应归谁：download-probe

### N03
- Prompt：`解析这个网盘链接的提取码`
- 不应触发原因：分享链接解析
- 应归谁：share-parser

### N04
- Prompt：`用我的 cookie 登录夸克网盘`
- 不应触发原因：登录鉴权
- 应归谁：cred-vault / learn-hub

### N05
- Prompt：`加密保存这个 token`
- 不应触发原因：凭证加密落盘
- 应归谁：cred-vault

### N06
- Prompt：`扫一下这个 docx 有没有广告`
- 不应触发原因：正文广告排查
- 应归谁：ad-audit

## B 组 · 边界样本（B≥3）

### B01
- 场景：status 是未知值 'weird_state'
- 边界判定：pending + continue_polling=true，不折叠成 done/failed
- 依据：三态诚实，未知继续轮询

### B02
- 场景：签名的盐不同
- 边界判定：device_sign('id','saltA') != device_sign('id','saltB')，盐真注入哈希链
- 依据：盐影响 SHA1 输入，可注入验证

### B03
- 场景：未登记的陌生平台查间隔
- 边界判定：返回 DEFAULT_INTERVAL_MS（1000），不抛崩、不编造平台专属值
- 依据：规则表驱动的默认分支
