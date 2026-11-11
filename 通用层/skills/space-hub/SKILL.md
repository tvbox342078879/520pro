---
version: "2.0.0"
name: space-hub
description: "库务司·云端资料库总管（可升级）。清理+归纳+整理+建库+搬运正门，管任意 WorkBuddy 云端空间的节点。能力：①垃圾扫描 scan（废弃标记/空库识别→自动投收件箱，--dry-run 预览）；②待删收件箱 inbox/add（AI 无删除权，只挪不删，用户按单删）；③归纳 classify（根层级散落文档按登记册规则归入目标夹，规则只改 classify_rules.json 零改代码）；④建库 create-db（薄封装 library 建库正本+写后回读）；⑤搬运/改名正门 move/rename（移前双校验+移后回读，全生态唯一通道）；⑥误投回退 restore；⑦分层普查 census；⑧四层空间解析（不写死账号，换账号跑 init 一次即适配）。触发词：清理 / 归纳 / 整理 / 归类 / 收纳 / 建库 / 建个库 / 新建数据库 / 删不掉 / 清一下 / 待删的放哪 / 收件箱 / 库务司 / 搬节点 / 节点搬家 / 改名 / 待删清单 / 冗余节点 / 重复节点 / 库房整理 / 换账号空间 / 空间登记 / 盘点空间 / 空间普查。"
---

# space-hub · 库务司（清理 + 归纳 + 整理 + 建库）

> **🗣 语言铁律**：本技能所有输出一律简体中文。
> **身世**：前身为 TVBox 生态 tvbox-janitor 清道夫（v1.2.12），v2.0.0 去业务化升级为通用库务能力。

## 0. 定位与边界

- **为什么存在**：WorkBuddy 云端库无删除 API，AI 删不掉节点 → 挪进收件箱+生成清单，**删除永远由用户手动**。
- **管什么**：任意空间（不只 TVBox）的节点——清理垃圾、归纳散落文档、建库、搬运/改名。
- **不管什么**：不删除任何节点；批量写记录走 library 正本（`database/batch_add_database_records.py`）；普通文件夹建立走同一 `manage/create_folder.py` 正门。

## 1. ★ 空间解析四层（v2.0.0 核心，禁止写死 space id）

```
① 显式 --space-id / 环境变量 SPACE_HUB_SPACE_ID
② space_hub_state.json 登记值（init 写入）
③ 动态发现：list-user-spaces 按标题匹配且 role∈{owner,admin}
④ 显式报错并列出全部可用空间，提示跑 init——绝不猜、不静默用错空间
```

**换账号 / 空间重建后的第一条命令**：

```bash
python3 space_hub.py init --list                 # 看当前账号有哪些空间
python3 space_hub.py init --space-id <ID>        # 登记（校验必须在可访问列表内）
python3 space_hub.py init --title "TVBox 生态空间"  # 或按标题登记
```

## 2. 命令（引擎 `scripts/space_hub.py`）

```bash
python3 space_hub.py init --list|--space-id <ID>|--title "<标题>"  # 空间登记/查看
python3 space_hub.py inbox                        # 建/确认收件箱（幂等）
python3 space_hub.py add --node ID [--reason R]   # 单节点投收件箱（移前记原位，可 restore）
python3 space_hub.py scan [--dry-run] [--dedup N] # 全局扫垃圾，命中即投；dry-run 仅预览
python3 space_hub.py list [--no-verify]           # 生成待删清单 md+csv（/workspace/待删清单_日期）
python3 space_hub.py classify [--dry-run] [--yes] # ★归纳：根层级散落文档按登记册归入目标夹
python3 space_hub.py create-db --schema-file <f.json> --yes  # ★建库（薄封装+写后回读）
python3 space_hub.py restore --node ID [--target 父ID]  # 误投回退（一键移回原位）
python3 space_hub.py move --node ID --to 父ID     # 节点移动正门（双校验+回读）
python3 space_hub.py rename --node ID --title "新名"  # 改名正门（改后回读）
python3 space_hub.py census [--json]              # 分层普查（归属/缝统计）
```

## 3. 归纳登记册（classify_rules.json，唯一真源）

```json
{"rules": [
  {"category": "报告与交付", "match": ["报告","交付","完工"], "target": "归档·报告与交付"}
]}
```

- **加/改分类规则只改本文件，零改代码**（对齐监测登记册模式）。
- 命中废弃标记（KW：废弃/作废/测试/重复/旧版/待删…）的节点**归 scan 管辖**，classify 永不抢。
- classify 执行必须 `--yes`；目标夹不存在会自动建（走 create_folder 正门 + 回读）；建失败的组**保持原位**（不漏项）。

## 4. 建库（create-db）

schema 为**正本原生格式**（不自造）：

```json
{"title": "库名",
 "properties": [
   {"name": "名称", "config": {"text": ""}},
   {"name": "状态", "config": {"select": {"options": [{"text": "进行中"}]}}}
 ]}
```

- 类型白名单：text/number/currency/select/multi_select/date/checkbox/url/email/phone_number/image/attachment/person（`select` 须非空 options）。
- 纪律：API 返回成功≠建成——**必须回读**（父容器枚举确认 id 在列，S169 教训）。
- 字段类型白名单/格式以 `library/database/_db_types.py` 为唯一真源。

## 5. 铁律（继承清道夫 9 条 + 空间解析纪律）

1. **只移动、不删除**：AI 无删除权，绝不假装删除。
2. **不漏项**：节点不存在/移动失败 → 显式告警，清单仍保留该行标"未移动"。
3. **幂等**：同 node_id 重复 add 不重复登记。
4. **状态损坏不折叠**（M-R60）：state json 损坏 → 显式报错退出，不当"空收件箱"。
5. **原因必填**：每项写清为什么该删，用户删前能核实。
6. **全局覆盖**：scan 从空间根（`--parent-node-id ""`）递归全空间；排除收件箱自身。
7. **发现即投**：scan 命中垃圾直接自动投递；`--dry-run` 仅用于预览核查。
8. **重复仅告警**：同父同名 ≤2 份视为正常留档；>2 份多余副本 `--dedup N` 才投。
9. **误投可回退**：add 移动前记录 origin_parent，restore 一键移回。
10. **空间解析失败即退出**：绝不带错坐标干活；写动作（classify/create-db/add）一律显式 `--yes`。

### 垃圾判定（scan）要点

| 类别 | 判定 | 处置 |
|---|---|---|
| 废弃标记 | 标题命中 KW（不含"库/总库/归档"等正常词，防误伤） | 自动投递 |
| 空文件夹 | 附件不占目录树，`0 子节点`不具备判空能力 | 标"无法判定"交人工（M-R125） |
| 空数据库 | 记录为 0 | 自动投递 |
| 重复节点 | 同父同名 | 仅告警；`--dedup N` 投多余副本 |
| 标题双义 | 同时含废弃词+容器词（如"测试库"） | **不投**，须人工裁决 |

## 6. 与其他技能的联动

- **probe-hub / learn-hub**：上游技能发现"该删但删不掉"的节点 → `add` 投收件箱（一行代码，见旧版联动契约）。
- **library**：本技能是其 space API 的上层闸门；建夹/建库/写记录全走 library 正本，不重写。
- **verify.sh**：检查本脚本存在、可编译、无写死 space id。

## 7. 升级契约

version 字段 + 本文件 + CHANGELOG.md 三件套；改命令/判据必须记 CHANGELOG。
