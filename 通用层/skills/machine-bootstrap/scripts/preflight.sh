#!/usr/bin/env bash
# preflight.sh —— 换机第 0 步之前的裸机前置体检（machine-bootstrap，2026-11-16）
#
# 定位：解决"鸡生蛋"——新设备上仓库还没 clone、钩子没装、check-env.sh/verify.sh 都还在
# 仓库里，此时唯一能跑的是这个**不依赖任何仓库/git** 的独立单文件。
#   裸机拿到它 → 先体检缺什么（git/curl/python3/网络/凭据）→ 按提示补齐 → 再跑手机指令.md:36
#   的 curl 拉 bootstrap → 换机 → 最后用 check-env.sh（换机后验收）核三通道。
#
# 设计与 check-env.sh 的区别（不是矛盾，是分工）：
#   check-env.sh = 换机**后**验收，缺件=不该发生 → 有 A/B/C 即 exit 2（不假绿）。
#   preflight.sh = 换机**前**侦察，缺件=预期发现 → rc 只表"体检能否跑完"（0 跑完/2 自身异常），
#                  缺什么用 A/B/C 标签如实报告 + 末尾给修复清单（借鉴旧生态 368817 的 L0 分层）。
#   两者共用三态口径（core-8.md B-02）：A 未装 / B 链路断 / C 假就绪 / OK 就绪。
#
# 用法：
#   bash preflight.sh                 # 体检裸机，输出三态 + 修复清单
#   bash preflight.sh --net-url URL   # 指定探测 URL（默认 GitHub raw，只 HEAD 不下载）
#   bash preflight.sh --selftest      # 正反自检（造错必报，不联网）
#   bash preflight.sh --help
# 纪律：只读探测，不改文件、不联网下载正文、不打印/存储任何 token。
set -uo pipefail

NET_URL="https://raw.githubusercontent.com/tvbox342078879/520pro/main/bootstrap.sh"
MODE="check"
while [ $# -gt 0 ]; do
  case "$1" in
    --net-url) NET_URL="${2:-}"; shift 2 ;;
    --selftest) MODE="selftest"; shift ;;
    --help|-h) MODE="help"; shift ;;
    *) printf '错误: 未知参数 %s\n用法: bash preflight.sh [--net-url URL] [--selftest]\n' "$1" >&2; exit 2 ;;
  esac
done

report() { printf '[%-4s] %-22s %s\n' "$1" "$2" "$3"; }

# 两级验证（沿用 check-env）：command -v 查存在 + 真跑 --version 查退出码
check_binary() {
  local name="$1" varg="${2:---version}" out rc
  if ! command -v "$name" >/dev/null 2>&1; then
    report A "$name" "未装（command -v 无输出）"; return
  fi
  out="$("$name" "$varg" 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    report C "$name" "存在但 '$varg' 退出码=$rc：$(printf '%s' "$out" | head -1)"; return
  fi
  report OK "$name" "$(printf '%s' "$out" | head -1)"
}

# 网络探测：curl -I 只取响应头，不下载正文；无 curl 时无法判定（不假装）
check_network() {
  local url="$1"
  if ! command -v curl >/dev/null 2>&1; then
    report B "网络/可达" "无 curl，无法探测 $url（无法判定，不是'没有网络'）"; return
  fi
  local rc code
  code="$(curl -sS -I -o /dev/null -w '%{http_code}' --max-time 12 "$url" 2>/dev/null)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    report B "网络/可达" "curl 探测失败 rc=$rc（弱网/被墙/URL 错，无法判定具体原因）"; return
  fi
  case "$code" in
    200|301|302|303|307|308) report OK "网络/可达" "$url → HTTP $code（可拉脚本）" ;;
    000) report B "网络/可达" "$url → 无响应（无法判定）" ;;
    *)   report C "网络/可达" "$url → HTTP $code（非预期，需核对 URL/权限）" ;;
  esac
}

# 凭据探测：只看"有没有来源"，绝不打印值、不落盘
check_credential() {
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    report OK "凭据/来源" "GITHUB_TOKEN 已在环境变量（脚本不读取值、不打印）"
    return
  fi
  if command -v gh >/dev/null 2>&1 && gh auth token >/dev/null 2>&1; then
    report OK "凭据/来源" "gh auth token 可用（公开仓无需；私有 fork 才需要）"
    return
  fi
  report A "凭据/来源" "无 token 来源——公开仓匿名克隆足够；私有 fork 需先配 GITHUB_TOKEN 或 gh auth login"
}

