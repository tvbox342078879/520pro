# 520pro · 测试清单

> 目标：验证融合后的三件事——**规则双轨是否生效、用户级技能是否被路由、云端脚本是否能跑**。
> 判定只用三态：**真阳性 / 真阴性 / 无法判定**（报错、超时、没反应都算「无法判定」）。

---

## 0. 安装（推荐 user-skill 模式）

```bash
cd /path/to/520pro
bash -n install.sh && echo "语法OK"
bash install.sh --user-skill --dry-run     # 只看不写
bash install.sh --user-skill               # 真装：通用层+TVBox 全到 ~/.codebuddy
bash verify.sh                             # 自检（会打印每个落点 + 脚本冒烟）
```

**预期**：`verify.sh` 里通用层 7 项、TVBox 技能 1 项、脚本 3 项全绿，冒烟显示 `check_live.py 可执行`。

> 只想项目隔离：`bash install.sh --capability-only --target /tmp/testproj`

---

## 1. 规则双轨（硬轨 + 软轨）

| 编号 | 动作 | 预期 |
|---|---|---|
| T1.1 | 把 `手机指令.md`【粘贴区】粘进 **桌面/手机 → 设置→给 WorkBuddy 的指令**，保存 | 硬轨就位 |
| T1.2 | **新开会话**，不贴规则问「core-8 第一条是什么？」 | 答「语言跟随用户/全程中文」= **真阳性**；反问「哪套」= 真阴性 |
| T1.3 | 用英文问一句（"what is git?"） | 仍用**中文**回答 = 语言铁律生效 |

> 若 T1.2 真阴性：硬轨没生效 → 检查是否真保存 + 是否重启客户端；软轨 `~/.codebuddy/rules/core-8.md` 是双保险。

---

## 2. 用户级技能路由（★ 520pro 的核心验证）

| 编号 | 动作 | 预期 |
|---|---|---|
| T2.1 | **新开会话**，说「帮我更新 TVBox 配置」 | 命中 `tvbox-pipeline` 或按三步链路执行 = **真阳性**（说明用户级技能被路由） |
| T2.2 | 输入 `/tvbox-sync all` | 命令被识别 |
| T2.3 | 观察是否调用了 `~/.codebuddy/scripts/`（而非报"找不到脚本"） | 脚本路径自动适配成功 |

> 这一步是关键：**项目级技能不路由，用户级才路由**。若 T2.1 没反应，回看 `verify.sh` 是否 `~/.codebuddy/skills/tvbox-pipeline` 存在。

---

## 3. 探源司四件套（★ 真正的干活能力）

> 前提：`probe-hub` + `tvbox-core` 两个目录必须齐全。**只装 probe-hub 必报 `ModuleNotFoundError: No module named 'core'`。**

| 编号 | 动作 | 预期 |
|---|---|---|
| T3.0 | `ls ~/.codebuddy/skills/` | 能看到 `probe-hub` / `tvbox-pipeline` / `tvbox-core`（core 无 SKILL.md 属正常） |
| T3.1 | `cd ~/.codebuddy/skills/tvbox-core/scripts && python3 -c "import core"` | 无报错 |
| T3.2 | `python3 ~/.codebuddy/skills/probe-hub/scripts/probe.py monitor status` | 输出 `📡 上游仓库监测台（186 个目标）` 表格 |
| T3.3 | `python3 .../probe.py monitor check --repo https://github.com/xxx/not-exist-999` | 返回 `❌ 未找到目标`（**若编出内容 = 幻觉**） |
| T3.4 | 新会话说「用探源司看看 hjdhnx/drpy3 还活着吗」 | 命中 probe-hub 技能并调用 |

**判定要点（四条硬指标，缺一即不可信）**：

1. 有落盘产物（`monitor_targets.json` / `dead_repos.json` mtime 更新）
2. 每条结论带 http_code 或 API 归因
3. 三态齐备，「无法判定」没被折叠成「失败」
4. 反证不倒（假目标不编内容）

> 沙箱内 `monitor check --repo` 单目标常超时无输出 → 记 **无法判定**（443 出站受限），不是能力缺陷。

---

## 5. 配置同步脚本可跑（证明"手机也能触发"的前提）

| 编号 | 动作 | 预期 |
|---|---|---|
| T5.1 | `bash verify.sh` 的冒烟段 | 显示 `check_live.py 可执行` |
| T5.2 | 准备 `master_config.json` 后跑链路 | 输出 `存活 N / 失效 M → master_config.new.json` |
| T5.3 | 手机上说「更新 TVBox 配置」 | 若用户级技能已随账号同步 → 能触发（执行在云端）= 真阳性；不能触发 = **无法判定/真阴性**（记下来） |

---

## 6. 换机司（bootstrap.sh）

