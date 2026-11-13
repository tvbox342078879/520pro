# machine-bootstrap · 故障排查（按症状查）

> **怎么用**：换机司的坑集中在"**clone 不全 / 装完不生效**"。
> 机检：`verify/tests/test_troubleshoot.py` 要求 ≥5 条真实条目。

## 1. clone 失败 / 卡住 / 权限拒绝

- **先查**：`BOOTSTRAP_REPO` 环境变量是否设置且可达；私有仓是否配了凭据（凭据只走环境变量，不落盘）。
- **怎么办**：确认 URL 与分支；用 `bootstrap.sh <repo> full <dir>` 正门重跑，它幂等。
- **别做**：不要把 token 写进脚本或命令行历史——零明文凭证（B-05）。

## 2. 稀疏检出后少了目录 / 技能起不来

- **先查**：`MANIFEST.json` 的 `sync_shape` 声明的稀疏集合；实际检出目录对不对。
- **怎么办**：按 `sync_shape` 重跑；不可读时脚本会回退内置清单，看它回退了没有。
- **别做**：不要手工补目录——下次 sparse 重跑还是缺，而且你不知道缺的还有哪些。

## 3. 脚本报"未知参数 --repo / --sparse"

- **先查**：旧文档写错过（2026-11-12 已修）。真实用法是位置参数：`bootstrap.sh <repo> <mode> <dir> [--install]`。
- **怎么办**：`bash bootstrap.sh --help` 看当前真实参数，照它跑。
- **别做**：不要照着记忆里的旧命令硬试（B-08：同类试错两次就回头查入口）。

## 4. 装完了，但规则/技能没生效

- **先查**：规则与技能只在**会话启动时**加载——装完必须开新会话。
- **怎么办**：开新会话后跑 `bash verify.sh` 确认落点齐全；手机端还要手动粘 `手机指令.md`（规则文本不随账号同步）。
- **别做**：不要在当前会话里反复重装——重装一百次也不会热加载。

## 5. 装到了错误的位置（用户级 vs 项目级）

- **先查**：`--user-skill` 装 `~/.codebuddy/`；`--capability-only` 装 `<项目>/.codebuddy/`。看 `MANIFEST.json` 的 `deploy_modes`。
- **怎么办**：按目标 SCOPE 重装；重装前旧目录会打快照（`~/.codebuddy/.520_state/deploy_snapshot.tar.gz`），可回滚。
- **别做**：不要两个模式混装——同一技能两份副本必然漂移（verify 会红）。

## 6. `git push` 卡住十几分钟、一个字都不输出

- **先查**：别急着重试。另开一条**只读**命令确认远端到底动没动：
  `gh api repos/<owner>/<repo>/commits/main --jq .sha` 对比本地 `git rev-parse HEAD`。
  远端 sha 没变 = 真没推上去；变了 = push 其实成功、只是进程没退出。
- **怎么办**：`GIT_HTTP_VERSION=HTTP/1.1 git push -v origin main`。
  2026-11-12 实测：HTTP/2 下 push 挂 13 分钟零输出，切 HTTP/1.1 后 3 秒完成
  （`POST git-receive-pack (35321 bytes)` → `8418cd4..f59bdf0`）。仓库只有 9MB、待推 1 个 commit，
  所以不是体积问题，是协议层握手挂起。
- **别做**：不要在 `gh api` 显示远端 sha 没变之前就 `git push --force`——
  万一那头其实已经收到了，force 会把别人的提交覆盖掉。也**别**在同一个卡住的进程上反复敲回车。
- **正本入口（v0.8.21 起）**：别手敲上面这些——520pro 仓库自带
  `hooks/git_push_safe.sh`（S228 落地：5 次指数退避 + jitter + 只重试瞬时错误 +
  单次限时 + rev-parse 终验 + SSH over 443 兜底）。推送一律
  `bash hooks/git_push_safe.sh [remote] [branch]`，结果用
  `bash hooks/git_push_safe.sh --status` 事后确认（三态）。本条保留手工步骤作原理说明。
