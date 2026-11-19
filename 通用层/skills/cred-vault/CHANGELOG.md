## v1.0.0 首次接入 520（云取三机制借鉴·凭证安全）
- 加密落盘：AES-GCM tag128 + 信封 wbcred:v1 + PBKDF2 21万轮 + 0600（云取 AuthCrypto 实证）。
- 域分离 AAD：domain 作 updateAAD，跨字段密文重放必失败（云取 AndroidKeystoreCredentialCipher 实证）。
- 密钥自愈：损坏删条目重建重试一次、再败 PermanentInvalid + 一次性全局失效标记（云取 41/40·30 实证）。
- 正门 scripts/cred_vault.py 自带真源实现（selftest 13 项）；判据 verify/tests/test_cred_vault.py 20 项含三元变异。
- 凭证名登记真源 verify/cred_names.json 扩 cred_vault 条目（零期闸4）。