| 编号 | 动作 | 预期 | 判据 |
|---|---|---|---|
| T6.1 | `bash bootstrap.sh <源> lite /tmp/e1 --dry-run` | 打印计划，不落盘 | 结束后 `/tmp/e1` 不存在 |
| T6.2 | `bash bootstrap.sh <源> lite /tmp/e1` | `换机成功`，断言 6 项全 `✔` | 工作区约 2.4M，含 probe-hub + tvbox-core |
| T6.3 | **再跑一遍同一命令**（幂等） | 出现 `[幂等] 跳过 clone` → `已拉取最新` → 断言仍全 `✔` | 无重复 clone、无副作用 |
| T6.4 | `bash bootstrap.sh <源> full /tmp/e2` | 断言 15 项全 `✔` | 含 2 个能力层技能 + 5 个通用层技能 + 3 脚本 + core.py |
| T6.5 | `bash bootstrap.sh <源> lite /tmp/e3 --install` | 装完显示 `✔ 已安装到 $HOME/.codebuddy` | 新会话可见 probe-hub 技能 |
| T6.6 | 目标目录已存在且非本仓（`mkdir /tmp/zz` 后跑） | `拒绝覆盖` + exit 1 | **不覆盖用户数据** |
| T6.7 | 源路径不是 git 仓（`bootstrap.sh /etc lite /tmp/x`） | `不是 git 仓库` + exit 1 | 明确报错不静默 |

> **零明文 token 自检**：`grep -c "$GITHUB_TOKEN" ~/.codebuddy -r` 应为 0；`git -C <target> config --get remote.origin.url` 中不应含 `x-access-token`。
>
> 2026-11-12 实测修正：旧版把 token 拼进 clone URL，git 会原样写进 `.git/config`，断言失败提前退出时 token 就留在盘上（"零明文"曾不成立）。现改为**默认匿名克隆**，token 仅在匿名失败后兜底，且 EXIT trap 强制还原 origin。换机后必须跑上面第二条命令确认。

---

## 7. 判定汇总（测完填）

| 层 | 测试项 | 真阳性 | 真阴性 | 无法判定 |
|---|---|---|---|---|
| 规则 | T1.2 core-8 双轨 | ☐ | ☐ | ☐ |
| 规则 | T1.3 语言铁律 | ☐ | ☐ | ☐ |
| 技能 | T2.1 用户级路由 | ☐ | ☐ | ☐ |
| 技能 | T2.3 脚本路径适配 | ☐ | ☐ | ☐ |
| **探源司** | **T3.2 monitor status** | ☐ | ☐ | ☐ |
| **探源司** | **T3.3 反证不编** | ☐ | ☐ | ☐ |
| 脚本 | T5.1 冒烟 | ☐ | ☐ | ☐ |
| 手机 | T5.3 手机触发 | ☐ | ☐ | ☐ |
| **换机** | **T6.3 幂等重跑** | ☐ | ☐ | ☐ |
| **换机** | **T6.4 full 断言** | ☐ | ☐ | ☐ |
| 换机 | T6.6 拒绝覆盖 | ☐ | ☐ | ☐ |

---

## 8. 常见假阴性排查

- **技能没反应** → 可能装成了项目级（不路由）。改用 `--user-skill` 重装，或确认 `~/.codebuddy/skills/tvbox-pipeline/` 存在。
- **找不到脚本** → `$SCRIPT_DIR` 没定位对；`verify.sh` 会报。
- **规则没生效** → `/clear` 不算重启；要新开进程/重启客户端。
- **手机没触发** → 用户级技能是否跨设备同步=无法判定；先在桌面验证 T2.1，再测手机 T3.3。

## 7. 学习工坊 + 网盘取料（v0.5.0 新增）

> 前置：`~/.codebuddy/skills/learn-hub/` 存在，含 `scripts/learn.py` 与 `scripts/pan.py`。

| 编号 | 操作 | 预期（判据） |
|---|---|---|
| T7.1 | `python3 ~/.codebuddy/skills/learn-hub/scripts/learn.py self-check` | `self-check 16/16` |
| T7.2 | `python3 ~/.codebuddy/skills/learn-hub/scripts/pan.py self-check` | `网盘模块自检 2/2 通过` |
| T7.3 | `python3 ~/.codebuddy/skills/learn-hub/scripts/pan.py info --url <真实夸克分享>` | 列出文件树与大小；**机房 IP 也能成，因为它只走 API** |
| T7.4 | `python3 ~/.codebuddy/skills/learn-hub/scripts/pan.py info --url https://example.com/s/x` | `❌ 认不出分享 id` 并列出四平台正确格式 |
| T7.5 | `python3 ~/.codebuddy/skills/learn-hub/scripts/pan.py save --url <链接>`（无 cookie） | `❌ 缺少 ... 网盘登录态` + 获取指引，不崩 |
| T7.6 | 新会话说「把这个网盘链接里的资料收了」 | 命中 `learn-hub` 并走 `intake pan` |

> 网盘取料原属探源司 `probe harvest pan`，v0.5.0 迁入学习工坊（与 TVBox 零耦合）。
> `pull` 若被 CDN 以 412 拒绝，属**出口 IP 段**问题，不是文件不存在——清单拿到了就说明东西在。
