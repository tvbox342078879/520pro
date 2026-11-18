---
name: push-safe
description: "当用户说「把这几笔推送到远端」「git 推送到 origin main」「安全推送别裸推」「推送前先自检」时使用本技能。Git 远端推送收口（正本 hooks/git_push_safe.sh，禁裸 git push）。能力：①自检在前（verify 0✗ + 版本/契约绿才推）；②瞬时错误重试+指数退避+jitter，认证错误不重试；③HTTP/2 挂死切 SSH over 443；④后台推送非阻塞+终验以 git rev-parse 比对远端为准（不看退出码）；⑤pre-push 欠账按正门 waive 留痕。正门：scripts/push_safe.sh（薄壳，转调 hooks/git_push_safe.sh）。不要用于：本地 commit（git 常规）、拉取/合并、非 git 网盘同步。触发词：推 git / 推送远端 / 安全推送 / push 收口 / 裸推禁止 / 远端比对 / 推送自检 / 推不上去 / HTTP2 卡死 / pre-push 欠账。"
version: "1.0.0"
allowed-tools: Read,Grep,Glob,Bash,Write,Edit
---

> **语言铁律**：全程简体中文，切模型/压缩/新会话不回退。

# push-safe（Git 远端推送收口）

> **定位**：把踩坑固化的 `hooks/git_push_safe.sh` 正门封成技能——推送前自动加载纪律，不靠自觉裸推。

## 1. 何时用
- 用户说"推一下/推到远端/push/main"，或排查"推不上去/卡死/pre-push 欠账"。
- 任何要写 GitHub 远端的操作。

## 2. 正门与自省
**先读本技能 + `hooks/git_push_safe.sh` 头部，不许裸 `git push`、不许跳过自检。**
- 正门：`scripts/push_safe.sh`（薄壳转调仓库 `hooks/git_push_safe.sh`）。
- 判据：`verify/tests/test_skill_entry.py`（薄壳真转调，非 AST 查存在）；终验 `git ls-remote origin refs/heads/main == 本地 HEAD`。
- 顺序铁律：自检在前、推送在后；commit-msg 五行齐；后台跑+落盘+非阻塞取。

## 3. 能力边界
- 只做 git 远端推送收口（重试/退避/切协议/终验/欠账 waive）。
- 本地 commit、pull、merge 走常规 git；网盘同步归 learn-hub。
- 三态诚实：网络抖动无法判定不洗绿，退出码 0 不等于推成功——终验以远端比对为准。

## 4. 交付
推送结果 + 远端 SHA 比对；失败报真因（网络/认证/pre-push 欠账），欠账走 `delivery_probe --waive` 留痕非洗绿。
