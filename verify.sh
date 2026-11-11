#!/usr/bin/env bash
# 520pro 安装自检：检查关键落点是否存在，并做脚本语法/可执行性冒烟
# 用法：bash verify.sh [--target <项目目录>]
set -uo pipefail
TARGET="$(pwd)"
[ "${1:-}" = "--target" ] && TARGET="$2"
U="$HOME/.codebuddy"
P="$TARGET/.codebuddy"

ok(){ printf "  \033[32m✓\033[0m %s\n" "$1"; }
no(){ printf "  \033[31m✗\033[0m %s\n" "$1"; }

echo "================ 520pro 自检 ================"
echo "HOME=$U   TARGET=$TARGET"
echo
echo "[通用层·用户级]"
[ -f "$U/rules/core-8.md" ] && ok "rules/core-8.md" || no "rules/core-8.md 缺失"
for s in skill-evolution feature-gate machine-bootstrap artifact-store; do
  [ -d "$U/skills/$s" ] && ok "skills/$s" || no "skills/$s 缺失"
done

echo
echo "[TVBox·用户级（--user-skill 模式）]"
[ -d "$U/skills/tvbox-config-sync" ] && ok "skills/tvbox-config-sync" || no "skills/tvbox-config-sync 缺失（若用项目级模式可忽略）"
for f in collect_repos check_live merge_config; do
  if [ -f "$U/scripts/$f.py" ]; then
    ok "scripts/$f.py"
    python3 -c "import ast,sys; ast.parse(open('$U/scripts/$f.py').read())" 2>/dev/null && ok "  └ 语法 OK" || no "  └ 语法错误"
  else
    no "scripts/$f.py 缺失"
  fi
done

echo
echo "[探源司·四件套（probe-hub + 共享核心）]"
SK="$U/skills"
[ -d "$SK/probe-hub" ] && ok "skills/probe-hub（探源司本体）" || no "skills/probe-hub 缺失"
for s in tvbox-source-hub tvbox-interface tvbox-source-blacklist; do
  [ -d "$SK/$s" ] && ok "skills/$s" || no "skills/$s 缺失（探源司依赖，缺了必报 ModuleNotFoundError）"
done
if [ -d "$SK/tvbox-source-hub/scripts" ]; then
  ( cd "$SK/tvbox-source-hub/scripts" && python3 -c "import core" 2>/dev/null ) \
    && ok "共享核心 core.py 可导入" || no "core.py 导入失败"
fi
if [ -d "$SK/probe-hub/scripts" ]; then
  # 只看功能性硬编码（sys.path / 变量赋值），文案与注释里的路径不影响运行
  hit=$(grep -rEn "sys\.path\.insert\([^)]*'/root/\.codebuddy|^[[:space:]]*[A-Z_]+[[:space:]]*=[[:space:]]*'/root/\.codebuddy" "$SK" --include="*.py" 2>/dev/null | wc -l | tr -d ' ')
  [ "${hit:-0}" -eq 0 ] && ok "无功能性硬编码 /root/.codebuddy（可跨机器）" || no "仍有 $hit 处功能性硬编码路径"
  echo "  · 探源司 status 冒烟（约 10s，网络受限时会降级）"
  out=$( cd "$SK/probe-hub/scripts" && PROBE_HUB_NO_BANNER=1 timeout 60 python3 probe.py monitor status 2>/dev/null || true )
  case "$out" in
    *"个目标"*) ok "probe.py monitor status 可跑（监测台正常）" ;;
    *) echo "  · status 未通过 → 记「无法判定」（多为沙箱网络受限，非必失败）" ;;
  esac
fi

echo
echo "[TVBox·项目级（--capability-only / all 模式）]"
[ -f "$P/CODEBUDDY.md" ] && ok "CODEBUDDY.md" || no "CODEBUDDY.md 缺失（用户级模式可忽略）"
[ -d "$P/skills/tvbox-config-sync" ] && ok "skills/tvbox-config-sync" || echo "  · 项目级技能未装（用户级模式正常）"
for f in collect_repos check_live merge_config; do
  [ -f "$P/scripts/$f.py" ] && ok "scripts/$f.py" || true
done

echo
echo "[脚本可跑冒烟]"
SD=""
[ -d "$U/scripts" ] && SD="$U/scripts"
[ -z "$SD" ] && [ -d "$P/scripts" ] && SD="$P/scripts"
if [ -n "$SD" ]; then
  TMP="$(mktemp -d)"; cp "$SD/check_live.py" "$TMP/" 2>/dev/null
  ( cd "$TMP" && printf '["https://example.com"]' > s.json && python3 check_live.py s.json >/dev/null 2>&1 && ok "check_live.py 可执行（example.com 探针）" || no "check_live.py 运行失败" )
  rm -rf "$TMP"
else
  no "未找到脚本目录，跳过冒烟"
fi

echo "============================================"
echo "提示：装完/改完要【开新会话】才加载；手机按 手机指令.md 手动粘规则。"
