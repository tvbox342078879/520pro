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
opt(){ printf "  \033[33m·\033[0m %s\n" "$1"; }

echo "================ 520pro 自检 ================"
echo "HOME=$U   TARGET=$TARGET"
echo
echo "[通用层·用户级]"
[ -f "$U/rules/core-8.md" ] && ok "rules/core-8.md" || no "rules/core-8.md 缺失"
for s in skill-evolution feature-gate machine-bootstrap artifact-store; do
  [ -d "$U/skills/$s" ] && ok "skills/$s" || no "skills/$s 缺失"
done
# 学习工坊（v0.5.0 起）：通用层业务技能，自带网盘取料模块（原 probe-hub harvest pan）
if [ -f "$U/skills/learn-hub/scripts/learn.py" ]; then
  ok "skills/learn-hub（学习工坊）"
  if [ -f "$U/skills/learn-hub/scripts/pan.py" ]; then
    ok "  └ pan.py 网盘取料（清单/下载/转存/删除）"
  else
    no "  └ pan.py 缺失（网盘取料不可用）"
  fi
else
  opt "skills/learn-hub 未安装（v0.5.0 之前的旧安装，正常）"
fi

# 库务司（v2.0.0 起）：通用层云端库总管（清道夫升级版，清理+归纳+建库）
if [ -f "$U/skills/space-hub/scripts/space_hub.py" ]; then
  ok "skills/space-hub（库务司）"
  python3 -c "import ast; ast.parse(open('$U/skills/space-hub/scripts/space_hub.py').read())" 2>/dev/null \
    && ok "  └ space_hub.py 语法 OK" || no "  └ space_hub.py 语法错误"
  if grep -q "8w5cnqCqQJ0wNoF2Hb6efH" "$U/skills/space-hub/scripts/space_hub.py"; then
    no "  └ 残留写死 space id（账号绑定缺陷复发）"
  else
    ok "  └ 无写死 space id（四层动态解析）"
  fi
  [ -f "$U/skills/space-hub/scripts/classify_rules.json" ] && ok "  └ 归纳登记册在位" || no "  └ 归纳登记册缺失"
  # v2.4.0 库房自举三件：蓝图在位可解析 / 两个新命令注册 / 出口门面可导入
  if [ -f "$U/skills/space-hub/scripts/base_blueprint.json" ]; then
    python3 -c "import json;d=json.load(open('$U/skills/space-hub/scripts/base_blueprint.json'));assert d.get('roots');assert any('生态演化' in r.get('title','') for r in d['roots'])" 2>/dev/null \
      && ok "  └ 基础蓝图可解析，且含固定分类「🧬 生态演化」" \
      || no "  └ 基础蓝图损坏或缺「🧬 生态演化」固定分类"
  else
    no "  └ 基础蓝图缺失（库房自举不可用）"
  fi
  python3 -c "
import sys; sys.path.insert(0,'$U/skills/space-hub/scripts')
import space_hub as s
need=['ensure_library','archive_out','cmd_ensure','cmd_evolve_log','_merge_blueprint','_artifact_rules']
miss=[n for n in need if not hasattr(s,n)]
sys.exit(1 if miss else 0)" 2>/dev/null \
    && ok "  └ 自举/跟随/台账入口齐全" || no "  └ 自举入口缺失（ensure/archive_out/evolve-log）"
else
  opt "skills/space-hub 未安装（正常，可后补）"
fi

echo
echo "[TVBox·用户级（--user-skill 模式）]"
[ -d "$U/skills/tvbox-pipeline" ] && ok "skills/tvbox-pipeline" || opt "skills/tvbox-pipeline 未安装（lite 形状或项目级模式，正常）"
for f in collect_repos check_live merge_config; do
  if [ -f "$U/scripts/$f.py" ]; then
    ok "scripts/$f.py"
    python3 -c "import ast,sys; ast.parse(open('$U/scripts/$f.py').read())" 2>/dev/null && ok "  └ 语法 OK" || no "  └ 语法错误"
  else
    no "scripts/$f.py 缺失"
  fi
done

echo
echo "[探源司（probe-hub + tvbox-core 共享库）]"
SK="$U/skills"
[ -d "$SK/probe-hub" ] && ok "skills/probe-hub（探源司本体）" || no "skills/probe-hub 缺失"
# tvbox-core 是硬依赖（core.py 来源），必须存在；它没有 SKILL.md，不参与路由
if [ -f "$SK/tvbox-core/scripts/core.py" ]; then
  ok "skills/tvbox-core（含 core.py，非技能·仅被 import）"
elif [ -d "$SK/tvbox-core" ]; then
  no "skills/tvbox-core 存在但缺 scripts/core.py（探源司必崩 ModuleNotFoundError）"
else
  no "skills/tvbox-core 缺失（探源司必崩 ModuleNotFoundError）"
fi
# pipeline 为出品流水线，lite 形状不含
[ -d "$SK/tvbox-pipeline" ] && ok "skills/tvbox-pipeline（整包加工+配置同步）" || opt "skills/tvbox-pipeline 未安装（lite 形状正常）"
if [ -d "$SK/tvbox-core/scripts" ]; then
  ( cd "$SK/tvbox-core/scripts" && python3 -c "import core" 2>/dev/null ) \
    && ok "共享核心 core.py 可导入" || no "core.py 导入失败"
