# 唯一真源登记表（520pro）

> **这是什么**：core-8 元规则 **M1「真源登记」**的执行化落点——每类事实**只在一个文件**权威定义，其余地方只写指针。
> **怎么用**：要改某类事实，先查本表找到真源文件，改真源；改完按 M5 同步所有指针点，跑 `python3 verify/terminology_check.py` 验断链与编号。
> **谁维护**：新增一类"会被多处引用的事实"时，在本表加一行；**不许**在别处平行定义（M2）。
> **机检**：`verify/terminology_check.py`（编号连续性 + 引用断链）；本表自身的存在性由 `verify.sh` 基线判据盯。

---

## 一、版本与分发

| 事实类别 | 唯一真源 | 说明 / 谁在读 |
|---|---|---|
| 生态版本号 | `VERSION`（首行） | install.sh / verify.sh / bootstrap.sh 读；**不许**在别处写死版本 |
| 分发清单与变更记录 | `MANIFEST.json`（`version` + `changelog_0_x_y`） | 安装范围、各技能登记版本（C4 第四方对账来源） |
| 换机稀疏检出集合 | `MANIFEST.json` 的 `sync_shape` | `bootstrap.sh` 读；不可读时回退脚本内置清单 |

## 二、规则层

| 事实类别 | 唯一真源 | 说明 |
|---|---|---|
| 通用铁律 B-01…B-10 | `通用层/rules/core-8.md`（正文十条，每条带 B-xx 标注 + `｜验证 V-xxx` 尾注） | 别的文件只写"见 B-05"这类指针 |
| 元规则 M1…M7 | `通用层/rules/core-8.md`（开头"元规则"节） | 口径统一纪律 |
| 中文风格约束 | `通用层/rules/zh-style.md` | 语言/排版口径 |
| TVBox 领域风格 | `能力层/tvbox/rules/tvbox-style.md` | 仅 TVBox 域 |

## 三、技能层

| 事实类别 | 唯一真源 | 说明 |
|---|---|---|
| 技能契约（结构/版本/描述/样本） | `verify/skill_contracts.json` | 加技能只加一行，`verify/skill_contract_check.py` 逐条读它判定 |
| 技能版本号（对外） | 各技能 `SKILL.md` 的 front matter `version` | 须与 `CHANGELOG.md` 首条、`MANIFEST.json` 登记、contracts 四处一致（C4） |
| 技能变更记录 | 各技能 `CHANGELOG.md` 首条 `## vX.Y.Z` | 历史档案，不参与引用断链检查 |
| 技能触发样本 | 各技能 `references/trigger-samples.md` | T/N/B 三组；C6 机检数量 + "第一动作/归属"完整性 |

## 四、运行时登记册（随使用增长，不入 git 或按需提交）

| 事实类别 | 唯一真源 | 说明 |
|---|---|---|
| 云端空间归属 | `通用层/skills/space-hub/scripts/space_hub_state.json`（`space_id` + `inbox` + `audit`） | 不入 git；损坏即报错，不折叠成"空" |
| 库房蓝图（该有哪些夹/库） | `通用层/skills/space-hub/scripts/base_blueprint.json` | `ensure` 按它收敛；各技能 `artifacts.json` 的 blueprint 分片合并进来 |
| 归纳规则 | `通用层/skills/space-hub/scripts/classify_rules.json` | 加规则零改代码 |
| 巡检面目录与阈值 | `通用层/skills/inspect-hub/scripts/inspect_registry.json` | 加巡检面零改代码 |
| 产物归属声明 | 各技能 `artifacts.json` | `archive_out` 按它决定落点；未声明 → 落「未归类」并点名 |
| 监测目标 / 死册 / 候选册 | `能力层/tvbox/skills/probe-hub/scripts/monitor_targets.json`、`能力层/tvbox/skills/probe-hub/scripts/dead_repos.json`、`能力层/tvbox/skills/probe-hub/scripts/shellcrack_cands.json` | 本机私产，安装器不随分发（RUNTIME_FILES） |
| 采样史基座 | `能力层/tvbox/skills/probe-hub/scripts/activity_log.json`（**运行时生成**） | 首次采样时创建；损坏拒绝回写 |
| 学习资料树 | `通用层/skills/learn-hub/library/tree.json` | 入库/检索依据 |

## 五、施工与验收

| 事实类别 | 唯一真源 | 说明 |
|---|---|---|
| 验收判据 | `verify.sh`（全量判据 + 分级 ✓/✗/⚠） | 判据数量与红绿是这个脚本的输出，不许手工报 |
| 技能契约判据代码 | `verify/skill_contract_check.py` | 只读 contracts.json，不在脚本里写死技能清单 |
| 口径机检 | `verify/terminology_check.py` | 编号连续 + 引用断链 + 规则↔验证器互引（CHANGELOG/测试记录不查） |
| 规则↔验证器映射 | `verify/rule_map.json` | 每条 B-xx 的判据号/入口/锚点；T4 双向核，锚点漂移即红 |
| 交付报告与派活模板 | `docs/模板_阶段完工交付报告.md`、`docs/派活提示模板.md` | 回执含「回滚路径」必填；派活含五段固定基线 |
| 回归测试（拒收契约 / 规则互引反向） | `verify/tests/` | 手动跑：`python3 verify/tests/test_reject_contract.py`、`bash verify/tests/test_rule_map_reverse.sh`；不进 verify.sh 自动跑（防云端/耗时） |
| 密钥与卫生扫描 | `secret_scan.py` | 九类凭证 + 个人绝对路径 + 本地 endpoint + 模板真值 |

---

## 六、明确不登记（有意例外，M7）

| 东西 | 为什么不登记 |
|---|---|
| 会话回执 / 交付报告（`/workspace/*.md`） | 过程产物，不是事实源；结论要沉淀就回写对应真源 |
| 云端资料库节点标题 | 可被用户随时改名，不能当判据 |
| 模型记忆 / 上会话上下文 | **不是事实**（B-06）；一切以仓内文件为准 |
| 旧仓 `tvbox-eco` 的文档 | 已随迁的部分在本仓有对应物；未随迁的在引用处已注明"旧仓内，未随迁" |

## 变更记录

- 2026-11-12 工程E：core-8 扩到 B-01…B-10（新增 B-10 拦截即停止）；新增 `verify/rule_map.json`（规则↔验证器映射，T4 双向核）；交付报告模板与派活模板进仓。
- 2026-11-12 建立：`verify/terminology_check.py` 首跑发现 core-8 M1 声称"登记表见 `docs/registry.md`"但本仓无此文件（悬空指针），按 M6 回真源建表。
