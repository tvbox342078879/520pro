## v1.0.0 — 2026-11-21
- 云取借鉴二期收口：网盘分享链接统一解析技能，取自云取 DEX 借鉴点 26（ShareLinkParser 17 正则+密码双通道）+ 33（ShareExpire 有效期代码映射）。
- 薄壳 `scripts/share_parser.py` 纯标准库实现：parse_share() 主流程 + PLATFORM_RULES 规则表 + extract_pwd() 双通道 + expire_text() 有效期映射 + UnknownExpireCode 显式报错。
- 判据 `verify/tests/test_share_parser.py`：函数级真链接样本 + 元变异有牙（规则表驱动性/双通道优先级/未知代码报错）。
- 触发样本 T8/N6/B3 在册；C9 前置 / C10 词桥 / C11 工具白名单对齐。
- 证据等级：DEX 方法体内机制实证（/tmp/yunget_round4_ops.txt 26/33）；正则按公开 URL 形态重建，非逐字节搬运。57 条清单原文不可恢复，编号按内容特征匹配。
