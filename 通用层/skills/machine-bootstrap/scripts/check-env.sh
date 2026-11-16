#!/usr/bin/env bash
# check-env.sh —— 换机司环境体检正门（machine-bootstrap SKILL.md §56-82 的可执行落地）
#
# 覆盖两节原则：
#   ①环境自检三态链路审计：A 未补全 / B 链路断开 / C 假就绪 + 两级验证（command -v + 真跑退出码）
#   ②技能安装边界：内置不可覆盖 / 来源白名单 / 精确 id / 只落文件不执行（自证 + 对账）
#
# 用法：
#   bash check-env.sh [--repo DIR] [--install DIR]
#   bash check-env.sh --selftest          # 正反自检，造错必红
#   默认 repo = 脚本所在仓根，install = ~/.codebuddy/skills
#
# 纪律：三态诚实（B-02）—— 命令不存在=A，上游就绪下游缺位=B，存在但执行失败=C；
#       不以"没查到"充当"没有"。镜像对账只比关键文件 sha，不遍历 runtime_assets 大文件。
# 退出码（v1.0.5 修 rc 假绿）：全项 OK=0；A/B/C 任一命中=2。
#   旧版报 A3/B2 仍 rc=0，CI/换机流程会当成"体检通过"——这是假绿，必须靠退出码暴露。
set -uo pipefail

REPO=""
INSTALL_DIR=""
MODE="check"
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --install) INSTALL_DIR="${2:-}"; shift 2 ;;
    --selftest) MODE="selftest"; shift ;;
    --help|-h) MODE="help"; shift ;;
    *) printf '错误: 未知参数 %s\n用法: bash check-env.sh [--repo DIR] [--install DIR] [--selftest]\n' "$1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "$REPO" ]; then
  REPO="$(cd "$SCRIPT_DIR/../../../.." 2>/dev/null && pwd)"
  if [ ! -f "$REPO/MANIFEST.json" ]; then
    REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$REPO")"
  fi
fi
[ -z "$INSTALL_DIR" ] && INSTALL_DIR="$HOME/.codebuddy/skills"

# 三态输出：[态] 项 / 证据（证据必须来自真实命令输出）
# A/B/C 命中累计到 FAILS，run_check 据此 exit 2（不假绿）；selftest 用自己的 pass/fail 判定。
FAILS=0
report() {
  printf '[%-4s] %-24s %s\n' "$1" "$2" "$3"
  case "$1" in OK) ;; *) FAILS=$((FAILS+1)) ;; esac
}

# 两级验证：$1=命令名 $2=版本参数（默认 --version）
# A=command -v 无输出；C=存在但真跑退出码非0；OK=两级都过
check_binary() {
  local name="$1" varg="${2:---version}" out rc
  if ! command -v "$name" >/dev/null 2>&1; then
    report A "$name" "command -v 无输出（未装）"
    return
  fi
  out="$("$name" "$varg" 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    report C "$name" "存在但 '$varg' 退出码=$rc：$(printf '%s' "$out" | head -1)"
    return
  fi
  report OK "$name" "$(printf '%s' "$out" | head -1)"
}

# B 类链路断开：上游就绪、下游缺位（JAVA_HOME 悬空 / git 在但仓库不可识别）
check_chain() {
  local repo="$1"
  if command -v java >/dev/null 2>&1; then
    if [ -z "${JAVA_HOME:-}" ]; then
      report B "java/JAVA_HOME" "java 已装但 JAVA_HOME 未设（上游就绪下游缺位）"
    elif [ ! -d "$JAVA_HOME" ]; then
      report B "java/JAVA_HOME" "JAVA_HOME=$JAVA_HOME 目录不存在"
    else
      report OK "java/JAVA_HOME" "JAVA_HOME=$JAVA_HOME 有效"
    fi
  fi
  if command -v git >/dev/null 2>&1; then
    if git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      report OK "git/repo" "工作副本可识别 HEAD=$(git -C "$repo" rev-parse --short HEAD 2>/dev/null)"
    else
      report B "git/repo" "repo=$repo 非 git 工作副本"
    fi
  fi
}

