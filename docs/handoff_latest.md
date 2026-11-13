# 交接摘要（handoff_latest）

> **用途**：换模型 / 新会话 / 换设备接手时，**先读这三项再动手**（core-8 `B-07`）。
> **纪律**：三项缺一 = 交接不完整；本文件由**当前主线负责人**在每次阶段收尾时更新，不写历史流水账。
> **机检**：`verify/tests/test_handoff.py` 查三项齐全 + 版本号与 `VERSION` 一致（过期即红）+ 第 4 段账目三齐（B-14）+ **三通道接手条款在位**（core-8 / 薄壳 / 手机指令各有一句"先读本文件"的动作）。

## 1. 当前主线（一句话）

**外部正本全面迁移（v0.8.33）**——平台把 `library/database/` 整层重构为 `db_create / db_query / db_edit / db_delete` 四件套，旧脚本名全部消失。本轮把 **8 类 24 处**调用迁移完毕（space-hub 6 / tvbox-core 11 / probe-hub 9），并补上一个**检查器盲区**：`_run_lib('database/xxx.py')` 与 `api('database/xxx.py')` 这类间接入口第一版完全扫不到，实测漏掉 5 处（core.py 3 + preflight 1 + probe 5）。迁移中暴露两件事：① **写入语义变了**——旧 `results[].success` 只代表服务端接受，新 `KS_DB_EDIT_OK` 是逐条回读确认后才发，因此核数逻辑必须按 `failed_*_indices / verified_count` 重算；② **同一个 JSON 解析 bug 在 6 个文件里各写了一遍**：`json.loads(text[i:])` 遇尾随 `KS_USER_REPLY` 行整体失败→ 静默返回 `{}`（实测丢 `record_ids/add_count`），已统一改 `raw_decode`。验证：真实库写入→回读 1 条→二段式删除→回读 0 条，全链路通；`lib_refs_check` 由 8 类失配 → **9/9 类 22 处全有效**。此前主线（artifact-store 执行体 v0.8.32、技能触发前置 v0.8.31、908 蓝图榨取）均已收口。

## 2. 版本与位置

- 仓库根：当前 clone 目录（用 `pwd -P` 确认，不在本文件写死绝对路径）
- 版本：0.8.33
- 远端：核对口径是 `git rev-parse HEAD` 与 `gh api repos/tvbox342078879/520pro/commits/main --jq .sha` **两值相等**——本文件不写死 sha，因为任何一次收尾提交都会让写死值过期（写方法不过期）；`ls-remote` 常因网络抖动超时，超时记「无法判定」不算通过
- 推送一律走 `hooks/git_push_safe.sh`，不裸 push
- 当前主线自检口径：`bash verify.sh` 应 **0 ✗ / 0 ⚠**；`python3 verify/skill_contract_check.py --require-mirror` 应无 ✗（体积项允许 ⚠）

## 3. 习惯快照指针（只指，不抄）

| 习惯 | 真源 |
|---|---|
| 十八条通用铁律 + 七条元规则 | `通用层/rules/core-8.md`（B-01…B-18 / M1–M7） |
| 规则↔验证器映射（哪条怎么查） | `verify/rule_map.json` |
| 台账四律判据（状态/指纹/幂等/退出码） | `verify/ledger_laws.py` + `verify/tests/test_ledger_laws.py` |
| 手机指令云端副本（nodeId/sha/条数） | `docs/手机指令云端副本.json`；写它的是 `sync_phone_directive.py`，判它的是 `verify.sh` |
| 旧生态规则去向（193 条） | `docs/规则迁移映射_193条.md` |
| 通病病历（反复犯的错） | `docs/通病台账.md`（与 `docs/遗留登记.md` 分工：病历 vs 待办） |
| 技能契约（版本四处对账 / 描述五组 / 样本 / 体积） | `verify/skill_contracts.json` |
| 施工纪律（中文 / 正反向才提交 / 顺手修 / 每章出报告） | 会话约定 + `docs/模板_阶段完工交付报告.md` |

> 不要在本文件里复制条文全文——抄一份就多一个会腐烂的副本（M2）。

## 4. 待办账目（三齐）

| 事项 | owner | next | due |
|---|---|---|---|
| 云端收件箱 2 个测试库待删 | 用户 | 在资料库 App 内手动点删 | 用户确认删除即完 |
| 手机端硬轨：App 无指令入口（2.8.0/2.9.1 两版实测）→ 每次新会话首条粘贴（14 条正文/13 条对应 B 编号；云端 doc v9） | 用户 | 每个新会话开始时，资料库打开「手机指令粘贴区（复制即用）」→ 从第 2 行起全选复制 → 作为该会话**第一条消息**发出，然后再提需求 | 已形成习惯（连续 2 个新会话都先粘贴）即算完 |
| library 引用失配 7 类 21 处 | 我 | 按 `verify/lib_refs_check.py --strict` 输出逐类迁移，每类先 `--help` 确认签名 | 2026-11-20 |
| 「📚 学习资料」「🔍 探源产出」两根 ID 失效（不在顶层） | 我 | 先确认原内容是否还在旧节点下，再决定重建还是重挂 | 2026-11-18 |
| GitHub 账号双因子 | 用户 | 在账号安全设置里开启 2FA | 2026-12-08 前 |
