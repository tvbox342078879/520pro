#!/usr/bin/env bash
# ============================================================
#  520pro · 融合部署
#  ------------------------------------------------------------
#  【融合思路】把我的"平台硬机制"接到你的"可移植业务"上：
#    · 通用层 → 用户级 ~/.codebuddy/（规则跨项目、技能被平台注册可路由）
#    · 能力层 → 两种模式二选一：
#        --user-skill      ：TVBox 装到用户级 ~/.codebuddy/（★推荐：路由可靠、跨项目、云端沙箱执行、手机可触发）
#        --capability-only ：TVBox 装到指定项目 .codebuddy/（隔离，仅本项目）
#    · 默认 all = 通用层→用户级 + 能力层→项目级（项目隔离版）
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET="$(pwd)"
SCOPE="all"      # all | generic | capability | user-skill
DRY=0
TS="$(date +%Y%m%d%H%M%S)"

usage() {
  cat <<'EOF'
用法:
  bash install.sh [选项]

模式（四选一，默认 all）:
  --user-skill        通用层 + TVBox 全部装【用户级】~/.codebuddy/  ★推荐
                      路由可靠、跨项目、云端沙箱可执行、手机登录同账号可触发
  --capability-only   TVBox 装【项目级】<目标>/.codebuddy/（项目隔离）
  --generic-only      只装通用层到 ~/.codebuddy/（不碰 TVBox）
  （默认 all）        通用层→用户级 + 能力层→项目级

其它:
  --target <目录>     能力层/项目级部署到该目录（默认当前目录）
  --dry-run           只打印将做什么，不实际写入
  -h, --help          显示帮助

部署后:
  1) 开【新会话】（规则/技能只在会话启动时加载）
  2) 手机端另按 手机指令.md 手动粘贴（规则文本无法自动同步）
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --target)          TARGET="$2"; shift 2 ;;
    --target=*)        TARGET="${1#*=}"; shift ;;
    --user-skill)      SCOPE="user-skill"; shift ;;
    --capability-only) SCOPE="capability"; shift ;;
    --generic-only)    SCOPE="generic"; shift ;;
    --dry-run)         DRY=1; shift ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "未知参数: $1"; echo; usage; exit 1 ;;
  esac
done

USER_DIR="$HOME/.codebuddy"
PROJ_DIR="$TARGET/.codebuddy"

cp_bak() {  # cp_bak <src> <dst>
  local src="$1" dst="$2"
  if [ "$DRY" = 1 ]; then
    echo "  [dry-run] $src  ->  $dst"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ]; then
    cp -r "$dst" "$dst.bak.$TS" 2>/dev/null || true
    echo "  (备份旧件: $dst.bak.$TS)"
  fi
  cp -r "$src" "$dst"
  echo "  ✓ $dst"
}

