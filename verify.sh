#!/usr/bin/env bash
# 520pro 安装自检：检查关键落点是否存在，并做脚本语法/可执行性冒烟
# 用法：bash verify.sh [--target <项目目录>]
set -uo pipefail
# ★ H2（v0.8.20）：参数可任意顺序（--target 与 --selftest 能并存，CI 会同时给）
TARGET="$(pwd)"
SELFTEST=0
REPO_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:-$TARGET}"; shift 2 2>/dev/null || shift ;;
    --selftest) SELFTEST=1; shift ;;
    --repo-only) REPO_ONLY=1; shift ;;
    *) shift ;;
  esac
done
U="$HOME/.codebuddy"
P="$TARGET/.codebuddy"

# ★ v0.8.17（工程E 施工时发现）：非 tty 自动关闭颜色。
#   原实现无条件上色，导致 `bash verify.sh | grep -c '  ✓'` 恒为 0——
#   想统计"过了几条"的人得到 0，会误判成"一条都没过"（工程C 的同款假绿，当时只修了 python 脚本，漏了这里）。
C_OK=""; C_NO=""; C_WARN=""; C_DIM=""
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_OK=$'\033[32m'; C_NO=$'\033[31m'; C_WARN=$'\033[33m'; C_DIM=$'\033[0m'
fi
# ★ v0.8.19（工程G-3）：**失败计数 + 真退出码**。
#   原实现只有打印、从不 exit——`bash verify.sh` 恒返回 0，于是任何自动化/发布脚本
#   都拿不到失败信号（有红项也照样过）。人眼看 ✓ 能过，机器看 rc 永远通过，这是最坏的一种假绿。
#   现约定：✗ 计失败并最终 exit 2；· 记"无法判定"单独计数（不阻断，但不许被当成通过）。
FAILS=0
UNKNOWNS=0
ok(){ printf "  %s✓%s %s\n" "$C_OK" "$C_DIM" "$1"; }
no(){ FAILS=$((FAILS + 1)); printf "  %s✗%s %s\n" "$C_NO" "$C_DIM" "$1"; }
opt(){ UNKNOWNS=$((UNKNOWNS + 1)); printf "  %s·%s %s\n" "$C_WARN" "$C_DIM" "$1"; }
# ★ v0.8.14（B4·WARN 分级）：卫生问题用黄叹号，与"绿✓通过/红✗失败"三态区分——不折叠
warn(){ printf "  %s⚠%s %s\n" "$C_WARN" "$C_DIM" "$1"; }

# ★ H2（v0.8.20 工程H）：判据自证注入点。只由 --selftest 的子进程携带。
#   2026-11-12 出过「return 2 if _reject(...) else 2」这种恒真表达式，人眼看不出、
#   但判据已经失去判红能力。所以判据本身也要能被验证：注入一条必红项，看 rc 会不会变 2。
if [ -n "${VERIFY_INJECT_FAIL:-}" ]; then
  no "【selftest 注入】这条永远失败——用来验证「判据→计数→退出码」整条链没断"
fi

echo "================ 520pro 自检 ================"
echo "HOME=$U   TARGET=$TARGET"

# ★ H1（v0.8.20 工程H）：副本完整性基线。
#   2026-11-12 连出两次误判，根因相同：拿一份"半份克隆"跑判据，缺文件 → 整片
#   "引用断链/技能缺失"假红，再被当成"仓库有毛病"。所以跑判据前先证明脚下的副本完整。
#   判据不写死绝对数（开发会增文件），用 git 索引自校准；无 .git 时退硬下限 200。
if [ -f "$TARGET/MANIFEST.json" ] && [ -f "$TARGET/verify.sh" ]; then
  _nfiles=$(find "$TARGET" -type f -not -path "$TARGET/.git/*" 2>/dev/null | wc -l | tr -d ' ')
  _nidx=$(git -C "$TARGET" ls-files 2>/dev/null | wc -l | tr -d ' ')
  _head=$(git -C "$TARGET" rev-parse --short HEAD 2>/dev/null || true)
  echo "副本：HEAD=${_head:-无 git}  工作区=${_nfiles} 文件  git 索引=${_nidx}"
  _min=200; _basis="无 git 时硬下限 200"
  if [ "${_nidx:-0}" -gt 0 ]; then
    _idx_min=$(( _nidx * 85 / 100 ))
    if [ "$_idx_min" -gt "$_min" ]; then _min=$_idx_min; fi
    _basis="git 索引 ${_nidx} 的 85%"
  fi
  if [ "$_nfiles" -lt "$_min" ]; then
    no "工作副本不完整：${_nfiles} 个文件 < 下限 ${_min}（${_basis}）——后续判据不可信，先重新检出"
    echo "✗ 副本不完整，中止自检（避免假红/假绿混入结论）"
    echo "  修法：git clone/pull 完整仓库，或 bootstrap.sh 重新稀疏检出"
    exit 2
  fi
  ok "工作副本完整（${_nfiles} 文件 ≥ 下限 ${_min}，${_basis}）"
