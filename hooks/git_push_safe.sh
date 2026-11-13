#!/usr/bin/env bash
# git_push_safe.sh — Git 远端推送安全包装（v0.8.21 自旧生态 tvbox-eco 随迁适配）
#
# ★ 520pro 推送纪律（正本入口）：向 GitHub 推送一律走本脚本，禁止裸 `git push`。
#   依据见 能力层/tvbox/skills/probe-hub/references/S228_Git远端卡顿_业内做法与safe推送.md
#   与 通用层/skills/machine-bootstrap/docs/TROUBLESHOOTING.md 第 6 条（HTTP/2 挂死实测）。
#
# 业内依据（2026-11-03 查证，2026-11-13 随迁进 520pro）：
#   1. git 本身不支持重试（StackOverflow 35014012），必须外包 wrapper —— Chromium
#      depot_tools/git_retry.py：默认 5 次、基础延迟 3s、指数退避 factor=2
#   2. 只重试**瞬时错误**；认证/权限错误不重试（git_retry.shouldRetry 只匹配
#      GIT_TRANSIENT_ERRORS_RE）—— 对 Permission denied 重试 5 次是纯浪费
#   3. jitter：depot_tools 没做（它的缺陷），多人 CI 同时重试会惊群；本脚本补上
#   4. HTTPS 抖动时切 SSH over 443（GitHub 官方排障文档"切换克隆方法"）
#   5. 终验以 git rev-parse 远端比对为准，不以退出码为准 ——
#      实测教训：timeout 杀进程后管道返回 0，看起来像成功实际没推上去（2026-11-12
#      520pro 又复验一次：HTTP/2 挂死 13 分钟零输出，切 HTTP/1.1 秒过）
#
# 用法: bash hooks/git_push_safe.sh [remote] [branch]
#   remote 默认 origin，branch 默认当前分支
#   bash hooks/git_push_safe.sh --status   # 查最近一次推送结果（不发起推送）
# 退出码: 0=远端已确认收到；1=不可重试错误或重试耗尽；2=无记录无法判定（三态，不折叠）
#
# 异步纪律：推送放后台跑、立即返回，结果经完成通知 / --status 事后确认，
#   禁止同步阻塞等推送（详见 S228 第五节）。
set -uo pipefail

LOG_DIR="${HOME}/.codebuddy"
LOG_FILE="${LOG_DIR}/push-safe-last.log"
REMOTE="${1:-origin}"
BRANCH="${2:-$(git rev-parse --abbrev-ref HEAD)}"

# --status：读最近一次结果，三态输出（M-R60：没跑过=没查到≠失败）
if [ "${1:-}" = "--status" ]; then
  if [ ! -f "$LOG_FILE" ]; then
    echo "⚠ 无法判定：尚无推送记录（$LOG_FILE 不存在）—— 没查到 ≠ 没有"
    exit 2
  fi
  tail -5 "$LOG_FILE"
  grep -q "✓ 远端已确认" "$LOG_FILE" && { echo "✓ 最近一次推送：成功"; exit 0; }
  grep -q "✗" "$LOG_FILE" && { echo "✗ 最近一次推送：失败（详情见上）"; exit 1; }
  echo "⚠ 无法判定：日志无成功/失败标记"; exit 2
fi
MAX_RETRIES="${GIT_PUSH_RETRIES:-5}"        # depot_tools DEFAULT_RETRY_COUNT=5
BASE_DELAY="${GIT_PUSH_DELAY:-3}"           # depot_tools DEFAULT_DELAY_SECS=3
FACTOR="${GIT_PUSH_DELAY_FACTOR:-2}"        # 指数退避倍数（0=线性 1=恒定）
ATTEMPT_TIMEOUT="${GIT_PUSH_ATTEMPT_TIMEOUT:-300}"  # 每次尝试单独限时（nick-fields/retry 设计：per-attempt，非整体）
VERBOSE="${GIT_PUSH_VERBOSE:-0}"            # 1=GIT_TRACE 全开（业内调试模式）

