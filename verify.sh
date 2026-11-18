#!/usr/bin/env bash
# 520pro 安装自检：检查关键落点是否存在，并做脚本语法/可执行性冒烟
# 用法：bash verify.sh [--target <项目目录>]
set -uo pipefail
# ★ v0.8.79（防卡死检查单 §四）：verify 自身总时限——判据链慢可以，死不行。
#   防嵌套：经环境变量标记，只包裹一层；pre-commit/pre-push/CI 调本脚本同样受保护。
#   超时 rc=124 非零，闸照样拦——不会出现"verify 卡死→钩子卡死→会话卡死"连锁。
if [ -z "${_520_VERIFY_TL:-}" ] && command -v timeout >/dev/null 2>&1; then
  exec env _520_VERIFY_TL=1 timeout 900 bash "$0" "$@"
fi
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
  _nidx=$(git -c core.quotepath=false -C "$TARGET" ls-files 2>/dev/null | wc -l | tr -d ' ')
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

# ★ v0.8.79（防卡死检查单，真源 docs/防卡死检查单.md）：四条硬判据
# 1) 检查单真源在位——防检查单成死文件
if [ -f "$TARGET/docs/防卡死检查单.md" ]; then
  ok "docs/防卡死检查单.md（防卡死口径真源在位）"
else
  no "docs/防卡死检查单.md 缺失——防卡死口径无真源，闸将成无判据散件"
fi
# 2) 等待闸在位+语法过（会话层防 block=true 轮询死等）；v0.8.80 连带子任务时限闸
for gw in task_wait_guard agent_turns_guard; do
  if [ -f "$TARGET/hooks/$gw.py" ] && python3 -m py_compile "$TARGET/hooks/$gw.py" 2>/dev/null; then
    ok "hooks/$gw.py（防卡死闸在位，语法过）"
  else
    no "hooks/$gw.py 缺失或语法错误——防卡死执行闸缺件"
  fi
done
# 3) SSH 兜底段限时——兜底不是法外之地
if grep -q 'timeout 300 git push "\$ssh_url"' "$TARGET/hooks/git_push_safe.sh" 2>/dev/null; then
  ok "git_push_safe SSH 段 timeout 300（兜底段限时在位）"
else
  no "git_push_safe SSH 段未限时——兜底推送可能挂死"
fi
# 3b) 推送纪律冲突裁决指针防删（v0.8.82 增量）：registry.md 推送纪律行必须显式声明
#     平台技能裸 push 法在本仓不适用。两段跨层文本无法合并，只能写死优先级；删这句
#     就退回「两套说法都像对的」——agent 读技能层可能踩裸 push（无 sha 终验+明文 token）。
#     锚定「推送纪律」行再找「本仓不适用」，避免病15 全文件乱匹配别的"不适用"。
if grep '推送纪律' "$TARGET/docs/registry.md" 2>/dev/null | grep -q '本仓不适用'; then
  ok "推送纪律行含『平台技能在本仓不适用』裁决指针（跨层冲突边界写死，防删）"
else
  no "registry.md 推送纪律行缺『本仓不适用』裁决——平台技能裸 push 法将与本仓纪律冲突"
fi
# 4) git 自愈通道行为级判据：8 条同步命令调 check() 必须零命中——
#    将来谁往 guard_cmd 加了拦 git 同步的规则，这条直接红（防传播死：旧设备被旧钩子咬时拉不了修复）
gchk="$(python3 -c "
import sys
sys.path.insert(0, '$TARGET/hooks')
import guard_cmd as g
cmds=['git pull','git fetch origin','git checkout main','git restore .','git switch main','git merge origin/main','git rebase main','git clone https://github.com/x/y.git']
hits=[c for c in cmds if g.check(c)]
print('命中:' + ','.join(hits) if hits else '')
" 2>&1)"
if [ -z "$gchk" ]; then
  ok "git 自愈通道恒通（pull/fetch/checkout/restore/switch/merge/rebase/clone 零命中 G 闸，行为级实证）"
else
  no "git 自愈通道被 G 闸拦：$gchk——传播死风险，闸锁死设备将拉不到修复"
fi