fi

# ★ H2（v0.8.20 工程H）：--selftest —— 判据自己也要被验证。
#   判据坏掉（恒真/恒假）时，正常跑永远绿；只有注入一条必红项才照得出来。
#   两次子进程：① 注入必红 → 必须 rc=2 且日志里能看到那条注入项；② 正常 → 必须 rc=0。
if [ "$SELFTEST" = 1 ]; then
  _self="$0"
  case "$_self" in /*) ;; *) _self="$(pwd)/$_self" ;; esac
  echo "[判据自证] 跑两次子进程：一次注入必红项，一次正常"
  VERIFY_INJECT_FAIL=1 bash "$_self" --target "$TARGET" >/tmp/_vf_bad.log 2>&1; _rc_bad=$?
  bash "$_self" --target "$TARGET" >/tmp/_vf_ok.log 2>&1; _rc_ok=$?
  _sf=0
  if [ "$_rc_bad" -eq 2 ] && grep -q 'selftest 注入' /tmp/_vf_bad.log; then
    ok "注入必红项 → rc=2 且红项可见（判据确实能判红）"
  else
    no "注入必红项但 rc=${_rc_bad} 或日志无该红项（判据疑似恒真/被短路）"; _sf=1
  fi
  if [ "$_rc_ok" -eq 0 ]; then
    ok "无注入 → rc=0（不误报）"
  else
    no "无注入却 rc=${_rc_ok}（存在假红，先看 /tmp/_vf_ok.log）"; _sf=1
  fi
  echo
  if [ "$_sf" -eq 0 ]; then echo "✓ 判据自证通过（红得起来、绿得下去）"; else echo "✗ 判据自证失败"; fi
  exit "$_sf"
fi

# ★ v0.8.21（S228 落地）：推送安全包装——向 GitHub 推送必须走 hooks/git_push_safe.sh，
#   禁止裸 `git push`。这里只验"执行体在、语法通"，不发起任何网络动作。
#   脚本自带三态退出码与 rev-parse 终验，是推送纪律的正本入口。
if [ -f "$TARGET/hooks/git_push_safe.sh" ] && bash -n "$TARGET/hooks/git_push_safe.sh" 2>/dev/null; then
  ok "hooks/git_push_safe.sh（推送安全包装在位，语法过）"
else
  no "hooks/git_push_safe.sh 缺失或语法错误——推送纪律没有执行体"
fi

# ★ v0.8.29：一行收尾入口——存在 + 语法过即可（不发起网络动作，推送本体由
#   git_push_safe.sh 判据与真实调用覆盖）
if [ -f "$TARGET/sync.sh" ] && bash -n "$TARGET/sync.sh" 2>/dev/null; then
  ok "sync.sh（一行收尾入口在位：verify → 对账 → push_safe，语法过）"
else
  no "sync.sh 缺失或语法错误——一行收尾没有执行体"
fi

echo
# ★ H4（v0.8.20）：--repo-only 只验仓库自身（检出完整性 + 契约 + 口径 + 回归），
#   不验安装落点。给 bootstrap.sh 用——它只负责"检出完整"，还没装到 ~/.codebuddy。
if [ "$REPO_ONLY" = 1 ]; then
  echo "[仓库级自检] --repo-only：跳过安装落点（用户级/项目级/冒烟/巡检）"
else
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
  # v0.8.12 学习产出出口：成品入库后自动进「📚 学习资料/成品」（主文档 + 整包）
  _ld="$U/skills/learn-hub/scripts/learn.py"
  if [ -f "$_ld" ]; then
    grep -q "def _pick_main_doc" "$_ld" && grep -q "def _zip_dir" "$_ld" \
      && grep -q "_archive_learning(name, dst)" "$_ld" \
      && ok "  └ 产出出口已接线（主文档 + 整包 → 资料库）" \
      || no "  └ 产出出口未接线（学习成品不会进资料库）"
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
need=['ensure_library','archive_out','cmd_ensure','cmd_evolve_log','_merge_blueprint','_artifact_rules',
      'adopt','detect_mode','_nodes_or_none','_adopt_stock','cmd_adopt']
miss=[n for n in need if not hasattr(s,n)]
sys.exit(1 if miss else 0)" 2>/dev/null \
    && ok "  └ 自举/跟随/台账/接管入口齐全" || no "  └ 入口缺失（ensure/archive_out/evolve-log/adopt）"
  # v0.8.12 账号接管：fresh/hybrid/foreign 三态**不可折叠**（unknown 不许当 fresh 去建库）
  python3 -c "
import sys; sys.path.insert(0,'$U/skills/space-hub/scripts')
import space_hub as s
o1,o2 = s._nodes_or_none, s.load_state
s._nodes_or_none = lambda pid: None
m1,_ = s.detect_mode()
s._nodes_or_none = lambda pid: []
m2,_ = s.detect_mode()
s._nodes_or_none = lambda pid: [{'kind':'folder','title':'别人的相册','id':'x'}]
s.load_state = lambda: {}
m3,_ = s.detect_mode()
s._nodes_or_none, s.load_state = o1, o2
sys.exit(0 if (m1,m2,m3)==('unknown','fresh','foreign') else 1)" 2>/dev/null \
    && ok "  └ 三态判定正确（枚举失败=unknown≠fresh，空= fresh，无指纹=foreign）" \
    || no "  └ 三态判定塌陷（unknown 可能被当成 fresh 去建库）"
  # classify 落点必须与 archive 同体系：target 不得再是根层级旧名（归档·xx）
  if grep -q '"target": *"归档·' "$U/skills/space-hub/scripts/classify_rules.json" 2>/dev/null; then
    no "  └ 归纳登记册仍在用根层级旧落点（会与新体系形成两套目录）"
  else
    ok "  └ 归纳落点与产物归档同体系（无根层级旧名）"
  fi
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
  echo "    （探源司 status 冒烟，约 10s；下面是结果，不是判定符号）"
  out=$( cd "$SK/probe-hub/scripts" && PROBE_HUB_NO_BANNER=1 timeout 60 python3 probe.py monitor status 2>/dev/null || true )
  case "$out" in
    *"个目标"*) ok "probe.py monitor status 可跑（监测台正常）" ;;
    *) opt "探源司 status 未通过 → 无法判定（多为沙箱网络受限，非必失败）" ;;
  esac
  # 分发卫生（v0.8.12）：个人资产册不得被 git 跟踪，模板册必须在位
  if git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1; then
    leaked=$(git -C "$TARGET" ls-files -- "能力层/tvbox/skills/probe-hub/scripts/*.json" 2>/dev/null \
             | grep -E "(monitor_targets|monitor_domains|monitor_pubsources|dead_repos|shellcrack_cands)\.json$" \
             | grep -v '\.example\.json$' | wc -l | tr -d ' ')
    [ "${leaked:-0}" -eq 0 ] && ok "个人资产册未进 git（分发不带私产）" \
      || no "仍有 $leaked 个真册被 git 跟踪（个人资产会随分发泄露）"
  fi
  miss_tpl=""
  for f in monitor_targets monitor_domains monitor_pubsources dead_repos shellcrack_cands; do
    [ -f "$SK/probe-hub/scripts/$f.example.json" ] || miss_tpl="$miss_tpl $f"
  done
  [ -z "$miss_tpl" ] && ok "五册模板齐全（新机器可建空册）" || no "模板册缺失：$miss_tpl"
  # 安装器必须剥离"源目录里的运行时私产"：gitignore 只挡 clone，挡不住从仓库目录 cp 过去。
  # 2026-11-12 实测过一次泄露（空机装完出现 185 个监测目标），这条防它回归。
  if [ -f "$TARGET/install.sh" ]; then
    grep -q 'rm -f "\$dst/scripts/\$f"' "$TARGET/install.sh" \
      && ok "安装器剥离源里的运行时私产（空机不会带出监测目标）" \
      || no "安装器未剥离源里的运行时私产（从仓库目录安装会泄露个人资产）"
  fi
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
[ -d "$P/skills/tvbox-pipeline" ] && ok "skills/tvbox-pipeline" || opt "项目级技能未装（用户级模式正常）"
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

fi

echo
echo "[密钥安全（v0.8.19 起·发布门默认 --strict）]"
if [ -f "$TARGET/secret_scan.py" ]; then
  # ★ v0.8.19（工程G-3）：默认 --strict——卫生问题（个人绝对路径 / 本地 endpoint）
  #   从"提示"升级为"发布前必须清或显式豁免"。理由：WARN 挂在面板上三轮都没人管，
  #   而这类东西一旦分发出去就是"别人的机器上跑不通 + 泄露我的目录结构"。
  #   临时排查可 SECRET_STRICT=0 bash verify.sh 关掉（关了要说出来，别静默降级）。
  SCAN_ARGS=""
  [ "${SECRET_STRICT:-1}" = "1" ] && SCAN_ARGS="--strict"
  scan_out=$(python3 "$TARGET/secret_scan.py" "$TARGET" $SCAN_ARGS 2>&1); scan_rc=$?
  echo "$scan_out"
  if [ "$scan_rc" -eq 0 ]; then
    if [ -n "$SCAN_ARGS" ]; then
      ok "secret_scan 无明文密钥、无未处置卫生问题（--strict 发布门）"
    else
      ok "secret_scan 无明文密钥（含 .git/config 复查；SECRET_STRICT=0 已关闭严格模式）"
    fi
  else
    no "secret_scan 未通过（明文密钥立即处置；卫生问题按 A 口径改文本，历史档案走 HYGIENE_EXEMPT 并写理由）"
  fi
  # WARN 级计数（strict 模式下这些已经会判红，这里仍单独报数，便于知道"红了几条卫生"）
  warn_n=$(printf '%s\n' "$scan_out" | sed -n 's/^\[WARN\] \([0-9]*\) 处.*/\1/p' | head -1)
  if [ -n "${warn_n:-}" ] && [ "$warn_n" -gt 0 ]; then
    if [ -n "$SCAN_ARGS" ]; then
      no "发布面卫生 ${warn_n} 处 WARN（--strict 下计为失败：活文档改中性表述，历史档案登记豁免）"
    else
      warn "发布面卫生 ${warn_n} 处 WARN（SECRET_STRICT=0，不阻断；仅用于临时排查）"
    fi
  fi
