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
│   └── skills/{skill-evolution,feature-gate,machine-bootstrap,artifact-store,learn-hub,space-hub}
├── 能力层/tvbox/                    →  用户级 或 项目级（按模式）
│   ├── skills/
│   │   ├── probe-hub/               →  技能①探源司（monitor/search/harvest/forge/shellcrack，1.6M）
│   │   ├── tvbox-pipeline/          →  技能②出品流水线（整包加工 + 配置同步）
│   │   └── tvbox-core/              →  ★共享代码库（core/link/pipeline/blk，**无 SKILL.md·不路由**）
│   ├── agents/tvbox-agent.md        →  ~/.codebuddy/agents/
│   ├── commands/tvbox-sync.md       →  ~/.codebuddy/commands/
│   ├── scripts/{collect,check,merge}.py → ~/.codebuddy/scripts/
│   ├── fix_paths.py                 路径适配（/root/.codebuddy → ~/.codebuddy）
│   ├── CODEBUDDY.md                 （项目级薄壳，兜底用）
│   ├── rules/{tvbox-style.md, tvbox.paths.md}
│   └── master_config.example.json
├── install.sh                       四种模式（见下）
├── bootstrap.sh                     换机司（一键换机/新设备初始化，幂等+零明文 token）
├── verify.sh                        安装自检（含探源司 status 冒烟）
├── 手机指令.md                      第三通道（手动粘贴）
├── TEST.md                         测试清单（含路由实测）
├── MANIFEST.json                   机读分层 + 融合映射 + 可靠性
└── docs/{融合架构.md, 分层落地表.md, 加载机制与可靠性.md, 探源司安装卡.md（★一页装完全套）}
```

> **技能 2 个 + 代码库 1 个**（v0.4.0 起）：`probe-hub`（找源）与 `tvbox-pipeline`（出成品）是唯二会被平台路由的入口；`tvbox-core` 是它们共同 import 的代码库，**故意不放 SKILL.md**——不占路由名额、不进上下文，但 `core.py` 必须在，否则探源司必崩 `ModuleNotFoundError`。
>
> 为什么不是 5 个技能：用户的话只落进两种意图（"给我找源" / "我有源帮我做成能用的"）。拆成 5 个会让平台在 2400 字触发词里挑，反而路由不准；合成 1 个则每次命中都要吃满 117KB 的 SKILL.md。2 入口 + 1 库是两者之间的解。

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

### 换机（新设备 / 重装 / 迁移）

```bash
# 一条命令：克隆 + 稀疏检出 + 断言（可选装完即装到用户级）
bash bootstrap.sh https://github.com/tvbox342078879/520pro.git full ~/520pro --install

# 探源司最小可跑集（2.4M，只含 probe-hub + source-hub + 脚本）
bash bootstrap.sh https://github.com/tvbox342078879/520pro.git lite ~/520pro-lite --install

# 先预览（不落盘）
bash bootstrap.sh <源> lite /tmp/x --dry-run

# 重跑同一命令 = 幂等（跳过 clone，仅 git pull + 重设稀疏）
```

| shape | 检出内容 | 工作区 |
|---|---|---|
| `full`（默认） | 全部（通用层 + 5 技能 + 脚本 + 文档 + 配置模板） | 约 2.8M |
| `lite` | `通用层/` + `probe-hub` + `tvbox-core`（含 `core.py`）+ 3 脚本 | 约 2.4M，**探源司可跑** |

三条承诺：**幂等**（同命令可重跑）、**零明文 token**（默认匿名克隆，token 只在匿名失败后兜底、EXIT trap 强制清 `.git/config`）、**失败显式**（报错即非 0，不静默降级）。

> 与 `tvbox-eco` 原版换机司的区别：原版断言绑死 `hooks/pre-push.hook` / `verify/model_handover.py` / `ARCHITECTURE.md`，搬过来必报断言失败。本版按 520pro 结构重写，稀疏集合改从 `MANIFEST.json` 的 `sync_shape` 读（单一真源）。

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
| 用户级技能**跨设备到新手机** | 🟡 **部分真阳性** | 2026-11-12 手机实测：路由机制可用——**账号技能库有注册的技能，说触发词即可加载**（「已使用技能 probe-hub」截图为证）；但账号库里当时注册的是私有仓旧版 v1.20.8，520 新版须在 App 技能管理**覆盖导入**才生效。手工放入 `~/.codebuddy/skills` 的目录不被检索 |
| **版本混淆教训** | ⚠️ 已修 | 方案 C 改造未升版本号，新旧都叫 v1.20.8 → 手机误载旧版。已升 probe-hub **1.21.0** / learn-hub **1.2.0** / tvbox-pipeline **1.0.0**；判别法：新版无 `harvest pan`、probe.py 共 9,051 行 |
| **手机通道：账号指令 + 命令直达** | ✅ **可靠（兜底）** | 每次会话 `bootstrap.sh` 重装约 30s + 账号指令写死脚本路径，见 `手机指令.md` 粘贴区 |

---

## 六、素材与边界

- 通用层（core-8 / 4 技能）取自 368817 去 TVBox 化版本，原样保留。
- 配置同步层取自 368817 仓根 `.codebuddy/` 存活的 TVBox 件（tvbox-config-sync → 现已并入 tvbox-pipeline / tvbox-agent / /tvbox-sync / 3 脚本 / 配置模板）。
- **探源司已找回并打包**：`probe-hub` + `tvbox-source-hub` + `tvbox-interface` + `tvbox-source-blacklist`（v0.4.0 合为 `probe-hub` + `tvbox-pipeline` + `tvbox-core`）取自 `tvbox342078879/tvbox-skills-eco`（此前判断"已丢失"有误——`tvbox-eco` 是 private 仓库，raw 取不到才显示 404）。
- 探源司实测可跑：`monitor status` 输出 186 个监测目标，带存活/活跃度/判定依据；缺 `core.py` 则必崩。
- **换机司仍未打包**：本仓无 `machine-bootstrap` 之外的换机流程件。

---

## 七、口令

**配置同步**

- 更新配置：`/tvbox-sync all` 或「帮我更新 TVBox 配置」
- 测活：`python3 "$SCRIPT_DIR/check_live.py" sources.json`
- 集成：`python3 "$SCRIPT_DIR/merge_config.py"`
- 必改：`collect_repos.py` 顶部 `REPOS`；项目根 `master_config.json`

**探源司（probe-hub）**

```bash
P="$HOME/.codebuddy/skills/probe-hub/scripts/probe.py"
python3 "$P" monitor status                     # 监测台（186 目标）
python3 "$P" monitor check --repo <仓库URL>      # 单仓三态检查
python3 "$P" search github --topic tvbox         # 搜新仓库
python3 "$P" harvest scan --repo <仓库URL>       # 采线路
```

> 触发词：「探源司」「作者仓库」「找源」「监测仓库」「线路失效」，或显式说「用探源司查一下 XX 仓库」。

> 📋 **第一次装？照 [`docs/探源司安装卡.md`](docs/探源司安装卡.md) 走**：3 条命令装完、自检判据、实测输出、排查表、以及"让新会话 AI 自己装"的可粘贴话术。
