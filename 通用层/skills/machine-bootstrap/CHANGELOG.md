# machine-bootstrap · CHANGELOG

## v1.1.0 — 弱网 raw 单文件补包 fallback（2026-11-19）
- **新增 `scripts/raw_sync.py`**：弱网 git clone 被掐断（GnuTLS -110 / promisor blob 超时）时的独立补包正门——按逐文件清单用 curl 逐个下小文件，中文路径 UTF-8 编码、断点续补（跳过已存在非空）、关键件优先、退出码=失败数。全仓文本真源 1.2M，排除 capability_63/runtime_assets 的 8 个逆向运行时大文件（约 200M，换机断言不查）。`--selftest` 10/0。
- **新增 `references/sync_filelist.txt`**：742 个 git 真源文件清单（`git -c core.quotepath=false ls-files` 生成，中文原文；改真源须同步清单，判据守护）。
- **bootstrap.sh 失败分支加指引**：clone 三次全败后打印 raw 补包命令 + "补包后勿跑 apply_sparse/verify（无完整 .git 会假失败）"；不内联改 git 主流程，保持 sparse/migrate/verify 干净。
- **手机指令.md 说明段加弱网补救 curl**（不入粘贴区、不触发云端副本同步，同 preflight 第-1步先例）。
- **新增 `docs/多场景部署.md`**：五场景（普通网络换机/弱网补包/只验证不换机/两账号多会话/别人匿名部署）命令原文 + 边界。
- **登记**：`verify/skill_contracts.json` required_files 加 raw_sync.py + sync_filelist.txt；四处版本 1.0.4→1.1.0。

## 换机司冷启动缺陷修复（2026-11-16；未 bump：脚本判据修复 + 设计参考，无版本交付承诺）
- **check-env.sh 修 rc 假绿**：旧版空仓报 A3/B2 仍 rc=0（体检失败被当通过）；现 A/B/C 命中累计并 `exit 2`，真仓全绿才 rc=0。`--selftest` 7→8 例（新增「空仓 rc≠0」回归反例）。
- **镜像对账 2→5 文件**：补 `scripts/check-env.sh`/`docs/TROUBLESHOOTING.md`/`references/trigger-samples.md`，篡改任一用户级副本必报 B；仍避开 runtime_assets 226MB 大文件。
- **bootstrap.sh 回退清单对齐**：FALLBACK_FULL 9→17 项、LITE 8→13 项，与 MANIFEST `sync_shape` 逐项一致——MANIFEST 不可读时不再因缺 `verify/`/`secret_scan.py`/`hooks/` 让检出闸假崩。迁移表加基线声明（0.8.10 后无一次性动作，不捏造空函数）。
- **修文档断链**：TROUBLESHOOTING.md:8 与 zh-style.md:51 的 `BOOTSTRAP_REPO`（脚本里不存在的变量）改指真实位置参数 $1。
- **新增 `scripts/preflight.sh`**：换机第 0 步之前的裸机前置体检——不依赖仓库/git，纯 bash+coreutils 体检 git/curl/python3/node/jq/unzip + 网络 + 凭据，三态报告 + 修复顺序；只读、不下载正文、不读 token 值。`--selftest` 6/6。与 check-env 的分工见脚本头。
- **新增 `references/cold-start-design.md`**：旧生态 368817 冷启动 6 步 + L0–L3 验收框架的方法论参考（硬编码坐标不照搬）。
- **登记**：`verify/skill_contracts.json` required_files 加 `scripts/preflight.sh`；`手机指令.md` 第 0 步前加 preflight 前置。未 bump 版本：判据/文档修复，不制造资料库交付承诺（避免假交付闸误判）。

