# inspect-hub CHANGELOG

## v1.3.1 — target 自解析 + 版本号对齐（2026-11-12）

- **仓库根自解析**：`--target` 缺省不再硬取 `'.'`，改为从 cwd 逐级向上找含 `MANIFEST.json`
  的目录（SKILL.md §1 一直这么承诺，代码没实现）。实测从安装目录
  `~/.codebuddy/skills/inspect-hub/scripts` 跑，旧实现把技能目录当仓库根，
  开门/生门/景门/伤门/死门/休门集体假红/假黄，健康分 76 全是噪声。
- **定不到根就报「无法判定」**：`require_target()` 兜底，exit 2 并给出 `--target` 提示，
  不再产出假红假黄（三态铁律：不知道 ≠ 有问题）。
- **版本号对齐**：frontmatter 停在 1.1.0、CHANGELOG 已到 1.3.0（两处断链），统一到 1.3.1。

## v1.3.0 — 监测登记门面 + 生门对账口径修复（2026-11-12）

- **register_monitor 迁入本技能**（原 tvbox-core 门面探旧生态 tvbox-inspect，在 520 恒失败）：
  真写入 `monitors.json`（运行时数据，独立于正本登记册），幂等、纯登记不动引擎。
- **生门对账排除运行时数据**：`findings_history.json` / `monitors.json` / `*_state.json`
  不参与副本 md5 对账——否则每台机器运行时演化都会误报「副本漂移」，真漂移被假黄淹没。
- 实测自举：抓到 space-hub 副本 state 与 learn-hub 脚本陈旧两处真漂移（同步后转绿）。

## 1.1.0 · 2026-11-12
- **对抗自测 `adversarial` 子命令**（借 tvbox-eco adversarial_suite，去旧生态化）：临时 clone 逐门造脏（7 门用例 + 无脏对照），断言「篡改必翻红」，任一未翻红 exit 2；8/8 实测通过。改检查器后必跑。
- **死门带过执法**（借 carryover_guard 思想）：【待】缺负责人或期限 → 红；同一主题 ≥2 次 → 复发红。遗留登记.md 四条目已补齐负责人+期限。
- 自指豁免：secret_scan 对 inspect_hub.py 对抗用例构造行做行级豁免（对抗用例的伪造密钥字面量曾误触自家扫描器，实测发现即修）。

## 1.0.0 · 2026-11-12
- 首版：八卦八门巡检面板（卦门合阵 · 双鱼抱数 · 数定阵心，模板与用户逐轮定稿一致）。
- 登记册驱动（inspect_registry.json 8 门），impl=null 门=灰色在册待补（惊门首发）。
- 健康预检双兜底：self-check + run 内逐门 try/except → 失灵报「无法判定」不装绿。
- 环比指纹：findings_history.json，🆕新增/✅已清零/♻️持续。
- 两层生效判定：结构生效（脚本）+ 行为生效（SKILL.md 强制 AI 自报对账）。
- 杜门直调仓库 secret_scan.py（件①产物复用）；景门计数锚点 `=\s*sub\.add_parser\('`（probe 16 / space-hub 11，2026-11-12 实测）。
- 面板纯 CSS 自适应（cqw 容器单位 + vw 兜底），手机/电脑双端不裁切——历经手机端三轮实测修正（JS 缩放不可靠，弃）。
