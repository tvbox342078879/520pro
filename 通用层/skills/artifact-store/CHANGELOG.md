# artifact-store · CHANGELOG

## v1.0.2 — 触发语义前置（520 v0.8.31 工程K，2026-11-13）
- description 首句改为「当用户说「…」「…」时使用本技能」，把 5 个高频口语说法提到前 80 字内：平台只把描述编成截断预览给模型看，触发词写在尾巴上等于没写（C9 机检）
- 依赖项：`verify/skill_contract_check.py` 新增 C9 触发前置 / C10 样本词桥；`verify/tests/test_trigger_frontload.py` 8 用例变异回归

## v1.0.1 — 触发样本集 + 文档断链修复（2026-11-12）
- 新增 `references/trigger-samples.md`：T8/N7/B4；固化「优先官方原生、仅兜底」的第一动作顺序
- B02 固化「云端都有备份」须先验证再清本地

## v1.0.0 — 2026-11-12
- 首次纳入技能契约机检（v0.8.15 工程C）：补 version / CHANGELOG / 能力枚举 / 负边界 / 自省锚点。内容无行为变更，四类堆积解法与官方能力对齐清单照旧。
