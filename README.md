# 520pro

> **把「平台硬机制」接到「可移植业务」上。**
> 规则：平台账号指令（硬·跨设备）+ `core-8.md`（本地兜底）双轨；
> 能力：TVBox 升级为**用户级技能**（平台注册可路由、跨项目、云端沙箱执行、手机登录同账号可触发）；
> 真源：GitHub + 资料库，沙箱只当执行窗口。

---

## 一、核心升级（相对 `新生态`）

| 项 | 新生态（旧） | **520pro（新）** |
|---|---|---|
| TVBox 技能位置 | 项目级 `.codebuddy/skills/`（**不路由**） | **用户级 `~/.codebuddy/skills/`（平台注册、可路由）** |
| TVBox 脚本位置 | 项目内，手机跑不了 | **用户级 `~/.codebuddy/scripts/` + 云端沙箱执行** → 手机也能触发 |
| 规则 | 仅本地 `core-8.md`（软） | **双轨**：平台账号指令（硬·跨设备）+ `core-8.md`（兜底） |
| 重活 | 主会话硬跑 | **派 `tvbox-agent` 子代理**，隔离上下文 |
| 部署脚本 | 只有项目级 | **新增 `--user-skill` 模式** |

> 一句话：**病根是"放错层"。项目级技能不注册、不路由；用户级技能被平台注册、能路由。520pro 把 TVBox 挪到用户级，路由/跨设备/手机问题一次解决。**

---

## 二、结构

```
520pro/
├── 通用层/                          →  ~/.codebuddy/
│   ├── rules/core-8.md              →  ~/.codebuddy/rules/（8 铁律）
│   └── skills/{skill-evolution,feature-gate,machine-bootstrap,artifact-store}
├── 能力层/tvbox/                    →  用户级 或 项目级（按模式）
│   ├── skills/tvbox-config-sync/    →  ~/.codebuddy/skills/（★用户级可路由）
│   ├── agents/tvbox-agent.md        →  ~/.codebuddy/agents/
│   ├── commands/tvbox-sync.md       →  ~/.codebuddy/commands/
│   ├── scripts/{collect,check,merge}.py → ~/.codebuddy/scripts/
│   ├── CODEBUDDY.md                 （项目级薄壳，兜底用）
│   ├── rules/{tvbox-style.md, tvbox.paths.md}
│   └── master_config.example.json
├── install.sh                       四种模式（见下）
├── verify.sh                        安装自检
├── 手机指令.md                      第三通道（手动粘贴）
├── TEST.md                         测试清单（含路由实测）
├── MANIFEST.json                   机读分层 + 融合映射 + 可靠性
└── docs/{融合架构.md, 分层落地表.md, 加载机制与可靠性.md}
```

---

## 三、部署（选模式）

```bash
# ★ 推荐：融合模式 —— 通用层 + TVBox 全装用户级（可路由、跨项目、手机可触发）
bash install.sh --user-skill

# 项目隔离模式 —— TVBox 只装进某个项目
bash install.sh --capability-only --target /path/to/项目

# 只装通用规则
bash install.sh --generic-only

# 先看要做什么
bash install.sh --user-skill --dry-run

# 装完自检
bash verify.sh
```

装完**开新会话**（规则/技能只在会话启动加载），按 `TEST.md` 验证。

---

## 四、规则双轨（这是"借平台硬机制"的关键）

| 轨道 | 放哪 | 作用 | 可靠性 |
|---|---|---|---|
| **硬轨** | 平台「账号指令 / 给 WorkBuddy 的指令」 | 8 铁律，跨设备必注入 | ✅ 平台强注入 |
| **软轨** | `~/.codebuddy/rules/core-8.md` | 本地兜底，换设备不丢 | 🟡 原生常驻 |

> 把 `手机指令.md` 的粘贴区同时放进**桌面与手机的账号指令**，就是硬轨；`core-8.md` 是软轨双保险。

---

## 五、可靠性（三态，诚实标注）

| 机制 | 结论 | 依据 |
|---|---|---|
| 用户级技能路由 | ✅ 可用 | 本环境 `~/.codebuddy/skills/` 的技能均在 active 列表（可路由） |
| `CODEBUDDY.md` 薄壳注入 | ✅ 真阳性 | 368817 报告：仅 CODEBUDDY.md 被注入 |
| 用户级 `core-8.md` | 🟡 一次真阳性 | 手机端历史真阴性 → 故走双轨 |
| 条件规则 `paths` | ❌ 不注入 | 实测未注入，仅作示例 |
| 项目级技能路由 | ❌ 不路由 | 368817 `L2.skill` |
| 用户级技能**跨设备到新手机** | ❓ 无法判定 | 需实测（新手机说"更新TVBox配置"看是否触发） |

---

## 六、素材与边界

- 通用层（core-8 / 4 技能）取自 368817 去 TVBox 化版本，原样保留。
- 能力层取自 368817 仓根 `.codebuddy/` 存活的 TVBox 件（tvbox-config-sync / tvbox-agent / /tvbox-sync / 3 脚本 / 配置模板）。
- **旧探源司 / 换机司已随 tvbox-eco 404 丢失**，本仓没有它们；本仓 TVBox = 「配置同步（搜集→测活→集成）」。

---

## 七、口令

- 更新配置：`/tvbox-sync all` 或「帮我更新 TVBox 配置」
- 测活：`python3 "$SCRIPT_DIR/check_live.py" sources.json`
- 集成：`python3 "$SCRIPT_DIR/merge_config.py"`
- 必改：`collect_repos.py` 顶部 `REPOS`；项目根 `master_config.json`