fi
# 核心库不该被当成技能注册：有 SKILL.md 就是装错了
[ -f "$SK/tvbox-core/SKILL.md" ] && no "tvbox-core 混入了 SKILL.md（会被误注册为技能）" || ok "tvbox-core 无 SKILL.md（正确：不路由）"
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
# 探源司 v1.26.0 能力（2026-11-12 从旧仓 tvbox-eco 并回）：修源 / 写源四门禁 / 广告治理
if [ -d "$SK/probe-hub/repair" ]; then
  ok "repair/ 修源模块在位"
  miss=""
  for f in engine.py recon.py llm.py ai_ast.py strategies.json \
           schemas/checkup_report.schema.json schemas/repair_result.schema.json; do
    [ -f "$SK/probe-hub/repair/$f" ] || miss="$miss $f"
  done
  [ -z "$miss" ] && ok "  └ 修源七件套齐全" || no "  └ 修源缺件:$miss"
  for spec in "r221:gate_r221_death_taxonomy" "r222:gate_r222_repair_contract"; do
    tag="${spec%%:*}"; g="${spec##*:}"
    if [ -f "$SK/probe-hub/verify/$g.py" ]; then
      python3 "$SK/probe-hub/verify/$g.py" >/dev/null 2>&1 \
        && ok "  └ ${tag^^} 闸门通过" || no "  └ ${tag^^} 闸门未过（见 python3 直跑输出）"
    else
      no "  └ verify/$g.py 缺失（规则闸门未装）"
    fi
  done
else
  no "repair/ 修源模块缺失（探源司自愈能力不可用）"
fi
[ -f "$SK/probe-hub/scripts/hls_clean.py" ] && ok "hls_clean.py 广告治理引擎（61 域名黑名单）" || no "hls_clean.py 缺失（广告判定退化）"
[ -f "$SK/probe-hub/scripts/forge_gate.py" ] && ok "forge_gate.py 写源四门禁" || no "forge_gate.py 缺失（forge gate 不可用）"
[ -d "$SK/probe-hub/forgekit" ] && ok "forgekit 模板库（forge hook 用）" || no "forgekit 缺失（forge hook 不可用）"
# AES 兜底（S224）：模块形态供 import、内联片段供 forge hook。两份算法核必须同源，
# 所以不只查在不在，还要跑 NIST 向量 + 与 forgekit 对账——漂移了要立刻红。
if [ -f "$SK/probe-hub/scripts/_aes_fallback.py" ]; then
  ok "_aes_fallback.py AES 兜底模块在位"
  out=$( cd "$SK/probe-hub/scripts" && timeout 60 python3 _aes_fallback.py 2>&1 ) || true
  case "$out" in
    *"NIST 向量: ✅"*) ok "  └ NIST 向量自检通过" ;;
    *) no "  └ NIST 向量自检未过" ;;
  esac
  out=$( cd "$SK/probe-hub/scripts" && timeout 60 python3 _aes_fallback.py --crosscheck 2>&1 )
  rc=$?
  case "$rc:$out" in
    0:*)            ok "  └ 与 forgekit 片段对账一致（SBOX + 同密文）" ;;
    2:*)            echo "  · 对账无法判定（forgekit 未就近找到，多为副本不完整）" ;;
    *)              no "  └ 与 forgekit 片段已漂移（两份 AES 实现不一致，改一份漏一份）" ;;
  esac
else
  no "_aes_fallback.py 缺失（羊壳无 Crypto 时无兜底，源会在 import 阶段整挂）"
fi

echo
echo "[TVBox·项目级（--capability-only / all 模式）]"
[ -f "$P/CODEBUDDY.md" ] && ok "CODEBUDDY.md" || opt "CODEBUDDY.md 未装（用户级模式正常）"
[ -d "$P/skills/tvbox-pipeline" ] && ok "skills/tvbox-pipeline" || echo "  · 项目级技能未装（用户级模式正常）"
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

# 巡检司（v0.7.0 起）：520 自家健康巡检（八卦八门面板）
if [ -f "$U/skills/inspect-hub/scripts/inspect_hub.py" ]; then
  ok "skills/inspect-hub（巡检司）"
  python3 "$U/skills/inspect-hub/scripts/inspect_hub.py" self-check >/dev/null 2>&1 \
    && ok "  └ self-check 通过（8 门齐+impl 映射+模板可渲染）" || no "  └ self-check 失败"
else
  opt "skills/inspect-hub 未安装（可后补）"
fi

echo
echo "[密钥安全（v0.7.0 起·core-8 规则 5 零明文凭证）]"
if [ -f "$TARGET/secret_scan.py" ]; then
  python3 "$TARGET/secret_scan.py" "$TARGET" && ok "secret_scan 无明文密钥（含 .git/config 复查）" \
    || no "secret_scan 发现疑似明文密钥（见上方清单，立即处置）"
else
  no "secret_scan.py 缺失（零明文凭证防线未装）"
fi

echo "============================================"
echo "提示：装完/改完要【开新会话】才加载；手机按 手机指令.md 手动粘规则。"
