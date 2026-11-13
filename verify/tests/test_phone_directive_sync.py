#!/usr/bin/env python3
"""test_phone_directive_sync.py — 手机指令副本同步器的变异回归（拆掉实现必须翻红）

为什么要有：同步器最容易"看起来在工作"——写了个请求、拿了个回执、打印 SUCCESS，
内容其实没落地或落错条。本测试不碰网络，只用**真实样本片段**验证三件事：
  ① 粘贴区提取对（剥注释、只取标记之间）
  ② 回读校验真的能判出「少一条 / 换内容 / 串条」
  ③ 过期判据（--check）真的会在过期时红，且幂等短路时一个 API 都不发

11 个用例，其中 T5/T6/T7 是"回读校验失效"的三种形态；T11 证明幂等不是嘴上说的。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(ROOT, 'sync_phone_directive.py')
sys.path.insert(0, ROOT)

import sync_phone_directive as S  # noqa: E402

fails = []


def case(name, cond, detail=''):
    if cond:
        print(f'  ✓ {name}')
    else:
        fails.append(f'{name}{("：" + detail) if detail else ""}')
        print(f'  ✗ {name}{("：" + detail) if detail else ""}')


# 真实样本：粘贴区结构（与 手机指令.md 同形，含注释登记行）
SRC = """# 手机指令

## 【粘贴区 · 从下一行开始复制】

<!-- hard-rail: B-01,B-02 -->
<!-- hard-rail-exempt: B-04 -->

你是我的长期助手，遵守以下铁律：

1. **全程简体中文**：思考、进度都用中文。
2. **三态诚实**：只分真假与无法判定。

**【粘贴区 结束】**

后面是说明，不该被取到。
"""

# 回读正例：照抄 get-doc-review 的真实块结构（标题 + 段落 + 列表块）
READBACK_OK = """---
title: 手机指令粘贴区（复制即用）
---

<Paragraph id="p1">
  你是我的长期助手，遵守以下铁律：
</Paragraph>

<NumberedList id="n1">
  <Mark bold>全程简体中文</Mark>：思考、进度都用中文。
</NumberedList>

<NumberedList id="n2">
  <Mark bold>三态诚实</Mark>：只分真假与无法判定。
</NumberedList>
"""


print('[T1 粘贴区提取]')
got = S.extract_paste(SRC)
case('T1 只取标记之间，剥掉 HTML 注释与说明段',
     got.startswith('你是我的长期助手') and got.rstrip().endswith('只分真假与无法判定。')
     and '<!--' not in got and '后面是说明' not in got, repr(got[:40]))
case('T1b 条数识别为 2', S.clause_count(got) == 2, str(S.clause_count(got)))

try:
    S.extract_paste('# 没有粘贴区的文件\n正文\n')
    case('T2 缺标记必须抛错（不静默取全文）', False, '未抛错')
except ValueError as e:
    case('T2 缺标记必须抛错（不静默取全文）', '起始标记' in str(e), str(e))

try:
    S.extract_paste('## 【粘贴区 · 从下一行开始复制】\n正文但没结束标记\n')
    case('T3 缺结束标记必须抛错', False, '未抛错')
except ValueError as e:
    case('T3 缺结束标记必须抛错', '结束标记' in str(e), str(e))


print('[T4-T7 回读校验]')
ok, probs = S.check_readback(READBACK_OK, got)
case('T4 正例通过（真实块结构）', ok, '；'.join(probs))

# 少一条：模拟"只落了第一条"
ok, probs = S.check_readback(
    READBACK_OK.replace('<NumberedList id="n2">\n  <Mark bold>三态诚实</Mark>：只分真假与无法判定。\n</NumberedList>\n', ''),
    got)
case('T5 少一条必须判失败', (not ok) and any('条数不一致' in p for p in probs), '；'.join(probs))

# 换了内容：首句被改成别的
ok, probs = S.check_readback(READBACK_OK.replace('你是我的长期助手', '你是我的短期助手'), got)
case('T6 首句被替换必须判失败', (not ok) and any('首句' in p for p in probs), '；'.join(probs))

# 串条：某条小标题没落地
ok, probs = S.check_readback(READBACK_OK.replace('三态诚实', '三态大概诚实'), got)
case('T7 小标题串改必须判失败', (not ok) and any('小标题' in p for p in probs), '；'.join(probs))


print('[T8-T10 过期判据（--check，离线）]')
def make_repo(tmp, src_text, state):
    os.makedirs(os.path.join(tmp, 'docs'), exist_ok=True)
    with open(os.path.join(tmp, '手机指令.md'), 'w', encoding='utf-8') as f:
        f.write(src_text)
    if state is not None:
        with open(os.path.join(tmp, 'docs', '手机指令云端副本.json'), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)


def run_check(tmp):
    p = subprocess.run([sys.executable, SCRIPT, '--repo', tmp, '--check'],
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or '').strip()


with tempfile.TemporaryDirectory() as t:
    sha = S.digest(S.extract_paste(SRC))
    make_repo(t, SRC, {'node_id': 'n1', 'sha256': sha})
    rc, out = run_check(t)
    case('T8 一致时 FRESH rc=0', rc == 0 and 'FRESH' in out, out)

with tempfile.TemporaryDirectory() as t:
    make_repo(t, SRC, {'node_id': 'n1', 'sha256': '0' * 64})
    rc, out = run_check(t)
    case('T9 过期时 STALE rc=1 且说明原因', rc == 1 and 'STALE' in out and '过期' in out, out)

with tempfile.TemporaryDirectory() as t:
    make_repo(t, SRC, None)
    rc, out = run_check(t)
    case('T10 无状态时 STALE rc=1（不装作已同步）', rc == 1 and '尚未建立' in out, out)


print('[T11 幂等短路真的不调 API]')
with tempfile.TemporaryDirectory() as t:
    sha = S.digest(S.extract_paste(SRC))
    make_repo(t, SRC, {'node_id': 'n1', 'sha256': sha, 'space_id': 's1', 'title': 'x'})
    # 把 skill 目录指向不存在的路径：若仍成功，说明根本没走网络分支
    env = dict(os.environ)
    env['CODEBUDDY_SKILL_DIR'] = os.path.join(t, '__no_such_skill__')
    env['HOME'] = os.path.join(t, '__no_home__')
    p = subprocess.run([sys.executable, SCRIPT, '--repo', t], capture_output=True, text=True, env=env)
    case('T11 sha 一致 → NOOP rc=0，且在"没装库"的环境里也能过',
         p.returncode == 0 and 'NOOP' in (p.stdout or ''), (p.stdout or p.stderr).strip()[:160])

if fails:
    for f in fails:
        print(f'  ✗ {f}')
    print(f'\n{len(fails)} 项失败')
    sys.exit(1)
print('\n手机指令副本同步器变异回归全部通过（11 用例：提取 2 + 缺标记 2 + 回读 4 + 判据 3）')
sys.exit(0)
