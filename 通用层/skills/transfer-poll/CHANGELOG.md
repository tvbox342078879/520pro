## v1.0.0 — 2026-11-21
- 云取借鉴二期收口：云转存轮询状态机+设备标识技能，取自云取 DEX 借鉴点 32（task_id 轮询 750/1000ms）+ 56/23（设备标识 div101 签名）。
- 薄壳 `scripts/transfer_poll.py` 纯标准库实现：poll_interval() 平台间隔表 + classify_task() 三态状态机 + random_device_id() randomHex32 + device_sign() div101.+MD5(SHA1) + 可注入盐。
- 判据 `verify/tests/test_transfer_poll.py`：函数级真状态样本 + 元变异有牙（间隔表驱动/三态判定/签名链/盐注入）。
- 触发样本 T8/N6/B3 在册；C9 前置 / C10 词桥 / C11 工具白名单对齐。
- 证据等级：轮询常量/状态字段/文案=DEX 方法体内实证；div101. 前缀+32hex=dex 字面量实证；SHA1→MD5 链=转录归纳；盐值 DEX 未实证由调用方提供。57 条清单原文不可恢复，编号按内容特征匹配。
