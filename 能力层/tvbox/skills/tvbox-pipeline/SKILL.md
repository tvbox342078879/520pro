---
name: tvbox-pipeline
description: >-
  TVBox 出品流水线（整包加工 + 配置同步两入口）。A 入口：手上有在线接口地址或本地包（.json/.txt/.m3u），
version: "1.0.0"
  要把它做成可用 json 并入库——体系识别→拆分→全量去重→全量测活→纯可用版→入库登记。
  B 入口：要更新主配置（搜集配置仓库→并发测活→把存活源集成回主配置）。
  触发词：这个接口做个json / 接口发你了 / 把这个包做成能用的 / 处理一下这个接口 / 这个地址能用吗 /
  帮我做个能用的包 / 这个配置能用吗 / 发来一个接口URL / 在线接口 / 配置地址 / 底包 / lives / 直播源 /
  接口入库 / 本地包 / py线 / 采集 / 解析 / 去重 / 拆分 / 入库 / 测活 / 可用版 / 体系识别 / jar系 / 直链系 /
  更新TVBox配置 / 更新订阅 / 测活线路 / 站点源 / 配置源 / 电视盒子。
---

# TVBox 出品流水线（tvbox-pipeline）

> 一条技能，两个入口。**判入口只看一件事：手上有没有源。**
> - 有源（接口 URL / 本地包）→ **A 入口·整包加工**，细则见 [`SOP_整包加工.md`](SOP_整包加工.md)
> - 没源，要更新主配置 → **B 入口·配置同步**
> - 连源都没有，要去上游找 → 走 `probe-hub`（探源司），不归本技能

---

## 0. 入口判据

| 用户说 | 入口 | 动作 |
|---|---|---|
| "这个接口做个 json"／"发你个包"／"这个地址能用吗" | **A** | 读 SOP 全流程 |
| "更新 TVBox 配置"／"测活一下线路"／"订阅源该换了" | **B** | 跑三脚本 |
| "帮我找点源"／"哪个仓库还有源" | 不归这里 | 转 `probe-hub` |

---

## A 入口 · 整包加工

**铁律顺序（不许跳步、不许换序）**：

```
体系识别 → 拆分 → 全量去重 → 全量测活 → 纯可用版 → 入库登记
```

收到 json 的**第一个动作是体系识别**（决定成品名 `<体系><日期>_<站数>站`），不是先抓取。

完整流程、四类站点线拆法、相对地址转绝对、采集/直链分开归档、18+ 隔离、入库登记表 —— 全在
**[`SOP_整包加工.md`](SOP_整包加工.md)**，进 A 入口必读，不要凭记忆做。

细则拆分在 `docs/manual_*.md`，SOP 里逐条标了正本位置（M-R38：同一判据只写一份，别抄）。

## B 入口 · 配置同步

```bash
# 脚本位置：用户级优先，回退项目级
if [ -d "$HOME/.codebuddy/scripts" ]; then SCRIPT_DIR="$HOME/.codebuddy/scripts"; else SCRIPT_DIR=".codebuddy/scripts"; fi

python3 "$SCRIPT_DIR/collect_repos.py"                # ① 拉仓库、抽源 → sources.json
python3 "$SCRIPT_DIR/check_live.py" sources.json      # ② 并发测活 → live_result.json
python3 "$SCRIPT_DIR/merge_config.py"                 # ③ 过滤失效源 → master_config.new.json
```

汇报格式：`存活 N / 失效 M → master_config.new.json`，**不堆过程日志**。

- 主配置不存在时先 `cp "$HOME/.codebuddy/tvbox/master_config.example.json" master_config.json`
- 测活**必须走并发脚本**，禁止手动逐条 curl
- 改仓库清单：`collect_repos.py` 顶部 `REPOS`
- 重活可派 `tvbox-agent` 子代理执行，避免主会话被日志刷屏

---

## 1. 共享核心（别自己实现）

本技能的测活判据、去重、分类，全部来自 `tvbox-core`：

| 能力 | 位置 |
|---|---|
| 测活判定码 `ALIVE_CODES` / `_alive` | `tvbox-core/scripts/pipeline.py` |
| 体系分类 `classify_line` | 同上 |
| 库坐标 `SRC_DBS` / `dest_db()` | `tvbox-core/scripts/core.py` |
| 拉黑第一道闸 `guard` | `tvbox-core/scripts/blk.py` |

> `tvbox-core` 是**纯代码库，没有 SKILL.md，不会被路由**。它只被 import，不要试图"调用"它。

## 2. 交付前自检

1. 体系识别结论写了吗（不能只写"已识别"）
2. 去重跑了吗（按内容哈希，不是按名字）
3. 测活是全量还是抽样？抽样必须标注
4. 入库登记表填了吗
5. 有源失效时，是"真失效"还是"无法判定"？（三态不许折叠）

## 3. 边界

- **不做**：找源、监测仓库、写新源 → `probe-hub`
- **不做**：判断某域名该不该永久拉黑 → `tvbox-core` 的拉黑判据
- **不做**：改动 `tvbox-core` 里的判据常量（那是单一事实源，改了全生态跟着变）

## 4. 无法判定时

脚本报错 / 超时 / 无输出 → 记「无法判定」，报清楚卡在哪一步，不臆造"成功"。
