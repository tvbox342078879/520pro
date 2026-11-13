#!/usr/bin/env python3
"""linkage_notice.py — 真源联动提醒（G6 轻量版，v0.8.28）

解决什么：改了真源文件，引用它的指针没跟上——M5 连带靠人记不可靠，而
terminology_check 只能查"文字断链"，查不了"语义过期"（引用还在、意思已旧）。

做什么（提醒性，不阻断）：本次提交若包含 registry.md 登记的真源文件，
自动 grep 全仓列出"谁在读"，打印一行清单——把「靠人记」变成「机器提醒」。

真源清单的唯一来源：docs/registry.md 表格第 2 列（唯一真源列）的反引号路径，
且该路径在仓库内真实存在（运行时登记册等不存在的路径自动过滤，M1 不复制清单）。

口径：
- 引用 = 出现完整相对路径，或反引号包裹的文件名（`X.md`），两者任一。
- 排除自身、registry.md（索引不算消费方）、本脚本、CHANGELOG.md（历史档案不查，
  与 terminology_check 同口径）。
- 退出码恒为 0（advisory）；脚本自身异常必须打印显式警告，不许静默（B-10）。
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_REL = 'docs/registry.md'
SELF_NAME = 'linkage_notice.py'
EXCLUDE_BASENAMES = {'registry.md', SELF_NAME, 'CHANGELOG.md'}
SCAN_SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.codebuddy'}
MAX_MB = 2
MAX_REF_NAMES = 8
TEXT_EXT = {'.md', '.py', '.json', '.sh', '.yml', '.yaml', '.txt', '.toml',
            '.cfg', '.html', ''}
BIN_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.zip', '.tar', '.gz', '.pdf',
           '.woff', '.ttf', '.ico', '.mp4', '.mp3'}


def _cells(line):
    return [c.strip() for c in line.split('|')]


def parse_truth_sources(root):
    """从 registry.md 表格第 2 列提取反引号路径，过滤出真实存在的文件。"""
    reg = os.path.join(root, REGISTRY_REL)
    if not os.path.isfile(reg):
        return []
    found = set()
    with open(reg, encoding='utf-8') as f:
        for line in f:
            if not line.lstrip().startswith('|'):
                continue
            cells = _cells(line.rstrip('\n'))
            if len(cells) < 3 or cells[1] in ('事实类别', '---', ':---', '---:'):
                continue
            for tok in re.findall(r'`([^`]+)`', cells[2]):
                tok = tok.strip()
                if not tok or ' ' in tok:
                    continue
                if '/' in tok:
                    if os.path.isfile(os.path.join(root, tok)):
                        found.add(tok)
                elif os.path.isfile(os.path.join(root, tok)):
                    # 根目录下的裸文件名（如 VERSION）
                    found.add(tok)
    return sorted(found)


def _is_scannable(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in BIN_EXT:
        return False
    return ext in TEXT_EXT


def _iter_repo_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SCAN_SKIP_DIRS and not d.endswith('.egg-info')]
        for name in filenames:
            yield os.path.join(dirpath, name)


def find_refs(root, rel_path):
    """列出仓库内引用了 rel_path 的文件（完整路径或反引号裸文件名）。"""
    rel_path = rel_path.replace(os.sep, '/')
    base = os.path.basename(rel_path)
    pat_full = re.escape(rel_path)
    pat_base = re.compile('`' + re.escape(base) + '`')
    self_abs = os.path.abspath(os.path.join(root, rel_path))
    refs = []
    for fp in _iter_repo_files(root):
        frel = os.path.relpath(fp, root).replace(os.sep, '/')
        base_name = os.path.basename(frel)
        if base_name in EXCLUDE_BASENAMES:
            continue
        if os.path.abspath(fp) == self_abs:
            continue
        if not _is_scannable(frel):
            continue
        try:
            if os.path.getsize(fp) > MAX_MB * 1024 * 1024:
                continue
            with open(fp, encoding='utf-8') as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        # 带路径的真源：完整路径或裸文件名命中都算（现实引用大量出现在 shell
        # 引号和正文裸写里，只认反引号会漏报——P3 教训）；无路径裸名（VERSION）
        # 只认反引号，防正文到处出现造成噪声。宁多报不漏报（advisory）。
        if ('/' in rel_path and (rel_path in text or base in text)) \
                or ('/' not in rel_path and pat_base.search(text)):
            refs.append(frel)
    return sorted(refs)


def staged_files(root):
    """本次提交暂存的文件（★ core.quotepath=false：中文名不转义，历史教训）。"""
    try:
        r = subprocess.run(
            ['git', '-c', 'core.quotepath=false', 'diff', '--cached',
             '--name-only', '--diff-filter=ACMR'],
            cwd=root, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print('  ⚠ linkage_notice: git diff 失败，无法判定本次改动（非静默）')
            return []
        return [ln for ln in r.stdout.splitlines() if ln.strip()]
    except Exception as e:  # noqa: BLE001 — 提醒器不许把提交挂住，但必须出声
        print(f'  ⚠ linkage_notice: 自身异常 {e!r}（本轮未检，非静默）')
        return []


def notice(root, staged):
    """对暂存文件里的真源逐个列引用方；返回打印的行数（供测试）。"""
    truths = parse_truth_sources(root)
    lines = 0
    for rel in truths:
        if rel not in staged:
            continue
        refs = find_refs(root, rel)
        names = ', '.join(refs[:MAX_REF_NAMES]) + (' …' if len(refs) > MAX_REF_NAMES else '')
        print(f'  ⚑ 改动了真源 `{rel}`：{len(refs)} 处引用（{names}）')
        print('     按 M5 核对指针口径是否仍成立（语义过期机检查不了，人眼过一遍）')
        lines += 2
    if lines == 0:
        print('  · 本次提交未动真源文件，联动提醒跳过')
        lines = 1
    return lines


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default='.')
    ap.add_argument('--staged', nargs='*', default=None,
                    help='显式传入暂存文件清单（测试用）；缺省时由 git 计算')
    args = ap.parse_args()
    root = os.path.abspath(args.repo)
    staged = args.staged if args.staged is not None else staged_files(root)
    notice(root, staged)
    return 0


if __name__ == '__main__':
    sys.exit(main())