else
  no "secret_scan.py 缺失（零明文凭证防线未装）"
fi

# ★ v0.8.14（工程B·B6）：公开基线文件必须被 git 跟踪——漏跟踪=分发件缺件
if git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1; then
  miss_base=""
  for f in MANIFEST.json VERSION secret_scan.py verify.sh install.sh; do
    git -C "$TARGET" ls-files --error-unmatch "$f" >/dev/null 2>&1 || miss_base="$miss_base $f"
  done
  while IFS= read -r sk; do
    git -C "$TARGET" ls-files --error-unmatch "$sk" >/dev/null 2>&1 || miss_base="$miss_base $sk"
  done < <(cd "$TARGET" && ls 通用层/skills/*/SKILL.md 能力层/tvbox/skills/*/SKILL.md 2>/dev/null)
  [ -z "$miss_base" ] && ok "公开基线文件全部被 git 跟踪（分发件齐全）" \
    || no "基线文件未被跟踪：$miss_base"
fi

# ★ v0.8.18（工程F-7）：三通道一致性——规则靠「用户级 + 项目薄壳 + 手机指令」叠加生效，
#   少一条通道就有场景兜不住：手机不读项目薄壳、桌面不读手机指令。
#   判据只查"通道在不在 + 有没有跟到当前铁律口径"，不查文字是否逐字相同（那会天天红）。
echo
echo "[三通道一致性（v0.8.18 起·工程F-7）]"
if [ -f "$TARGET/手机指令.md" ]; then
  ok "手机指令.md 在位（硬轨）"
  # ★ v0.8.23：判据从「抽查 B-10 一条 + 比范围字符串」升级为**结构化对账**。
  #   旧判据的两个漏洞（都是真发生过的）：
  #     ① 只查一条 → 其余 15 条漏没漏看不出（本次 B-11/13/16 就是漏着的）；
  #     ② 查 "B-01~B-16" 这串字 → 只要写对范围就过，跟"到底放没放进去"无关。
  #   新判据要求：hard-rail ∪ hard-rail-exempt 必须**不重不漏**等于 core-8 全部编号。
  #   这样 core-8 下次扩条时，这里会立刻红，逼一次「进硬轨 or 登记豁免」的决定。
  _hr_out=$(python3 - "$TARGET" <<'PYEOF'
import re, sys, os
tgt = sys.argv[1]
core = os.path.join(tgt, '通用层/rules/core-8.md')
mob = os.path.join(tgt, '手机指令.md')
try:
    ct = open(core, encoding='utf-8').read()
    mt = open(mob, encoding='utf-8').read()
except Exception as e:
    print('OPT core-8 或手机指令不可读：%s' % e); sys.exit(0)

allb = set(re.findall(r'(?m)^\s*[0-9]+\.\s+\*\*(B-[0-9]{2})', ct))
if not allb:
    print('OPT core-8 未识别到 B 编号条款——硬轨对账无法判定'); sys.exit(0)

def grab(tag):
    m = re.search(r'<!--\s*%s\s*:\s*([^>]*?)-->' % tag, mt)
    if not m:
        return None
    return set(re.findall(r'B-[0-9]{2}', m.group(1)))

rail = grab('hard-rail')
exem = grab('hard-rail-exempt')
if rail is None or exem is None:
    print('FAIL 手机指令缺登记注释（hard-rail / hard-rail-exempt）——硬轨放没放全无从判断')
    sys.exit(0)

MUST = {'B-02', 'B-10', 'B-11', 'B-13', 'B-16'}   # 手机端踩了当场出事的五条
probs = []
ghost = (rail | exem) - allb
if ghost:
    probs.append('登记了 core-8 里不存在的编号 %s（编号写错，或 core-8 已删条）'
                 % '、'.join(sorted(ghost)))
dup = rail & exem
if dup:
    probs.append('%s 同时被登记为「进硬轨」和「豁免」——口径自相矛盾' % '、'.join(sorted(dup)))
miss = allb - rail - exem
if miss:
    probs.append('core-8 有但硬轨没放也没登记豁免：%s（扩条后忘记决定去哪）'
                 % '、'.join(sorted(miss)))
lack = MUST - rail
if lack:
    probs.append('必入清单缺：%s（这几条手机端踩了当场出事，不能豁免）'
                 % '、'.join(sorted(lack)))

if probs:
    print('FAIL ' + '；'.join(probs))
else:
    print('OK %d 进硬轨 + %d 登记豁免 = core-8 全 %d 条，不重不漏'
          % (len(rail), len(exem), len(allb)))
PYEOF
)
  case "$_hr_out" in
    OK*)   ok "  └ 手机硬轨对账：${_hr_out#OK }" ;;
    OPT*)  opt "  └ 手机硬轨对账无法判定：${_hr_out#OPT }" ;;
    FAIL*) no "  └ 手机硬轨对账失败：${_hr_out#FAIL }" ;;
    *)     opt "  └ 手机硬轨对账无输出（判据自身可能异常）" ;;
  esac
