## v2.7.5 — database 正本全面迁移（520 v0.8.33，2026-11-13）
- 平台把 `database/` 层重构成 `db_create / db_query / db_edit / db_delete` 四件套，本技能 6 处旧调用全部失配（`get_database_schema` / `get_database_content` / `batch_add_database_records` / `add_database_field`）。新增适配层 `_db_call / _db_query / _db_add_records`：只做参数映射与状态行解析，写入仍 exec 正本
- **`_first_json_object` 修了一个会吞数据的 bug**：原实现 `json.loads(text[i:])` 把尾随的 `KS_USER_REPLY` 行算进去 → 解析失败 → 返回 `{}`。实测 `db_edit set-records` 的 `record_ids / add_count` 全丢，只剩一个成功标签。改 `json.JSONDecoder().raw_decode`
- 建库/补列/索引写入全部改走新正本；`_probe_empty_databases` 里的 `_run_lib('database/get_database_content.py')` 已删（间接入口，第一版引用检查器扫不到，现由 `lib_refs_check.py` 的 `_run_lib|api` 模式覆盖）
- 实证：`ensure --dry-run` → 认领 10 / 新建 7（schema 通路正常）；真实库写入 → 回读 1 条 → 删除 → 回读 0 条

## v2.7.4 — 建库正本迁移（520 v0.8.32，2026-11-13）
- 平台 library 把 `database/create_database.py` 重构为 `db_create.py`，字段键 `properties` → `fields`（`db_create.py:450` 读 `payload["fields"]`）；`_create_db_api` 改为新路径 + 键名适配，三处调用点继续传 properties 不用各改一遍
- 建库正本输出加了状态前缀（实测 `KS_DB_CREATE_OK\t{json}`），JSON 不在行首，旧的「逐行找 `{` 开头」解析漏掉 → 新增 `_first_json_object`（逐个 `{` 试解析到末尾）；不修会导致「库建成了但判失败」，进而每跑一次自举就多建一个空库
- 实证：`printf '{"title":"T","fields":[...]}' | db_create.py --stdin --dry-run` → `source: fields, property_count: 1`；`space_hub.py ensure --dry-run` → 原「将建」变「认领」
- 背景：全仓 8 类 library 引用失配（22 处），本次只修建库 1 类，其余见 `docs/遗留登记.md` + `verify/lib_refs_check.py`

## v2.7.3 — 触发语义前置（520 v0.8.31 工程K，2026-11-13）
- description 首句改为「当用户说「…」「…」时使用本技能」，把 5 个高频口语说法提到前 80 字内：平台只把描述编成截断预览给模型看，触发词写在尾巴上等于没写（C9 机检）
- 依赖项：`verify/skill_contract_check.py` 新增 C9 触发前置 / C10 样本词桥；`verify/tests/test_trigger_frontload.py` 8 用例变异回归

## v2.7.2 — cmd_add「回执≠回读」闭环（2026-11-13 空间重置实战）
- 幂等命中必须回读核实：登记册过期记录（收件箱夹被删后的旧记录）会被清掉放行重投，不再静默 return 0（实战：重投 49 项回执全"成功"、回读落地 0）
- 移动回执成功后回读收件箱一层：未落地按 readback_mismatch / rc=3 处理，对齐 cmd_move 既有口径；两种失败文案分开，不再把索引延迟误读成权限问题
- _nodes_or_none 补 offset 翻页：服务端单页实测上限 50，>单页容器漏读（顶层 130 项实测漏 81）；「失败→None」语义不变
- 回归测试 verify/tests/test_space_hub_add.py（16 断言）；三处变异（拆幂等回读/拆落地回读/拆翻页）各自精确翻红

# space-hub · 库务司 CHANGELOG

## v2.7.1 — 修 database 反查 + 删 render 死桩（工程G-2，2026-11-12）
- **修 `_node_parent`**：原实现只走全树遍历，对 `kind=database` 节点恒返回空串；调用方把空串当"不在收件箱"，于是「add 报成功 → 回读说不在箱」自相矛盾（投两个测试库时实测踩到，差点误判为移动失败去重试）。改为 node-info 的 `parentId` 优先、遍历兜底（`parentNodeId` 恒 None 不可信，`parentId` 是准的）
- **删 `render` 子命令**：空壳桩（只 print 一句、return 0 什么都不做），无任何调用方、文档也从未列它。保留假成功比报错更危险——调它的人会以为清单真重写了。现调 `render` 会明确报 invalid choice
- 命令数因此 19 → 18，与 SKILL 文档列出的 18 条完全对齐（景门集合比对可证）
- 回归：`verify/tests/test_node_parent.py` 6 组（parentId 优先 / 空值退回 / 异常退回 / 都查不到返空串 / 遍历异常不冒泡 / 真接口）