deploy_generic_user() {
  echo
  echo "【通用层 → $USER_DIR】（跨项目，平台注册可路由）"
  cp_bak "$ROOT/通用层/rules/core-8.md" "$USER_DIR/rules/core-8.md"
  for d in "$ROOT"/通用层/skills/*/; do
    [ -d "$d" ] || continue
    cp_bak "$d" "$USER_DIR/skills/$(basename "$d")"
  done
}

adapt_paths() {  # 把技能里硬编码的 /root/.codebuddy 改成当前 HOME 可解析
  local dir="$1"
  [ "$DRY" = 1 ] && return 0
  [ -d "$dir" ] || return 0
  command -v python3 >/dev/null 2>&1 || { echo "  · 无 python3，跳过路径适配"; return 0; }
  [ -f "$ROOT/能力层/tvbox/fix_paths.py" ] || return 0
  local out
  out="$(python3 "$ROOT/能力层/tvbox/fix_paths.py" "$dir" 2>/dev/null | tail -1)"
  [ -n "$out" ] && echo "  · 路径适配：$out"
}

deploy_tvbox_user() {
  echo
  echo "【TVBox 能力 → $USER_DIR】（★用户级：路由可靠、云端可执行）"
  for d in "$ROOT"/能力层/tvbox/skills/*/; do
    [ -d "$d" ] || continue
    cp_bak "$d" "$USER_DIR/skills/$(basename "$d")"
  done
  adapt_paths "$USER_DIR/skills"
  for f in "$ROOT"/能力层/tvbox/agents/*.md; do
    [ -e "$f" ] || continue
    cp_bak "$f" "$USER_DIR/agents/$(basename "$f")"
  done
  for f in "$ROOT"/能力层/tvbox/commands/*.md; do
    [ -e "$f" ] || continue
    cp_bak "$f" "$USER_DIR/commands/$(basename "$f")"
  done
  for f in "$ROOT"/能力层/tvbox/scripts/*.py; do
    [ -e "$f" ] || continue
    cp_bak "$f" "$USER_DIR/scripts/$(basename "$f")"
  done
  cp_bak "$ROOT/能力层/tvbox/master_config.example.json" "$USER_DIR/tvbox/master_config.example.json"
}

deploy_capability_project() {
  echo
  echo "【能力层 → $PROJ_DIR】（项目隔离）"
  cp_bak "$ROOT/通用层/rules/zh-style.md" "$PROJ_DIR/rules/zh-style.md"
  cp_bak "$ROOT/能力层/tvbox/CODEBUDDY.md" "$PROJ_DIR/CODEBUDDY.md"
  for f in "$ROOT"/能力层/tvbox/rules/*.md; do
    [ -e "$f" ] || continue
    cp_bak "$f" "$PROJ_DIR/rules/$(basename "$f")"
  done
  for d in "$ROOT"/能力层/tvbox/skills/*/; do
    [ -d "$d" ] || continue
    cp_bak "$d" "$PROJ_DIR/skills/$(basename "$d")"
  done
  adapt_paths "$PROJ_DIR/skills"
  for f in "$ROOT"/能力层/tvbox/agents/*.md; do
    [ -e "$f" ] || continue
    cp_bak "$f" "$PROJ_DIR/agents/$(basename "$f")"
  done
  for f in "$ROOT"/能力层/tvbox/commands/*.md; do
    [ -e "$f" ] || continue
    cp_bak "$f" "$PROJ_DIR/commands/$(basename "$f")"
  done
  for f in "$ROOT"/能力层/tvbox/scripts/*.py; do
    [ -e "$f" ] || continue
    cp_bak "$f" "$PROJ_DIR/scripts/$(basename "$f")"
  done
  if [ ! -e "$TARGET/master_config.json" ] && [ "$DRY" = 0 ]; then
    cp "$ROOT/能力层/tvbox/master_config.example.json" "$TARGET/master_config.json"
    echo "  ✓ $TARGET/master_config.json （示例模板，请填入你的源）"
  elif [ "$DRY" = 1 ]; then
    echo "  [dry-run] 若不存在则复制 master_config.example.json -> $TARGET/master_config.json"
  else
    echo "  · 已存在 $TARGET/master_config.json，跳过（不覆盖真配置）"
  fi
}

echo "════════════════════════════════════════════════════"
echo " 520pro 部署   mode=$SCOPE   target=$TARGET   dry=$DRY"
echo " 源: $ROOT"
echo "════════════════════════════════════════════════════"

case "$SCOPE" in
  generic)
    deploy_generic_user ;;
  user-skill)
    deploy_generic_user
    deploy_tvbox_user ;;
  capability)
    deploy_capability_project ;;
  all)
    deploy_generic_user
    deploy_capability_project ;;
esac

echo
echo "════════════════════════════════════════════════════"
echo " ✅ 完成（mode=$SCOPE）。下一步："
echo "   1) 开【新会话】使规则/技能生效（会话启动时才加载）"
echo "   2) 手机端：按 手机指令.md 手动粘进 App 设置→指令"
echo "   3) 测试：照 TEST.md 逐项验证（含路由实测）"
echo "════════════════════════════════════════════════════"