else
  no "手机指令.md 缺失（手机通道断：手机端不读项目薄壳）"
fi

# ★ v0.8.26：手机指令云端副本新鲜度
#   起因：手机打不开本地路径、GitHub raw 在手机 App 里也不稳，所以硬轨正文另存了一份
#   云端 doc 供直接复制。但镜像靠人手动更新必然过期——过期后手机上粘的是旧规则，
#   而且没有任何信号。这里只判「有没有过期」（离线，断网也能判），同步动作在
#   sync_phone_directive.py，触发出现在 hooks/pre-commit。
echo
echo "[手机指令云端副本（v0.8.26 起）]"
if [ -f "$TARGET/sync_phone_directive.py" ]; then
  phout="$(python3 "$TARGET/sync_phone_directive.py" --repo "$TARGET" --check 2>&1)"
  phrc=$?
  case "$phrc" in
    0) ok "$(printf '%s' "$phout" | sed 's/^FRESH  *//')" ;;
    1) no "$(printf '%s' "$phout" | sed 's/^STALE  *//')"
       echo "     处置：python3 sync_phone_directive.py（同步 + 回读校验，幂等）" ;;
    *) opt "云端副本判据无法判定：$(printf '%s' "$phout" | head -1)" ;;
  esac
else
  opt "sync_phone_directive.py 缺失——云端副本新鲜度未检"
