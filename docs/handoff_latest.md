# 交接摘要（handoff_latest）

> **用途**：换模型 / 新会话 / 换设备接手时，**先读这三项再动手**（core-8 `B-07`）。
> **纪律**：三项缺一 = 交接不完整；本文件由**当前主线负责人**在每次阶段收尾时更新，不写历史流水账。
> **机检**：`verify/tests/test_handoff.py` 查三项齐全 + 版本号与 `VERSION` 一致（过期即红）+ 第 4 段账目三齐（B-14）+ **三通道接手条款在位**（core-8 / 薄壳 / 手机指令各有一句"先读本文件"的动作）。

## 1. 当前主线（一句话）

v0.8.45 锚点钩子挖到**第二层**：cwd 回退修好后，实测钩子确实被调用、确实命中、确实打印，
但 **PreToolUse 的 stdout 不进模型上下文**（probe 有 hit，工具输出里没有 `⏭`）。模型侧
锚点改走 `UserPromptSubmit.additionalContext`，PreToolUse 降级为「只给用户看」的提示。

**下一步**：`git log -1 --format=%B | sed -n 's/^Next: //p'`（正文即细则）

> v0.8.40–44 已收口：`git show 1c5a2ae` / `f5973ae` / `c4d8bee` / `596c2d8` / `d7a92c2`。


## 2. 版本与位置

- 仓库根：当前 clone 目录（用 `pwd -P` 确认，不在本文件写死绝对路径）
- 版本：0.8.45
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

**级别**：`P0` 主线推进（**全表至多 1 条**，超了就是主次不分，`test_handoff.py` 直接红）；`P1` 有 due 且会阻断功能；`P2` 杂务/习惯，不阻断。`Next:` 必须对应那条 P0。

| 级别 | 事项 | owner | next | due |
|---|---|---|---|---|
| P1 | 下一件主线待用户选定（P0 已收口，不自己发明——第 1 条纠偏） | 用户 | 三选一：① `probe-hub` SKILL.md 40.1KB 卡阈值（常年 ⚠）② feature-gate / skill-evolution 三处残留处置（已批准未执行）③ 两根失效 ID 复挂 | 下次会话首轮 |
| P1 | 锚点钩子（`hooks/next_anchor.py`）**两层根因已修，待新会话验收**：① Bash cwd 恒 `/workspace`（非 git 仓），旧版只认 `payload.cwd` → 三级回退已修；② **PreToolUse 的 stdout 不进模型上下文**（实测：probe 有 `hit:true`，工具输出无 `⏭` 行）→ 模型侧改走 `UserPromptSubmit.additionalContext` | 我 | 新会话首条消息后跑 `--probe`：应出现 `event:UserPromptSubmit` 且 `hit:true`；再让我原样复述注入的 Next（能复述=真进了上下文，复述不出=没注入） | 下一次新会话首条消息 |
| P2 | 云端收件箱 2 个测试库待删 | 用户 | 在资料库 App 内手动点删 | 用户确认删除即完 |
| P2 | 手机端硬轨：App 无指令入口（2.8.0/2.9.1 两版实测）→ 每次新会话首条粘贴（14 条正文/13 条对应 B 编号；云端 doc v9） | 用户 | 每个新会话开始时，资料库打开「手机指令粘贴区（复制即用）」→ 从第 2 行起全选复制 → 作为该会话**第一条消息**发出，然后再提需求 | 已形成习惯（连续 2 个新会话都先粘贴）即算完 |
| P2 | GitHub 账号双因子 | 用户 | 在账号安全设置里开启 2FA | 2026-12-08 前 |