# ★ v0.8.78：pre-push 本地闸——commit 可 --no-verify 绕过，push 前必须有最后一道本地校验。
#   只验"源在位 + 语法过 + 装门白名单含它"；落点(.git/hooks/pre-push)由 install.sh 负责装，
#   这里不验落点（--repo-only/换机检出还没装，验了是环境噪声不是仓库问题，B-02 不折叠）。
if [ -f "$TARGET/hooks/pre-push" ] && bash -n "$TARGET/hooks/pre-push" 2>/dev/null; then
  if grep -qE 'for h in .*pre-push' "$TARGET/install.sh" 2>/dev/null; then
    ok "hooks/pre-push（push 前本地闸在位 + 语法过 + install.sh 装门接线）"
  else
    no "hooks/pre-push 在位，但 install.sh 装门白名单没含它——钩子不会真装上"
  fi
else
  no "hooks/pre-push 缺失或语法错误——push 前无本地闸（仅 CI 兜底）"
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
[ -f "$U/rules/施工纪律.md" ] && ok "rules/施工纪律.md" || no "rules/施工纪律.md 缺失"
for s in machine-bootstrap artifact-store; do
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
  # v1.4.5 网盘监测上游取料仓（测活+测更新）
  if [ -f "$U/skills/learn-hub/scripts/pan_monitor.py" ]; then
    ok "  └ pan_monitor.py 网盘监测（测活+测更新→待转存队列）"
  else
    no "  └ pan_monitor.py 缺失（网盘监测不可用）"
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
    python3 -c "import json;d=json.load(open('$U/skills/space-hub/scripts/base_blueprint.json'));assert d.get('roots');assert any('520进化论' in r.get('title','') for r in d['roots'])" 2>/dev/null \
      && ok "  └ 基础蓝图可解析，且含固定分类「🧬 520进化论」" \
      || no "  └ 基础蓝图损坏或缺「🧬 520进化论」固定分类"
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
    leaked=$(git -c core.quotepath=false -C "$TARGET" ls-files -- "能力层/tvbox/skills/probe-hub/scripts/*.json" 2>/dev/null \
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
# ★S231 六层资产 + 通道三件的离线自检（不联网）——**判据必须在执行路径上**：
#   只写 selftest 不接电 = 判据挂空（病「判据不在执行路径」的形态）。
#   正向：装了且全过；反向：selftest 缺失/失败即 ✗，不折叠成 opt。
#   通道三件（atomicio/pushconfig/imgproxy）原先只是 S231 文档里的「常备资产」，无实现，
#   2026-11-15 补成可执行正门后一并在电。
for spec in "livecheck:scripts/livecheck.py:--selftest（TLS指纹段+语义测活）" \
            "recon:repair/recon.py:--selftest（sniff聚类+五层正则）" \
            "shellcrack:scripts/shellcrack.py:--selftest（6层播放集兜底+第7条金律）" \
            "atomicio:scripts/atomicio.py:--selftest（原子写+内容不变不重写）" \
            "pushconfig:scripts/pushconfig.py:--selftest（FongMi 本地推送·假Proxy）" \
            "imgproxy:scripts/imgproxy.py:--selftest（wsrv.nl 图代理开关）"; do
  name="${spec%%:*}"; rest="${spec#*:}"; rel="${rest%%:*}"; label="${rest##*:}"
  if [ -f "$SK/probe-hub/$rel" ]; then
    if out=$( cd "$SK/probe-hub/$(dirname "$rel")" && timeout 90 python3 "$(basename "$rel")" --selftest 2>&1 ); then
      ok "  └ $name $label"
    else
      no "  └ $name $label 未过：$(printf '%s' "$out" | grep -E '^\[FAIL\]|✗' | head -3 | tr '\n' ' ')"
    fi
  else
    no "  └ $SK/probe-hub/$rel 缺失（$name 自检无从跑起）"
  fi
done
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

# artifact-store（本地轻量化总闸）：执行体真跑判据（v0.8.82）
# 只查目录存在＝纸面生效——脚本被换掉/语法坏/自省挂了照样绿。
# 对齐机器司 check-env.sh、巡检司 inspect_hub.py 先例：在位之外必须真跑 self-check。
if [ -f "$U/skills/artifact-store/scripts/artifact.py" ]; then
  python3 "$U/skills/artifact-store/scripts/artifact.py" self-check >/dev/null 2>&1 \
    && ok "artifact-store/scripts/artifact.py self-check 通过（LRU 归档候选自省）" \
    || no "artifact-store 执行体 self-check 失败——技能在位是纸面，自省挂了"
else
  no "artifact-store/scripts/artifact.py 缺失——本地轻量化总闸无执行体"
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
    git -c core.quotepath=false -C "$TARGET" ls-files --error-unmatch "$f" >/dev/null 2>&1 || miss_base="$miss_base $f"
  done
  while IFS= read -r sk; do
    git -c core.quotepath=false -C "$TARGET" ls-files --error-unmatch "$sk" >/dev/null 2>&1 || miss_base="$miss_base $sk"
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

# ★ 施工纪律 S 段对账（S-02 机制解决）：B 段有 hard-rail 对账，S 段真源化后一度没有，
#   导致"真源改了手机端/云端副本没同步"的假闭环。这里把 S 段接进同一条链：
#   施工纪律.md 改 → 这里红 → 同步手机指令.md → pre-commit 同步云端 doc → 新鲜度绿。
echo
echo "[施工纪律 S 段对账]"
if [ -f "$TARGET/verify/build_rail_check.py" ]; then
  _br_out="$(python3 "$TARGET/verify/build_rail_check.py" --repo "$TARGET" --check 2>&1)"
  case $? in
    0) ok "  └ 施工纪律 S 段硬轨：${_br_out#OK }" ;;
    1) no "  └ 施工纪律 S 段硬轨：${_br_out#FAIL }"
       echo "     处置：把新增/变更的 S 编号同步进 手机指令.md 的 build-rail 注释与粘贴区正文" ;;
    *) opt "  └ S 段对账无法判定：${_br_out#OPT }" ;;
  esac