fi
if [ -f "$TARGET/能力层/tvbox/CODEBUDDY.md" ]; then
  ok "项目薄壳 CODEBUDDY.md 在位"
  grep -q "core-8" "$TARGET/能力层/tvbox/CODEBUDDY.md" \
    && ok "  └ 薄壳指向 core-8（不重复条文，M2）" \
    || no "  └ 薄壳未指向 core-8（可能在自己抄条文）"
else
  no "项目薄壳 CODEBUDDY.md 缺失（项目级通道断）"
fi
# ★ v0.8.18（工程F-4）：交接摘要三项 + 版本不过期（B-07 的执行面）
if [ -f "$TARGET/verify/tests/test_handoff.py" ]; then
  hout="$(python3 "$TARGET/verify/tests/test_handoff.py" 2>&1)"
  if [ $? -eq 0 ]; then
    ok "交接摘要齐三项且版本不过期（B-07 可核）"
  else
    no "交接摘要过期或缺项（接手的人会按旧口径干活）"
    printf '%s\n' "$hout" | grep '  ✗ ' | head -3 | sed 's/^/     /'
  fi
fi

# ★ v0.8.22（工程J·B-16）：双核必保——probe-hub 与 tvbox-core 是硬依赖，不是"最好有"。
#   core.py 被 probe-hub 全量 import，缺了不是"某个功能不好使"，是探源司整片 ModuleNotFoundError。
#   判据只查"在不在"（版本归契约 C4，不在这里重复判），位置取仓内真源，不取安装副本——
#   仓里没有就是仓库问题，装没装是另一回事。
echo
echo "[双核必保（v0.8.22 起·B-16）]"
[ -f "$TARGET/能力层/tvbox/skills/probe-hub/SKILL.md" ] \
  && ok "probe-hub 在位（探源司本体）" \
  || no "probe-hub 缺失/改名——探源司不可用（B-16 双核必保）"
