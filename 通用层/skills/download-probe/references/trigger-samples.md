# download-probe 触发样本集

> **判据真源**：`SKILL.md`（能力/边界）。本文件只放样本。
> **登记**：`verify/skill_contracts.json` → `trigger_samples`；C6 机检 T≥8/N≥6/B≥3。

## T 组 · 应触发（T≥8）

### T01
- Prompt：`下载前先探测一下这个链接能不能续传`
- 为什么该触发：判断能否 Range 续传是本技能核心
- 预期第一动作：读 SKILL 正门 → `probe.py --help` → probe() 发 bytes=0-0 探测 → 报三态
- 不许：直接 urlopen 下载整文件

### T02
- Prompt：`这个直链是不是被机房拦了，返回假成功`
- 为什么该触发：HTML 假成功页识别是本技能主场
- 预期第一动作：probe() → 看 content-type/body → html_blocked 单独标记
- 不许：把 HTML 错误页折叠成"下载成功"

### T03
- Prompt：`看看返回是不是假 200 的错误页`
- 为什么该触发：假成功识别，text/html 嗅探
- 预期第一动作：classify(200, headers, body) → 判 html_blocked
- 不许：只看 HTTP 200 就判定成功

### T04
- Prompt：`探测下载能不能 Range 断点续传`
- 为什么该触发：Range 能力探测（Accept-Ranges/ETag）
- 预期第一动作：probe() → 判 range_ok / range_ignored
- 不许：不探测就假设支持续传

### T05
- Prompt：`下载诊断查一下这个链接会不会打向内网`
- 为什么该触发：SSRF 防内网是本技能能力②
- 预期第一动作：ssrf_safe() → 内网/回环/保留地址一律拒
- 不许：对私网地址发起探测请求

### T06
- Prompt：`这个地址解析到内网了，探测要拦住`
- 为什么该触发：SSRF 解析判定，fail-closed
- 预期第一动作：ssrf_safe(resolve=...) → 内网 IP 拒、解析失败也拒
- 不许：解析失败还放行

### T07
- Prompt：`机房 IP 被拦返回 Tengine 页，帮我识别`
- 为什么该触发：机房 IP 被拦的 HTML 错误页识别（云取 28 实证）
- 预期第一动作：probe() → content-type text/html → html_blocked=true + unknown
- 不许：把拦截页当真实资源

### T08
- Prompt：`下载前探一下这个 URL 的响应头安不安全`
- 为什么该触发：探测响应头 + SSRF 边界属本技能
- 预期第一动作：读 SKILL → probe() → 输出 headers/status/ssrf_safe 三态 JSON
- 不许：绕过正门自己拼 urllib

## N 组 · 不应触发（N≥6）

### N01
- Prompt：`帮我把这个链接的文件下载到本地`
- 不应触发原因：实际下载/落盘，不是探测
- 应归谁：learn-hub 的 pan.py（cmd_pan_pull）

### N02
- Prompt：`把这个网盘文件转存到我的目录`
- 不应触发原因：转存是业务操作
- 应归谁：learn-hub 的 pan.py（transfer）

### N03
- Prompt：`用我的 cookie 登录百度网盘`
- 不应触发原因：网盘登录鉴权
- 应归谁：learn-hub / cred-vault（凭证，非探测）

### N04
- Prompt：`扫一下这个 docx 正文有没有微信广告`
- 不应触发原因：正文广告排查
- 应归谁：ad-audit

### N05
- Prompt：`把这几笔推送到远端 main`
- 不应触发原因：git 推送
- 应归谁：push-safe

### N06
- Prompt：`帮我加密保存这个 token`
- 不应触发原因：凭证加密落盘
- 应归谁：cred-vault

## B 组 · 边界样本（B≥3）

### B01
- 场景：直链既返回 206 又 content-type 是 text/html（矛盾响应）
- 边界判定：html_blocked 优先，判 unknown，不因 206 就报 range_ok
- 依据：被拦页也可能伪装 206，安全侧从严

### B02
- 场景：域名解析出多个 IP，其中一个是私网
- 边界判定：任一内网即拒（ssrf_safe=false），不因有公网 IP 放行
- 依据：DNS rebinding/多 A 记录场景

### B03
- 场景：探测请求本身超时/异常
- 边界判定：status=unknown，记"探测异常"，不折叠成 range_ok 或 blocked
- 依据：三态诚实，无法判定就是无法判定
