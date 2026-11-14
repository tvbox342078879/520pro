# 唯一真源登记表（520pro）

> **这是什么**：core-8 元规则 **M1「真源登记」**的执行化落点——每类事实**只在一个文件**权威定义，其余地方只写指针。
> **怎么用**：要改某类事实，先查本表找到真源文件，改真源；改完按 M5 同步所有指针点，跑 `python3 verify/terminology_check.py` 验断链与编号。
> **谁维护**：新增一类"会被多处引用的事实"时，在本表加一行；**不许**在别处平行定义（M2）。
> **提方案前先查本表**（工程纪律 §9）：已有真源能扩就扩、能复用就复用；确要新建，须在提交信息 `Reuse:` 行写明四查结果与不复用理由。
> **机检**：`verify/terminology_check.py`（编号连续性 + 引用断链）；本表自身的存在性由 `verify.sh` 基线判据盯。

---

## 一、版本与分发

| 事实类别 | 唯一真源 | 说明 / 谁在读 |
|---|---|---|
| 生态版本号 | `VERSION`（首行） | install.sh / verify.sh / bootstrap.sh 读；**不许**在别处写死版本 |
| 分发清单与变更记录 | `MANIFEST.json`（`version` + `changelog_0_x_y`） | 安装范围、各技能登记版本（C4 第四方对账来源） |
| 换机稀疏检出集合 | `MANIFEST.json` 的 `sync_shape` | `bootstrap.sh` 读；不可读时回退脚本内置清单 |
| 手机指令云端副本（nodeId + 内容 sha） | `docs/手机指令云端副本.json` | 由 `sync_phone_directive.py` 写；`verify.sh` 用它离线判「副本是否过期」。**手改这个文件等于伪造"已同步"**，比对 sha 只能由脚本算 |

## 二、规则层

| 事实类别 | 唯一真源 | 说明 |
|---|---|---|
| 通用铁律 B-01…B-18 | `通用层/rules/core-8.md`（正文十八条，每条带 B-xx 标注 + `｜验证 V-xxx` 尾注） | 别的文件只写"见 B-05"这类指针 |
| 元规则 M1…M7 | `通用层/rules/core-8.md`（开头"元规则"节） | 口径统一纪律 |
| 规则↔判据映射 | `verify/rule_map.json` | 每条 B 条一个验证入口；T4 双向核对（映射集合 == core-8 编号集合） |
| 台账四律判据 | `verify/ledger_laws.py` | M-R75/82/86/93 的机检落点；变异对照见 `verify/tests/test_ledger_laws.py` |
| 旧生态规则迁移台账 | `docs/规则迁移映射_193条.md` | 193 条逐条去向（A/B/C/D）；只登记指针，不复制条文 |
| 工程纪律（人工复核项） | `docs/工程纪律.md` | 7 条机器判不了的教训；含"怎么查" |
| 通病台账（重复犯的错） | `docs/通病台账.md` | 与 `docs/遗留登记.md`（待办）分工：这里是病历，那里是待办 |
| 中文风格约束 | `通用层/rules/zh-style.md` | 语言/排版口径 |
| TVBox 领域风格 | `能力层/tvbox/rules/tvbox-style.md` | 仅 TVBox 域 |

## 三、技能层

