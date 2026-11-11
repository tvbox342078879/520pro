# CODEBUDDY.md（520pro · TVBox 薄壳）

> 本文件部署到「目标项目」的 `.codebuddy/CODEBUDDY.md`，是**唯一被实测证明"必被注入"**的通道。
> 因此把 TVBox 的**触发词 + 执行链路**直接内联——**即使技能没路由、条件规则没注入，这一层也兜得住**。
> 通用 8 条铁律真源在用户级 `~/.codebuddy/rules/core-8.md`（B-01~B-08）；本文件只保留"无条件三条"。
> 注：若用 `--user-skill` 模式（TVBox 装用户级），本薄壳可不在项目里；此时靠技能 description 路由。

---

## 一、无条件三条（不依赖用户级是否同步到本机）

- **语言**：跟随用户消息语言（中文 → 全程简体中文，术语可保留英文原词）；换模型 / 压缩 / 新会话 / 恢复会话都不得回退英文。
- **三态诚实**：输出只判 真阳性 / 真阴性 / 无法判定；报错、超时、无输出、被拦截一律记"无法判定"，"没查到" ≠ "没有"。
- **先验开工**：动手前先 `pwd -P` + `git log --oneline -1`，确认真实环境，不凭记忆假定目录。

---

## 二、TVBox 能力 · 触发词即路由（内联兜底）

**当用户提到**：`TVBox`、`电视盒子`、`测活`、`直播源`、`站点源`、`配置源`、`线路`、`订阅源`、`更新tvbox配置`、`/tvbox-sync`
**→ 立即执行三步链路，不要手动逐条 curl、不要手动改 JSON。**

先定位脚本目录（用户级优先，回退项目级）：
```bash
if [ -d "$HOME/.codebuddy/scripts" ]; then SCRIPT_DIR="$HOME/.codebuddy/scripts"; else SCRIPT_DIR=".codebuddy/scripts"; fi
```

| 步 | 命令 | 产出 |
|---|---|---|
| 1 | `python3 "$SCRIPT_DIR/collect_repos.py"` | `sources.json` |
| 2 | `python3 "$SCRIPT_DIR/check_live.py" sources.json` | `live_result.json` |
| 3 | `python3 "$SCRIPT_DIR/merge_config.py"` | `master_config.new.json` |

汇报：`存活 N / 失效 M → master_config.new.json`，**输出精简**。
> 步骤多时可派 `tvbox-agent` **子代理**执行，隔离日志、不污染主会话。

---

## 三、能力清单

| 组件 | 用户级路径（--user-skill） | 项目级路径（--capability-only） | 作用 |
|---|---|---|---|
| 技能 | `~/.codebuddy/skills/tvbox-config-sync/` | `.codebuddy/skills/tvbox-config-sync/` | 流程编排（用户级可被平台路由） |
| 工人 | `~/.codebuddy/agents/tvbox-agent.md` | `.codebuddy/agents/` | 隔离执行 |
| 命令 | `~/.codebuddy/commands/tvbox-sync.md` | `.codebuddy/commands/` | `/tvbox-sync` |
| 脚本 | `~/.codebuddy/scripts/` | `.codebuddy/scripts/` | 收集→测活→集成 |
| 规则 | （不全局注入） | `.codebuddy/rules/tvbox-style.md` 等 | 项目纪律 |
| 配置 | `~/.codebuddy/tvbox/master_config.example.json` | `.codebuddy/tvbox/` | 主配置模板 |

---

## 四、使用前必改两处

1. **登记配置仓库**：编辑 `collect_repos.py` 顶部 `REPOS`，把 `xxx/yyy` 换成你的真实仓库地址。
2. **准备主配置**：`cp <example> master_config.json`，填入你的站点源 / 直播源。

> 改完规则 / 新装能力后，**开新会话**才生效。手机端按 `手机指令.md` 手动粘规则。