if [ -f "$TARGET/能力层/tvbox/skills/tvbox-core/scripts/core.py" ]; then
  ok "tvbox-core/scripts/core.py 在位（共享内核）"
else
  no "tvbox-core/scripts/core.py 缺失——probe-hub 会 ModuleNotFoundError（B-16 双核必保）"
fi
[ -f "$TARGET/通用层/skills/learn-hub/scripts/learn.py" ] \
  && ok "learn-hub 在位（通用层业务主件，B-16 同保项）" \
  || no "learn-hub 缺失/改名——学习工坊不可用（B-16 同保项）"

# ★ v0.8.15（工程C）：技能契约机检——结构/头部/描述五组/版本三处/镜像 sha/样本集
echo
echo "[技能契约（v0.8.15 起·工程C：技能该长什么样是机器判据）]"
if [ -f "$TARGET/verify/skill_contract_check.py" ]; then
  # --require-mirror 只在"本机确实装了技能"时启用：装了就必须一致（红）；
  # 空机未装则退回「无法判定」，不让"没装"冒充"通过"，也不误伤只跑仓检的场景。
  mirror_arg=""
  # ★ H4（v0.8.20）：--repo-only 时不比对本机安装副本——该场景（换机检出/CI/新机）
  #   本来就还没装，比出来只会是"残留/私产"这类环境噪声，不是仓库问题。
  #   把 --install 指到不存在的路径，C5 自动记「无法判定」，不折算通过也不判红。
  if [ "$REPO_ONLY" = 1 ]; then
    mirror_arg="--install /nonexistent-520pro-mirror"
  elif [ -d "$HOME/.codebuddy/skills" ]; then
    mirror_arg="--require-mirror"
  fi
  cout="$(python3 "$TARGET/verify/skill_contract_check.py" --repo "$TARGET" $mirror_arg 2>&1)"
  cstat=$?
  cok=$(printf '%s\n' "$cout" | grep -c '  ✓ \[' || true)
  cno=$(printf '%s\n' "$cout" | grep -c '  ✗ \[' || true)
  cwarn=$(printf '%s\n' "$cout" | grep -c '  ⚠ \[' || true)
  if [ "$cstat" -eq 0 ]; then
    ok "技能契约 $cok 项通过（$cwarn 项 WARN 不阻断）"
  else
    no "技能契约 $cno 项失败（$cok 项通过）——详情: python3 verify/skill_contract_check.py"
    printf '%s\n' "$cout" | grep '  ✗ \[' | head -6 | sed 's/^/     /'
  fi
