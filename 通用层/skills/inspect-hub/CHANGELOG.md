# inspect-hub CHANGELOG

## 1.0.0 · 2026-11-12
- 首版：八卦八门巡检面板（卦门合阵 · 双鱼抱数 · 数定阵心，模板与用户逐轮定稿一致）。
- 登记册驱动（inspect_registry.json 8 门），impl=null 门=灰色在册待补（惊门首发）。
- 健康预检双兜底：self-check + run 内逐门 try/except → 失灵报「无法判定」不装绿。
- 环比指纹：findings_history.json，🆕新增/✅已清零/♻️持续。
- 两层生效判定：结构生效（脚本）+ 行为生效（SKILL.md 强制 AI 自报对账）。
- 杜门直调仓库 secret_scan.py（件①产物复用）；景门计数锚点 `=\s*sub\.add_parser\('`（probe 16 / space-hub 11，2026-11-12 实测）。
- 面板纯 CSS 自适应（cqw 容器单位 + vw 兜底），手机/电脑双端不裁切——历经手机端三轮实测修正（JS 缩放不可靠，弃）。