else
  no "verify/build_rail_check.py 缺失（S 段对账判据未装）"
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
# impl: B-16 S5   ← 双核存在性（probe-hub / tvbox-core/scripts/core.py）
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

# ★ W3（v0.8.76 增量）：熔铸司判据接电 —— 只写 selftest 不接电 = 判据挂空
#   （病「判据不在执行路径」，同上方 S231 六层资产的教训）。W2 的三个 selftest 一直是
#   install.sh / 手工跑，从未进 verify.sh 执行路径；这里补进仓库级段，验 $TARGET 仓内真源，
#   --repo-only 干净检出也在电。正向全过 ✓；反向脚本缺失或 selftest 未过即 ✗，不折叠成 opt。
echo
echo "[熔铸司 foundry 判据接电（W3 起·通用层横向能力板块）]"
for _sp in "foundry-core/scripts/core.py|core.py --selftest（26 工具转正 + 63 目录能力面登记 + 多形态造错）" \
           "foundry-core/scripts/jadx_engine.py|jadx_engine.py --selftest（FakeTransport / PROC_DEAD 三态）" \
           "foundry/scripts/foundry.py|foundry.py selftest（正门层正反向）"; do
  _rel="${_sp%%|*}"; _label="${_sp##*|}"
  _full="$TARGET/通用层/skills/$_rel"
  if [ -f "$_full" ]; then
    _dir="$(dirname "$_full")"; _base="$(basename "$_full")"
    _arg="--selftest"; [ "$_base" = "foundry.py" ] && _arg="selftest"
    if _o=$( cd "$_dir" && timeout 90 python3 "$_base" "$_arg" 2>&1 ); then
      ok "  └ ${_label} 正反向全绿"
    else
      no "  └ ${_label} 未过：$(printf '%s' "$_o" | grep -E '✗|项失败|Error' | head -3 | tr '\n' ' ')"
    fi
  else
    no "  └ ${_rel} 缺失（判据挂空）"
  fi
done

# ★ W7（v0.8.76 增量）：熔铸司 26 工具链「真跑通」判据——区别于上方 FakeTransport 离线 selftest。
#   真起 jadx java 子进程走 stdio，核对 26 名册 + status 真响应，证据落盘可回读。
#   三态按 rc 分：0=真跑通 ok / 3=无 jar 或 java（opt 无法判定，不假绿不置红）/ 2=真跑失败 no。
#   换机/CI 无 jar 时走 opt，不阻断 verify；本机有 jar 必须真跑通，失败即红（病15 识别=对象）。
echo
echo "[熔铸司 26 工具链真跑通（W7 起·real-java-stdio 实证）]"
_jx="$TARGET/通用层/skills/foundry-core/scripts/jadx_engine.py"
if [ -f "$_jx" ]; then
  _jd="$(dirname "$_jx")"
  _ro=$( cd "$_jd" && timeout 120 python3 jadx_engine.py --realcall 2>&1 ); _rr=$?
  case "$_rr" in
    0) ok "  └ 真起 java 跑通 26 工具 + 证据落盘（$(printf '%s' "$_ro" | tail -1)）" ;;
    3) opt "  └ 无法判定：$(printf '%s' "$_ro" | tail -1)" ;;
    *) no "  └ 真跑失败：$(printf '%s' "$_ro" | tail -1)" ;;
  esac
