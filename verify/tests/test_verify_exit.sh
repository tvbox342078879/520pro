#!/usr/bin/env bash
# 520pro verify.sh 退出码 · 回归测试（工程G-3）
# 用法：bash verify/tests/test_verify_exit.sh
# 退出码：0 全过 / 2 有失败
#
# 为什么单测这个：verify.sh 到 v0.8.18 为止**从不 exit**，恒返回 0。
# 人眼看 ✓ 能过，机器看 rc 永远通过——任何"跑一下自检再发布"的脚本都被静默放行。
# 这类假绿最难发现，因为一切都"看起来正常"。
set -uo pipefail
R="$(cd "$(dirname "$0")/../.." && pwd)"
fails=0
ok(){ printf '  ✓ %s\n' "$1"; }
no(){ printf '  ✗ %s\n' "$1"; fails=$((fails+1)); }

echo "【①】健全仓库 → rc=0"
if bash "$R/verify.sh" >/tmp/tve_ok.out 2>&1; then
  ok "健全仓 rc=0"
else
  no "健全仓应 rc=0，实得 $?（先修仓库再跑本测试）"
fi
grep -q '自检通过（退出码 0）' /tmp/tve_ok.out && ok "成功时明说退出码" || no "成功时没说退出码"

echo "【②】残缺目录 → rc=2（不许沉默通过）"
TMP="$(mktemp -d)"
if bash "$R/verify.sh" --target "$TMP" >/tmp/tve_bad.out 2>&1; then
  no "残缺目录竟 rc=0（假绿）"
else
  rc=$?
  [ "$rc" -eq 2 ] && ok "残缺目录 rc=2" || no "残缺目录 rc=$rc，期望 2"
fi
grep -q '自检未通过（退出码 2）' /tmp/tve_bad.out && ok "失败时明说退出码" || no "失败时没说退出码"
rm -rf "$TMP"

echo "【③】汇总行数字必须与输出行数一致（防止计数漏项）"
n_dot=$(grep -c '^  ·' /tmp/tve_ok.out || true)
claim=$(sed -n 's/.*· 无法判定 \([0-9]*\).*/\1/p' /tmp/tve_ok.out | head -1)
[ "${n_dot:-0}" = "${claim:-x}" ] && ok "· 计数一致（$claim）" || no "· 输出 ${n_dot:-0} 行但汇总报 ${claim:-?}"

echo
if [ "$fails" -gt 0 ]; then
  echo "✗ $fails 项失败"
  exit 2
fi
echo "✓ verify.sh 退出码回归全过"
exit 0
