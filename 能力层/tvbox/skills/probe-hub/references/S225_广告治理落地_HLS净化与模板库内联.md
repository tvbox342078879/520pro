# S225 · 广告治理落地：HLS 净化引擎 + 模板库内联

> 承接 S224 的 8 项资产。用户「在深入看看，都要」——既要业内做法的深化，也要把 P1-P3 落地。
> 本文只记**已落地的代码与判据**，以及落地过程中改掉的设计和踩到的坑。

---

## 一、业内做法查证（三条直接改了我们的设计）

### 1. HLS 净化不是「字符串替换」，是有协议约束的

RFC 8216 §6.2.2 对直播清单（Live Playlist）的硬约束：

| 约束 | 原文要求 | 天真替换的后果 |
|---|---|---|
| `EXT-X-MEDIA-SEQUENCE` | MUST 存在；删头部 N 个分片后 **+N**；**不得减小、不得回绕** | 序号错位 → 播放器拉到已删分片 → 卡住/报错 |
| 剩余时长 | 删完不得少于 **3× TARGETDURATION** | 清单被判失效 → 整个源黑屏 |
| `EXT-X-DISCONTINUITY` | 删掉一个标签，`EXT-X-DISCONTINUITY-SEQUENCE` **必须 +1** | 时间轴错位 |

> 这三条比「正则写得多准」重要得多。**去广告把源搞死，比有广告更糟**，
> 且用户只看到黑屏，无从归因。

### 2. 判定必须三层：Allow → Block → 启发式

uBlock / AdGuard 一类工具的形态。单层黑名单的通病：误杀率随规则增长而失控。
具体到我们：`cdn.bootcss.com`、`raw.githubusercontent.com` 同时出现在 base(5) 的广告清单
和大量站点的**正片/公共 JS** 里 —— 只有 Block 层就没法正确处理。

### 3. 指纹必须 `hostname + pathname`

同一 CDN 下正片与广告共存是常态。只看文件名（`xxx.ts`）必然误杀。

---

## 二、落地：`scripts/hls_clean.py`

单文件、纯标准库、可直接被 quality.py / forge / armor 复用。

### 三段判定

```
① Allow  : ALLOW_HOSTS（jsdelivr/unpkg/cloudflare/githubusercontent…）→ 直接放行
② Block  : 61 条广告域名精确匹配 → 拦
③ Block  : 15 条规则库域名特征（vip.lz / vip.ffzy / bfzy / kuaikan …）→ 拦
④ 启发式 : 路径含 adjump/advert/promo/gg/tui 且 **不在主 CDN** → 拦
            在路径里但同属主 CDN → unknown（不动，可能是站自己的目录）
其余 → unknown（判不了就是判不了，不猜成广告）
```

### 安全策略：要么整份改对，要么一个字不改

```
删前预检 → 剩余时长 < 3×TD ？ → unsafe_skip，原文不动
        → 删完 0 个分片 ？   → unsafe_skip
改后回读 → 分片数对得上？ MEDIA-SEQUENCE == 原值+头部删除数？ 总时长 > 0？
        → 任一对不上 → 整体回退 unsafe_skip
```

`status` 五态：`cleaned / unchanged / unsafe_skip / master_skip / invalid`。
**`unsafe_skip` 不是「没广告」**（M-R60 三态纪律）。

### 自检要求的样本规格

每条规则上线前必须有 **正样本 + 同站负样本 + 错域负样本**：

| 样本 | 用途 |
|---|---|
| 正样本 | 证明能识别 |
| 同站负样本 | 证明不会误杀同 CDN 的正片 |
| 错域负样本 | 证明「同样文件名换到主 CDN 上」不会误判 |

现在 `--selftest` 覆盖 6 条判定样本 + 4 个净化场景（中间插广告 / 头部广告+序列递增 /
时长保护 / 多码率主清单）。

### 落地时改掉的三个真 bug（都是自检抓出来的）

1. **启发式漏判**：`/(?:ad)/` 要求斜杠**紧邻**广告词，`/xx/promo.ts`（广告词当文件名）整类漏掉。
   → 改成同时覆盖「目录名」与「文件名」两种位置。
2. **解析器把分片区标签塞进 header**：第一版的判断是「有 `#EXTINF` 才进 buf」，
   导致 `#EXT-X-DISCONTINUITY` / `#EXT-X-KEY` 全跑到 header，回写时飞到清单最前面（`#EXTM3U` 出现两次）。
   → 改成用 `in_seg` 标记「是否已进入分片区」。
3. **回写吞掉 `#EXTINF` 行**：只写了最后一行（URI），回读解析出 0 个分片、总时长归零。
   → 这才是**回读校验存在的意义**：它当场抓住了自己的作者。

---

## 三、落地：广告域名清单 `references/S225_ad_domains.json`

62 条原样收录，但**核对结果与 S224 资产文有两处不符，已更正**：

| 项 | S224 说法 | 实测 |
|---|---|---|
| 条数 | 62 | 62 条含 1 条重复（`xg.huataisangao.cn` 出现两次），**去重 61** |
| cnzz 子域 | 21 个 | **18 个** |

复扫 dex 字符串池（8538348 B，仅 61 个域名样串，全为框架/站点域名）与 `assets/*.js`
均未发现更大清单 —— 故「两轮挖出更多域名」这个判断不成立，如实记录。

---

## 四、落地：`forgekit/` 模板库（构建期内联）

### 为什么是构建期，不是运行期

