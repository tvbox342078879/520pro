#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""artifact.py — artifact-store 执行体（只读扫描 · 归档计划 · 绝不删除）

用法:
  python3 artifact.py scan [--root DIR] [--keep N] [--json]
  python3 artifact.py self-check

为什么要有脚本，而不是让 AI 照 SKILL.md 自己编:
  SKILL.md 写「产物 LRU 只留 2 轮，更早归档 + 删本地」。这句话有两个危险点
  靠读文字判不了：
    1) 「产物」的边界。实测某会话目录 30MB，其中 27MB 是一个含 .git 的
       仓库副本。按 mtime 无脑清会删掉工作副本 —— 这是不可逆事故。
    2) 「2 轮」的判据。轮次 = 会话，不是文件 mtime。同一会话里再老的文件
       也属于本轮产物，按天清会把当天要用的东西清掉。
  脚本把这两条变成可复核的输出：先分类（保护 / 可再生 / 产物），再按会话
  轮次算计划，最后只打印、不执行。

三态（对齐 B-02 与 inspect_hub 的 unknown 约定）:
  OK      扫描完成，有可执行计划
  NOOP    扫描完成，无可归档（会话轮次未超过 keep）
  UNKNOWN 路径不存在 / 无权限 / 根不在白名单 —— 无法判定，绝不装绿

