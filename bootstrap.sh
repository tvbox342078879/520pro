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
  # 520pro 是公开仓 → 默认匿名克隆即可。
  # 实测：带 x-access-token 的 URL 反而更容易被 TLS 断连（GnuTLS -110，重试 3 次全败），
  # 且 token 会被 git 写进 .git/config。所以 token 只当"匿名失败后的兜底"，不作默认。
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    TOKEN="$GITHUB_TOKEN"
  elif command -v gh >/dev/null 2>&1; then
    TOKEN="$(gh auth token 2>/dev/null)" || TOKEN=""
  fi
  CLONE_URL="$REPO_ARG"
  TOKEN_URL=""
  if [ -n "$TOKEN" ]; then
    TOKEN_URL="${REPO_ARG/#https:\/\//https://x-access-token:${TOKEN}@}"
    TOKEN_URL="${TOKEN_URL/#http:\/\//http://x-access-token:${TOKEN}@}"
    say "[凭证] 内存 token 待用（先匿名，失败才升级；用完即清）"
  else
    say "[凭证] 未提供 token → 匿名克隆（公开仓足够；私有 fork 请设 GITHUB_TOKEN）"
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
      CLONE_URL="$origin_url"
      TOKEN_URL="${origin_url/#https:\/\//https://x-access-token:${TOKEN}@}"
      CLONE_MODE=remote
      say "[注意] 源是部分克隆且本地缺 $missing 个对象 → 改从 origin 远程克隆（token 兜底）"
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

# ── 凭证不外落 ──────────────────────────────────────────────
# git 会把含 token 的 clone URL 原样写进 .git/config。实测过：稀疏检出失败提前 exit 时，
# token 就留在盘上了（README 承诺的"零明文"因此是假的）。任何退出路径都要还原 origin：
# EXIT trap 兜底中断/断言失败，成功路径再显式清一次。
scrub_remote() {
  local cfg="$TARGET/.git/config" cur clean
  [ -f "$cfg" ] || return 0
  cur="$(git -C "$TARGET" config --get remote.origin.url 2>/dev/null)" || return 0
  case "$cur" in
    *x-access-token:*)
      clean="$(printf '%s' "$cur" | sed -E 's#https://x-access-token:[^@]*@#https://#')"
      git -C "$TARGET" remote set-url origin "$clean" 2>/dev/null || true
      say "  · 已清除 .git/config 中的 token"
      ;;
  esac
}
[ -n "${TOKEN_URL:-}" ] && trap scrub_remote EXIT

# ────────────────────── 稀疏检出（MANIFEST 为单一真源）──────────────────────
FALLBACK_FULL=( "MANIFEST.json" "install.sh" "verify.sh" "README.md" "TEST.md" "手机指令.md" "通用层/" "能力层/" "docs/" )
FALLBACK_LITE=( "MANIFEST.json" "install.sh" "verify.sh" "通用层/rules/" "通用层/skills/" "能力层/tvbox/skills/probe-hub/" "能力层/tvbox/skills/tvbox-core/" "能力层/tvbox/scripts/" )

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
  local sperr; sperr="$(mktemp)"
  if git read-tree -mu HEAD >/dev/null 2>"$sperr"; then
    rm -f "$sperr"
  else
    # 部分克隆（--filter=blob:none）下 read-tree 要按需拉 blob，弱网会瞬时断。
    # 实测：首次 GnuTLS -110 失败，重试即成功 → 不能一次失败就判定装坏。
    say "  ⚠ 稀疏检出首次失败，重试一次…"
    sleep 1
    if git read-tree -mu HEAD >/dev/null 2>>"$sperr"; then
      rm -f "$sperr"
      say "  ✔ 稀疏检出完成（首次失败已重试成功）: ${sets[*]}"
      return 0
    fi
    echo "错误: 应用稀疏检出失败（集合: ${sets[*]}）。原始报错（已脱敏）:" >&2
    sed -E 's#(x-access-token:)[^@]*@#\1***@#g; s#ghp_[A-Za-z0-9]+#ghp_***#g' "$sperr" \
      | sed -n '1,6p' | sed 's/^/  /' >&2
    rm -f "$sperr"
    return 1
  fi
  say "  ✔ 稀疏检出完成: ${sets[*]}"
  return 0
}

