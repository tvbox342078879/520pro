#!/usr/bin/env bash
# bootstrap.sh —— 520pro 换机司（一键换机 / 新设备初始化 / 重装迁移）
#
# 用法:
#   bash bootstrap.sh <repo_url_or_path> [shape] [target] [--dry-run] [--install]
#
#   shape  : full(默认，全量) | lite(探源司最小可跑集)
#   target : 目标目录，默认 ~/520pro
#   --dry-run : 只打印将执行的命令，不落盘
#   --install : 换机完成后自动执行 install.sh --user-skill
#
# 三条承诺（与 tvbox-eco 换机司对齐，按 520pro 结构重写）:
#   ① 幂等      同命令可重跑；目标已是本仓 → 跳过 clone，仅 git pull --ff-only + 重设稀疏
#   ② 零明文     token 仅从 $GITHUB_TOKEN / gh auth token 读入内存，用完立即 unset，
#                不写 .git/config、不写 .netrc、不打印含 token 的 URL
#   ③ 失败显式  任何步骤失败 → 中文报错 + exit 非 0，不静默降级
#
# 稀疏检出集合以 MANIFEST.json 的 sync_shape 为单一真源，不可读时回退内置清单。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ────────────────────────── 参数解析 ──────────────────────────
REPO_ARG="${1:-}"
SHAPE="full"
TARGET=""
DRY=0
DO_INSTALL=0
POS=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --install) DO_INSTALL=1 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --*) echo "错误: 未知参数 $arg" >&2; exit 2 ;;
    *)
      POS=$((POS+1))
      case $POS in
        1) REPO_ARG="$arg" ;;
        2) SHAPE="$arg" ;;
        3) TARGET="$arg" ;;
        *) echo "错误: 多余参数 $arg" >&2; exit 2 ;;
      esac
      ;;
  esac
done

[ -z "$TARGET" ] && TARGET="$HOME/520pro"

case "$SHAPE" in
  full|lite) ;;
  *) echo "错误: 未知 shape '$SHAPE'（仅支持 full / lite）" >&2; exit 2 ;;
esac

if [ -z "$REPO_ARG" ]; then
  cat >&2 <<'EOF'
用法: bash bootstrap.sh <repo_url_or_path> [shape] [target] [--dry-run] [--install]

  shape 可选: full(默认) / lite
  target 缺省: ~/520pro

例（本地路径，无需 token）:
  bash bootstrap.sh /workspace/520pro full /tmp/eco
例（远程，私有 fork 需 GITHUB_TOKEN）:
  GITHUB_TOKEN=*** bash bootstrap.sh https://github.com/you/520pro.git lite ~/520pro --install
EOF
  exit 2
fi

command -v git >/dev/null 2>&1 || { echo "错误: 未找到 git，请先安装。" >&2; exit 1; }

say() { printf '%s\n' "$*"; }
run() {  # dry-run 时只打印
  if [ "$DRY" = 1 ]; then say "  [dry-run] $*"; else eval "$@"; fi
}

say "=========================================="
say "520pro 换机司 bootstrap"
say "  源:       $REPO_ARG"
say "  shape:    $SHAPE"
say "  目标:     $TARGET"
say "  预览:     $([ "$DRY" = 1 ] && echo 是 || echo 否)"
say "  装完即装: $([ "$DO_INSTALL" = 1 ] && echo 是 || echo 否)"
say "=========================================="

# ────────────────────── 源类型 + token（仅内存）──────────────────────
case "$REPO_ARG" in
  http://*|https://*) is_remote=1 ;;
  *)                  is_remote=0 ;;
esac

TOKEN=""
CLONE_URL="$REPO_ARG"
CLONE_MODE=""

if [ "$is_remote" -eq 1 ]; then
  CLONE_MODE=remote
  # 520pro 是公开仓 → 无 token 也能 clone；有 token 则注入（支持私有 fork）
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    TOKEN="$GITHUB_TOKEN"
  elif command -v gh >/dev/null 2>&1; then
    TOKEN="$(gh auth token 2>/dev/null)" || TOKEN=""
  fi
  if [ -n "$TOKEN" ]; then
    CLONE_URL="${REPO_ARG/#https:\/\//https://x-access-token:${TOKEN}@}"
    CLONE_URL="${CLONE_URL/#http:\/\//http://x-access-token:${TOKEN}@}"
    say "[凭证] 使用内存 token（来源: 环境变量或 gh auth），不落盘、不打印"
  else
    say "[凭证] 未提供 token → 按公开仓匿名克隆（若是私有 fork 会失败，请设 GITHUB_TOKEN）"
  fi