else
  no "  └ jadx_engine.py 缺失（真跑判据挂空）"
fi

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
  # v0.8.36：◐=环境欠账（该装没装），·=结构性不适用（lib 类/本机不装）。两者都不阻断，
  # 但看输出要能分清「去装一下」和「这本来就不该管」——原先都记 ·，分不出来。
  cpart=$(printf '%s\n' "$cout" | grep -c '  ◐ \[' || true)
  cskip=$(printf '%s\n' "$cout" | grep -c '  · \[' || true)
  if [ "$cstat" -eq 0 ]; then
    ok "技能契约 $cok 项通过（$cwarn WARN / $cpart 环境欠账 / $cskip 不适用，均不阻断）"
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
  # v0.8.34：默认带 --probe（每个引用脚本真跑一次 --help + 参数契约回查）。
  # 存在的文件也可能调不通——2026-11-13 实测把 db_query 的 --ask 改名后，
  # 只查存在性的版本全绿，三个包装调用点（space_hub/core/backfill_jar）已经全断。
  # 探活要起 10 来个进程，用 120s 兜底防挂：超时按「无法判定」降级并说明，不静默。
  # v0.8.40（账目 P0 收口）：加 --strict——失配不再只是 ⚠ 而是 rc=1 直接红。
  # 依据：观察 3 次全绿（d9ad68e / 9b84dfa / a8d3458 后各一次）。
  # 关探活（LIB_REFS_NO_PROBE=1）同样带 --strict：否则「关探活」就等于悄悄降级成 warn 级。
  if [ "${LIB_REFS_NO_PROBE:-0}" = "1" ]; then
    lout="$(python3 "$TARGET/verify/lib_refs_check.py" --strict 2>&1)"; lrc=$?
  else
    lout="$(timeout 120 python3 "$TARGET/verify/lib_refs_check.py" --probe --strict 2>&1)"; lrc=$?
    if [ "$lrc" -eq 124 ]; then
      lout='  · 无法判定：--probe 超过 120s 未返回，已退化为存在性检查（LIB_REFS_NO_PROBE=1 可关闭探活）'
      lrc=2
    fi
  fi
  if [ "$lrc" -eq 2 ]; then
    # v0.8.36：◐=环境欠账（library 没装，该装）→ 黄色提醒；·=无法判定 → 灰色可选项
    if printf '%s' "$lout" | grep -q '◐'; then
      warn "$(printf '%s' "$lout" | sed 's/^  ◐ 环境欠账：//' | head -1)"
    else
      opt "$(printf '%s' "$lout" | sed 's/^  · 无法判定：//' | head -1)"
    fi
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

# ★ v0.8.38（病11）：作废结论残留闸——真源已订正的结论，副本不得再以现役口径出现
# 为什么要有：「手机不跑钩子」2026-11-12 已在 docs/钩子来源判定.md 作废，但 5 个副本
# 没同步，AI 连续多轮引用旧口径被用户当场抓住。真源改了，指针必须连带（M5）；
# 本闸兜住「改了真源、忘了副本」的那类漏网。新作废结论入库时在此登记关键词。
echo
echo "[作废结论残留（v0.8.38 起·病11：真源已订正，副本须同步）]"
STALE_HITS="$(grep -rn '手机不跑钩子\|手机/云端不跑钩子\|手机/云端任务不跑钩子' "$TARGET" \
  --include='*.md' --include='*.sh' --include='*.py' \
  | grep -v 'docs/钩子来源判定.md' | grep -v 'docs/通病台账.md' | grep -v 'verify.sh' || true)"
if [ -n "$STALE_HITS" ]; then
  no "旧口径残留（「手机不跑钩子」已作废，真源 docs/钩子来源判定.md）："
  printf '%s\n' "$STALE_HITS" | head -4 | sed 's/^/     /'
else
  ok "无作废结论残留（已作废：手机不跑钩子；真源 docs/钩子来源判定.md）"
fi

