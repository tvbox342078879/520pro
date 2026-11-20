---
name: download-probe
description: "当用户说「下载前先探测一下这个链接」「这个直链是不是被机房拦了」「看看返回是不是假成功」「探测下载能不能 Range 续传」「下载诊断查一下内网」时使用本技能。下载能力探测（云取 28+52 借鉴·纯 Python 标准库）。能力：①Range 能力探测——发 bytes=0-0，读 ETag/Last-Modified/Accept-Ranges，分 200/206 分支，识别 text/html 假成功错误页（直击机房 IP 被拦返 262 字节 Tengine 页）；②SSRF 防护——探测目标拒 loopback/私网/保留地址，防直链探测被打向内网友好的服务；③三态诚实——可续传/不可续传/无法判定分开，不把被拦页折叠成成功。正门：scripts/probe.py（薄壳，独立实现，标准库）。不要用于：实际下载/转存（归 learn-hub 的 pan.py）、网盘登录鉴权、正文广告排查（归 ad-audit）。触发词：下载探测 / Range 探测 / 假成功识别 / 错误页识别 / HTML 拦截页 / 机房 IP 被拦 / 下载诊断 / SSRF 防护 / 内网探测拦截 / 能否续传。"
version: "1.0.0"
allowed-tools: Read,Grep,Glob,Bash,Write,Edit
---

> **语言铁律**：全程简体中文，切模型/压缩/新会话不回退。

# download-probe（下载能力探测 + SSRF 防护）

> **定位**：把云取借鉴点 28（Range 能力探测识别 HTML 错误页）+ 52（性能诊断 + SSRF 防内网）封成独立薄壳技能——下载前先验链路真假，不靠"看起来下载成功"。

## 1. 何时用
- 下载/抓正文前怀疑被机房 IP 拦（返回假 200、HTML 错误页）。
- 需要判断一个直链是否支持 Range 续传、是否返回真实内容。
- 要确认探测不会打向内网（SSRF 边界）。

## 2. 正门与自省
**先读本技能 + `scripts/probe.py --help`，不许看见脚本就直接跑、不许自己拼 urllib 探测。**
- 正门：`scripts/probe.py`（薄壳，标准库独立实现；不转调 pan.py）。
- 判据：`verify/tests/test_download_probe.py`（函数级喂真实 URL 样本 + 元变异有牙）。
- 三态：`range_ok` / `range_ignored` / `unknown` 分开，HTML 错误页单独标 `blocked`，不折叠成成功。

## 3. 能力边界
- 只做**探测**：判断能否续传、是否被拦、是否安全；不落盘实际内容。
- 实际下载/转存归 learn-hub 的 `pan.py`；网盘登录鉴权、正文广告排查不归本技能。
- SSRF：私网/回环/保留地址一律拒，探测请求永不打向内网。

## 4. 交付
探测结果 JSON（`--json-out` 或 stdout）：`status`（三态）、`headers`、`html_blocked`、`ssrf_safe`、`reason`。