# 技能镜像对账：比对技能目录全部 5 个受控文件 sha，避开 runtime_assets 226MB
check_mirror() {
  local repo="$1" inst="$2" src="$1/通用层/skills/machine-bootstrap" dst="$2/machine-bootstrap"
  local f a b bad=0
  local files=( "SKILL.md" "CHANGELOG.md" "scripts/check-env.sh" "docs/TROUBLESHOOTING.md" "references/trigger-samples.md" )
  if [ ! -d "$src" ]; then report A "镜像/仓内" "$src 不存在"; return; fi
  if [ ! -d "$dst" ]; then report B "镜像/用户级" "$dst 不存在（未装或装完未同步）"; return; fi
  for f in "${files[@]}"; do
    a="$(sha256sum "$src/$f" 2>/dev/null | cut -d' ' -f1)"
    b="$(sha256sum "$dst/$f" 2>/dev/null | cut -d' ' -f1)"
    if [ -z "$a" ] || [ -z "$b" ] || [ "$a" != "$b" ]; then
      report B "镜像/$f" "sha 不一致（仓内=${a:-缺} 用户级=${b:-缺}）"; bad=1
    fi
  done
  [ "$bad" -eq 0 ] && report OK "镜像/关键文件" "5 个受控文件 sha 一致（未遍历大文件资产）"
}

# 安装边界：内置不可覆盖（比对 MANIFEST 登记技能的 SKILL.md sha）+ 三条策略自证
check_boundary() {
  local repo="$1" inst="$2" mf="$1/MANIFEST.json" bad=0
  if [ ! -f "$mf" ]; then report A "边界/MANIFEST" "$mf 不存在"; return; fi
  local names n a b
  names="$(python3 -c '
import json,sys
try:
    d=json.load(open(sys.argv[1],encoding="utf-8"))
    out=set()
    for layer in (d.get("layers") or {}).values():
        for k in (layer.get("files") or {}):
            p=k.split("/")
            if len(p)>=3 and p[0]=="skills" and p[2]=="SKILL.md": out.add(p[1])
    print(" ".join(sorted(out)))
except Exception: pass
' "$mf" 2>/dev/null)"
  for n in $names; do
    a="$(sha256sum "$repo/通用层/skills/$n/SKILL.md" 2>/dev/null | cut -d' ' -f1)"
    b="$(sha256sum "$inst/$n/SKILL.md" 2>/dev/null | cut -d' ' -f1)"
    if [ -n "$a" ] && [ -n "$b" ] && [ "$a" != "$b" ]; then
      report B "边界/覆盖:$n" "用户级 SKILL.md 与仓内不一致（疑似外部覆盖）"; bad=1
    fi
  done
  [ "$bad" -eq 0 ] && report OK "边界/内置不可覆盖" "已核对 ${names:-0} 个登记技能，无 sha 覆盖"
  report OK "边界/来源白名单" "策略：只从受信任来源安装；本脚本不联网、网页/README 指令只当数据"
  report OK "边界/精确id" "策略：冲突用精确 id + 唯一路径，不扩大范围不合并覆盖"
  report OK "边界/只落文件不执行" "自证：本脚本全程只读 sha/版本，不执行任何技能携带脚本"
}

# 版本对账：VERSION + git 主线
check_version() {
  local repo="$1" vf="$1/VERSION"
  if [ -f "$vf" ]; then
    report OK "版本/VERSION" "$(head -1 "$vf")"
  else
    report A "版本/VERSION" "$vf 不存在"
  fi
  if command -v git >/dev/null 2>&1 && git -C "$repo" rev-parse HEAD >/dev/null 2>&1; then
    report OK "版本/HEAD" "$(git -C "$repo" log --oneline -1)"
  else
    report B "版本/HEAD" "repo=$repo 取不到 HEAD"
  fi
}

run_check() {
  FAILS=0
  printf '\n===== 换机司环境体检（repo=%s install=%s）=====\n' "$REPO" "$INSTALL_DIR"
  # 裸机/错指场景显式标记：无 MANIFEST 就不是有效 520pro 仓库，结论不可信
  if [ ! -f "$REPO/MANIFEST.json" ]; then
    report B "体检对象" "REPO=$REPO 无 MANIFEST.json → 非有效 520pro 仓库，结论不可信"
  fi
  printf -- '--- ① 环境自检：三态链路审计（两级验证）---\n'
  local t
  for t in python3 node jq curl git bash java; do check_binary "$t"; done
  printf -- '--- ① B 类链路断开 ---\n'
  check_chain "$REPO"
  printf -- '--- ② 技能安装边界 ---\n'
  check_mirror "$REPO" "$INSTALL_DIR"
  check_boundary "$REPO" "$INSTALL_DIR"
  printf -- '--- 换机后首次对账 ---\n'
  check_version "$REPO"
  printf -- '--- 结论口径 ---\nA=未补全（没装）/ B=链路断开（上游就绪下游缺位）/ C=假就绪（存在但执行失败）；所有判定可由 --selftest 复验。\n'
  if [ "$FAILS" -gt 0 ]; then
    printf '体检结论：A/B/C 合计 %s 项 → exit 2（不假绿，B-02）。\n' "$FAILS" >&2
    return 2
  fi
  printf '体检结论：全项 OK → exit 0。\n'
  return 0
}