# ★ v0.8.47（病10/病13）：落地判据扫描——中文路径转义 + 平台钩子观测要件
# 为什么要有：这两道病之前只有文字病历没有机器判据；verify.sh 全绿 ≠ 它们被守着。
# 判据三件套（造违例/拦下/改坏溜过）见 verify/tests/test_gate_scan.py。
echo
echo "[落地判据扫描（v0.8.47 起·病10 quotepath / 病13 hook-probe+hook-registered / 病12 case-count / 强度对账 impl-reconcile）]"
if [ -f "$TARGET/verify/gate_scan.py" ]; then
  if python3 "$TARGET/verify/gate_scan.py" --root "$TARGET" > /tmp/_gate_scan.out 2>&1; then
    ok "gate_scan：quotepath + hook-probe + hook-registered + case-count + impl-reconcile 全绿"
  else
    no "gate_scan 有红项（细节见上/下）："
    sed 's/^/     /' /tmp/_gate_scan.out | head -8
  fi
else
  no "verify/gate_scan.py 缺失——病10/病12/病13 判据闸未装（不静默跳过）"
fi

# ★ v0.8.64（方案v3 梯度④）：交付落库对账——每轮交付必落资料库，有 bump 无回执=假交付
# 判据与三态见 verify/gate_archive_ledger.py（--selftest 内置正反向）。
echo
echo "[交付落库对账（v0.8.64 起·方案v3：archive_ledger 数据基座）]"
if python3 "$TARGET/verify/gate_archive_ledger.py" > /tmp/_arch_ledger.out 2>&1; then
  ok "交付落库对账：近期版本 bump 均有落库回执（或无可判对象）"
  grep -c '  ✓ \[archive-ledger\]' /tmp/_arch_ledger.out >/dev/null 2>&1
else
  no "交付落库对账有红项（假交付/ledger 损坏）："
  sed 's/^/     /' /tmp/_arch_ledger.out | head -9
fi

# ★ v0.8.66（批1-①）：M12 经验门接电——chk_contentflow 四判据（断流/账实脱节/复发超限/效果指标）
#   此前只在巡检 run（模型自愿发起）时跑，闸建了没接电；接进 verify.sh 必经链路后每轮必检。
#   黄（断路夹/复发超限）=账面提醒不阻断，红（过期账实脱节/无源内容）才拦。
# 判据与三态见 verify/gate_experience.py（--selftest 内置正反向）。
echo
echo "[M12 经验门（v0.8.66 起·接电：verify 必经链路）]"
if python3 "$TARGET/verify/gate_experience.py" > /tmp/_exp_gate.out 2>&1; then
  ok "M12 经验门：无红项（黄提醒见明细）"
  sed 's/^/     /' /tmp/_exp_gate.out | head -6
else
  no "M12 经验门有红项（无源内容/过期账实脱节）："
  sed 's/^/     /' /tmp/_exp_gate.out | head -9
fi
# v0.8.73：闸化登记判据自证接电（判据不在执行路径=挂空）。五形态/六反例/端到端 green-yellow 正反向。
if exp_st_out=$( python3 "$TARGET/verify/gate_experience.py" --selftest 2>&1 ); then
  ok "  └ M12 闸化登记 --selftest 正反向全过（五形态+反例+端到端+多病号混合 green/yellow）"
else
  no "  └ M12 闸化登记 --selftest 未过：$(printf '%s' "$exp_st_out" | grep -E '✗|FAIL' | head -3 | tr '\n' ' ')"
fi
# ★ 经验闭环 v2（2026-11-15）：①淬炼器 + ②③观测④呈现探针接电（判据不在执行路径=挂空）。
#   淬炼器只读回读派生态 + selftest；探针回读四环状态，死库存/假经验如实报，不折叠成通过。
echo
echo "[经验闭环 v2（淬炼→呈现→复用→进化）]"
if python3 "$TARGET/verify/exp_distill.py" --status > /tmp/_exp_distill.out 2>&1; then
  ok "淬炼状态：$(head -1 /tmp/_exp_distill.out)"
else
  no "淬炼状态回读失败：$(head -2 /tmp/_exp_distill.out | tr '\n' ' ')"
fi
if python3 "$TARGET/verify/exp_probe.py" > /tmp/_exp_probe.out 2>&1; then
  ok "$(head -1 /tmp/_exp_probe.out)"
  sed 's/^/     /' /tmp/_exp_probe.out | tail -3