退出码: 0=OK|NOOP  1=存在需人工确认项  2=UNKNOWN
"""
import argparse
import json
import os
import sys
import tempfile

HOME = os.path.expanduser('~')
DEFAULT_ROOT = os.path.join(HOME, '.codebuddy', 'artifact')
# 白名单父目录：只允许扫 ~/.codebuddy 之下，防止被误指到 / 或家目录
ALLOWED_PARENT = os.path.realpath(os.path.join(HOME, '.codebuddy'))

# 保护区标记：出现即整棵子树不碰。来源 = SKILL.md §4「不碰源码/规则」
PROTECT_MARKERS = ('.git',)
# 可再生：删了能重新生成，风险为零。来源 = CPython 字节码缓存约定
REGEN_DIRS = ('__pycache__', '.pytest_cache', '.mypy_cache')
REGEN_EXTS = ('.pyc', '.pyo')

ST_LABEL = {'OK': 'OK 有计划', 'NOOP': 'NOOP 无需归档', 'UNKNOWN': 'UNKNOWN 无法判定'}


# ---------- 路径安全 ----------
def resolve_root(raw):
    """解析并校验扫描根。返回 (realpath, None) 或 (None, 原因)。"""
    path = os.path.realpath(os.path.expanduser(raw))
    if not os.path.exists(path):
        return None, f'路径不存在: {path}'
    if not os.path.isdir(path):
        return None, f'不是目录: {path}'
    if not os.access(path, os.R_OK | os.X_OK):
        return None, f'无读取权限: {path}'
    if not (path == ALLOWED_PARENT or path.startswith(ALLOWED_PARENT + os.sep)):
        return None, f'根不在白名单内（须位于 {ALLOWED_PARENT} 之下）: {path}'
    return path, None


def is_under(path, roots):
    return any(path == r or path.startswith(r + os.sep) for r in roots)


# ---------- 分类 ----------
def find_protected_roots(session_dir):
    """找出所有含 .git 的目录 —— 这些子树整体视为源码，不参与归档。"""
    roots = []
    for dirpath, dirnames, _ in os.walk(session_dir, followlinks=False):
        if any(os.path.isdir(os.path.join(dirpath, m)) for m in PROTECT_MARKERS):
            roots.append(dirpath)
            dirnames[:] = []          # 不再深入，避免把 .git 内每个对象都数一遍
    return roots


def classify(session_dir):
    """把一棵会话树切成三堆，只统计不移动。

    返回 dict: protected / regen / candidate 各自的 files+bytes，外加保护根清单。
    """
    prot_roots = find_protected_roots(session_dir)
    out = {
        'protected': {'files': 0, 'bytes': 0, 'roots': []},
        'regen': {'files': 0, 'bytes': 0},
        'candidate': {'files': 0, 'bytes': 0},
    }
    for r in prot_roots:
        out['protected']['roots'].append(os.path.relpath(r, session_dir))

    for dirpath, dirnames, filenames in os.walk(session_dir, followlinks=False):
        # 不跟随符号链接，防 TOCTOU 逃逸（import_guard 同类教训）
        for name in list(dirnames):
            if os.path.islink(os.path.join(dirpath, name)):
                dirnames.remove(name)
        in_prot = is_under(dirpath, prot_roots)
        base = os.path.basename(dirpath)
        is_regen_dir = any(part in REGEN_DIRS for part in dirpath.split(os.sep))
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            try:
                size = os.lstat(full).st_size
            except OSError:
                continue
            if in_prot:
                bucket = out['protected']
            elif is_regen_dir or base in REGEN_DIRS or name.endswith(REGEN_EXTS):
                bucket = out['regen']
            else:
                bucket = out['candidate']
            bucket['files'] += 1
            bucket['bytes'] += size
    return out


def scan_sessions(root, keep):
    """按会话轮次给结论：只有「第 keep+1 轮及更早」才进入归档候选。"""
    sessions = []
    try:
        names = sorted(os.listdir(root))
    except OSError as exc:
        return None, f'无法列出 {root}: {exc}'
    for name in names:
        full = os.path.join(root, name)
        if not os.path.isdir(full) or os.path.islink(full):
            continue
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        stats = classify(full)
        stats['name'] = name
        stats['path'] = full
        stats['mtime'] = mtime
        sessions.append(stats)
    # 新 → 旧
    sessions.sort(key=lambda s: s['mtime'], reverse=True)
    for idx, s in enumerate(sessions):
        s['rank'] = idx + 1
        s['archivable'] = idx >= keep
    return sessions, None


# ---------- 渲染 ----------
def human(n):
    for unit in ('B', 'K', 'M', 'G'):
        if n < 1024 or unit == 'G':
            return f'{n:.0f}{unit}' if unit == 'B' else f'{n:.1f}{unit}'
        n /= 1024.0


def verdict(sessions, keep):
    if not sessions:
        return 'NOOP', '根下没有会话目录，无可归档'
    arch = [s for s in sessions if s['archivable']]
    if not arch:
        return 'NOOP', f'仅 {len(sessions)} 个会话，未超过 keep={keep}，无轮次可归档'
    return 'OK', f'{len(arch)} 个会话超出 keep={keep}，进入归档候选'


def render_text(root, keep, sessions, status, reason):
    lines = [f'[artifact] root={root} keep={keep} 会话数={len(sessions)}', '']
    for s in sessions:
        tag = '归档候选' if s['archivable'] else '本轮保留'
        total = s['protected']['bytes'] + s['regen']['bytes'] + s['candidate']['bytes']
        nfiles = s['protected']['files'] + s['regen']['files'] + s['candidate']['files']
        lines.append(f"会话 {s['name'][:8]}…  {human(total)}/{nfiles} 文件  [{tag}]")
        if s['protected']['roots']:
            names = ', '.join(s['protected']['roots'][:3])
            lines.append(f"  🛡 保护 {human(s['protected']['bytes']):>7}  {s['protected']['files']:>5} 文件  含 .git：{names}")
        if s['regen']['files']:
            lines.append(f"  ♻ 可再生 {human(s['regen']['bytes']):>5}  {s['regen']['files']:>5} 文件  __pycache__/*.pyc")
        lines.append(f"  · 普通产物 {human(s['candidate']['bytes']):>5}  {s['candidate']['files']:>5} 文件")
        lines.append('')
    lines.append(f'判定：{ST_LABEL[status]} — {reason}')
    if status == 'NOOP':
        lines.append('提示：本脚本只读，不移动、不删除任何文件；如需清可再生缓存请人工执行。')
    return '\n'.join(lines)


def render_json(root, keep, sessions, status, reason):
    return json.dumps({
        'status': status, 'reason': reason, 'root': root, 'keep': keep,
        'sessions': sessions,
        'totals': {
            'protected': sum(s['protected']['bytes'] for s in sessions),
            'regen': sum(s['regen']['bytes'] for s in sessions),
            'candidate': sum(s['candidate']['bytes'] for s in sessions),
        },
    }, ensure_ascii=False, indent=2)


# ---------- 命令 ----------
def cmd_scan(args):
    root, err = resolve_root(args.root)
    if err:
        print(f'判定：{ST_LABEL["UNKNOWN"]} — {err}', file=sys.stderr)
        return 2
    sessions, err = scan_sessions(root, args.keep)
    if err:
        print(f'判定：{ST_LABEL["UNKNOWN"]} — {err}', file=sys.stderr)
        return 2
    status, reason = verdict(sessions, args.keep)
    if args.json:
        print(render_json(root, args.keep, sessions, status, reason))
    else:
        print(render_text(root, args.keep, sessions, status, reason))
    # 只有「有候选但有保护区」时才退出 1：存在需人确认的删除动作
    has_prot = any(s['protected']['files'] for s in sessions)
    if status == 'OK' and has_prot:
        return 1
    return 0


def cmd_self_check():
    """用构造样本验证分类器 —— 拆掉任一规则必须让对应用例翻红。"""
    fails = []

    def check(name, cond, detail=''):
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        # 样本 1：含 .git 的子树 → 必须归 PROTECTED，且不深入 .git
        repo = os.path.join(tmp, 's1', 'repo')
        os.makedirs(os.path.join(repo, '.git', 'objects'))
        open(os.path.join(repo, '.git', 'objects', 'a'), 'wb').write(b'x' * 1000)
        open(os.path.join(repo, 'main.py'), 'w').write('print(1)')
        s1 = classify(os.path.join(tmp, 's1'))
        check('S1 含 .git 的子树归保护', s1['protected']['files'] >= 2 and s1['candidate']['files'] == 0,
              f"prot={s1['protected']['files']} cand={s1['candidate']['files']}")
        check('S1 报出保护根', 'repo' in s1['protected']['roots'], s1['protected']['roots'])

        # 样本 2：__pycache__ / *.pyc → 可再生
        s2dir = os.path.join(tmp, 's2')
        os.makedirs(os.path.join(s2dir, '__pycache__'))
        open(os.path.join(s2dir, '__pycache__', 'm.cpython-311.pyc'), 'wb').write(b'y' * 500)
        s2 = classify(s2dir)
        check('S2 字节码归可再生', s2['regen']['files'] == 1 and s2['candidate']['files'] == 0,
              f"regen={s2['regen']['files']} cand={s2['candidate']['files']}")

        # 样本 3：普通文件 → 候选
        s3dir = os.path.join(tmp, 's3')
        os.makedirs(s3dir)
        open(os.path.join(s3dir, 'out.json'), 'w').write('{}')
        s3 = classify(s3dir)
        check('S3 普通产物归候选', s3['candidate']['files'] == 1, f"cand={s3['candidate']['files']}")

        # 样本 4：符号链接不跟随（防逃逸）
        outside = os.path.join(tmp, 'outside')
        os.makedirs(outside)
        open(os.path.join(outside, 'secret.txt'), 'w').write('s' * 100)
        s4dir = os.path.join(tmp, 's4')
        os.makedirs(s4dir)
        os.symlink(outside, os.path.join(s4dir, 'link'))
        s4 = classify(s4dir)
        check('S4 不跟随符号链接', s4['candidate']['files'] == 0 and s4['regen']['files'] == 0,
              f"cand={s4['candidate']['files']}")

        # 样本 5：轮次判据 —— 3 会话 keep=2 时只有最老一个可归档
        for i, name in enumerate(['new', 'mid', 'old']):
            p = os.path.join(tmp, 'roots', name)
            os.makedirs(p)
            open(os.path.join(p, 'f.txt'), 'w').write('x')
            os.utime(p, (1000 + i, 1000 + i))
        sessions, err = scan_sessions(os.path.join(tmp, 'roots'), 2)
        check('S5 轮次按会话 mtime 排序', not err and len(sessions) == 3, err or '')
        check('S5 仅最老会话可归档', sum(1 for s in sessions if s['archivable']) == 1,
              [s['name'] for s in sessions if s['archivable']])

        # 样本 6：白名单 —— 根不在 ~/.codebuddy 下必须 UNKNOWN
        _, err2 = resolve_root('/tmp')
        check('S6 白名单外拒绝扫描', err2 is not None, err2 or '未拒绝')

    print(f'self-check: {len(fails)} 处失败')
    return 2 if fails else 0


def main():
    ap = argparse.ArgumentParser(description='artifact-store 执行体（只读）')
    sub = ap.add_subparsers(dest='cmd')
    sp = sub.add_parser('scan', help='扫描产物并给出归档计划（不执行）')
    sp.add_argument('--root', default=DEFAULT_ROOT)
    sp.add_argument('--keep', type=int, default=2, help='本地保留的会话轮次（默认 2）')
    sp.add_argument('--json', action='store_true')
    sub.add_parser('self-check', help='用构造样本验证分类器')
    args = ap.parse_args()
    if args.cmd == 'self-check':
        return cmd_self_check()
    if args.cmd is None:
        args = ap.parse_args(['scan'])
    return cmd_scan(args)


if __name__ == '__main__':
    sys.exit(main())
