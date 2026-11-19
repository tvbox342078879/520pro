---
name: cred-vault
description: "当用户说「把这个 cookie/token 加密保存」「凭证别明文放着」「密钥泄露了怎么批量失效」「不同网站的密码能用同一套加密吗」「登录凭据帮我安全落盘」时使用本技能。凭证安全落盘（云取 YunGet 机制借鉴·三合一）。能力：①AES-GCM tag128 加密落盘，信封 wbcred:v1，PBKDF2 21万轮派生密钥，0600 权限；②域分离 AAD——domain（如 baidu_cookie/github_token）作更新 AAD，密文跨字段/跨站点重放必失败；③密钥自愈——密钥条目损坏自动删条目重建重试一次，再败抛永久失效，一次性全局失效标记（轮换后旧密文全失效，不逐字段试错）。正门：scripts/cred_vault.py（自带真源实现，selftest 13 项 + 判据 20 项）。不要用于：网盘转存/下载（归 learn-hub）、公众号发布凭证（归 wechat 发布技能）、明文口令的日常记忆、非本地落盘的密钥托管服务。触发词：凭证加密 / cookie 加密保存 / token 安全落盘 / 密钥自愈 / 域分离加密 / AES-GCM 凭证 / 密码明文风险 / 密钥轮换失效 / 凭据泄露排查 / 加密信封 / 0600 凭证 / PBKDF2 派生。"
version: "1.0.0"
allowed-tools: Read,Grep,Glob,Bash,Write,Edit
---

> **语言铁律**：全程简体中文，切模型/压缩/新会话不回退。

# cred-vault（凭证安全落盘 · 凭证司）

> **定位**：把云取 YunGet 的凭证加密/域分离/密钥自愈三机制（DEX 实证 39·22·2 / 41 / 40·30）收敛为一个可复用技能。用户说人话就加载，不手写 AES/PBKDF2。

## 1. 何时用
- 用户要把 cookie/token/密码加密落盘，或问「凭证别明文放着」「密钥泄露怎么办」。
- 多站点凭证要隔离（github_token 的密文不能当 baidu_cookie 用）、密钥损坏要自愈、轮换要一次性全失效。

## 2. 正门与自省
**先读本技能 + `scripts/cred_vault.py --help`，不许看见脚本就直接跑、不许自己拼 AES/PBKDF2 参数、不许把口令写进文件或日志。**
- 正门：`scripts/cred_vault.py`（自带真源实现，非薄壳——云取是 Android DEX 无法转调）。子命令：`key-init` / `seal` / `open` / `key-status` / `selftest`。
- 密钥：默认 `--key` 指向仓库外 0600 密钥文件；口令模式 `--passphrase-env` 运行时从环境变量注入，零明文（B-05）。明文只在内存，输出一律 0600。
- 判据：`verify/tests/test_cred_vault.py`（20 项，贴真函数 + 元变异：去 AAD/去自愈/去失效标记均转红）；自检 `scripts/cred_vault.py selftest`（13 项）。
- 前置：Python `cryptography` 库（本机实测 46.0.4 + AESGCM 可用）；缺库报「无法判定」不假绿。

## 3. 能力边界
- 三态诚实：域不匹配/篡改/错密钥统一报 InvalidTag，不区分具体哪一种（防侧信道）， caller 自行按上下文判读。
- 密钥损坏→重建重试一次；重建后仍失败→PermanentInvalid 停止，不静默放行。密钥轮换后旧密文失效，靠一次性全局标记提示重登，不逐字段试错。
- 不保管口令、不做密钥托管服务、不碰网盘转存与公众号发布凭证（各归其技能）。

## 4. 交付
密文信封（`wbcred:v1:<b64IV>:<b64CT>`，0600）+ 密钥文件（仓库外 0600）；验 `key-status` 在位、`selftest` 全绿、判据 20/0；凭证名若新增须先登记 `verify/cred_names.json`（零期闸4）才算合法。