| 事实类别 | 唯一真源 | 说明 |
|---|---|---|
| 技能契约（结构/版本/描述/样本/触发可命中性） | `verify/skill_contracts.json` | 加技能只加一行，`verify/skill_contract_check.py` 逐条读它判定（C1–C7 结构类 + C9 触发前置 + C10 样本词桥） |
| 技能版本号（对外） | 各技能 `SKILL.md` 的 front matter `version` | 须与 `CHANGELOG.md` 首条、`MANIFEST.json` 登记、contracts 四处一致（C4） |
| 技能变更记录 | 各技能 `CHANGELOG.md` 首条 `## vX.Y.Z` | 历史档案，不参与引用断链检查 |
| 外置文档索引 | `能力层/tvbox/skills/tvbox-pipeline/docs/manual_索引.md`、`能力层/tvbox/skills/probe-hub/docs/外置_索引.md` | 条目集合必须等于目录集合（`verify/tests/test_doc_index.py`） |
| 路径政策（canonical） | `MANIFEST.json` 的 `path_policy` | 新文档一律 `references/`；`docs/` 为过渡存量 |
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
| 推送纪律 | `hooks/git_push_safe.sh` | 向 GitHub 推送一律走它（重试 + 远端 sha 终验），禁止裸 `git push` |
| 一行收尾入口 | `sync.sh`（仓库根） | 优化完跑 `bash sync.sh` = verify.sh → fetch 对账 → git_push_safe；不做自动提交（过 pre-commit 闸）、不强制推送、不内嵌令牌 |
| 技能契约判据代码 | `verify/skill_contract_check.py` | 只读 contracts.json，不在脚本里写死技能清单 |
| 口径机检 | `verify/terminology_check.py` | 编号连续 + 引用断链 + 规则↔验证器互引（CHANGELOG/测试记录不查） |
| 真源联动提醒（G6 轻量版） | `verify/linkage_notice.py` | pre-commit 检出"本次改了 registry 登记的真源"时自动列全仓引用方清单（advisory 不阻断；语义过期机检查不了，人眼过 M5）；判据 `verify/tests/test_linkage_notice.py` |
| 规则↔验证器映射 | `verify/rule_map.json` | 每条 B-xx 的判据号/入口/锚点；T4 双向核，锚点漂移即红 |
| 交付报告与派活模板 | `docs/模板_阶段完工交付报告.md`、`docs/派活提示模板.md` | 回执含「回滚路径」必填；派活含五段固定基线 |
| 技能卡片导出（手机端导入用） | `export_skill_cards.py` | 从 SKILL.md 现读现出，不手抄；坏技能整条不输出（半张卡片更难查）；`verify/tests/test_skill_cards.py` 盯"description 不许夹带 frontmatter 其它键" |
| verify.sh 退出码 | `verify.sh` 末尾 | ✗ 计 FAILS 并 exit 2；· 记 UNKNOWNS 不阻断。**自动化只认 rc，人眼只认 ✓，两者必须同源** |
| 回归测试 | `verify/tests/` | 八个随 verify.sh 自动跑（troubleshoot/language/doc_index/reading_guide/reject_contract/triggers/docsync/skill_cards）+ 三个手动（test_verify_exit 会递归调 verify.sh 故不挂、test_node_parent 需真接口、rule_map_reverse 会改文件）；每个都做过"拆实现即翻红"的变异验证 |
| 每技能故障排查（症状索引） | 各技能 `docs/` 下的 `TROUBLESHOOTING.md` | 按症状排，≥5 条真实条目；`verify/tests/test_troubleshoot.py` 机检，占位符判红 |
| 密钥与卫生扫描 | `secret_scan.py` | 九类凭证 + 个人绝对路径 + 本地 endpoint + 模板真值 + 凭据文件三态 + **大文件闸（>10MB，git-as-DB 边界，工程纪律 §8）** |

---

## 六、明确不登记（有意例外，M7）

| 东西 | 为什么不登记 |
|---|---|
| 会话回执 / 交付报告（工作区根下的 `*.md`） | 过程产物，不是事实源；结论要沉淀就回写对应真源 |
| 云端资料库节点标题 | 可被用户随时改名，不能当判据 |
| 历史档案的卫生豁免（`HYGIENE_EXEMPT`） | 唯一真源 `secret_scan.py` 常量；只按**文件名模式**豁免且必须写理由，活文档不豁免；豁免数在扫描输出里可见 |
| 模型记忆 / 上会话上下文 | **不是事实**（B-06）；一切以仓内文件为准 |
| 旧仓 `tvbox-eco` 的文档 | 已随迁的部分在本仓有对应物；未随迁的在引用处已注明"旧仓内，未随迁" |

## 变更记录

- 2026-11-13 v0.8.31：技能描述「触发语义前置」（借 Memory Palace 的 must_use 契约 + 本会话实测「描述被截断成 120–250 字预览」）——9 个技能 description 首句改为「当用户说「…」时使用本技能」，5 个高频口语说法进前 80 字；新增 C9（前 40 字须有句式、前 80 字须命中 ≥3 触发词）与 C10（每条 T 样本须能在描述里找到非泛用词桥），8 用例变异回归 `verify/tests/test_trigger_frontload.py`；inspect-hub 去重（前置句与原句重复 4 词，惊门判黄）。
- 2026-11-13 v0.8.29：登记 sync.sh 一行收尾入口（借 908 换机说明的心智，实现走本仓正本）；machine-bootstrap v1.0.3 补「诚实边界」表并修手机通道语义过期（bbbe8a2 漏网第 6 处）。
- 2026-11-13 G6 轻量版：新增 `verify/linkage_notice.py`（pre-commit 真源联动提醒）+ 7 用例变异回归；registry.md 自此成为它的真源清单唯一来源（表格第 2 列、存在性过滤）。
- 2026-11-12 工程E：core-8 扩到 B-01…B-10（新增 B-10 拦截即停止）；新增 `verify/rule_map.json`（规则↔验证器映射，T4 双向核）；交付报告模板与派活模板进仓。
- 2026-11-12 建立：`verify/terminology_check.py` 首跑发现 core-8 M1 声称"登记表见 `docs/registry.md`"但本仓无此文件（悬空指针），按 M6 回真源建表。