## v2.7.0 — 拒收结构化三元组 + 写前必读（工程E，2026-11-12）
机制借鉴 Memory Palace 的 guard 三元组（`{reason, target, method}`）与"写前必读目标"。

- **★ 拒收/失败统一结构化**：新增 `_reject(code, reason, target, method)`，`add`/`move`/`rename` 的
  护栏与失败路径全部接入。人读文案之后追加一行 `↳ {json}`；`SPACE_HUB_JSON=1` 时 stdout 只出 JSON。
  机器码：`force_requires_reason` / `inbox_missing` / `guard_nonempty_container` /
  `guard_container_like_name` / `node_unreadable` / `target_missing` / `target_not_folder` /
  `move_rejected` / `rename_rejected` / `empty_title` / `readback_mismatch`。
  **为什么**：调用方拿到的只有一句"🛑 拒收"时，唯一动作是换参数重试——而重试同一道闸正是
  core-8 B-10 禁止的。给 `target`（建议去哪）+ `method`（怎么去），动作才能从"猜"变成"按提示走"。
- **★ 铁律 +2 条**：第 11 条「写前必读」（写动作前回读目标父容器与目标节点，禁止拿旧清单标题下刀）、
  第 12 条「拦截即停止」（按 reason/target/method 决策，绕行必须 --force + --reason）。
- 实测：离线 mock 正反向 10 项全过（非空拒收 / 名字像库拒收 / 正常不误拦 / 移动失败带码）；
  变异测试（吞掉结构化输出）5 项翻红，恢复后 10 ✓。

## v2.6.1 — 触发样本集 + 文档断链修复（2026-11-12）
- 新增 `references/trigger-samples.md`：T10/N6/B5，T 组均带「预期第一动作」、N 组均带「应归谁」。B01 直接采用 2026-11-12 真实案例（01·数据源总库 名字带库但内容已移空，该不该 force 删）
- 样本强调三条现场教训：先 init 解析空间、AI 无删除权只投收件箱、unknown 不折叠成 fresh

## v2.6.0 — 数据保全四件套：快照/原子写/轮换/自愈 + 迁移锁 + force 审计（2026-11-12）

机制借鉴 Memory Palace（snapshot.py / write_lane / DB_MIGRATION_LOCK），逐条对应本日三次现场事故。

- **★ 写前快照（幂等）**：每次 save_state 前把"即将被覆盖的 state"拍进 `snapshots/`；
  同资源同进程只拍一次（MP 语义），改坏了有干净基线可回滚。
- **原子写**：state 落盘改 tmpfile+fsync+os.replace——半截写不可能落盘，
  杜绝"截断后恰好还能解析、没人知道少哪几条"的暗坑。
- **轮换 GC**：`snapshots/` 保留 KEEP=20（env `SPACE_HUB_SNAPSHOT_KEEP`，0=关），
  机会式触发；**当前进程刚拍的快照绝不碰**。
- **索引自愈**：`snapshots/index.json` 损坏时从快照文件自愈重建（数据本体不丢），
  重建必打日志——比"损坏即报错"（M-R60）更进一步的"可自愈"。
- **ensure 迁移锁**：flock 跨进程互斥，超时报结构化错误
  `{"error":"ensure_lock_timeout"}`——两会话并发自举不再撞出半成品蓝图。
- **--force 审计留痕**：`add --force` / `adopt --force` 必须配 `--reason`
  （参数校验放在一切云端调用之前），绕行动作写进 state `audit` 节（上限 50 条）。
  现场依据：01·数据源总库 force 放行无留痕案例。

## v2.5.0 — 账号接管 adopt（新账号建齐 / 老账号接住 / 别人空间不碰）（2026-11-12） — 账号接管 adopt（新账号建齐 / 老账号接住 / 别人空间不碰）（2026-11-12）

- **★ `adopt` 三态接管（本版核心）**：
  | 形态 | 判据（可实证） | 动作 |
  |---|---|---|
  | fresh | 顶层 0 节点 | 按蓝图建 17 单元（4 根 + 11 子夹 + 2 库） |
  | hybrid | 有生态指纹（`📦 产物归档` 或 present state.space_id 匹配） | 认领已有 + **登记存量**，不建不搬不删 |
  | foreign | 有节点但零指纹 | 拒绝（exit 3），要 `--force` |
  | unknown | 枚举失败（授权/网络） | 报"无法判定"（exit 2），**绝不折叠成 fresh** |

  `unknown ≠ fresh` 是关键：`_kids()` 失败返回 `[]`，和空空间长得一样，用它判形态会把
  授权失效误判成新账号，然后一次建 17 个单元全失败。故新增 `_nodes_or_none()`（失败返回 None）。
