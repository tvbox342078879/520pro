# space-hub · 库务司 CHANGELOG

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
