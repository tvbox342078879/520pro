# market-verify 触发样本集

> **判据真源**：`SKILL.md`（能力/边界）。本文件只放样本。
> **登记**：`verify/skill_contracts.json` → `trigger_samples`；C6 机检 T≥8/N≥6/B≥3。

## T 组 · 应触发（T≥8）

### T01
- Prompt：`这个技能包能不能装，校验一下`
- 为什么该触发：三重校验是本技能核心
- 预期第一动作：读 SKILL 正门 → market_verify.py --help → verify_entry() → 三态 JSON
- 不许：自己拼 hashlib 验签逻辑

### T02
- Prompt：`校验一下这个包的 sha256 和签名`
- 为什么该触发：sha256/签名是三重校验两项
- 预期第一动作：verify_entry() → checks.sha256 / checks.signature
- 不许：只比摘要不验签就放行

### T03
- Prompt：`这个插件公钥在撤销表里吗`
- 为什么该触发：撤销表命中即拒是本技能能力
- 预期第一动作：verify_entry(revoked={...}) → rejected
- 不许：撤销表命中还判 verified

### T04
- Prompt：`版本 v1 能不能升到 v2`
- 为什么该触发：schema 版本门控是本技能能力②
- 预期第一动作：schema_gate('v1','v2') → True/False/None
- 不许：跨前缀硬判能升

### T05
- Prompt：`安装失败怎么回滚到上一版`
- 为什么该触发：回滚决策是本技能能力③
- 预期第一动作：rollback_to_previous() → action=rollback，指明落盘走 cred_vault
- 不许：自己实现原子写复制 cred_vault 代码

### T06
- Prompt：`版本串 v1.x 合法吗，别瞎判`
- 为什么该触发：非法版本串 unknown，三态诚实
- 预期第一动作：parse_schema('v1.x') → InvalidSchema / schema_gate → None
- 不许：把非法串当 v1 比较

### T07
- Prompt：`新增一个校验项要改主流程吗`
- 为什么该触发：verify_entry 单点扩展是本技能设计要点
- 预期第一动作：说明改 verify_entry 一处，checks 字典加一项
- 不许：每个调用点各写一套校验

### T08
- Prompt：`缺了公钥这个文件能过校验吗`
- 为什么该触发：公钥缺失 → unknown fail-closed
- 预期第一动作：verify_entry(keyring={}) → status=unknown
- 不许：公钥缺失默认放行

## N 组 · 不应触发（N≥6）

### N01
- Prompt：`把我的网盘 cookie 加密保存`
- 不应触发原因：凭证加密
- 应归谁：cred-vault

### N02
- Prompt：`探测这个下载直链通不通`
- 不应触发原因：下载能力探测
- 应归谁：download-probe

### N03
- Prompt：`这个网盘链接的提取码在哪`
- 不应触发原因：链接解析
- 应归谁：share-parser

### N04
- Prompt：`转存任务轮询到哪一步了`
- 不应触发原因：转存轮询
- 应归谁：transfer-poll

### N05
- Prompt：`把这个技能包安装到本地并写磁盘`
- 不应触发原因：真实落盘安装
- 应归谁：install.sh 正门 / cred_vault 原子写

### N06
- Prompt：`推送代码到远端 main`
- 不应触发原因：git 推送
- 应归谁：push-safe

## B 组 · 边界样本（B≥3）

### B01
- 场景：sha256 过、体积过、签名不过
- 边界判定：status=rejected，reason 指明"三重校验失败：signature"
- 依据：DEX 三重校验任一失败即拒

### B02
- 场景：版本 v1 → a2（跨前缀）
- 边界判定：schema_gate → None（无法判定），不硬判升降
- 依据：正则拆前缀，前缀不同不可比

### B03
- 场景：安装失败但无上一版快照
- 边界判定：rollback → status=unknown，不伪造快照
- 依据：三态诚实 + cred_vault 回滚需真实快照存在
