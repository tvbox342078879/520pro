# machine-bootstrap · CHANGELOG

## v1.0.2 — 补「git push 卡住」排查（2026-11-12 实测）
- TROUBLESHOOTING 加第 6 条：HTTP/2 下 push 挂 13 分钟零输出，切 `GIT_HTTP_VERSION=HTTP/1.1` 后秒过（仓库仅 9MB、待推 1 commit，非体积问题）
- 关键纪律：先用只读 `gh api .../commits/main` 比对远端 sha，确认"真没推上去"再动作；**别**在 sha 未确认前 force push（那头可能已收到，force 会覆盖别人提交）

## v1.0.1 — 触发样本集 + 文档断链修复（2026-11-12）
- 新增 `references/trigger-samples.md`：T9/N6/B4；B01 固化「脚本没有 --verify，不得宣称验证通过」
- 修文档断链（实查发现）：原文写「可选件、本脚手架未搬入」并给 ${CODEBUDDY_SKILL_DIR}/scripts/bootstrap.sh --repo --sparse——脚本实际早在仓库根，且无这两个参数；照原文跑必然失败，已改为真实位置参数用法

## v1.0.0 — 2026-11-12
- 首次纳入技能契约机检（v0.8.15 工程C）：补 version / CHANGELOG / 能力枚举 / 负边界 / 自省锚点。内容无行为变更。