# shell 基本件：bash / coreutils（cat/mkdir/sed/grep）——这几个没有则本脚本都跑不稳
check_coreutils() {
  local c
  for c in bash sed grep mkdir cat; do
    if command -v "$c" >/dev/null 2>&1; then
      report OK "基础/$c" "在位"
    else
      report A "基础/$c" "缺失（coreutils 不全，先补系统基础件）"
    fi
  done
}

run_check() {
  printf '\n===== 换机裸机前置体检（preflight，不依赖仓库/git）=====\n'
  printf -- '--- 基础件 ---\n';        check_coreutils
  printf -- '--- 换机主工具（两级验证）---\n'
  check_binary git
  check_binary curl
  check_binary python3 --version
  check_binary node --version
  check_binary jq --version
  check_binary unzip -v
  printf -- '--- 链路与凭据 ---\n'
  check_network "$NET_URL"
  check_credential
  printf -- '--- 结论 ---\n'
  printf '本脚本只读探测、未改任何文件、未下载正文、未读取任何 token 值。\n'
  printf '下一步：缺 git/curl/python3 → 先装基础件；网络 B → 弱网重试或换 URL；\n'
  printf '        齐了再跑手机指令.md 第 0 步 curl 拉 bootstrap → 换机 → check-env.sh 验收。\n'
  # rc 只表体检能否跑完；缺件是如实报告，不是脚本故障（见文件头设计说明）。
  return 0
}

selftest() {
  local pass=0 fail=0 out
  local chk
  chk() {
    case "$3" in *"$2"*) printf '  ✓ %s\n' "$1"; pass=$((pass+1));; *) printf '  ✗ %s（期望「%s」，实得：%s）\n' "$1" "$2" "$3"; fail=$((fail+1));; esac
  }
  printf '===== preflight.sh selftest（不联网）=====\n'
  out="$(check_binary bash)";            chk "正向 基础件在位=OK" "[OK  ] bash" "$out"
  out="$(check_binary zzz_no_such_cmd)"; chk "反向 缺工具=A" "[A   ]" "$out"
  # 反：存在但执行失败 → C
  local t; t="$(mktemp -d)"; printf '#!/bin/sh\nexit 7\n' > "$t/ff"; chmod +x "$t/ff"
  out="$(PATH="$t:$PATH" check_binary ff)"; chk "反向 假就绪=C" "[C   ] ff" "$out"
  # 网络：指向必然失败的本地地址 → B（不联网、快速失败）
  out="$(check_network 'http://127.0.0.1:1/nope')"; chk "反向 网络不可达=B" "[B   ] 网络/可达" "$out"
  # 凭据：本进程内临时清空两来源 → A（公开仓正常态），跑完恢复，不污染环境
  local _gt="${GITHUB_TOKEN-}" _path="$PATH" _had=0
  [ -n "${GITHUB_TOKEN+x}" ] && _had=1
  unset GITHUB_TOKEN; PATH=/nonexistent-gh-path
  out="$(check_credential 2>/dev/null)"
  chk "反向 无 token=A" "[A   ] 凭据/来源" "$out"
  PATH="$_path"; [ "$_had" -eq 1 ] && GITHUB_TOKEN="$_gt"
  # 正：GITHUB_TOKEN 在 → OK（脚本只读存在性、不打印值）
  out="$(GITHUB_TOKEN=dummy-not-real check_credential 2>/dev/null)"
  chk "正向 有 token=OK" "[OK  ] 凭据/来源" "$out"
  rm -rf "$t"
  printf '结果：%s pass / %s fail\n' "$pass" "$fail"
  [ "$fail" -eq 0 ]
}

case "$MODE" in
  --help|help) printf '用法: bash preflight.sh [--net-url URL] [--selftest]\n  裸机前置体检：不依赖仓库/git，三态报告缺什么 + 修复顺序。\n  --selftest 正反自检（造错必报，不联网）。\n' ;;
  selftest) selftest ;;
  *) run_check; exit $? ;;
esac