else
  no "经验闭环探针异常：$(head -2 /tmp/_exp_probe.out | tr '\n' ' ')"
fi
if exp_v2_st=$( python3 "$TARGET/verify/exp_distill.py" --selftest 2>&1 ) && \
   exp_pv_st=$( python3 "$TARGET/verify/exp_probe.py" --selftest 2>&1 ); then
  ok "  └ 淬炼+探针 --selftest 正反向全过（反稀释/幂等/抗洗绿/死库存/缺呈现）"
else
  no "  └ 经验闭环 --selftest 未过：$(printf '%s%s' "$exp_v2_st" "$exp_pv_st" | grep -E '✗' | head -3 | tr '\n' ' ')"
fi

# ★ 经验闭环 v3 步骤5（2026-11-18）：闭环完成判据——同一 symptom 复发计数停增。
#   三态不折叠：plateau/no-seal=ok；recurring=黄（复发本身提醒级，不阻断提交）；
#   unknown/selftest 失败=红（判据自己不可信=机制缺陷）。真读用户级账本，与写侧同真源。
echo
echo "[经验闭环 v3 步骤5（收口判据：复发停增）]"
_exp_closure_st=$( python3 "$TARGET/verify/exp_closure.py" --selftest 2>&1 )
if [ $? -eq 0 ]; then
  ok "  └ 停增判据 --selftest 正反向全过（10 例：无基线/停增/复发/手改洗绿/重复封盘）"
else
  no "  └ 停增判据 --selftest 未过：$(printf '%s' "$_exp_closure_st" | grep -E '✗' | head -3 | tr '\n' ' ')"
fi
if _exp_closure_out=$( python3 "$TARGET/verify/exp_closure.py" 2>&1 ); then
  _ec_state=$( printf '%s' "$_exp_closure_out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("state","unknown"))' 2>/dev/null )
  case "$_ec_state" in
    plateau|ready)
      ok "闭环收口回读：$(printf '%s' "$_exp_closure_out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["summary"])' 2>/dev/null)" ;;
    recurring)
      echo "     ⚠ 闭环收口：仍有症状在复发（提醒级，不阻断）：$(printf '%s' "$_exp_closure_out" | grep -o '"symptom": *"[^"]*"' | head -2 | tr '\n' ' ')" ;;
    *)
      no "  └ 闭环收口回读异常/unknown：$(printf '%s' "$_exp_closure_out" | head -2 | tr '\n' ' ')" ;;
  esac
else
  no "  └ 闭环收口回读失败：$(head -2 <<<"$_exp_closure_out" | tr '\n' ' ')"
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
         test_build_rail test_classify_routing test_linkage_notice test_secret_scan_size test_trigger_frontload \
         test_artifact_scan test_lib_refs_probe \
         test_skill_contract_mutants test_partial_level test_terminology_mutants \
         test_commit_fields test_gate_scan test_pack_skills test_guard_cmd test_stop_guard \
         test_pre_push test_sync_channels test_task_wait_guard test_database_exempt \
         test_pan_monitor test_exp_direct test_exp_closure test_ad_audit test_skill_entry; do
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

# ★ 交接锚点（v0.8.37）：真源是最后一次提交的 Next: 行，本处只负责"喊出来"。
#   为什么放在自检里：自检是必跑动作（pre-commit 每次都跑），锚点搭它的车就能每提交一次
#   被看见一次——不依赖谁记得去读 handoff（多轮会话后纪律会衰减，这是已知事实）。
#   红了也打印：失败时更要知道下一步是不是"先修红"。
NEXT_LINE="$(git -C "${TARGET:-.}" log -1 --format=%B 2>/dev/null | grep -E '^Next: ' | head -1 || true)"
if [ -n "$NEXT_LINE" ]; then
  echo "--------------------------------------------"
  echo "上一轮定的下一步（真源 git log -1）："
  echo "  ${NEXT_LINE#Next: }"
fi

echo "============================================"
printf '汇总：✓ 通过 ／ ✗ 失败 %d ／ · 不适用或无法判定 %d\n' "$FAILS" "$UNKNOWNS"
if [ "$FAILS" -gt 0 ]; then
  echo "✗ 自检未通过（退出码 2）——红项在上方，逐条处置后重跑"
  exit 2
fi
echo "✓ 自检通过（退出码 0）"
echo "提示：装完/改完要【开新会话】才加载；手机按 手机指令.md 手动粘规则。"
exit 0
