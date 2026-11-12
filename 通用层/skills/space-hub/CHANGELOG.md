# space-hub · 库务司 CHANGELOG

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
