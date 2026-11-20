---
name: share-parser
description: "当用户说「解析这个网盘分享链接」「提取码在哪」「这个链接有效期几天」时使用本技能。网盘分享链接统一解析（云取 26+33 借鉴·纯 Python 标准库）：①统一平台正则表——夸克/百度/115/蓝奏/迅雷/移动一条正则一个平台，新增平台只加一条不动主流程；②密码双通道——先查 URL query(pwd/pass/password) 再回退全文中文标签「提取码/访问码/密码」；③有效期代码映射——-1/1/3/7/15→永久有效/1天/3天/7天/15天，未知值显式报错。正门：scripts/share_parser.py。不要用于：实际下载/转存（归 learn-hub pan.py）、下载能力探测（归 download-probe）、网盘登录鉴权（归 cred-vault）。触发词：拆链接拿shareId / 提取码 / 访问码 / 有效期 / shareId / 平台正则表 / 夸克链接 / 百度网盘 / 密码双通道。"
version: "1.0.0"
allowed-tools: Read,Grep,Glob,Bash,Write,Edit
---

> **语言铁律**：全程简体中文，切模型/压缩/新会话不回退。

# share-parser（网盘分享链接统一解析）

> **定位**：把云取借鉴点 26（通用分享链接解析+提取码提取引擎，17 正则）+ 33（有效期代码分级提示）封成独立薄壳技能——一条正则接一个平台，密码 URL→正文双通道，不靠逐个平台写 if。

## 1. 何时用
- 拿到一段含网盘链接的文本，要拆出平台 / shareId / 提取码。
- 提取码藏在中文正文（"提取码: x9k2"）而非 URL query 里。
- 要把有效期代码（-1/1/3/7/15）转成用户可读文案。

## 2. 正门与自省
**先读本技能 + `scripts/share_parser.py --help`，不许看见脚本就直接跑、不许自己写正则拆链接。**
- 正门：`scripts/share_parser.py`（薄壳，标准库独立实现；不转调 pan.py）。
- 判据：`verify/tests/test_share_parser.py`（函数级喂真链接样本 + 元变异有牙）。
- 三态：`parsed` / `no_match` / `unknown` 分开；未知有效期代码抛 `UnknownExpireCode`，不静默折叠。

## 3. 能力边界
- 只做**解析**：拆平台 / shareId / 密码 / 有效期文案，不触网、不落盘、不调登录态。
- 新增平台 = 往 `PLATFORM_RULES` 加一条正则（`parse_share` 主流程不动）。
- 实际下载/转存归 learn-hub 的 `pan.py`；链接可达性/是否被拦归 `download-probe`；凭证归 `cred-vault`。

## 4. 交付
解析结果 JSON（`--json-out` 或 stdout）：`status`（三态）、`platform`、`share_id`、`pwd`、`pwd_channel`、`url`。
有效期查询：`--expire <code>` → `{"code":..,"text":..}`；未知代码 status=unknown + reason。

## 5. 证据等级（B-02 三态诚实）
机制取自云取 YunGet v2.7.12 DEX 方法体内实证：`/tmp/yunget_round4_ops.txt` 26/33（dex classes4 ShareLinkParser / ShareExpire）。此处是**机制移植**（正则表+双通道+代码映射），非原 APK 逐字节搬运；平台正则按公开 URL 形态重建，未提供原 dex 17 条常量的逐条字节级对照。