# ────────────────────── 克隆 / 幂等 ──────────────────────
if [ -d "$TARGET/.git" ] && [ -f "$TARGET/MANIFEST.json" ]; then
  say "[幂等] 目标已是 520pro 仓库 → 跳过 clone"
  cd "$TARGET" || { echo "错误: 无法进入 $TARGET。" >&2; exit 1; }
  scrub_remote   # 旧副本可能残留上次的 token（历史版本没清）
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

  # 错误脱敏：URL 里可能含 token，回显前统一打码（保留排障信息，不泄凭证）
  ERRF="$(mktemp)"
  redact() { sed -E 's#(x-access-token:)[^@]*@#\1***@#g; s#ghp_[A-Za-z0-9]+#ghp_***#g; s#github_pat_[A-Za-z0-9_]+#github_pat_***#g'; }
  if [ "$CLONE_MODE" = local_complete ]; then
    if ! git clone "$CLONE_URL" "$TARGET" >/dev/null 2>"$ERRF"; then
      echo "错误: 本地克隆失败（检查源路径/权限）。" >&2
      redact < "$ERRF" | sed -n '1,5p' | sed 's/^/  /' >&2
      rm -f "$ERRF"; rm -rf "$TARGET"; exit 1
    fi
  else
    # 沙箱/弱网实测：GnuTLS recv error (-110) 是随机断连，同一条命令重跑就成功。
    # 一次失败不能判定"装坏"，给 3 次机会。
    ok_clone=0; try=1; cur_url="$CLONE_URL"
    while [ "$try" -le 3 ]; do
      rm -rf "$TARGET"
      if git clone --depth 1 --filter=blob:none --sparse "$cur_url" "$TARGET" >/dev/null 2>"$ERRF"; then
        ok_clone=1; break
      fi
      if [ "$try" -lt 3 ]; then
        if [ "$try" -eq 1 ] && [ -n "$TOKEN_URL" ]; then
          say "  ⚠ 匿名克隆失败 → 换 token 再试（第 2 次）"
          cur_url="$TOKEN_URL"
        else
          say "  ⚠ 克隆失败（第 $try/3 次，弱网常见）→ 3s 后重试"
        fi
        sleep 3
      fi
      try=$((try+1))
    done
    if [ "$ok_clone" -ne 1 ]; then
      echo "错误: git clone 失败（网络/凭证/仓库地址，已重试 3 次）。原始报错（已脱敏）:" >&2
      redact < "$ERRF" | sed -n '1,6p' | sed 's/^/  /' >&2
      rm -f "$ERRF"; rm -rf "$TARGET"; exit 1
    fi
  fi
  rm -f "$ERRF"
  say "  ✔ 克隆成功"
  cd "$TARGET" || { echo "错误: 无法进入 $TARGET。" >&2; exit 1; }
  scrub_remote   # 先清再干活：后面任何一步失败都不会把 token 留在盘上
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
check "VERSION"

if [ "$SHAPE" = full ]; then
  check "通用层/rules/core-8.md"
  for s in artifact-store feature-gate machine-bootstrap skill-evolution learn-hub space-hub inspect-hub; do
    check "通用层/skills/$s/SKILL.md"
  done
  for s in probe-hub tvbox-pipeline; do
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
check "能力层/tvbox/skills/tvbox-core/scripts/core.py"

# ────────────────────── 可选：立即安装到用户级 ──────────────────────
if [ "$DO_INSTALL" = 1 ] && [ "$ok" -eq 1 ]; then
  say "[步骤3] 安装到用户级（install.sh --user-skill）..."
  if bash install.sh --user-skill; then
    say "  ✔ 已安装到 \$HOME/.codebuddy"
  else
    echo "  ✘ 安装失败" >&2; ok=0
  fi
fi

# ────────────────────── 版本化迁移（借 tvbox-eco upgrade.sh 思想，v0.8.0 起）──────────────────────
# 铁律: ① 本地已部署版本记在 ~/.codebuddy/.520_state/version，与仓库 VERSION 对账
#       ② 逐条应用 DEPLOYED → TARGET 之间的 migrate_to_<ver>（一次性动作，全部幂等）
#       ③ 已是最新 → 跳过全部迁移；VERSION 不可读 → 明说无法判定，不瞎迁
#       ④ 新版本发布时在此追加 migrate_to_<ver> 函数并登记进 MIGRATIONS 列表
STATE_DIR="$HOME/.codebuddy/.520_state"
DEPLOYED_VER="$(cat "$STATE_DIR/version" 2>/dev/null || echo "0.0.0")"
TARGET_VER="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || cat VERSION 2>/dev/null || echo "")"

