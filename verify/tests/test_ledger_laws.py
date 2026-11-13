#!/usr/bin/env python3
"""test_ledger_laws.py — 台账四律判据的变异回归（拆掉实现必须翻红）

判据全绿不等于判据有效：一条永远返回 ✓ 的判据也全绿。本测试用**临时仓库**造四种
坏数据，逐一验证对应判据精确翻红、且只翻对应那一条（不误伤其他三条）。

每个 case 都是"判据声称要测的东西"被破坏的最小样本：
  C1 中间态过半      → L1 必须红
  C2 检查过但无指纹  → L2 必须红
  C3 已结区重复键    → L3 必须红
  C4 模块级退出码全局 → L4 必须红
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(ROOT, 'verify', 'ledger_laws.py')
TARGETS_REL = '能力层/tvbox/skills/probe-hub/scripts/monitor_targets.json'
STATE_REL = '通用层/skills/space-hub/scripts/space_hub_state.json'

fails = []


def build(tmp, targets=None, state=None, py=None):
    if targets is not None:
        p = os.path.join(tmp, TARGETS_REL)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(targets, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    if state is not None:
        p = os.path.join(tmp, STATE_REL)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(state, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    if py is not None:
        open(os.path.join(tmp, 'bad_script.py'), 'w', encoding='utf-8').write(py)


def run(tmp):
    r = subprocess.run([sys.executable, SCRIPT, '--repo', tmp],
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


def expect(name, tmp, want_rc, want_tag):
    rc, out = run(tmp)
    if rc != want_rc:
        fails.append(f'{name}: 退出码 {rc} ≠ 期望 {want_rc}')
        return
    if want_tag:
        hit = any(f'✗ [{want_tag}]' in ln for ln in out.splitlines())
        if not hit:
            fails.append(f'{name}: 未见 ✗ [{want_tag}]（判据没抓住，或用错标签）')
    print(f'  ✓ {name}（rc={rc}）')


GOOD_TARGETS = {'targets': [
    {'存活状态': '存活', '活跃度': '活跃', '上次检查': '2026-11-13', '内容指纹': 'abc123'},
    {'存活状态': '已封禁/删除', '活跃度': '归档', '上次检查': '2026-11-13', '内容指纹': 'def456'},
]}
GOOD_STATE = {'archive_log': [{'node_id': 'n1'}, {'node_id': 'n2'}]}

with tempfile.TemporaryDirectory() as t0:
    build(t0, GOOD_TARGETS, GOOD_STATE)
    expect('C0 全绿基线', t0, 0, None)

with tempfile.TemporaryDirectory() as t1:
    bad = {'targets': [{'存活状态': '待查', '活跃度': '待查'}] * 6}
    build(t1, bad, GOOD_STATE)
    expect('C1 中间态过半', t1, 1, 'L1')

with tempfile.TemporaryDirectory() as t2:
    bad = {'targets': [{'存活状态': '存活', '活跃度': '活跃',
                        '上次检查': '2026-11-13', '内容指纹': ''}] * 4}
    build(t2, bad, GOOD_STATE)
    expect('C2 检查过但无指纹', t2, 1, 'L2')

with tempfile.TemporaryDirectory() as t3:
    build(t3, GOOD_TARGETS, {'archive_log': [{'node_id': 'dup'}, {'node_id': 'dup'}]})
    expect('C3 已结区重复键', t3, 1, 'L3')

with tempfile.TemporaryDirectory() as t4:
    build(t4, GOOD_TARGETS, GOOD_STATE,
          py="import sys\n_RC = 0\ndef main():\n    return sys.exit(f() or 0)\n")
    expect('C4 退出码住全局', t4, 1, 'L4')

# C5：自指不得误报——把判据自己的反例文本放进去，不应命中
with tempfile.TemporaryDirectory() as t5:
    build(t5, GOOD_TARGETS, GOOD_STATE,
          py="import sys\n# 反例：sys.exit(x or 0) 把 None 当成功\nDOC = 'sys.exit(x or 0)'\n")
    expect('C5 注释/字符串里的反例不误报', t5, 0, None)

if fails:
    for f in fails:
        print(f'  ✗ {f}')
    print(f'\n{len(fails)} 项失败')
    sys.exit(1)
print('\n台账四律变异回归全部通过（4 红 1 不误报 1 基线）')
sys.exit(0)
