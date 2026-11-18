#!/usr/bin/env bash
# push-safe 正门薄壳：转调仓库 hooks/git_push_safe.sh（不重复实现重试/终验）。
# 从自身位置推 skills 根 → 仓库根，找 hooks/git_push_safe.sh。
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 逐级向上找 hooks/git_push_safe.sh（仓内 ~/.codebuddy 两种布局上溯级数不同，不写死）
target=""
d="$here"
for _ in 1 2 3 4 5 6; do
  if [ -f "$d/hooks/git_push_safe.sh" ]; then target="$d/hooks/git_push_safe.sh"; break; fi
  d="$(dirname "$d")"
done
if [ -z "$target" ]; then
  echo "无法判定：git_push_safe.sh 不在位（找过 $repo_root/ 与 $base/）" >&2
  exit 2
fi
exec bash "$target" "$@"
