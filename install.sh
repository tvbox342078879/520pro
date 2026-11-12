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
  3) 回滚：安装前的整目录快照在 ~/.codebuddy/.520_state/deploy_snapshot.tar.gz（只留最近一份）
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

# 运行时数据：装在技能 scripts/ 下、随使用增长。有的不在 git（巡检历史/库务司状态），
# 有的是「入库的种子 + 现场会增长」（探源司监测台 monitor_*.json、壳源候选 shellcrack_cands.json）。
# 覆盖安装会先删目标，这几个必须先搬走再回填，否则每装一次丢一次巡检历史/监测目标/候选。
RUNTIME_FILES="findings_history.json monitors.json space_hub_state.json monitor_targets.json monitor_domains.json monitor_pubsources.json dead_repos.json shellcrack_cands.json"

# 回滚快照：安装前整目录压一次，只留最近一份（v0.8.6）。
# 替代此前每个目标各留一份 .bak.<TS> —— 2026-11-12 实测 10 份目录合计 13MB，
# 其中重复内容占大半；整目录压缩后 3.2MB，且回滚点唯一、不会越装越多。
SNAP_FILE="$HOME/.codebuddy/.520_state/deploy_snapshot.tar.gz"
SNAP_OLD="$HOME/.codebuddy/.520_state/skills_snapshot.tar.gz"  # v0.8.6 及更早的旧名，升级时自动迁移

