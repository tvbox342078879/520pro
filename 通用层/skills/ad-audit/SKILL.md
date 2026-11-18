---
name: ad-audit
description: "当用户说「查这个百度网盘文档正文有没有微信引流」「这份周刊 docx 帮我扫一下正文广告」「网盘分享的周刊里是不是加了二维码」时使用本技能。百度网盘 docx 正文广告全量排查（踩坑固化·一键命令）。能力：①鉴权（带密码分享 randsk→BDCLND）；②docview→PDF→OCR→关键词命中（微信/二维码/加我/xmly）；③全量扫描 + 三态诚实（带广告/干净/无法判定）；④预列元数据复用绕开实时列目录卡死；⑤结果 JSON + 差异留痕。正门：scripts/ad_audit.py（薄壳，转调 learn-hub/scripts/pan.py ad-audit）。不要用于：网盘转存/下载（归 learn-hub）、单文件本地 PDF 广告（直接用 pan.py ad-audit 或 pdf 技能）、非百度网盘来源。触发词：查正文广告 / 正文有没有微信 / 文档引流排查 / 周刊广告扫描 / 网盘文档二维码 / docx 加我微信 / 全量广告清单 / embedded 引流 / 商业周刊广告复核。"
version: "1.0.0"
allowed-tools: Read,Grep,Glob,Bash,Write,Edit
---

> **语言铁律**：全程简体中文，切模型/压缩/新会话不回退。

# ad-audit（百度网盘 docx 正文广告排查）

> **定位**：把踩坑固化的 `pan.py ad-audit` 一键命令封成技能——用户说人话就加载，不必手动拼参数。

## 1. 何时用
- 用户给百度分享链接/已监测的周刊，问"正文有没有广告/引流/微信/二维码"。
- 全量扫某分享下所有 docx 的正文广告，出清单。

## 2. 正门与自省
**先读本技能 + `pan.py ad-audit --help`，不许看见脚本就直接跑、不许自己重写 OCR 链。**
- 正门：`scripts/ad_audit.py`（薄壳转调 `learn-hub/scripts/pan.py ad-audit`，两者须在同一 skills 根下）。
- 判据：`verify/tests/test_ad_audit.py`（18 项，AST 词级锚禁硬取 `r['fid']`/须兼容 `fs_id`/须有 `--meta`）。
- 前置：登录态 cookie + tesseract chi_sim；实时列目录可能卡死，优先 `--meta` 复用预列元数据。

## 3. 能力边界
- 只做百度网盘分享 docx 正文的引流关键词排查（微信/二维码/加我/xmly 等）。
- 转存/下载归 learn-hub；非百度来源不归本技能。
- 三态诚实：`无预览`/`无 dlink` 记「无法判定」，不折叠成「干净」，不沿用旧判。

## 4. 交付
结果 JSON（`--json-out`）+ 清单，带命中词频与期号；差异（与历史清单）单列不静默删除。
