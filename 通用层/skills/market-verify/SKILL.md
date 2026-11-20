---
name: market-verify
description: "当用户说「这个技能包能不能装」「校验一下 sha256 和签名」「插件公钥撤销了吗」「版本 v1 能不能升 v2」「安装失败怎么回滚」时使用本技能。技能市场包完整性校验链（云取 4+25+47 借鉴·纯 Python 标准库）：①索引三重校验——sha256 摘要+体积+签名(keyId→<keyId>.pub)，撤销表命中即拒；②schema 版本门控——正则 ^([a-zA-Z]*)(\\d*)$ 拆前缀+序号，同前缀才可比，跨前缀/非法→无法判定；③安装失败回滚——只产回滚决策，真实原子写落盘引用 cred_vault 已落地快照，不复制。正门：scripts/market_verify.py。不要用于：凭证加密(归 cred-vault)、下载探测(归 download-probe)、转存轮询(归 transfer-poll)。触发词：技能包校验 / 三重校验 / sha256验签 / 公钥撤销表 / schema版本门控 / 安装回滚 / keyId。"
version: "1.0.0"
allowed-tools: Read,Grep,Glob,Bash,Write,Edit
---

> **语言铁律**：全程简体中文，切模型/压缩/新会话不回退。

# market-verify（技能市场包完整性校验链）

> **定位**：把云取借鉴点 4（技能市场规模化：索引外置+sha256/体积/签名三重校验+公钥/撤销表+失败回滚）+ 25（schema 版本门控）+ 47（回滚快照原子写）封成独立薄壳技能。

## 1. 何时用
- 装技能包前校验索引条目：摘要、体积、签名三项是否全过。
- 查某插件/公钥是否在撤销表；给了 keyId 找对应公钥验签。
- 判断版本 v1→v2 能否升级（schema 门控）；安装失败产回滚决策。

## 2. 正门与自省
**先读本技能 + `scripts/market_verify.py --help`，不许看见脚本就直接跑、不许自己拼验签逻辑。**
- 正门：`scripts/market_verify.py`（薄壳，标准库独立实现）。
- 判据：`verify/tests/test_market_verify.py`（真样本喂函数 + 元变异有牙）。
- 三态：`verified` / `rejected` / `unknown` 分开；字段缺失、公钥缺失、版本跨前缀/非法 → unknown（fail-closed 不放行）。

## 3. 能力边界
- 只做**校验与决策**：三重校验 + 版本门控 + 回滚决策；不触网、不真的安装/卸载。
- 真实回滚落盘 = `cred_vault.py:100` 已落地的"回滚快照原子写"——本技能**引用不复制**（M1/M2）。
- 撤销表/keyring 可注入（`verify_entry(entry, keyring=..., revoked=...)`）；新增校验项改 `verify_entry` 一处。

## 4. 交付
校验结果 JSON：`status`（三态）、`plugin_id`、`checks`（sha256/size/signature）、`reason`。
版本门控：`--installed v1 --required v2` → `upgrade` = True/False/None。
回滚：`rollback_to_previous(current, previous, ok)` → `action` = keep/rollback/none。

## 5. 三项校验实现口径
签名用 **HMAC-SHA256 作确定性验签代理**（Python 标准库无 Ed25519），验签链结构真实（按 keyId 取公钥、compare_digest 比对）；不是云取原 Ed25519 逐字节算法。摘要用标准库 `hashlib.sha256`。

## 6. 证据等级（B-02 三态诚实）
取自云取 YunGet v2.7.12 DEX：classes4 `MarketClient`/`PluginSignature$Ed25519`/`PluginTrust$BuiltinKey`/`KeyVerdict`/`sha256Hex`/`rollbackToPrevious$2`，classes3 `computeSHA256Digest`，classes5 `PluginMarketScreen`；版本正则与三重校验语义来自会话转录归纳（原 57 条清单 `session.jsonl:65888` 已删不可恢复）。**方法体未 dump，机制重建非逐字节还原**——不冒称完整复刻原 APK。