## v1.0.4 — 环境体检正门 scripts/check-env.sh（2026-11-16；未 bump：原则落成可执行脚本，无资料库交付承诺）
- 新增 `scripts/check-env.sh`：把 W8-B1 吸收的两节原则落成可执行体检正门——①三态链路审计（7 工具两级验证 command -v + 真跑退出码；B 类 JAVA_HOME/git 仓库链路；A 未补全/C 假就绪）；②技能安装边界（比对 MANIFEST 登记技能 SKILL.md sha 验内置不可覆盖 + 来源白名单/精确 id/只落文件不执行三条策略自证）；③换机后版本对账（VERSION + git HEAD）。`--selftest` 正反 7 例（缺工具=A/假就绪=C/仓库不可识别=B/镜像缺失=B/sha漂移=B/正向两级过/镜像一致）全绿。
- 镜像对账只比 SKILL.md/CHANGELOG.md 的 sha，刻意不遍历 runtime_assets（226MB）——避开 W8-D 大文件。
- frontmatter description 加正门锚点（C3），契约 required_files + entry 登记 scripts/check-env.sh。未 bump：易名为原则的可执行化，无对应资料库交付承诺，沿用 v1.0.4（避免假交付闸）。

## W8-B1 吸收 MilkCode 环境自检 + 安装边界原则（2026-11-16；未 bump：纯原则文档吸收）
- SKILL.md 新增「环境自检：三态链路审计」节（吸收 env-audit 的 A 未补全/B 链路断开/C 假就绪三态 + `command -v` 与真跑退出码两级验证；只存在但执行失败归 C 不报已就绪）。MilkCode 语境的 `/.milkcode-*` 标记与 MCP 专有工具不照搬（520 无此环境），只吸收可迁移原则
- 新增「技能安装边界」节（吸收 skill-installer 三条原则：内置不可覆盖 / 来源白名单 / 冲突需精确 id + 装文件不执行）。520 安装正门仍是 `install.sh --user-skill`，不另造通道
- 未 bump 版本：本次为原则文档吸收，无对应资料库交付承诺，不制造版本升级（避免假交付闸误判）

## v1.0.4 — 触发语义前置（520 v0.8.31 工程K，2026-11-13）
- description 首句改为「当用户说「…」「…」时使用本技能」，把 5 个高频口语说法提到前 80 字内：平台只把描述编成截断预览给模型看，触发词写在尾巴上等于没写（C9 机检）
- 依赖项：`verify/skill_contract_check.py` 新增 C9 触发前置 / C10 样本词桥；`verify/tests/test_trigger_frontload.py` 8 用例变异回归

## v1.0.3 — 诚实边界表 + 手机通道语义过期修复（2026-11-13）
- SKILL.md 新增「诚实边界」节（借鉴 908 DmaxPro908 换机说明的边界表写作模式）：明写只搬代码与规则真源 / 账号配置不搬 / 会话历史不搬 / 凭据不给 URL 内嵌（防 .git/config 明文持久化，B-05）/ 不押平台钩子
- 修第 31 行语义过期：三通道确认里的手机通道仍写 App「给 WorkBuddy 的指令」——该入口 2.8.0/2.9.1 两版实测均无，bbbe8a2 回写时本文件漏网（第 6 处），改为「会话首条粘贴 + 云端 doc」。全仓 grep 复核其余 2 处均已是带定论注解的正确写法（孤例，非模式）

## v1.0.2 — 补「git push 卡住」排查（2026-11-12 实测）
- TROUBLESHOOTING 加第 6 条：HTTP/2 下 push 挂 13 分钟零输出，切 `GIT_HTTP_VERSION=HTTP/1.1` 后秒过（仓库仅 9MB、待推 1 commit，非体积问题）
- 关键纪律：先用只读 `gh api .../commits/main` 比对远端 sha，确认"真没推上去"再动作；**别**在 sha 未确认前 force push（那头可能已收到，force 会覆盖别人提交）

## v1.0.1 — 触发样本集 + 文档断链修复（2026-11-12）
- 新增 `references/trigger-samples.md`：T9/N6/B4；B01 固化「脚本没有 --verify，不得宣称验证通过」
- 修文档断链（实查发现）：原文写「可选件、本脚手架未搬入」并给 ${CODEBUDDY_SKILL_DIR}/scripts/bootstrap.sh --repo --sparse——脚本实际早在仓库根，且无这两个参数；照原文跑必然失败，已改为真实位置参数用法

## v1.0.0 — 2026-11-12
- 首次纳入技能契约机检（v0.8.15 工程C）：补 version / CHANGELOG / 能力枚举 / 负边界 / 自省锚点。内容无行为变更。