- **存量登记只登记、不搬运**：云端文档被网页/台账引用的是 node_id，一搬老账号既有链接全断。
  实测本账号 246 节点 → 认领 4 根 / 保留 6 个自有体系夹（01·数据源总库 等，原位不动）/
  登记 14 条历史（10 条给出建议落点、4 条标"未归类"）/ 跳过 13 个已标废弃（归 scan）。
  「落点路径」列**故意留空**——它还没被搬，写假路径就是骗人。
- **疑似两套体系只报不合**：`产物区` ≈ `📦 产物归档` 会在报告里点名（difflib 相似度 ≥0.5 且首字相同），
  合并不逆，交人决定。
- **索引类别改按节点类型**：原先往 select 写业务分类（报告与交付），9 个值里 8 个不在选项内，
  全部降级"其他"，类别列等于废掉（实测 14 条清一色"其他"）。改为 doc→文档 / web→面板 /
  database→数据 / 按扩展名 → 图片·数据·其他，业务分类移入「说明」。
- **`archive_out` 新增 `name` / `write_index` / `target`**：供学习成品用——主文档写索引、
  整包 zip 不写索引（一份成品只该有一条记录）、落点显式指定（成品目录名不含"学习"关键词，match 匹配不到）。
- **修 v2.4.0 潜伏缺陷**：`archive_out` 在"当天已自举"分支跳过空间解析，新进程里 `SPACE=None`，
  建夹时 subprocess 收到 None 抛 `TypeError`（栈指向 subprocess，极难反查）→ 归档全挂。
  现入口显式 `resolve_space`，`_create_folder` 加 None 守卫并说清原因。
- **doc 标题改用记录名**：主文档文件叫 `index.md`，按文件名建节点会在云端出现一堆叫「index」的文档。
- **`classify` 落点统一**：登记册 target 改为路径（`📦 产物归档/文档`），与 archive 共用 `_ensure_path`，
  不再在根层级建同名夹（此前两套体系并存，同一份文件两个入口归到两处）。

## v2.4.0 — 库房自举 + 生态演化台账 + 产出自动跟随（2026-11-12）

- **★ 库房自举 `ensure`（本版核心）**：`base_blueprint.json` 声明"该有什么"（📦 产物归档/<类别>、
  🧬 生态演化），各技能 `artifacts.json` 的 `blueprint` 分片可追加自己的根，清道夫合并后**收敛**：
  **认领已有（绝不重建/不删）、补建缺失、每步回读**。首次产出即建库，用户不用 init/create-db。
  边界：账号下**零可写空间**才自动 `create-space`；已有多个可写空间但未登记 → 报错让人选，不替人决定。
- **★ 产出自动跟随（能力层→资料库）**：新增 `archive_out(path, source, note)` 门面，
  能力层出口一行调用即完成"落库+写索引"；**永不抛异常**，失败本地保留 + 记 `local_pending`
  （kind=待归档），`products --retry` 一条命令补投。实测：livecheck → 「🔍 探源产出/测活报告」
  + 索引（来源/类别/日期/说明"1条/✅0 ❌0 ⚠️1 死因{…}"/落点路径）。
- **★ 归类由声明驱动**：`artifacts.json` 的 `match/target/category/source` 决定落点；
  未命中的产出落「📦 产物归档/未归类」并点名"某技能未声明"——**加技能即跟随，清道夫零改动**。
- **★ 生态演化台账**：固定分类「🧬 生态演化/版本演化台账」（版本/日期/类型/新增能力/变更摘要/证据），
  `evolve-log` 按技能快照做差集回答"这版增加了什么"，同版本+同快照去重；`install.sh` 收尾自动记账；
  `evolve-view` 出时间线。数据源全部可实证（VERSION / MANIFEST.changelog / 已装技能快照）。
- **实测修四坑**：① 索引日期写 `{"text":...}` 被静默丢弃（date 必须 oneof `{"date":...}`）；
  ② select 字段写 `{"text":...}` 同样静默丢 → 按 schema 类型写，类别不在选项时降级"其他"并把真类别写进说明；
  ③ `drive` 上传 `.md` 被拒（"该文件类型不走网盘"）→ 按类型分流（md→create_doc，其余→drive）；
  ④ `archive_log` 漏记 space_id、`products` 扫 `/workspace` 全盘把 50+ 无关文件算产物 → 收窄为"声明可识别"。
