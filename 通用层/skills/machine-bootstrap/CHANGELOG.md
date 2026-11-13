# machine-bootstrap · CHANGELOG

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
