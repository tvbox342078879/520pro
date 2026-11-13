# S228 · Git 远端卡顿：业内做法与本仓 safe 推送落地

> **★ 520pro 落地登记（v0.8.21，2026-11-13）**：本文描述的方案已有执行体——
> `hooks/git_push_safe.sh`（自旧生态随迁适配，含 5 次指数退避 + jitter + 瞬时错误白名单 +
> per-attempt timeout + rev-parse 终验 + SSH over 443 兜底 + 平台降级，三态退出码）。
> 推送纪律：**向 GitHub 推送一律走该脚本，禁止裸 `git push`**；
> `verify.sh` 检查其存在与语法（缺失即红），检出清单（MANIFEST `sync_shape`）已含它。
> 本文保留为**业内依据真源**，参数与理由只读这里，不在脚本注释里复制全文（M2）。

> 起因：S227 推送时连续 `Failed to connect to github.com port 443`（133s 超时），
> 出口网络抖动（同一地址 25s 超时与 200 交替）。用户明令：**遇到新问题先看业内，别自己瞎琢磨**。

---

## 一、业内查证（2026-11-03）

### 1. 重试：git 不支持，必须外包 wrapper

StackOverflow 35014012 原话：*"No, git itself, it does not support natively that feature."*

最权威工程实现是 Chromium **depot_tools/git_retry.py**（官方注明 largely DEPRECATED，但参数仍是业内基准）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `DEFAULT_RETRY_COUNT` | **5** | 含首次共 5 次尝试 |
| `DEFAULT_DELAY_SECS` | **3.0** | 基础延迟 |
| `--delay-factor` | **2** | 指数退避；0=线性、1=恒定 |
| jitter | **无** | 它的缺陷（见下） |
| 可重试判定 | 仅 stderr 匹配 `GIT_TRANSIENT_ERRORS_RE` | **认证/权限错误一律不重试** |

### 2. 传输协议：HTTPS 与 SSH 的失败模式不同

- GitHub 官方排障文档将「切换克隆方法」（HTTPS ↔ SSH）列为标准动作
- 实践共识：只许出站 443 时用 HTTPS 或 **SSH over 443**（`ssh.github.com:443`）；
  SSH 长连接更耐抖动——HTTPS 每次 push 重做 TLS 握手，握手失败即报错
- clonzone 2026 对比文要点：**平均 RTT 会骗人，CI 该盯 jitter 和意外 reset**；
  跨境链路瓶颈常在 TLS 拦截/证书库/路径抖动，别把"HTTPS 慢"当定律，同机跑分再定

### 3. 诊断顺序（dev.to 排障清单）

```
curl -s -o /dev/null -w "%{http_code}" https://github.com   # 000 = 完全不通（非服务器错误）
nc -zv github.com 443 -w 5                                  # 端口可达性
traceroute github.com                                       # 断在哪一跳
```

---

## 二、本仓落地：`hooks/git_push_safe.sh`

逐条对应业内做法，不自创参数：

| 业内做法 | 本脚本实现 |
|---|---|
| 5 次 / 3s / factor=2（depot_tools 默认） | `GIT_PUSH_RETRIES=5` `GIT_PUSH_DELAY=3` `GIT_PUSH_DELAY_FACTOR=2`（可用环境变量覆盖） |
| 只重试瞬时错误 | `TRANSIENT_RE`：Could not connect / Connection reset / port 443 / SSL / RPC failed 等；认证类立即失败退出并打印原因 |
| jitter（depot_tools 缺，业内公认该补） | 每次重试前追加 0~1.5s 随机抖动，防多会话同时重试惊群 |
| 切换传输通道（GitHub 官方第 4 招） | HTTPS 耗尽后试 SSH over 443（`git@ssh.github.com`，需已配 SSH key，没有则如实报失败） |
| **终验以 rev-parse 为准** | 推送命令无报错≠成功，必做 `git fetch` + 本地/远端 SHA 比对。本仓实测教训：`timeout` 杀进程后管道返回 0，看似成功实际没推上去 |
| HTTP/1.1 | 本仓实测 HTTP/2 在抖动链路更易整体失败（S226 推送时验证） |

### 退出码契约（三态，M-R60）