else
  # 本地路径
  [ -d "$REPO_ARG/.git" ] || { echo "错误: 源路径 $REPO_ARG 不是 git 仓库（缺 .git）。" >&2; exit 1; }
  missing="$(git -C "$REPO_ARG" rev-list --objects --all --missing=print 2>/dev/null | grep -c '^[?]' || true)"
  missing="${missing:-0}"
  if [ "$missing" -gt 0 ]; then
    if [ -n "${GITHUB_TOKEN:-}" ]; then
      TOKEN="$GITHUB_TOKEN"
      origin_url="$(git -C "$REPO_ARG" config remote.origin.url 2>/dev/null)"
      [ -n "$origin_url" ] || { echo "错误: 源是部分克隆且缺 $missing 个对象，但无 origin 可补全。" >&2; exit 1; }
      CLONE_URL="${origin_url/#https:\/\//https://x-access-token:${TOKEN}@}"
      CLONE_MODE=remote
      say "[注意] 源是部分克隆且本地缺 $missing 个对象 → 改从 origin 远程克隆（已注入内存 token）"
    else
      echo "错误: 源仓库是部分克隆，本地缺 $missing 个对象（promisor），无法离线补全。" >&2
      echo "      请设置 GITHUB_TOKEN 后重跑，或在源仓库先 'git fetch' 补全对象。" >&2
      exit 1
    fi
  else
    CLONE_MODE=local_complete
    say "[判定] 源为本地完整仓库 → 离线克隆（不注入 token）"
  fi
fi

# ────────────────────── 稀疏检出（MANIFEST 为单一真源）──────────────────────
FALLBACK_FULL=( "MANIFEST.json" "install.sh" "verify.sh" "README.md" "TEST.md" "手机指令.md" "通用层/" "能力层/" "docs/" )
FALLBACK_LITE=( "MANIFEST.json" "install.sh" "verify.sh" "通用层/rules/" "通用层/skills/" "能力层/tvbox/skills/probe-hub/" "能力层/tvbox/skills/tvbox-source-hub/" "能力层/tvbox/scripts/" )

apply_sparse() {
  local -a sets=() raw=()
  if [ -f MANIFEST.json ] && command -v python3 >/dev/null 2>&1; then
    mapfile -t raw < <(python3 - "$SHAPE" MANIFEST.json <<'PY' 2>/dev/null
import json,sys
shape, f = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(f, encoding='utf-8'))
    s = (d.get('sync_shape') or {}).get(shape) or []
    for x in s:
        if str(x).strip():
            print(str(x).strip())
except Exception:
    pass
PY
)
    # 过滤空行：早期版本 MANIFEST 无 sync_shape 时 python 可能只输出空行，
    # 若把空串当 pattern 写入 sparse-checkout，git read-tree 会把工作区清空。
    local line
    for line in ${raw[@]+"${raw[@]}"}; do
      [ -n "$line" ] && sets+=("$line")
    done
  fi
  if [ "${#sets[@]}" -eq 0 ]; then
    case "$SHAPE" in
      lite) sets=("${FALLBACK_LITE[@]}") ;;
      *)    sets=("${FALLBACK_FULL[@]}") ;;
    esac
    say "  · MANIFEST.sync_shape 不可读 → 用内置 $SHAPE 清单"
  else
    say "  · 稀疏集合取自 MANIFEST.sync_shape.$SHAPE"
  fi

  # 硬防护：集合为空绝不写 sparse-checkout（空 pattern 会清空工作区）
  if [ "${#sets[@]}" -eq 0 ]; then
    echo "错误: 稀疏检出集合为空，拒绝执行（避免清空工作区）。" >&2
    return 1
  fi

  if [ "$DRY" = 1 ]; then
    say "  [dry-run] git sparse-checkout init --no-cone"
    say "  [dry-run] 写入 .git/info/sparse-checkout: ${sets[*]}"
    say "  [dry-run] git read-tree -mu HEAD"
    return 0
  fi

  git sparse-checkout init --no-cone >/dev/null 2>&1 || true
  mkdir -p .git/info
  printf '%s\n' "${sets[@]}" > .git/info/sparse-checkout
  if ! git read-tree -mu HEAD >/dev/null 2>&1; then
    echo "错误: 应用稀疏检出失败（集合: ${sets[*]}）。" >&2
    return 1
  fi
  say "  ✔ 稀疏检出完成: ${sets[*]}"
  return 0
}

