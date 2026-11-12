---
name: inspect-hub
description: 520 巡检司（监察司思想通用化）。当用户说「520 体检」「体检」「巡检」「拉面板」「520健康吗」「哪里没检查」「有什么遗留」「inspect」等触发词时使用。对 520pro 仓库自身跑 8 面巡检（规则生效/技能生效/密钥安全/文档一致/结构完整/遗留登记/新鲜度/触发词），产出单文件 dashboard.html 八卦八门面板并拉到用户眼前；登记册驱动加巡检面零改代码；检查器失灵报「无法判定」绝不装绿（三态铁律）。与 probe-hub（盯外部 TVBox 上游）相对，本技能盯 520 自家健康。 能力：①八面巡检（规则生效/技能生效/密钥安全/文档一致/结构完整/遗留登记/新鲜度/触发词）；②登记册驱动（加巡检面零改代码，先登记占位灰）；③八卦八门面板（单文件 dashboard.html，拉到眼前）；④三态判定（检查器失灵报「无法判定」，绝不装绿）；⑤环比指纹（findings_history 对比上次，只看变化）。正门：scripts/inspect_hub.py（run 出面板 / self-check 自检）。不要用于：盯 TVBox 上游仓库与线路（归 probe-hub 探源司）；不要用于技能契约的逐项机检（归 verify/skill_contract_check.py）；不要用于修改被检对象（只体检、不动刀，修由各技能正门做）。
version: 1.4.1
---

# inspect-hub · 520 巡检司 v1.3.1

> **第一动作（自省锚点）**：命中触发词后**先读本技能与 inspect_registry.json 再跑**；
> 不许看见触发词就直接 `inspect_hub.py run`——面目/判据/阈值都在登记册里，跳过即无判据。

盯 520 自家的健康。probe-hub 盯外面，这里盯家里。

## 触发词
`520 体检` / `体检` / `巡检` / `拉面板` / `520健康吗` / `哪里没检查` / `有什么遗留`

## 八门 ↔ 巡检面

| 门 | 卦 | 面 | 查什么 |
|---|---|---|---|
| 开 | ☰ | 规则生效 | 用户级/项目级规则在位 + 指纹 vs 仓库正本 |
| 生 | ☳ | 技能生效 | 安装副本 vs 仓库正本全量 md5 + .bak 残留 |
| 杜 | ☵ | 密钥安全 | 调仓库 secret_scan.py（件①），红=明文密钥 |
| 景 | ☲ | 文档一致 | SKILL 声明命令数 vs 代码实况（防文档吹牛） |
| 伤 | ☷ | 结构完整 | MANIFEST 登记文件逐个存在性 |
| 死 | ☶ | 遗留登记 | docs/遗留登记.md 的【待】/【阻】条目；**带过执法**：每条必须带「负责人+期限」缺一即红，同一主题 ≥2 次按复发升红（借 tvbox-eco carryover_guard 思想） |
| 休 | ☴ | 新鲜度 | 最近提交距今 + 各技能 CHANGELOG 停更天数 |
| 惊 | ☱ | 触发词冲突 | 各 SKILL description 的「触发词」跨技能比对：**同词撞车判红**（用户说这词路由二义）；技能内重复判黄；未声明触发词判黄（冲突无从判定，非无冲突）。**只查字面**，语义近义靠各技能 trigger-samples 的 N 组人工核 |

## 使用流程（强制，逐条执行不许跳）

1. **定位仓库**：`--target` 指向 520pro 根目录；未给则依次试当前目录含 `MANIFEST.json` 的父级。
2. **自检引擎**：`python3 <skill>/scripts/inspect_hub.py self-check` —— 失败先修引擎，不许带病巡检。
3. **跑巡检**：`python3 <skill>/scripts/inspect_hub.py run --target <520pro根>`
   产出 `docs/巡检/dashboard.html`（单文件，手机/电脑双端）+ `findings.json` + 环比指纹落 `findings_history.json`。
4. **拉面板**：把 `dashboard.html` 用 present_files 拉到用户眼前 —— **这是硬性步骤，面板必须出现在用户眼前**。
5. **行为生效自报对账（AI 必做，脚本做不了）**：
   - 自报 ①「我当前会话实际可见的 520 技能清单是：…」（对照本会话 Skill 工具扫描 `~/.codebuddy/skills/` 的实况）
   - 自报 ②「我当前上下文里注入的 520 规则是：…」（开场 system-reminder 里有没有 core-8 条文）
   - 与结构层结果对账：文件在但本会话叫不动/没注入 → 当面声明「行为生效红」，并提醒**改规则必须开新会话才生效**。
6. **红门处置**：红门条目自带「问题+证据+可复制命令」，逐条给用户；不要只报分不给出路。

## 纪律（三态铁律）

- 检查器抛异常 → 该门显示「⚪ 无法判定」，**绝不装绿**（健康预检在 self-check 与 run 内双层兜底）。
- 加巡检面：先在 `inspect_registry.json` 登记（impl 留 null → 灰色待补），再实现 `chk_*` 函数改登记指向 —— 加面零改引擎。
- 每期巡检自动与上期环比：🆕新增 / ✅已清零 / ♻️持续，写进面板顶部。

## 自检

```
python3 scripts/inspect_hub.py self-check    # 登记 8 门齐 + impl 映射一致 + 模板可渲染
python3 verify/tests/test_triggers.py       # 惊门：真仓 green / 撞词红 / 缺词黄 / 单技能 unknown（G1）
python3 verify/tests/test_troubleshoot.py   # 每技能「按症状排」的故障排查是否 ≥5 条（F3）
python3 scripts/inspect_hub.py adversarial --target <520pro根>   # 对抗自测（v1.1.0）
```

## 对抗自测（adversarial，v1.1.0 起）

方法论（借 tvbox-eco adversarial_suite）：**每个门禁必须配「篡改输入→必翻红」用例**。
在临时 `git clone` 副本上逐门造脏（改规则正本/脏 SKILL.md/伪造密钥/注假子命令/藏登记文件/无主无期阻塞项/回拨 CHANGELOG），断言对应门翻红；另配一组无脏对照防「用例恒红」。任一未翻红 exit 2 = 门禁失灵，先修再巡。

- 使用时机：改过任何检查器/登记册之后必跑；平时建议每周随体检跑一次。
- 不污染仓库：造脏全在临时 clone 上，跑完即删。
- 自指豁免：secret_scan 对 inspect_hub.py 的对抗用例构造行做**行级**豁免（只豁构造行，不豁整文件）。
