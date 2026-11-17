#!/usr/bin/env bash
# 三通道安装副本同步（pre-commit 调用，幂等，M5 变更连带）
# ------------------------------------------------------------------
# 通道① 用户级规则：通用层/rules/{core-8.md,施工纪律.md} → ~/.codebuddy/rules/
# 通道② 项目薄壳：能力层/tvbox/CODEBUDDY.md → <仓库>/.codebuddy/CODEBUDDY.md（仅目标已存在时）
# 通道③ 手机指令云端副本：由 pre-commit 单独调 sync_phone_directive.py（本脚本不碰）
#
# ★ 只同步「已存在的安装副本」，不创建新文件——避免提交钩子在用户主目录/项目目录
#   凭空造出未安装通道的副本，也避免制造 git 未跟踪文件。没装就不装（出声跳过）。
# ★ 三态诚实：SYNCED（真复制+回读一致）/ NOOP（sha 相同）/ SKIP（目标不存在）/ FAIL（复制或回读失败）。
#   不把 NOOP/SKIP 说成"已同步"；FAIL 返回非 0。
# ★ 幂等：sha 一致直接短路，不做无谓写入。
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT" || exit 1
USER_DIR="${HOME}/.codebuddy"

sync_one() {
  local src="$1" dst="$2" name="$3"
  if [ ! -f "$src" ]; then
    echo "  · $name：真源不存在（src=$src），跳过"
    return 0
  fi
  if [ ! -e "$dst" ]; then
    echo "  · $name：目标未安装（$dst），SKIP 不创建"
    return 0
  fi
  local ssha dsha after
  ssha="$(sha256sum "$src" | awk '{print $1}')"
  dsha="$(sha256sum "$dst" | awk '{print $1}')"
  if [ "$ssha" = "$dsha" ]; then
    echo "  · $name：NOOP（副本已最新）"
    return 0
  fi
  mkdir -p "$(dirname "$dst")" || { echo "  ✗ $name：无法创建目录"; return 1; }
  if ! cp "$src" "$dst"; then
    echo "  ✗ $name：复制失败"
    return 1
  fi
  after="$(sha256sum "$dst" | awk '{print $1}')"
  if [ "$after" != "$ssha" ]; then
    echo "  ✗ $name：复制后回读不一致（无法判定，不冒充成功）"
    return 1
  fi
  echo "  ✓ $name：SYNCED（真源→副本，回读一致）"
  return 0
}

fail=0
sync_one "$ROOT/通用层/rules/core-8.md"    "$USER_DIR/rules/core-8.md"    "用户级规则 core-8"   || fail=1
sync_one "$ROOT/通用层/rules/施工纪律.md"  "$USER_DIR/rules/施工纪律.md"  "用户级规则 施工纪律" || fail=1
sync_one "$ROOT/能力层/tvbox/CODEBUDDY.md" "$ROOT/.codebuddy/CODEBUDDY.md" "项目薄壳 CODEBUDDY"  || fail=1
exit "$fail"
