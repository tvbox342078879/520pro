#!/usr/bin/env python3
"""test_linkage_notice.py — 真源联动提醒的变异回归（拆掉实现必须翻红）

对照 v0.8.26 的教训：pre-commit 触发条件静默失效（中文名转义导致 grep 永不
命中，看起来在工作实际一次没跑过）。提醒型判据必须用正样本证明它会命中。

用临时仓库造 7 个样本：
  P1 改真源 + 存在完整路径引用  → 必须列出引用方
  P2 改真源 + 仅反引号裸名引用  → 必须列出（裸名只认反引号）
  P3 中文文件名真源             → 必须命中（quotepath 教训的直测）
  P4 shell 引号/正文裸写引用    → 必须列出（首版只认反引号，被现实用法漏报）
  N1 改的不是真源               → 不得误报
  N2 引用被删除                 → 不得再报该引用方
  N3 registry.md / CHANGELOG 里的引用不算消费方 → 不得计入
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'verify'))
import linkage_notice as ln  # noqa: E402

fails = []

REGISTRY = '''# 唯一真源登记表（tmp）

## 一、规则层

| 事实类别 | 唯一真源 | 说明 |
|---|---|---|
| 通用铁律 | `规则/core-8.md` | 十八条 |
| 生态版本号 | `VERSION` | 首行 |
| 运行时（不存在，应被过滤） | `通用层/不存在的文件.json` | — |
'''


def build(tmp, truth_content, ref_content, extra_registry=None):
    os.makedirs(os.path.join(tmp, '规则'), exist_ok=True)
    with open(os.path.join(tmp, '规则', 'core-8.md'), 'w', encoding='utf-8') as f:
        f.write(truth_content)
    with open(os.path.join(tmp, 'VERSION'), 'w', encoding='utf-8') as f:
        f.write('0.8.28\n')
    os.makedirs(os.path.join(tmp, 'docs'), exist_ok=True)
    reg = extra_registry if extra_registry is not None else REGISTRY
    with open(os.path.join(tmp, 'docs', 'registry.md'), 'w', encoding='utf-8') as f:
        f.write(reg)
    if ref_content is not None:
        with open(os.path.join(tmp, '消费方.py'), 'w', encoding='utf-8') as f:
            f.write(ref_content)


def check(name, cond, detail=''):
    if cond:
        print(f'  ✓ {name}')
    else:
        fails.append(f'{name}: {detail}')
        print(f'  ✗ {name}——{detail}')


# P1 完整路径引用 → 命中
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, '# 基座\nB-01 语言\n', 'x = "见 规则/core-8.md 的 B-01"\n')
    refs = ln.find_refs(tmp, '规则/core-8.md')
    check('P1 完整路径引用被列出', refs == ['消费方.py'], f'实际 {refs}')

# P4 裸文件名引用（shell 引号/正文裸写，不带路径不带反引号）→ 也必须列出
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, '# 基座\n', "grep -qx 'core-8.md'\n")
    refs = ln.find_refs(tmp, '规则/core-8.md')
    check('P4 裸文件名引用被列出', refs == ['消费方.py'], f'实际 {refs}')

# P2 仅反引号裸名引用（VERSION）→ 命中；不带反引号的 VERSION 不算
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, '# 基座\n',
          '读 `VERSION`；另外正文里裸写 VERSION 不应算\n')
    refs = ln.find_refs(tmp, 'VERSION')
    check('P2 反引号裸名被列出', refs == ['消费方.py'], f'实际 {refs}')

# P3 中文文件名真源 + 中文引用 → 命中（quotepath 教训直测）
with tempfile.TemporaryDirectory() as tmp:
    os.makedirs(os.path.join(tmp, 'docs'), exist_ok=True)
    with open(os.path.join(tmp, 'docs', 'registry.md'), 'w', encoding='utf-8') as f:
        f.write('| 事实 | 唯一真源 | 说明 |\n|---|---|---|\n| 手册 | `docs/手机指令.md` | — |\n')
    with open(os.path.join(tmp, 'docs', '手机指令.md'), 'w', encoding='utf-8') as f:
        f.write('# 手机指令\n')
    with open(os.path.join(tmp, '钩子'), 'w', encoding='utf-8') as f:
        f.write("grep -qx '手机指令.md'\n")
    refs = ln.find_refs(tmp, 'docs/手机指令.md')
    check('P3 中文真源引用被列出', refs == ['钩子'], f'实际 {refs}')

# N1 暂存的不是真源 → notice 不出⚑行
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, '# 基座\n', 'x = "见 规则/core-8.md"\n')
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        n = ln.notice(tmp, ['别的文件.md'])
    check('N1 非真源不误报', '⚑' not in buf.getvalue() and '跳过' in buf.getvalue(),
          f'输出: {buf.getvalue()!r}')

# N2 引用被删除 → 引用方列表为空
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, '# 基座\n', 'x = 1  # 不再引用\n')
    refs = ln.find_refs(tmp, '规则/core-8.md')
    check('N2 删除引用后不再列出', refs == [], f'实际 {refs}')

# N3 registry.md / CHANGELOG.md / 自身不算消费方
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, '# 基座\n', None,
          extra_registry=REGISTRY.replace('十八条',
                                          '十八条，见 规则/core-8.md 与 `规则/core-8.md`'))
    with open(os.path.join(tmp, 'CHANGELOG.md'), 'w', encoding='utf-8') as f:
        f.write('## v1\n引用 规则/core-8.md\n')
    refs = ln.find_refs(tmp, '规则/core-8.md')
    check('N3 索引/历史档案/自身不计入', refs == [], f'实际 {refs}')

# 附加：解析过滤——registry 里不存在的路径不进真源清单
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, '# 基座\n', None)
    truths = ln.parse_truth_sources(tmp)
    check('T1 不存在的登记路径被过滤',
          '规则/core-8.md' in truths and 'VERSION' in truths
          and '通用层/不存在的文件.json' not in truths,
          f'实际 {truths}')

print('============================================')
if fails:
    print(f'✗ {len(fails)} 项失败')
    for f in fails:
        print(f'  ✗ {f}')
    sys.exit(1)
print('✓ 联动提醒回归通过（7 用例 + 1 过滤项）')