deploy_snapshot() {
  if [ "$DRY" = 1 ]; then
    echo "  [dry-run] 快照 -> $SNAP_FILE（仅一份，覆盖旧快照）"
    return 0
  fi
  local items=() p
  # 旧名迁移（v0.8.7）：skills_snapshot → deploy_snapshot，与 `tvbox snapshot`（数据快照）区分开。
  # 新旧同时存在时只留新的，避免又出现"两个版本"。
  if [ -f "$SNAP_OLD" ]; then
    if [ ! -f "$SNAP_FILE" ]; then
      mv "$SNAP_OLD" "$SNAP_FILE"
      echo "  · 旧快照改名: skills_snapshot.tar.gz → deploy_snapshot.tar.gz"
    else
      rm -f "$SNAP_OLD"
      echo "  · 已清旧名快照（新名已存在）"
    fi
  fi
  for p in skills rules agents commands scripts tvbox; do
    if [ -e "$HOME/.codebuddy/$p" ]; then items+=("$p"); fi
  done
  if [ ${#items[@]} -eq 0 ]; then return 0; fi
  mkdir -p "$(dirname "$SNAP_FILE")"
  if tar -czf "$SNAP_FILE.tmp" -C "$HOME/.codebuddy" \
       --exclude='*.bak.*' --exclude='__pycache__' "${items[@]}" 2>/dev/null; then
    mv "$SNAP_FILE.tmp" "$SNAP_FILE"
    # 清历史逐目标 .bak.<TS>（v0.8.5 及更早产物），已被整目录快照取代
    find "$HOME/.codebuddy/skills" -maxdepth 1 -type d -name '*.bak.*' -exec rm -rf {} + 2>/dev/null || true
    echo "  (安装前快照: $SNAP_FILE  $(du -h "$SNAP_FILE" | cut -f1)，只留这一份)"
  else
    rm -f "$SNAP_FILE.tmp"
    echo "  ⚠ 快照失败（不阻断安装；回滚真源在仓库 git）"
  fi
}

cp_bak() {  # cp_bak <src> <dst>
  local src="$1" dst="$2"
  if [ "$DRY" = 1 ]; then
    echo "  [dry-run] $src  ->  $dst"
    return 0
  fi
  case "$dst" in
    ""|"/"|"$HOME") echo "  ✗ 拒绝操作危险路径: '$dst'"; return 1 ;;
  esac
  mkdir -p "$(dirname "$dst")"
  # 逐目标 .bak 已废弃（v0.8.6）：备份统一由 deploy_snapshot 在安装前做一份整目录快照（与 tvbox snapshot 数据快照无关）
  # 覆盖安装：先删目标再拷。此前直接 `cp -r src dst` 且 dst 已存在时，
  # cp 会把源拷成 dst/basename —— 2026-11-12 实测生成
  # ~/.codebuddy/skills/tvbox-core/tvbox-core 全量副本（1.1M），
  # 技能目录里出现"第二份实现"，改哪份生效都说不清。
  local tmpdir="" f
  if [ -d "$dst/scripts" ]; then
    for f in $RUNTIME_FILES; do
      [ -e "$dst/scripts/$f" ] || continue
      [ -n "$tmpdir" ] || tmpdir="$(mktemp -d)"
      cp -a "$dst/scripts/$f" "$tmpdir/$f"
    done
  fi
  if [ -e "$dst" ]; then rm -rf "$dst"; fi
  cp -r "$src" "$dst"
  # ★ 源目录里的运行时文件是**本机私产**（186 条监测目标 / 死册 / 候选册 / state），
  #   绝不能随安装漏到目标机：gitignore 只挡 git clone，挡不住"从仓库目录 cp 过去"。
  #   2026-11-12 实测：HOME=/tmp/blank 空机安装后探源司里出现 185 个目标——就是这一步漏的。
  #   所以 cp 完先删源带来的那份，再回填现场那份（若有）。
  if [ -d "$dst/scripts" ]; then
    for f in $RUNTIME_FILES; do
      [ -e "$dst/scripts/$f" ] && rm -f "$dst/scripts/$f"
    done
  fi
  if [ -n "$tmpdir" ]; then
    mkdir -p "$dst/scripts"
    local kept=""
    for f in $RUNTIME_FILES; do
      [ -e "$tmpdir/$f" ] || continue
      # 现场优先：仓库工作区里可能残留一份过期的运行时文件，装完不能反把现场盖掉
      cp -a "$tmpdir/$f" "$dst/scripts/$f"
      kept="$kept $f"
    done
    rm -rf "$tmpdir"
    echo "  · 已保留运行时数据（${kept:-无}）"
  fi
  echo "  ✓ $dst"
}

check_no_nested() {  # 防 cp 语义回归：技能目录里不允许再出现同名子目录
  local base="$1" name
  [ -d "$base" ] || return 0
  name="$(basename "$base")"
  if [ -d "$base/$name" ]; then
    echo "  ✗ 嵌套副本：$base/$name"
    return 1
  fi
  return 0
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
  # lite 形状不含配置模板，缺失时跳过（不阻断安装）
  if [ -e "$ROOT/能力层/tvbox/master_config.example.json" ]; then
    cp_bak "$ROOT/能力层/tvbox/master_config.example.json" "$USER_DIR/tvbox/master_config.example.json"
  else
    echo "  · 无 master_config.example.json（lite 形状正常，跳过）"
  fi
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
echo
echo "【安装前快照】（回滚点唯一，覆盖旧快照）"
deploy_snapshot

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

# 安装后自检：技能目录里不许出现嵌套同名副本（cp -r 语义回归的硬信号）
if [ "$DRY" = 0 ]; then
  bad=0
  for base in "$USER_DIR"/skills/*/ "$PROJ_DIR"/skills/*/; do
    [ -d "$base" ] || continue
    check_no_nested "${base%/}" || bad=1
  done
  if [ "$bad" = 1 ]; then
    echo
    echo " ✗ 自检失败：存在嵌套副本（install.sh 的 cp_bak 已修复，出现即说明有历史残留），"
    echo "   删掉上面列出的目录后重装。"
    exit 1
  fi
  echo " · 自检：技能目录无嵌套副本"
  # 记录部署版本：bootstrap 迁移器与巡检对账都读这里；不写会让下次 bootstrap 重放迁移
  if [ -f "$ROOT/VERSION" ]; then
    mkdir -p "$HOME/.codebuddy/.520_state"
    cp "$ROOT/VERSION" "$HOME/.codebuddy/.520_state/version"
    echo " · 部署版本: $(cat "$HOME/.codebuddy/.520_state/version")"
  fi
  # 账号接管 + 演化记账（v0.8.12）
  # ① adopt：新账号（云端全空）→ 按蓝图建齐；老账号（有历史）→ 认领已有 + 登记存量（不搬不删）；
  #    别人的空间 → 拒绝并在终端说明。这样"装完就有库"和"老账号接得住以前的东西"是同一入口。
  # ② evolve-log：把这一版装了什么写进「🧬 生态演化」台账，可逐版追溯。
  # 两步都失败只告警，不中断安装——没网/没授权/没空间都不该让装到一半失败。
  if [ -f "$USER_DIR/skills/space-hub/scripts/space_hub.py" ]; then
    python3 "$USER_DIR/skills/space-hub/scripts/space_hub.py" adopt 2>&1 | sed 's/^/   /' || true
    python3 "$USER_DIR/skills/space-hub/scripts/space_hub.py" evolve-log \
      --version "$(cat "$ROOT/VERSION" 2>/dev/null)" \
      --manifest "$ROOT/MANIFEST.json" 2>&1 | sed 's/^/   /' || true
  fi
fi

echo
echo "════════════════════════════════════════════════════"
echo " ✅ 完成（mode=$SCOPE）。下一步："
echo "   1) 开【新会话】使规则/技能生效（会话启动时才加载）"
echo "   2) 手机端：按 手机指令.md 手动粘进 App 设置→指令"
echo "   3) 测试：照 TEST.md 逐项验证（含路由实测）"
echo "════════════════════════════════════════════════════"