kasas ADR 0001 的约束：壳只吃**一个文件**；打包进来的 lodash 能排数组但打不开 socket，
**能用什么能力由打包那一刻决定**。

运行期动态加载（塞 `sys.modules` + 改写 import）的坑：
- `__package__` 在 `__main__` 下是 `None` → 相对 import 直接 `SystemError`
- 模块名冲突会覆盖真模块
- 部分库依赖 `__file__`，动态模块没有
- 清 `sys.modules` 不更新已持有引用

这些坑在用户手机上是黑屏/闪退，且**没法远程排查**。所以一次都不走。

### 形态

```
forgekit/_template_src.py   模板源（带注释、带说明，给人读）
forgekit/builder.py         构建器：去注释/docstring → 依赖排序 → 拼成字符串 → ast/exec 自检
```

五个片段，可单独要也可全要：

| 片段 | 内容 | 体积 |
|---|---|---|
| `inline` | 内联首屏数据提取四件套 + 打分表（100/40/25/20/10/5） | — |
| `pic` | 封面 8 级兜底 + 占位图排除表 | — |
| `play_groups` | r148 三数字模板选集（`正片` / `第%02d集` / `$` `#` `$$$`） | — |
| `flags` | 线路名归一化 11 组（含「优 酷」「哔 哩 哔 哩」） | — |
| `aes` | 纯 Python AES-CBC 兜底（Crypto 在就走 Crypto） | — |
| 合计 | 308 行 / 10311 B | 单源预算 ~8KB 的 1.3 倍 |

### 接入方式：只改一行类头

```python
class Spider(Spider):            →    class Spider(ForgeMixin, Spider):
```

MRO 兜底，用户自己写的方法优先。**业务代码一个字不动**，所以不会覆盖已有实现。
幂等：检测到 `class ForgeMixin` 就整体跳过（重复注入会生成两份定义、白涨体积）。

### 构建器的四个坑（全部由 `--selftest` 抓出，靠 `ast.parse` 一个都抓不到）

| 坑 | 症状 | 原因 |
|---|---|---|
| 漏搬 import | `NameError: name 're' is not defined` | 只搬「方法+常量赋值」，模板顶部的 `import` 没带 |
| 常量先于函数 | `NameError: name '_build_sbox' is not defined` | 排序规则写成「赋值全排前面」 |
| 模块级循环丢失 | 解密结果**正好等于 key**（看着很有结构但全错） | `_INV` 靠 `for _i,_v in enumerate(_SBOX)` 填充，只搬了 `_INV = [0]*256` |
| 循环挂不到名字上 | 上一条的根因 | 只收 `Name(ctx=Store)`；`_INV[_v]` 是 Subscript，`_INV` 只以 Load 出现 |

> 结论：**模板产物必须 exec 一遍再跑行为断言，不能只 parse。**
> 语法合法的代码可以 100% 全是错的。

### 验证

```
[OK] 构建成功 / 体积 <80KB / 语法可解析 / 可 exec / ForgeMixin 存在
[OK] AES 与 pycryptodome 一致
[OK] 纯 Python AES 单块正确（密文由 pycryptodome 现算，不写死向量）
[OK] 内联提取选片单而非导航（20 条 text_link vs 20 条 video_list 的实测场景）
[OK] 封面跳过占位图 / // 补 https / data: 丢弃
[OK] 单集多线路 → 每线路 1 集「正片」
[OK] 线路名「优 酷」「爱 奇 艺」归一化
[OK] 相对路径/协议相对路径补全
```

### 写源四门禁交叉验证

注入后的源过 `forge_gate.py`：

```
✅ [size]    334行/10958B，注释0，docstring0，__main__0，六接口齐
✅ [filter]  分页/filter 静态检查通过
✅ [release] 未命中发布页特征
⚠️ [stream]  UNDETERMINED（没给 api，不做「能播」的假结论）
```

---

## 五、命令

```bash
# HLS 净化
python3 scripts/hls_clean.py <file.m3u8> [--base URL] [--dry-run] [--json]
python3 scripts/hls_clean.py --selftest
python3 scripts/hls_clean.py --ads

# 模板库内联
python3 scripts/forge.py hook <源.py> [--only flags,pic,inline] [--out x.py] [--dry-run] [--gate]
python3 forgekit/builder.py --selftest
```

`quality.py` 的 `ad_judgment()` 已改为**委托** `hls_clean.judge_segment`，
原来的 8 条子串特征（`AD_HOST_HINTS`）作废 —— 原因：子串匹配会误命中，
且真实统计域名（`mimg.0c1q0l.cn`）一个语义特征都不占。

---

## 六、边界如实说（M-R136）

- **未做真机验证**：HLS 净化的实际播放效果、模板库在壳端的加载耗时，沙箱都测不了。
  目前只能保证「结构合法 + 单元行为正确」。
- **规则会过期**：15 条规则与 61 条域名是 base(5) 当时的静态清单。
  用法是「命中即用、不命中不猜」，**不做白名单硬依赖**。
- **`ext-x-cue-in` / `cue-out` 未处理**：一起看广告那条规则依赖它，但 SCTE-35 标记的
  正确移除方式取决于具体封装，没实测就不写。
- **纯 Python AES 只保证正确性，不保证性能**：>100KB 数据必须走 pycryptodome
  （陷阱库 G 组第一条：纯 Python 解 457KB 要 16.4s，超壳端图片窗口）。
  模板里 `_aes_decrypt` 已经是「有 Crypto 走 Crypto」的形态，但没有做体积分流。
