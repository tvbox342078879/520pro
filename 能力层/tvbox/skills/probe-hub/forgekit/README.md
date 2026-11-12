# forgekit —— 构建期内联模板库（S225）

## 这里放什么

写源时反复要用的几块代码，**在构建期**打进单文件源里，运行时不 import 任何东西。

| 文件 | 作用 |
|---|---|
| `_template_src.py` | 模板源。带注释、带说明，**给人读** |
| `builder.py` | 构建器。去注释/docstring → 依赖排序 → 拼成字符串 → `ast.parse` + `exec` + 行为断言 |

## 怎么用

```bash
# 给现有源注入（默认就地改写，先备份 .bak）
python3 scripts/forge.py hook sources/xxx.py

# 只要其中几块
python3 scripts/forge.py hook sources/xxx.py --only pic,inline

# 另存 + 顺带过写源四门禁
python3 scripts/forge.py hook sources/xxx.py --out /tmp/new.py --gate

# 直接看产物
python3 forgekit/builder.py
python3 forgekit/builder.py --only aes --out /tmp/aes_kit.py

# 自检（会 exec 产物并跑行为断言，别只跑 parse）
python3 forgekit/builder.py --selftest
```

注入只做一件事：把 `class Spider(Spider):` 改成 `class Spider(ForgeMixin, Spider):`，
**业务代码一个字不动**。用户自己写的方法优先，模板只是兜底。

## 五个片段

| 片段 | 提供的方法 | 用在哪 |
|---|---|---|
| `inline` | `_json_block/_inline_state/_inline_walk/_inline_items` | 站点把首屏片单内联在 HTML 里（`__NUXT__` / `APP_DATA`）时，比找 XHR 接口稳 |
| `pic` | `_pic` | 列表页一张 `<img>` 都没有、封面挂在 `data-src`/`poster`/`background-image` 上 |
| `play_groups` | `_play_groups/_play_build` | 详情页是 `/bofang/{id}-{sid}-{nid}.html`（r148 三数字模板） |
| `flags` | `_norm_flag/_fix_url` | 线路名带字间空格（「优 酷」「哔 哩 哔 哩」）、相对地址补全 |
| `aes` | `_aes_decrypt` | 站点加密载荷，壳没有 pycryptodome 时的兜底 |

合计 **308 行 / 10311 B**。单源体积预算约 8KB，这套约 1.3 倍，所以**按需取，别默认全要**：

- 纯 CMS 采集源（接口直接返 `vod_play_url`）→ 一块都不需要
- HTML 站 + 需要解线路 → `pic` + `play_groups` + `flags`
- 内联数据站 → `inline`
- 有加密载荷 → `aes`

## 为什么不在运行时拼

业内（kasas ADR 0001）的约束：壳只吃一个文件；`sys.modules` 注入那套的坑
（`__package__` 为 None、模块名冲突、缺 `__file__`、清缓存不更新已持有引用）
在用户手机上表现为黑屏/闪退，且没法远程排查。

## 三个必须知道的约束

1. **只用标准库**。模板里只允许 `json` `re` `urllib.parse`；`Crypto` 只能出现在
   `try/except ImportError` 里（构建器会机器检查这一条）。
2. **产物必须过 `forge_gate`**。注释、docstring、`__main__` 一律不落进产物。
3. **改动模板后必须跑 `--selftest`**。`ast.parse` 过了不代表能跑 —— 见下。

## 踩过的坑（都记在这里，别重犯）

| 坑 | 症状 | 教训 |
|---|---|---|
| 漏搬 import | `NameError: name 're' is not defined` | 只搬了「方法+常量」，模板顶部的 import 没带 |
| 常量先于函数 | `NameError: name '_build_sbox' is not defined` | 排序写成「赋值全排前面」 |
| 模块级循环丢失 | 解密结果**正好等于 key** | `_INV` 靠 `for … enumerate(_SBOX)` 填充，只搬了 `_INV=[0]*256` |
| 循环挂不到名字 | 上条的根因 | 只收 `Store`，而 `_INV[_v]` 是 Subscript，`_INV` 只以 Load 出现 |
| 重复注入 | 体积翻倍、两份定义互相覆盖 | 幂等判断要查 `class ForgeMixin`，不能只查类头 |

> 一句话：**语法合法的代码可以 100% 全错。产物必须 exec 再断言。**