# 已知瞬时错误（对齐 git_retry 的 shouldRetry 思路，按实测错误文本扩充；
# 失败分类学：429/503/限流可重试；401/403 认证类、OOM(137)、磁盘满绝不在此列。
# 2026-11-13 520pro 实测新增 Empty reply from server——服务器空响应=链路抖动，
# 狗粮测试首推即撞上，旧白名单漏了它导致误判非瞬时。）
TRANSIENT_RE='Could not (resolve host|connect)|Connection (reset|timed out)|port 443|Connection refused|SSL_|GnuTLS|RPC failed|early EOF|index-pack failed|the remote end hung up|Failed to connect|HTTP (429|503)|rate limit|too many requests|i/o timeout|Exit code 124|Empty reply from server|Connection was reset by peer|connection closed by remote'

log() { echo "[push-safe] $*" | tee -a "$LOG_FILE" >&2; }

# 瞬时错误判定：匹配才允许重试
is_transient() {
  echo "$1" | grep -qE "$TRANSIENT_RE"
}

# 随机抖动 0~1.5s，防多人同时重试惊群（depot_tools 没做，业内公认该补）
jitter() { python3 -c "import random;print(round(random.uniform(0,1.5),2))"; }

# —— 终验：不以退出码判定，直接问远端 ——
verify_pushed() {
  local local_sha remote_sha
  git fetch --quiet "$REMOTE" "$BRANCH" 2>/dev/null || return 2   # fetch 失败=无法判定
  local_sha="$(git rev-parse "refs/heads/$BRANCH")"
  remote_sha="$(git rev-parse "refs/remotes/$REMOTE/$BRANCH")"
  [ "$local_sha" = "$remote_sha" ]
}

attempt_push() {
  # http.version=HTTP/1.1：本仓实测 HTTP/2 在抖动链路上更易整体失败
  # per-attempt timeout（nick-fields/retry 设计）：挂死的 push 被杀掉按瞬时重试，
  # 而不是等 133s+。退出码 124 显式视为瞬时 —— 这也是本仓「timeout 假成功」坑的正规解：
  # 超时被杀=未确认，绝不算成功。
  local trace=""
  [ "$VERBOSE" = "1" ] && trace="GIT_TRACE=1 GIT_CURL_VERBOSE=1 GIT_TRACE_PACKET=1"
  local out rc
  out=$( (cd "$PWD" && env $trace timeout "$ATTEMPT_TIMEOUT" \
    env GIT_HTTP_LOW_SPEED_LIMIT=0 GIT_HTTP_POST_BUFFER=524288000 \
    git -c http.version=HTTP/1.1 push "$REMOTE" "$BRANCH") 2>&1 )
  rc=$?
  if [ "$rc" -eq 124 ]; then
    echo "Exit code 124: push attempt exceeded ${ATTEMPT_TIMEOUT}s (per-attempt timeout)"
  fi
  echo "$out"
}

