#!/usr/bin/env bash
# 工程E T4 反向测试：四种破坏各自必须翻红，恢复后必须全绿
# 用法：bash verify/tests/test_rule_map_reverse.sh
set -u
R="$(cd "$(dirname "$0")/../.." && pwd)"
RM=$R/verify/rule_map.json
C8=$R/通用层/rules/core-8.md
cp "$RM" /tmp/rm.bak; cp "$C8" /tmp/c8.bak
run(){ python3 "$R/verify/terminology_check.py" --repo "$R" >/tmp/t4.out 2>&1; echo "rc=$? | $(grep '\[T4\]' /tmp/t4.out)"; }
restore(){ cp /tmp/rm.bak "$RM"; cp /tmp/c8.bak "$C8"; }

echo "【0】基线（应 rc=0 且 T4 ✓）"; run

echo "【1】删掉 B-05 映射（应红：规则无映射）"
python3 - <<'EOF'
import json;p='/workspace/520pro/verify/rule_map.json'
d=json.load(open(p,encoding='utf-8')); del d['rules']['B-05']
json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
EOF
run; restore

echo "【2】锚点漂移 PATTERNS → PATTERNS_XX（应红）"
python3 - <<'EOF'
import json;p='/workspace/520pro/verify/rule_map.json'
d=json.load(open(p,encoding='utf-8')); d['rules']['B-05']['anchor']='PATTERNS_XX'
json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
EOF
run; restore

echo "【3】core-8 删掉 B-07 尾注（应红：缺尾注 + 尾注不等）"
python3 - <<'EOF'
p='/workspace/520pro/通用层/rules/core-8.md'
t=open(p,encoding='utf-8').read().replace('｜验证 V-MANUAL-07','',1)
open(p,'w',encoding='utf-8').write(t)
EOF
run; restore

echo "【4】kind 写错（应红）"
python3 - <<'EOF'
import json;p='/workspace/520pro/verify/rule_map.json'
d=json.load(open(p,encoding='utf-8')); d['rules']['B-01']['kind']='auto'
json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
EOF
run; restore

echo "【5】恢复后（应 rc=0 且 T4 ✓）"; run