- **新增 `--note`**：archive/archive_out 可写入"批次/条数/结论"，索引"说明"列不再是空的。

## v2.3.0 — 生态投递门面接管 + 核库解耦（2026-11-12 · 架构重规划 A）

- **file_to_janitor 迁入本技能**（原 tvbox-core 中转壳删除）：投递目标就是本技能收件箱，
  门面与收件箱同文件——从结构上消灭「改名断链」（v0.8.1 修过一次的那类事故）。
  入参分流：真 node_id → 收件箱；本地路径 → 本地欠账；其他 → 拒收告警（S156 护栏保留）。
- **核库解耦**：`_probe_empty_databases` 不再 import 能力层 tvbox-core 的 `_run_lib`，
  改为直调 library 正门（依赖方向 通用层→平台，不再反向）。
- **对照组动态化**：硬编码对照组 id `Xjqn2Wf5…` 随空间重建失效（实测 permission denied），
  改为 显式入参 → `SPACE_HUB_CONTROL_DB` → `state.control_db` 三级解析；
  无有效对照时如实报「未配置对照组」并全项无法判定——**绝不把读不到当空库**。

## v2.2.0 — 产物纪律三件套：archive 落库正门 + products 盘点 + 搜索框（2026-11-12）

- **规则联动**：core-8 新增 B-09 产物纪律（产出默认不落产物区，点名例外，归宿=文本呈现或经本正门落库）。本技能是 B-09 的执行正门。
- **archive --file**：上传「📦 产物归档」根夹（幂等建夹）→ 写「📦 产物索引」库记录（名称/类别/日期/来源/说明，幂等建库）→ 本地清理（--keep 保留）。全步走 library 正门+写后回读；实测修两坑：KS 行空格分隔解析、新建节点目录索引传播延迟（S200 同款带间隔重试）。
- **products --scan / --search-box**：盘点已落库+本地产物区现存（只打印不落盘）；搜索框=单文件 HTML 内嵌索引，零依赖。
- **顺手修**：_find_parent 残留 ROOT（v2.0.0 漏改）→ NameError，add 在记录原父位即崩、节点从未移动——今日实测投递现场踩到，改遍历 ROOTS。

## v2.1.0 — 本地欠账登记 + learn-hub 门面改道（2026-11-12）

- **auto_file_local(path, reason)**：本地欠账登记入口——本地文件系统里"删不决"的残留（如 learn-hub intake 半成品）记入 state 的 local_pending，不碰云端、不占收件箱。实证背景：learn-hub 旧门面把本地路径投进云端通道 file_to_janitor，被 S156 node_id 护栏拒收，投递从未成功（名义联动）。
- **list 出单**：本地欠账单独成节（云端项的陈旧剔除逻辑会误剔本地路径，不可混）。
- **local-rm 子命令**：--path 前缀销账 / --all 全清；未命中拒绝销账（exit 2，不销不存在的账）；纯本地命令不再强制空间解析。
- **classify_rules**：+「学习与资料」类（学习工坊/学习资料/课程/读书/阅读/笔记 → 归档·学习资料），learn-hub 产业认主。

## v2.0.0 — 去 TVBox 化升级：清理+归纳+整理+建库（2026-11-12）

由 tvbox-janitor 清道夫 v1.2.12 升级而来，业务无关化并大扩容：

- **改名**：tvbox-janitor → space-hub（库务司），入 520 通用层（与 learn-hub 平级）。
- **空间解析四层**（本版核心）：废除写死 space id——旧 ID 8w5cnq… 随空间重建
  role=invalid 致整链瘫痪（实测教训）。换账号 = 跑 `init` 一次。
- **新增 `init`**：--list / --space-id / --title 登记，校验必须在可访问列表内。
- **新增 `classify` 归纳**：根层级散落文档按 classify_rules.json（登记册唯一真源）
  归入目标夹；dry-run 预览、--yes 执行、建夹走正门+回读、失败组保持原位。
- **新增 `create-db` 建库**：薄封装 library/database/create_database.py 正本
  （stdin 传参）+ 父容器回读。schema 用正本原生列表格式；select 须非空 options。
- **修正坐标**：扫描根改空间根（旧超根 gZ4x… 已随旧空间消亡）。
- **测试实录**（全部真跑）：scan --dry-run 16 候选 7 重复组处置正确；
  建库端到端真建 2 个测试库（jNcVYb…/WEDPaX…）回读确认；标题双义护栏
  正确把"测试库"标为须人工裁决而非自动投递。

## v1.2.12 — 清道夫终点（旧仓 DmaxPro908）

待删收件箱、scan 发现即投、dedup 护栏、restore 回退、census 普查。
