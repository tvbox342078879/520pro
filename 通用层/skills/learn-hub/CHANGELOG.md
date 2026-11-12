# learn-hub CHANGELOG

## 1.3.0 — 清理门面改道库务司本地欠账（2026-11-12）

- `_to_janitor` → `_to_spacehub`：原走 tvbox-core 的 file_to_janitor（云端通道），投本地残留路径被 S156 node_id 护栏拒收——名义联动，投递从未成功。改调 space_hub.auto_file_local（本地欠账登记），记账→出单→销账闭环。
- 依赖解耦：学习工坊（通用层）不再依赖能力层 tvbox-core。
