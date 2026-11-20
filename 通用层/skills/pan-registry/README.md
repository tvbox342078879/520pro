# pan-registry（网盘 provider 统一注册表 · lib）

> **定位**：云取借鉴第 10 条——把"每家网盘各写一份差异表"收敛成唯一真源。无 SKILL.md，平台不注册不路由、不进上下文，只被 `share-parser` / `transfer-poll` import。

## 1. 解决什么问题

此前新增一家网盘要在多处各改一遍：

- `share-parser` 的 `PLATFORM_RULES`（分享链接正则）
- `transfer-poll` 的 `POLL_INTERVAL_MS`（轮询间隔）+ `TEXT_IN_PROGRESS`（进度文案）

三处各写、命名不一（`guangya`/`quark`/`uc` vs `quark`/`baidu`/`115`…），漏改即静默出错。这正是第 10 条要消除的"一个一个改"。

## 2. 机制

`scripts/registry.py` 唯一一张 `PLATFORMS` 表，每条记录含四类差异维度：

| 维度 | 投影函数 | 消费方 |
|---|---|---|
| 分享链接正则 | `share_rules()` | share-parser |
| 有效期代码 | `expire_codes()` | share-parser |
| 轮询间隔 | `poll_intervals()` | transfer-poll |
| 进度文案 | `progress_texts()` | transfer-poll |

**新增网盘 = 在 `PLATFORMS` 加一条记录，四类投影自动可见，两技能主流程零改。**

## 3. import 约定

两技能 scripts 目录的 `parents[2]` = `skills` 根，与用户级 `~/.codebuddy/skills/` 结构对称：

```python
_SKILLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_SKILLS, 'pan-registry', 'scripts'))
import registry
```

## 4. 自省 / 判据

- 自省：`python3 scripts/registry.py --selftest` / `--list`
- 判据：`verify/tests/test_pan_registry.py`（单一真源有牙 + 元变异：删一条记录两技能投影同步变、新增一条即刻可见）

## 5. 边界

- 本 lib 不含登录鉴权、不触网、不转调 `pan.py`。
- 平台不在册 → 投影返回空/不走该维度，调用方用默认值，不硬造。
- 正则写坏 → 编译期显式抛，不静默跳过。