v_ge() {  # $1 >= $2 ?
  [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$2" ]
}

migrate_to_0_6_0() {
  say "  · [0.6.0] 清理 tvbox-janitor 半成品（已被库务司 space-hub 取代）"
  run "rm -rf \"\$HOME/.codebuddy/skills/tvbox-janitor\""
}

migrate_to_0_7_0() {
  say "  · [0.7.0] 清理 skills 顶层 .bak.* 历史备份 + 补装巡检司副本"
  run "rm -rf \"\$HOME\"/.codebuddy/skills/*.bak.*"
  if [ -d "通用层/skills/inspect-hub" ]; then
    run "cp -r 通用层/skills/inspect-hub \"\$HOME/.codebuddy/skills/\""
  fi
}

migrate_to_0_7_1() {
  say "  · [0.7.1] 同步巡检司 v1.1.0 副本（adversarial + 带过执法）"
  if [ -d "通用层/skills/inspect-hub" ]; then
    run "cp -r 通用层/skills/inspect-hub/. \"\$HOME/.codebuddy/skills/inspect-hub/\""
  fi
}

migrate_to_0_8_0() {
  say "  · [0.8.0] 引入版本化迁移机制本身，本版无一次性动作"
}

migrate_to_0_8_1() {
  say "  · [0.8.1] 修复投递链改名断链：同步 tvbox-core/probe-hub 副本（core.py 投递改指 space-hub，探针同步）"
  if [ -d "能力层/tvbox/skills/tvbox-core" ]; then
    run "cp -r 能力层/tvbox/skills/tvbox-core/. \"\$HOME/.codebuddy/skills/tvbox-core/\""
  fi
  if [ -d "能力层/tvbox/skills/probe-hub" ]; then
    run "cp -r 能力层/tvbox/skills/probe-hub/. \"\$HOME/.codebuddy/skills/probe-hub/\""
  fi
}

migrate_to_0_8_2() {
  say "  · [0.8.2] 库务司 v2.1.0（本地欠账 auto_file_local/local-rm）+ 学习工坊 v1.3.0（门面改道）：同步 space-hub/learn-hub 副本"
  if [ -d "通用层/skills/space-hub" ]; then
    run "cp -r 通用层/skills/space-hub/. \"\$HOME/.codebuddy/skills/space-hub/\""
  fi
  if [ -d "通用层/skills/learn-hub" ]; then
    run "cp -r 通用层/skills/learn-hub/. \"\$HOME/.codebuddy/skills/learn-hub/\""
  fi
}

migrate_to_0_8_3() {
  say "  · [0.8.3] 产物纪律 B-09 + 库务司 v2.2.0（archive/products/搜索框）+ 巡检司 v1.2.0（伤门复合）：同步 space-hub/inspect-hub 副本与用户级规则"
  if [ -d "通用层/skills/space-hub" ]; then
    run "cp -r 通用层/skills/space-hub/. \"\$HOME/.codebuddy/skills/space-hub/\""
  fi
  if [ -d "通用层/skills/inspect-hub" ]; then
    run "cp -r 通用层/skills/inspect-hub/. \"\$HOME/.codebuddy/skills/inspect-hub/\""
  fi
  if [ -f "通用层/rules/core-8.md" ]; then
    run "cp 通用层/rules/core-8.md \"\$HOME/.codebuddy/rules/core-8.md\""
  fi
}

migrate_to_0_8_4() {
  say "  · [0.8.4] 总线归目标方：投递门面迁库务司、登记门面迁巡检司，core 中转壳删除——同步 6 个技能副本"
  for _s in tvbox-core probe-hub tvbox-pipeline; do
    if [ -d "能力层/tvbox/skills/$_s" ]; then
      run "cp -r 能力层/tvbox/skills/$_s/. \"\$HOME/.codebuddy/skills/$_s/\""
    fi
  done
  for _s in space-hub inspect-hub learn-hub; do
    if [ -d "通用层/skills/$_s" ]; then
      run "cp -r 通用层/skills/$_s/. \"\$HOME/.codebuddy/skills/$_s/\""
    fi
  done
  # 旧版残留：pipeline 旧 CHANGELOG 名（已并入 CHANGELOG.md）
  run "rm -f \"\$HOME/.codebuddy/skills/tvbox-pipeline/CHANGELOG-interface.md\""
}

migrate_to_0_8_5() {
  say "  · [0.8.5] 部署器修复：cp_bak 不再把源拷成 dst/basename 嵌套；巡检司 target 自解析。清历史嵌套 + 同步副本"
  # 清历史嵌套副本（旧 cp -r 到已存在目录的产物，如 tvbox-core/tvbox-core）
  run "for b in \"\$HOME\"/.codebuddy/skills/*/; do [ -d \"\$b\" ] || continue; n=\$(basename \"\$b\"); if [ -d \"\${b}\${n}\" ]; then rm -rf \"\${b}\${n}\"; fi; done"
  if [ -d "通用层/skills/inspect-hub" ]; then
    run "cp -r 通用层/skills/inspect-hub/. \"\$HOME/.codebuddy/skills/inspect-hub/\""
  fi
}

migrate_to_0_8_6() {
  say "  · [0.8.6] 备份改为整目录单份快照（.520_state/，v0.8.7 起改名 deploy_snapshot.tar.gz）：清历史 skills/*.bak.* 目录"
  run "find \"\$HOME/.codebuddy/skills\" -maxdepth 1 -type d -name '*.bak.*' -exec rm -rf {} + 2>/dev/null || true"
}

migrate_to_0_8_7() {
  say "  · [0.8.7] 部署快照改名 deploy_snapshot.tar.gz（与 tvbox snapshot 数据快照区分）：迁移旧文件名"
  run "if [ ! -f \"\$HOME/.codebuddy/.520_state/deploy_snapshot.tar.gz\" ]; then mv \"\$HOME/.codebuddy/.520_state/skills_snapshot.tar.gz\" \"\$HOME/.codebuddy/.520_state/deploy_snapshot.tar.gz\" 2>/dev/null || true; else rm -f \"\$HOME/.codebuddy/.520_state/skills_snapshot.tar.gz\"; fi"
}

migrate_to_0_8_8() {
  say "  · [0.8.8] 探源司 1.26.0 并回（repair/forgekit/hls_clean/forge_gate/verify 闸门）：清旧 pyc，缺件提示重装"
  run "rm -rf \"\$HOME/.codebuddy/skills/probe-hub/repair/__pycache__\" \"\$HOME/.codebuddy/skills/probe-hub/forgekit/__pycache__\" \"\$HOME/.codebuddy/skills/probe-hub/verify/__pycache__\" 2>/dev/null; true"
  if [ ! -d "$HOME/.codebuddy/skills/probe-hub/repair" ]; then
    say "  ⚠ 探源司 repair/ 未落地 → 请重跑 bash install.sh --user-skill"
  fi
}

MIGRATIONS=( "0.6.0" "0.7.0" "0.7.1" "0.8.0" "0.8.1" "0.8.2" "0.8.3" "0.8.4" "0.8.5" "0.8.6" "0.8.7" "0.8.8" )

say "[步骤4] 版本迁移（已部署 v$DEPLOYED_VER → 目标 v${TARGET_VER:-未知}）..."
if [ -z "$TARGET_VER" ]; then
  say "  ⚠ 仓库 VERSION 不可读 → 无法判定迁移区间，跳过迁移（不瞎迁）"
elif v_ge "$DEPLOYED_VER" "$TARGET_VER"; then
  say "  ✔ 已是最新（v$DEPLOYED_VER），幂等跳过全部迁移"
else
  applied=0
  for v in "${MIGRATIONS[@]}"; do
    if v_ge "$TARGET_VER" "$v" && ! v_ge "$DEPLOYED_VER" "$v"; then
      "migrate_to_$(echo "$v" | tr '.' '_')"
      applied=1
    fi
  done
  if [ "$DRY" = 1 ]; then
    say "  [dry-run] mkdir -p $STATE_DIR && 写入 version=$TARGET_VER"
  else
    mkdir -p "$STATE_DIR"
    printf '%s\n' "$TARGET_VER" > "$STATE_DIR/version"
    say "  ✔ 迁移完成，已部署标记更新为 v$TARGET_VER"
  fi
  [ "$applied" -eq 0 ] && say "  ⚠ 无迁移被应用（目标版本未高于已部署？标记可能超前）"
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