# ────────────────────── 克隆 / 幂等 ──────────────────────
if [ -d "$TARGET/.git" ] && [ -f "$TARGET/MANIFEST.json" ]; then
  say "[幂等] 目标已是 520pro 仓库 → 跳过 clone"
  cd "$TARGET" || { echo "错误: 无法进入 $TARGET。" >&2; exit 1; }
  if [ "$DRY" = 1 ]; then
    say "  [dry-run] git pull --ff-only"
  elif git pull --ff-only >/dev/null 2>&1; then
    say "  ✔ 已拉取最新"
  else
    say "  ⚠ git pull 失败（可能无网络/无 remote）→ 以本地副本为准继续"
  fi
  apply_sparse || exit 1
else
  if [ -e "$TARGET" ]; then
    if [ "$DRY" = 1 ]; then
      say "  ⚠ 目标目录已存在且非本仓 → 真跑会拒绝覆盖（预览继续）"
    else
      echo "错误: $TARGET 已存在但不是 520pro 仓库（缺 .git 或 MANIFEST.json），拒绝覆盖。" >&2
      echo "      请换一个目录，或手动确认后删除该目录。" >&2
      exit 1
    fi
  fi

  say "[步骤1] 克隆 (mode=$CLONE_MODE)..."
  if [ "$DRY" = 1 ]; then
    if [ "$CLONE_MODE" = local_complete ]; then
      say "  [dry-run] git clone <src> $TARGET"
    else
      say "  [dry-run] git clone --depth 1 --filter=blob:none --sparse <src> $TARGET"
    fi
    say "  [dry-run] cd $TARGET && 应用稀疏检出"
    say "  [dry-run] 断言关键文件"
    [ "$DO_INSTALL" = 1 ] && say "  [dry-run] bash install.sh --user-skill"
    say
    say "预览结束，未写入任何文件。"
    exit 0
  fi

  if [ "$CLONE_MODE" = local_complete ]; then
    git clone "$CLONE_URL" "$TARGET" >/dev/null 2>&1 || {
      echo "错误: 本地克隆失败（检查源路径/权限）。" >&2; rm -rf "$TARGET"; exit 1; }
  else
    git clone --depth 1 --filter=blob:none --sparse "$CLONE_URL" "$TARGET" >/dev/null 2>&1 || {
      echo "错误: git clone 失败（检查网络/凭证/仓库地址）。" >&2; rm -rf "$TARGET"; exit 1; }
  fi
  say "  ✔ 克隆成功"
  cd "$TARGET" || { echo "错误: 无法进入 $TARGET。" >&2; exit 1; }
  apply_sparse || exit 1
fi

# token 用完即弃
unset TOKEN CLONE_URL 2>/dev/null || true

# ────────────────────── 断言 ──────────────────────
say "[步骤2] 断言关键文件..."
ok=1
check() { if [ -e "$1" ]; then say "  ✔ $1"; else echo "  ✘ 缺失 $1" >&2; ok=0; fi; }

check "MANIFEST.json"
check "install.sh"
check "verify.sh"

if [ "$SHAPE" = full ]; then
  check "通用层/rules/core-8.md"
  for s in artifact-store feature-gate machine-bootstrap skill-evolution; do
    check "通用层/skills/$s/SKILL.md"
  done
  for s in probe-hub tvbox-source-hub tvbox-interface tvbox-source-blacklist tvbox-config-sync; do
    check "能力层/tvbox/skills/$s/SKILL.md"
  done
  for p in collect_repos.py check_live.py merge_config.py; do
    check "能力层/tvbox/scripts/$p"
  done
else
  check "通用层/rules/core-8.md"
  check "能力层/tvbox/skills/probe-hub/SKILL.md"
fi

# 探源司的硬依赖：缺 core.py 必然 ModuleNotFoundError
check "能力层/tvbox/skills/tvbox-source-hub/scripts/core.py"

# ────────────────────── 可选：立即安装到用户级 ──────────────────────
if [ "$DO_INSTALL" = 1 ] && [ "$ok" -eq 1 ]; then
  say "[步骤3] 安装到用户级（install.sh --user-skill）..."
  if bash install.sh --user-skill; then
    say "  ✔ 已安装到 \$HOME/.codebuddy"
  else
    echo "  ✘ 安装失败" >&2; ok=0
  fi
fi

say "=========================================="
if [ "$ok" -eq 1 ]; then
  say "换机成功: 有界工作副本已就绪 @ $TARGET (shape=$SHAPE)"
  say "下一步: cd $TARGET && bash verify.sh"
  [ "$DO_INSTALL" -eq 0 ] && say "         bash install.sh --user-skill   # 装到 ~/.codebuddy"
  say "=========================================="
  exit 0
else
  echo "换机失败: 关键文件缺失或安装失败，见上。" >&2
  say "=========================================="
  exit 1
fi
