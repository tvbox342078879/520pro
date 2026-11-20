# market-verify CHANGELOG

## v1.0.0（2026-11-21）
- 新建：技能市场包完整性校验链（云取借鉴 4+25+47）。
- `scripts/market_verify.py`：`parse_schema`（版本正则 ^([a-zA-Z]*)(\d*)$）、`schema_gate`（同前缀序号门控，跨前缀/非法→None）、`sha256_hex`、`verify_entry`（sha256/体积/签名三重校验 + 撤销表 + keyring 注入，三态 verified/rejected/unknown，fail-closed）、`rollback_to_previous`（回滚决策，落盘引用 cred_vault 原子写不复制）。
- 证据等级标注：DEX 类名实证 + 转录归纳，方法体未 dump，签名用 HMAC-SHA256 验签代理非原 Ed25519。
- 判据：`verify/tests/test_market_verify.py`（A-E 五层，元变异有牙：注入 keyring/撤销表/改签名/改 schema 正则）。