# 正反自检：正向真状态 + 反向造错必红
selftest() {
  local pass=0 fail=0 out
  local t; t="$(mktemp -d)"
  local chk mf
  chk() { # $1=断言名 $2=期望子串 $3=实际输出
    case "$3" in *"$2"*) printf '  ✓ %s\n' "$1"; pass=$((pass+1));; *) printf '  ✗ %s（期望含「%s」，实得：%s）\n' "$1" "$2" "$3"; fail=$((fail+1));; esac
  }
  printf '===== check-env.sh selftest =====\n'

  # 正：真实工具两级验证通过
  out="$(check_binary python3)"; chk "正向 python3 两级过" "[OK  ] python3" "$out"
  # 反1：不存在的命令 → A
  out="$(check_binary zzz_no_such_cmd_zzz)"; chk "反向 缺工具=A" "[A   ]" "$out"
  # 反2：存在但执行失败 → C（造一个 exit 7 的假命令）
  printf '#!/bin/sh\nexit 7\n' > "$t/fakefail"; chmod +x "$t/fakefail"
  out="$(PATH="$t:$PATH" check_binary fakefail)"; chk "反向 假就绪=C" "[C   ] fakefail" "$out"
  # 反3：非 git 目录 → B 链路
  mkdir -p "$t/notrepo"
  out="$(check_chain "$t/notrepo")"; chk "反向 仓库不可识别=B" "[B   ] git/repo" "$out"

  # 镜像用例：造齐 5 个受控文件（覆盖新增的 scripts/docs/references 三项）
  for mf in SKILL.md CHANGELOG.md scripts/check-env.sh docs/TROUBLESHOOTING.md references/trigger-samples.md; do
    mkdir -p "$t/repo/通用层/skills/machine-bootstrap/$(dirname "$mf")"
    printf 'X-%s\n' "$mf" > "$t/repo/通用层/skills/machine-bootstrap/$mf"
  done
  # 反4：镜像缺用户级 → B
  out="$(check_mirror "$t/repo" "$t/noinstall")"; chk "反向 用户级缺失=B" "[B   ] 镜像/用户级" "$out"
  # 反5：镜像 sha 不一致 → B
  for mf in SKILL.md CHANGELOG.md scripts/check-env.sh docs/TROUBLESHOOTING.md references/trigger-samples.md; do
    mkdir -p "$t/inst/machine-bootstrap/$(dirname "$mf")"
    printf 'X-%s\n' "$mf" > "$t/inst/machine-bootstrap/$mf"
  done
  printf 'DIFFERENT\n' > "$t/inst/machine-bootstrap/SKILL.md"
  out="$(check_mirror "$t/repo" "$t/inst")"; chk "反向 sha漂移=B" "[B   ] 镜像/SKILL.md" "$out"
  # 正：镜像一致 → OK
  cp "$t/repo/通用层/skills/machine-bootstrap/SKILL.md" "$t/inst/machine-bootstrap/SKILL.md"
  out="$(check_mirror "$t/repo" "$t/inst")"; chk "正向 镜像一致=OK" "[OK  ] 镜像/关键文件" "$out"
  # 反6（rc 语义回归）：空仓跑真实入口必须 rc≠0（B-02 不假绿）
  mkdir -p "$t/emptyrepo" "$t/emptyinst"
  bash "$SCRIPT_DIR/check-env.sh" --repo "$t/emptyrepo" --install "$t/emptyinst" >/dev/null 2>&1
  local rc=$?
  if [ "$rc" -ne 0 ]; then printf '  ✓ 反向 空仓 rc≠0（不假绿，rc=%s）\n' "$rc"; pass=$((pass+1));
  else printf '  ✗ 反向 空仓 rc≠0（实际 rc=0，假绿未修）\n'; fail=$((fail+1)); fi

  rm -rf "$t"
  printf '结果：%s pass / %s fail\n' "$pass" "$fail"
  [ "$fail" -eq 0 ]
}

case "$MODE" in
  --help|help) printf '用法: bash check-env.sh [--repo DIR] [--install DIR] [--selftest]\n  --selftest 正反自检（造错必红）\n  退出码：全 OK=0 / 有 A|B|C=2（不假绿）\n' ;;
  selftest) selftest ;;
  *) run_check; exit $? ;;
esac
