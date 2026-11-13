#!/usr/bin/env bash
# 520pro · 一行收尾（v0.8.29）：优化完跑这条 = 验证 + 对账 + 推送
# ------------------------------------------------------------------
# 借鉴 908 DmaxPro908「sync.sh 一行同步」的心智；实现只走本仓正本：
#   验证 = verify.sh（判据唯一真源）  推送 = hooks/git_push_safe.sh（重试 + 远端确认）
# 与 908 版的三个有意差异：
#   1. 不做自动收集/自动提交——提交必须过 pre-commit 闸（B-10），产物不进 git（B-09 落资料库）
#   2. 不强制推送——git_push_safe.sh 重试 + 远端 sha 终验，毁历史的事不干
#   3. 不内嵌令牌——零明文凭证（B-05），凭据走环境变量/凭证管理器
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "✗ 不在 git 仓库内"; exit 1; }
cd "$ROOT" || exit 1

echo "[sync] ① 仓库自检（verify.sh）"
if ! bash verify.sh; then
  echo "✗ 自检未过，不推送（先修红项；不许带病同步）"
  exit 2
fi

echo "[sync] ② 与远端对账（fetch 设 60s 超时，失败按无法判定处理不冒充一致）"
if timeout 60 git fetch origin main --quiet 2>/dev/null; then
  LOCAL="$(git rev-parse HEAD)"
  REMOTE="$(git rev-parse origin/main 2>/dev/null || echo unknown)"
  if [ "$LOCAL" = "$REMOTE" ]; then
    echo "✓ 本地与远端一致（${LOCAL:0:7}），无新提交，无需推送"
    exit 0
  fi
  echo "  本地 ${LOCAL:0:7} ≠ 远端 ${REMOTE:0:7}，继续推送"
else
  echo "  ⚠ fetch 失败/超时（无法判定远端状态，B-02 不折叠成一致）；仍按本地视角继续"
fi

echo "[sync] ③ 推送（git_push_safe.sh：瞬时错误重试 + 远端 sha 终验）"
bash hooks/git_push_safe.sh