- `0` = 远端 SHA 已确认与本机一致（不是"命令没报错"）
- `1` = 非瞬时错误（不重试）或重试+SSH 兜底全部耗尽；提交仍在本地不丢失
- fetch 失败单独标记"无法判定"，不折叠成通过

---

## 三、实测记录（2026-11-03）

```
[push-safe] 推送 origin/master（最多 5 次，指数退避 base=3s factor=2）
[push-safe] 瞬时错误（第 1/5 次）：port 443
[push-safe] 第 2 次重试前等待 3s + jitter 0.47s
[push-safe] 瞬时错误（第 2/5 次）：port 443
[push-safe] 第 3 次重试前等待 6s + jitter 1.22s
```

指数退避按 3→6→12→24s 递增，与 depot_tools 公式一致；jitter 生效。

## 五、二轮业内查证（2026-11-03，S228.2 落地）

用户要求"再多看业内做法"，第二轮补充四项：

| 业内做法 | 来源 | 落地 |
|---|---|---|
| **per-attempt timeout**：超时作用于每次尝试而非整体，挂死连接被杀按瞬时重试 | nick-fields/retry（说明原文：*"a hung connection is killed and retried instead of holding the runner"*） | `GIT_PUSH_ATTEMPT_TIMEOUT=300`；退出码 124 显式列瞬时。**这也是本仓「timeout 假成功」坑的正规解：超时被杀=未确认，绝不算成功** |
| **平台故障降级**：平台挂着就别重试，*"大量重试会放大队列压力"*，走降级预案 | hqwc 排障指南 + GHA 失败目录 | 第 2 次起查 `githubstatus.com/api/v2/status.json`，indicator 非 none 即停止；查不到=无法判定不阻塞（M-R60） |
| **失败分类学**：429/503/限流可重试；401/403、OOM(137)、磁盘满不重试。原则：*"retry the step that talks to a machine you do not control"* | WarpBuild GHA 失败分类表 | TRANSIENT_RE 补 429/503/rate limit/i/o timeout |
| **SSH 协议内心跳**：`ServerAliveInterval 30`（加密、由 sshd 处理，优于裸 TCP keepalive） | 多来源一致（devops.aibit / tsecurity / proxymac） | SSH 兜底命令加 `-o ServerAliveInterval=30 -o ServerAliveCountMax=3` |

### 查到但未采纳（如实记录理由）

- **`core.compression 0`**：针对大文件（75MB+）推送；本仓提交均小，禁压缩反而增大传输量
- **ControlMaster 连接复用**：本仓 SSH 兜底是单次低频调用，复用收益趋零；且 master socket 死掉会连带子会话（新故障面）。若未来高频 SSH 操作再启用
- **MTR/丢包诊断**：运维级工具，本沙箱无 mtr；诊断步骤已录入文档备查
- **Git LFS / 分批推送**：针对大文件仓，本仓不适用

### 二轮实况（S228.2 推送）

```
第 1 次：瞬时错误（443 超时）→ 等 3s+jitter
第 2 次：瞬时错误（port 443）→ 等 6s+jitter
第 3 次：瞬时错误（port 443）→ 等 12s+jitter
第 4 次：✓ 远端已确认收到 master = ed0bd61
```

指数退避 3→6→12s 逐级生效；全程无人工干预。

### 已知小瑕疵

错误摘要行（`瞬时错误（第 N/5 次）：...`）的提取正则比判定正则窄，
个别瞬时错误（如 `i/o timeout`）会被判定重试但摘要显示为空。不影响功能，仅显示层，待修。

## 六、如实声明（一轮 + 二轮合并）

- SSH over 443 兜底在**本沙箱未验证成功路径**（无 SSH key，只验证了失败路径如实报错）；
  成功路径逻辑与 GitHub 文档一致但未经真实推送确认。
- jitter 上限 1.5s 是本仓定的，业内无标准值（depot_tools 为 0）。
- `TRANSIENT_RE` 是按本仓实测错误文本归纳的子集，非 depot_tools 原正则全文；
  遇新错误形态需扩充（明说：这是已知不完整，不是完备集）。
- 不做断点续传：push 中途断线仍是整包重推（git 内部自会做 pack 级去重，够用）。
- per-attempt timeout 300s 与平台降级阈值（第 2 次起查 status）为本仓定的，
  业内只有"要有"没有统一数值；两者都可用环境变量覆盖或按需调整。

