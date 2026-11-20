---
name: transfer-poll
description: "当用户说「转存任务轮询间隔多少」「查一下 task_id 状态」「生成设备标识 deviceId」「算一下 div101 设备签名」时使用本技能。云转存任务轮询+设备标识（云取 32+56/23 借鉴·纯 Python 标准库）：①轮询状态机——task_id 状态字段判定 done/failed/pending 三态+用户可读进度文案，光鸭间隔 750ms、夸克/UC 1000ms 常量表；②设备标识——randomHex(32) 生成 deviceId，deviceSign=div101.+MD5(SHA1(id+盐))，可注入盐。正门：scripts/transfer_poll.py。不要用于：真实转存操作（归 learn-hub pan.py）、下载能力探测（归 download-probe）、凭证加密（归 cred-vault）。触发词：转存轮询 / task_id 状态 / 轮询间隔 / 设备标识 / deviceId / div101 / 设备签名 / 转存进度 / 光鸭轮询 / 夸克轮询。"
version: "1.0.0"
allowed-tools: Read,Grep,Glob,Bash,Write,Edit
---

> **语言铁律**：全程简体中文，切模型/压缩/新会话不回退。

# transfer-poll（云转存轮询状态机 + 设备标识）

> **定位**：把云取借鉴点 32（云转存 task_id 轮询状态机）+ 56/23（设备标识 div101 签名）封成独立薄壳技能——轮询间隔按平台常量表，状态判定三态诚实，设备签名可注入盐，不靠每个平台写一套循环。

## 1. 何时用
- 要知道某平台云转存轮询该用多少间隔（光鸭 750ms / 夸克UC 1000ms）。
- 拿到 task_id 的 status/detail/code，要判定转存是否完成、是否继续轮询。
- 要生成设备标识 deviceId 或计算 div101. 设备签名。

## 2. 正门与自省
**先读本技能 + `scripts/transfer_poll.py --help`，不许看见脚本就直接跑、不许自己拼哈希链。**
- 正门：`scripts/transfer_poll.py`（薄壳，标准库独立实现；不触网、不转调 pan.py）。
- 判据：`verify/tests/test_transfer_poll.py`（函数级喂真状态样本 + 元变异有牙）。
- 三态：`done` / `failed` / `pending` 分开，pending 明确"继续轮询"，不折叠成成功。

## 3. 能力边界
- 只做**状态判定 + 标识生成**：不发起真实转存、不触网、不落盘、不读登录态。
- 轮询间隔 = 平台常量表（`POLL_INTERVAL_MS`），新增平台加一条。
- 真实转存归 learn-hub 的 `pan.py`；下载链路探测归 `download-probe`；凭证归 `cred-vault`。

## 4. 交付
- `--interval <平台>` → `{platform, interval_ms}`
- `--status <状态> --platform <平台>` → `{status, text, continue_polling}`（三态）
- `--device-id` → `{device_id}`（randomHex 32）
- `--sign <id> --salt <盐>` → `{device_sign}`（div101.+32hex）

## 5. 证据等级（B-02 三态诚实）
- **实证**：轮询间隔常量、status/detail/code 字段、进度文案 —— DEX 方法体内实证（`/tmp/yunget_round4_ops.txt` 32，`GuangYaApi$waitTask$2` / `QuarkApi$pollShareTask$2` 的 750/1000 常量）。
- **字面量实证+算法重建**：`div101.` 前缀 + 32 hex —— classes4.dex 字面量 `div101.78a70629a2b17d0b4302317ffa948`；MD5/SHA-1 字面量在 dex 存在；SHA1→MD5 链取自转录归纳。
- **未实证**：盐的具体取值 DEX 未给出，由调用方通过 `--salt` 提供，本技能不编造固定盐。
- 57 条清单原文不可恢复，编号 56/23 按内容特征匹配（设备标识+轮询），非原文编号逐条对照。
