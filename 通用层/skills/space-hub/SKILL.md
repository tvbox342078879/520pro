---
version: "2.7.1"
name: space-hub
description: "库务司·云端资料库总管（可升级）。清理+归纳+整理+建库+搬运正门，管任意 WorkBuddy 云端空间的节点。能力：①垃圾扫描 scan（废弃标记/空库识别→自动投收件箱，--dry-run 预览）；②待删收件箱 inbox/add（AI 无删除权，只挪不删，用户按单删）；③归纳 classify（根层级散落文档按登记册规则归入目标夹，规则只改 classify_rules.json 零改代码）；④建库 create-db（薄封装 library 建库正本+写后回读）；⑤搬运/改名正门 move/rename（移前双校验+移后回读，全生态唯一通道）；⑥误投回退 restore；⑦分层普查 census；⑧四层空间解析（不写死账号，换账号跑 init 一次即适配）；⑨★库房自举 ensure（按蓝图收敛：认领已有+补建缺失，新机首次产出即自动建齐）；⑩★产出自动跟随 archive_out＋演化台账 evolve-log（能力层产出自动进资料库并归类）；⑪★账号接管 adopt（新账号按蓝图建齐 / 老账号认领并存量登记 / 别人空间拒绝）。触发词：清理 / 归纳 / 整理 / 归类 / 收纳 / 建库 / 建个库 / 新建数据库 / 删不掉 / 清一下 / 待删的放哪 / 收件箱 / 库务司 / 搬节点 / 节点搬家 / 改名 / 待删清单 / 冗余节点 / 重复节点 / 库房整理 / 换账号空间 / 空间登记 / 盘点空间 / 空间普查。不要用于：源码/规则/技能文件的编辑（git 真源，走 git 正门）；不要用于本地文件删除与瘦身（归 artifact-store）；不要用于替用户执行云端删除（AI 无删除权，只投待删收件箱+出清单）；不要主动写入别人空间（adopt 会拒绝，写前先确认空间归属）。"
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
python3 space_hub.py list [--no-verify]           # 生成待删清单 md+csv（<工作区>/待删清单_日期）
python3 space_hub.py classify [--dry-run] [--yes] # ★归纳：根层级散落文档按登记册归入目标夹
python3 space_hub.py create-db --schema-file <f.json> --yes  # ★建库（薄封装+写后回读）
python3 space_hub.py restore --node ID [--target 父ID]  # 误投回退（一键移回原位）
python3 space_hub.py move --node ID --to 父ID     # 节点移动正门（双校验+回读）
python3 space_hub.py rename --node ID --title "新名"  # 改名正门（改后回读）
python3 space_hub.py census [--json]              # 分层普查（归属/缝统计）
python3 space_hub.py local-rm --path <前缀>|--all # ★销账：本地欠账已人工处置，从清单移除
python3 space_hub.py archive --file <f> [--category 类] [--source 来源] [--note 说明] [--keep]  # ★落库正门：按声明归类+写索引+本地清理
python3 space_hub.py products --scan|--search-box|--retry  # ★盘点/搜索框/待归档补投
python3 space_hub.py adopt [--dry-run] [--force]    # ★账号接管：判 fresh/hybrid/foreign → 建齐 或 接管存量（登记不搬）
python3 space_hub.py ensure [--dry-run]            # ★库房自举：按蓝图收敛（认领已有+补建缺失），幂等
python3 space_hub.py evolve-log [--version V] [--summary S] [--evidence E]  # ★演化记账（版本/新增能力/摘要/证据）
python3 space_hub.py evolve-view [--md]            # ★演化时间线
```

> **产物纪律（v2.2.0 · 规则真源 core-8 B-09）**：产出默认不落产物区，除非用户点名。需留档的走 `archive` 正门（上传归档夹+写「📦 产物索引」库五字段记录+本地清理，全步回读）；`products --scan` 盘点、`--search-box` 生成搜索框。交互型面板（必须落盘才能预览）属点名例外。
> **拒收契约（v2.7.0 · B-10 执行面）**：`add`/`move`/`rename` 被拒时除人读文案外，还会输出一行 `↳ {"error","reason","target","method"}`——`error` 是机器码（如 `guard_nonempty_container` / `guard_container_like_name` / `target_not_folder` / `readback_mismatch`），`target` 是**建议下一步**、`method` 是可直接跑的命令模板。上层技能按 `error` 分支，**不要**按文案做字符串匹配。程序调用可设 `SPACE_HUB_JSON=1`：stdout 只出一行 JSON，人读文案转 stderr。
> **本地欠账（v2.1.0）**：本地文件系统里"删不决"的残留，其他技能经 `auto_file_local(path, reason)` 记账（不碰云端）；`list` 出单时单独成节（云端项的陈旧剔除会误剔本地路径），用户按单处置后 `local-rm` 销账。

## 2.5 ★ 库房自举与产出跟随（v2.4.0）

**问题**：生态要分发给别人。别人没有我的资产，云端一个库都没有；让他先 init 再 create-db 不现实——
他根本不知道库务司存在。**正确形态：能力层第一次产出时，库已经在。**

### 自举（ensure）：按蓝图收敛，不是"一次建库"

| 层 | 真源 | 作用 |
|---|---|---|
| 基础蓝图 | `base_blueprint.json`（随技能分发） | 声明必有结构：📦 产物归档/<类别>、🧬 生态演化 |
| 能力分片 | 各技能 `artifacts.json` 的 `blueprint` | 追加自己的根（如 🔍 探源产出、📚 学习资料） |
| 收敛 | `ensure` | **认领已有（不重建/不删）→ 补建缺失 → 每步回读**，幂等 |

- 空间：四层解析；**仅当账号下零可写空间**才自动 `create-space`；有多个但未登记 → 报错让人选。
- 已存在同名夹一律认领，绝不重建；空夹（0 子节点）不可信（S179），不删不并。
- 能力层分片里的 `match/target/category/source` 决定产出落点；没声明的落「📦 产物归档/未归类」并点名提示。

### 产出跟随（archive_out）：能力层出口一行调用

```python
import space_hub                      # ~/.codebuddy/skills/space-hub/scripts
ok, info = space_hub.archive_out(report_path, source='探源司·测活', note='12条/✅9 ❌2 ⚠️1')
```

- **永不抛异常**：失败 → 本地文件保留 + `local_pending(kind=待归档)`，`products --retry` 补投。
- 落库=上传到声明落点 + 写「📦 产物索引」（名称/类别/日期/来源/说明/落点路径）+ 回读确认。
- md 走 `doc/create_doc`，其余走 `drive`（实测 drive 拒收 .md）；类别不在 select 选项时降级"其他"并保留真类别。

### 账号接管（adopt）：一个入口对付三种账号

| 形态 | 判据（可实证） | 动作 |
|---|---|---|
| **fresh** 新账号 | 顶层 0 节点 | 按蓝图建 17 单元（4 根 + 11 子夹 + 2 库） |
| **hybrid** 老账号 | 有生态指纹（`📦 产物归档` 或 present state.space_id 匹配） | 认领已有 + **登记存量**（不建不搬不删） |
| **foreign** 别人空间 | 有节点但零指纹 | 拒绝（exit 3），确认要接管才加 `--force` |
| **unknown** | 枚举失败（授权/网络） | 报"无法判定"（exit 2），**绝不折叠成 fresh** |

**为什么 unknown 不能当 fresh**：`_kids()` 失败返回 `[]`，和空空间长得一样。用它判形态，授权失效
就会被当成新账号，然后一次建 17 个单元全失败，报一堆看不懂的错。故判定走 `_nodes_or_none()`
（失败返回 None），`unknown` 直接停手。

**存量只登记不搬运**：云端文档被网页/台账引用的是 `node_id`，一搬老账号里的既有链接全断。
所以「归位」只写进索引的说明列（建议落点），物理移动交给用户显式 `classify --yes`。
实测本账号：246 节点 → 认领 4 根 / 保留 6 个自有体系夹 / 登记 14 条历史 / 跳过 13 个已标废弃。

**疑似两套体系只报不合**：`产物区` ≈ `📦 产物归档` 会在报告里点名——合并不可逆，交人定。

### 生态演化（evolve-log）

固定分类「🧬 生态演化/版本演化台账」：版本/日期/类型/新增能力/变更摘要/证据。
`install.sh` 收尾自动记账；新增能力由**已装技能快照差集**得出，同版本+同快照去重。

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

## 5. 铁律（继承清道夫 9 条 + 空间解析 + 写前必读）

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
11. **写前必读（v2.7.0 · B-10 配套）**：任何写动作（`add`/`move`/`rename`/`restore`/`classify`）动手前，必须**回读目标父容器与目标节点**（标题 / `kind` / 子节点数）确认现状；读不到就不动。**禁止拿会话记忆、旧清单或上一次的标题直接下刀**——清单里的标题是下单时的快照，节点可能已被改名/移动/清空。
12. **拦截即停止（B-10）**：被护栏拦下时按它给的 `reason`/`target`/`method` 决定下一步，不换写法硬试同一道闸；确要绕行必须 `--force` + `--reason`，留审计。

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