else
  no "verify/skill_contract_check.py 缺失（技能契约机检未装）"
fi

# ★ v0.8.15（工程C·M5）：运行时豁免清单两处同源——contracts.json 与 install.sh 不得漂移
if [ -f "$TARGET/verify/skill_contracts.json" ] && [ -f "$TARGET/install.sh" ]; then
  if python3 - "$TARGET" <<'PYEOF'
import json, re, sys
t = open(sys.argv[1] + '/install.sh', encoding='utf-8').read()
reg = json.load(open(sys.argv[1] + '/verify/skill_contracts.json', encoding='utf-8'))
mf = re.search(r'^RUNTIME_FILES="([^"]*)"', t, re.M)
md = re.search(r'^RUNTIME_DIRS="([^"]*)"', t, re.M)
if not mf:
    sys.exit(1)                      # install.sh 里找不到清单 = 契约无从对账
inst_f = set(mf.group(1).split())
reg_f = set(reg['runtime_files'])
inst_d = set(md.group(1).split()) if md else set()
reg_d = set(reg.get('runtime_dirs') or [])
bad = (inst_f - reg_f) or (inst_d - reg_d) or (reg_d - inst_d)
sys.exit(0 if not bad else 1)
PYEOF
  then
    ok "运行时豁免清单两处同源（文件 + 目录，contracts.json ↔ install.sh）"
  else
    no "运行时豁免清单漂移（文件或目录，install.sh ↔ contracts.json 不一致——镜像闸会误报）"
  fi
fi

echo
echo "[外部引用对账（v0.8.32 起·library 升级后指针失效的闸）]"
if [ -f "$TARGET/verify/lib_refs_check.py" ]; then
  lout="$(python3 "$TARGET/verify/lib_refs_check.py" 2>&1)"; lrc=$?
  if [ "$lrc" -eq 2 ]; then
    opt "$(printf '%s' "$lout" | sed 's/^  · 无法判定：//')"
  elif [ "$lrc" -ne 0 ]; then
    no "外部引用失配——详情: python3 verify/lib_refs_check.py --strict"
    printf '%s\n' "$lout" | grep '↳' | head -3 | sed 's/^/     /'
  elif printf '%s' "$lout" | grep -q '⚠'; then
    warn "$(printf '%s' "$lout" | head -1 | sed 's/^  ⚠ //')"
  else
    ok "$(printf '%s' "$lout" | head -1 | sed 's/^  ✓ //')"
  fi
else
  no "verify/lib_refs_check.py 缺失（外部引用闸未装）"
fi

# ★ v0.8.16（工程D）：口径机检——M4 编号连续（每条须带 B-xx 且与序号对齐）+ M2/M5 引用断链
# 为什么要有：core-8 的 M5 自己写着"断链/词表误用/编号越界/复制条款四类须全绿"，
# 但在此之前这四类**没有任何机检入口**（M1 声称的 docs/registry.md 与 verify/terminology_check.py
# 两个落点当时都不存在）——规则说要查，实际没人查。
echo
echo "[口径机检（v0.8.16 起·工程D：M4 编号 / M5 引用断链）]"
if [ -f "$TARGET/verify/terminology_check.py" ]; then
  tout="$(python3 "$TARGET/verify/terminology_check.py" --repo "$TARGET" 2>&1)"
  tstat=$?
  tok=$(printf '%s\n' "$tout" | grep -c '  ✓ \[' || true)
  tno=$(printf '%s\n' "$tout" | grep -c '  ✗ \[' || true)
  tskip=$(printf '%s\n' "$tout" | grep -c '  · \[' || true)
  if [ "$tno" -gt 0 ] || [ "$tstat" -ne 0 ]; then
    no "口径机检 $tno 项失败——详情: python3 verify/terminology_check.py"
    printf '%s\n' "$tout" | grep '  ✗ \[' | head -4 | sed 's/^/     /'
  elif [ "$tskip" -gt 0 ]; then
    # 有项判不了就不算通过（三态：无法判定 ≠ 通过）
    warn "口径机检 $tok 项通过，另有 $tskip 项无法判定（缺真源文件，不算通过）"
  else
    ok "口径机检通过（$tok 项全绿：编号连续 + 引用无断链）"
  fi
