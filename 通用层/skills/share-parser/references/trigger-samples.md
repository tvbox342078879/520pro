# share-parser 触发样本集

> **判据真源**：`SKILL.md`（能力/边界）。本文件只放样本。
> **登记**：`verify/skill_contracts.json` → `trigger_samples`；C6 机检 T≥8/N≥6/B≥3。

## T 组 · 应触发（T≥8）

### T01
- Prompt：`解析这个网盘分享链接 pan.quark.cn/s/abc123`
- 为什么该触发：拆平台+shareId 是本技能核心
- 预期第一动作：读 SKILL 正门 → `share_parser.py --help` → parse_share() → 报三态 JSON
- 不许：自己写正则拆链接

### T02
- Prompt：`这段文本的提取码在哪`
- 为什么该触发：中文正文提取码提取是本技能主场
- 预期第一动作：extract_pwd() → 中文标签回退通道 → 返回 pwd+pwd_channel
- 不许：只看 URL query 找不到就说没有提取码

### T03
- Prompt：`这个链接有效期几天，代码是 7`
- 为什么该触发：有效期代码映射是本技能能力③
- 预期第一动作：`--expire 7` → expire_text() → "7 天"
- 不许：把未知代码静默当永久

### T04
- Prompt：`从百度网盘链接里拆出 shareId`
- 为什么该触发：平台正则表取 shareId
- 预期第一动作：parse_share() → PLATFORM_RULES 命中 baidu → share_id
- 不许：给每个平台写 if 分支

### T05
- Prompt：`新增一个网盘平台只要加正则吗`
- 为什么该触发：规则表驱动性是本技能设计要点
- 预期第一动作：说明往 PLATFORM_RULES 加一条，主流程不动
- 不许：改 parse_share 主流程

### T06
- Prompt：`提取码藏在 URL 参数 pwd 里能提出来吗`
- 为什么该触发：密码双通道的 URL query 通道
- 预期第一动作：extract_pwd(url=...) → channel='url' 优先
- 不许：URL 有 pwd 还去正文找

### T07
- Prompt：`迅雷链接 pan.xunlei.com/s/xxx 解析一下`
- 为什么该触发：平台正则表覆盖迅雷
- 预期第一动作：parse_share() → platform='xunlei'
- 不许：只认夸克/百度两个平台

### T08
- Prompt：`有效期代码 99 是什么，别瞎猜`
- 为什么该触发：未知代码显式报错，三态诚实
- 预期第一动作：expire_text(99) → UnknownExpireCode → status=unknown
- 不许：把 99 折叠成永久或某天数

## N 组 · 不应触发（N≥6）

### N01
- Prompt：`把这个链接的文件下载到本地`
- 不应触发原因：实际下载/落盘，不是解析
- 应归谁：learn-hub 的 pan.py（cmd_pan_pull）

### N02
- Prompt：`把网盘文件转存到我的目录`
- 不应触发原因：转存是业务操作
- 应归谁：learn-hub 的 pan.py（transfer）

### N03
- Prompt：`探测这个直链是不是被机房拦了`
- 不应触发原因：下载能力探测
- 应归谁：download-probe

### N04
- Prompt：`用我的 cookie 登录百度网盘`
- 不应触发原因：登录鉴权
- 应归谁：cred-vault / learn-hub

### N05
- Prompt：`扫一下这个 docx 有没有微信广告`
- 不应触发原因：正文广告排查
- 应归谁：ad-audit

### N06
- Prompt：`把这几笔推送到远端 main`
- 不应触发原因：git 推送
- 应归谁：push-safe

## B 组 · 边界样本（B≥3）

### B01
- 场景：URL query 有 pwd=abc123，正文也有"提取码: xyz9"
- 边界判定：URL 通道优先（channel='url'），不取正文
- 依据：DEX parse() 先查 URL query 再回退全文中文标签

### B02
- 场景：文本含链接但无平台正则命中
- 边界判定：status='no_match'，不硬造 share_id
- 依据：三态诚实，无命中就是无命中

### B03
- 场景：有效期代码 0 / 99 / 字符串
- 边界判定：抛 UnknownExpireCode，显式 reason，不折叠成永久
- 依据：DEX ShareExpire 未知值抛"未知的分享有效期代码："
