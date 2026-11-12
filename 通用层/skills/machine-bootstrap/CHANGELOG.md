# machine-bootstrap · CHANGELOG

## v1.0.1 — 触发样本集 + 文档断链修复（2026-11-12）
- 新增 `references/trigger-samples.md`：T9/N6/B4；B01 固化「脚本没有 --verify，不得宣称验证通过」
- 修文档断链（实查发现）：原文写「可选件、本脚手架未搬入」并给 ${CODEBUDDY_SKILL_DIR}/scripts/bootstrap.sh --repo --sparse——脚本实际早在仓库根，且无这两个参数；照原文跑必然失败，已改为真实位置参数用法

## v1.0.0 — 2026-11-12
- 首次纳入技能契约机检（v0.8.15 工程C）：补 version / CHANGELOG / 能力枚举 / 负边界 / 自省锚点。内容无行为变更。