else
  no "verify/terminology_check.py 缺失（M5 口径机检未装）"
fi

# ★ v0.8.25（规则迁移批2）：台账四律——旧生态 M-R75/82/86/93 的判据化落点
# 为什么要有：这四条原本是旧生态的"教训条目"，只在文档里躺着。docs 不加载
# （docs/加载机制与可靠性.md 实测），所以只搬条文 = 纸面迁移。这里只挑能机检的形态，
# 检不了的（"须显式收口才变绿"等）留给人工与 docs/通病台账.md，不假装覆盖。
echo
echo "[台账四律（v0.8.25 起·规则迁移批2：M-R75/82/86/93）]"
if [ -f "$TARGET/verify/ledger_laws.py" ]; then
  lout="$(python3 "$TARGET/verify/ledger_laws.py" --repo "$TARGET" 2>&1)"
  lrc=$?
  lok=$(printf '%s\n' "$lout" | grep -c '  ✓ \[' || true)
  lno=$(printf '%s\n' "$lout" | grep -c '  ✗ \[' || true)
  lskip=$(printf '%s\n' "$lout" | grep -c '  · \[' || true)
  if [ "$lno" -gt 0 ] || [ "$lrc" -ne 0 ]; then
    no "台账四律 $lno 项失败——详情: python3 verify/ledger_laws.py --repo $TARGET"
    printf '%s\n' "$lout" | grep '  ✗ \[' | head -3 | sed 's/^/     /'
  elif [ "$lskip" -gt 0 ]; then
    warn "台账四律 $lok 项通过，另有 $lskip 项无法判定（缺台账文件，不算通过）"
  else
    ok "台账四律通过（$lok 项全绿：状态终态化/指纹对账/已结区幂等/退出码不驻全局）"
  fi
else
  no "verify/ledger_laws.py 缺失（台账四律判据未装）"
fi

# ★ v0.8.18（工程F）：扩展回归——每个都是一个"拆掉实现就翻红"的小测试
#   不进上一节的统计口径（它们是行为判据，不是落点判据），失败单独列原因。
echo
echo "[扩展回归（v0.8.18 起·工程F）]"
# ★ 注意：test_verify_exit.sh **不能**挂在这里——它内部会调 verify.sh，会无限递归。
#   它由人手动跑（或在 CI 里作为最外层一步）。
for t in test_troubleshoot test_language test_doc_index test_reading_guide test_reject_contract \
         test_triggers test_docsync test_skill_cards test_ledger_laws test_phone_directive_sync \
         test_linkage_notice test_secret_scan_size test_trigger_frontload \
         test_artifact_scan; do
  if [ -f "$TARGET/verify/tests/$t.py" ]; then
    if tout="$(python3 "$TARGET/verify/tests/$t.py" 2>&1)"; then
      ok "$t"
    else
      no "$t 失败——详情: python3 verify/tests/$t.py"
      printf '%s\n' "$tout" | grep '  ✗ ' | head -2 | sed 's/^/     /'
    fi
  else
    no "verify/tests/$t.py 缺失"
  fi
done

echo "============================================"
printf '汇总：✓ 通过 ／ ✗ 失败 %d ／ · 无法判定 %d\n' "$FAILS" "$UNKNOWNS"
if [ "$FAILS" -gt 0 ]; then
  echo "✗ 自检未通过（退出码 2）——红项在上方，逐条处置后重跑"
  exit 2
fi
echo "✓ 自检通过（退出码 0）"
echo "提示：装完/改完要【开新会话】才加载；手机按 手机指令.md 手动粘规则。"
exit 0