# 平台故障降级（hqwc 排障指南）：连续失败时查 GitHub status，平台挂着就不该硬重试。
# 只读一次、失败不阻塞（status 查不到=无法判定，继续按原流程）。
check_platform_status() {
  local code
  code=$(curl -sS -o /tmp/gh_status.json -w '%{http_code}' --max-time 8 \
    https://www.githubstatus.com/api/v2/status.json 2>/dev/null) || return 2
  [ "$code" = "200" ] || return 2
  python3 -c "
import json
try:
    d=json.load(open('/tmp/gh_status.json'))
    ind=d.get('status',{}).get('indicator','')
    print(ind)
except Exception:
    print('unknown')
" 2>/dev/null
}

main() {
  local attempt=1 delay=0 err=""
  : > "$LOG_FILE"   # 每次新推送重置最近结果
  log "推送 $REMOTE/$BRANCH（最多 $MAX_RETRIES 次，指数退避 base=${BASE_DELAY}s factor=${FACTOR}，单次限时 ${ATTEMPT_TIMEOUT}s）"

  while [ "$attempt" -le "$MAX_RETRIES" ]; do
    if [ "$delay" -gt 0 ]; then
      local j; j="$(jitter)"
      log "第 ${attempt} 次重试前等待 ${delay}s + jitter ${j}s"
      sleep "$delay"; sleep "$j"
    fi

    err="$(attempt_push)"
    vrc=0
    if [ -z "$(echo "$err" | grep -E '^fatal|^error')" ]; then
      # 退出码不可信，问远端。verify 三态：0=已确认 2=fetch失败无法判定
      verify_pushed; vrc=$?
      if [ "$vrc" -eq 0 ]; then
        log "✓ 远端已确认收到 $BRANCH = $(git rev-parse --short "refs/heads/$BRANCH")（第 ${attempt} 次尝试）"
        exit 0
      elif [ "$vrc" -eq 2 ]; then
        # ★ S228 实测踩坑：push 可能已成功但验证 fetch 撞上网络抖。
        #   「无法判定」不得折叠成失败（M-R60），按瞬时处理重试——
        #   下轮 push 显示 up-to-date + verify 成功即可自愈。
        log "⚠ 推送无报错但验证 fetch 失败（无法判定，按瞬时网络问题重试）"
        err="Could not connect during push verification (fetch failed)"
      else
        log "⚠ 推送命令无报错但远端未确认（退出码不可信，以 rev-parse 为准）"
        err="remote mismatch after silent push"
      fi
    fi

    if ! is_transient "$err"; then
      log "✗ 非瞬时错误，不重试（业内做法：认证/权限类重试无意义）："
      echo "$err" | grep -E '^fatal|^error' | head -3 | sed 's/^/    /'
      exit 1
    fi

    # 平台故障降级：第 2 次起若 GitHub 官方 status 报故障，停止重试（业内降级预案）
    if [ "$attempt" -ge 2 ]; then
      ind="$(check_platform_status)"
      if [ "$ind" != "none" ] && [ "$ind" != "unknown" ]; then
        log "✗ GitHub 平台状态异常（indicator=$ind），按业内降级预案停止重试："
        log "  平台故障期重试只是放大队列压力；提交已在本地不丢失，稍后重跑本脚本即可"
        exit 1
      fi
    fi

    log "瞬时错误（第 ${attempt}/${MAX_RETRIES} 次）：$(echo "$err" | grep -oE 'Could not connect|Connection (reset|timed out)|port 443|SSL_|Exit code 124|HTTP (429|503)' | head -1)"
    # depot_tools 指数退避：delay = factor^(attempt-1) * base
    if [ "$FACTOR" -eq 0 ]; then
      delay=$((attempt * BASE_DELAY))
    else
      delay=$(( BASE_DELAY * (FACTOR ** (attempt - 1)) ))
    fi
    attempt=$((attempt + 1))
  done

  # 重试耗尽 → 换传输通道（GitHub 官方排障"切换克隆方法"；SSH over 443 走 ssh.github.com）
  log "HTTPS 重试耗尽，尝试 SSH over 443（需已配置 SSH key，没有则如实报失败）"
  local path_part ssh_url
  path_part="$(git remote get-url "$REMOTE" | sed -E 's#https://github\.com/##; s#\.git$##')"
  ssh_url="git@ssh.github.com:${path_part}.git"
  # ServerAliveInterval=30：SSH 协议内加密心跳，防 NAT/防火墙掐空闲连接（业内共识值）
  if GIT_SSH_COMMAND="ssh -p 443 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3" git push "$ssh_url" "$BRANCH" 2>&1 | tail -3; then
    if verify_pushed; then
      log "✓ SSH over 443 推送成功并经 rev-parse 确认"
      exit 0
    fi
  fi
  log "✗ ${MAX_RETRIES} 次 HTTPS + SSH 兜底均失败，远端未确认。最后错误样本："
  echo "$err" | head -3 | sed 's/^/    /'
  log "（提交已在本地，不丢失；建议稍后手动重跑本脚本）"
  exit 1
}

main "$@"
