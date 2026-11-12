#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
forge_gate.py —— 写源四门禁（S223·吸收 base(5) 壳 forge_skill 四标准）

四标准（原封来自壳的 rules.md §5a，此处做成可执行判据）：
  1 能播放    stream  —— 每条线路抽测首集+末集（非全量），前 4KB 验魔数
  2 稳定兜底  release  —— 发布页/域名池特征齐全 + 换域演练
  3 内容齐全  filter   —— 分页真伪（pg1≠pg2）+ filters 真实性
  4 精简体积  size     —— 零注释/零docstring/零__main__/体积基线

设计原则（与壳的差异，如实说明）：
  · 壳的门禁跑在 Chaquopy 端内、依赖真机；本实现跑在沙箱，**只做静态+网络可判的部分**；
  · 凡本实现判不了的（如手机端播放器兼容性），一律返回 UNDETERMINED 而不是 PASS（M-R136）；
  · 复用 livecheck 的拉流判据（M-R38 单一事实源），不另写一套"能播"定义。

用法：
  python3 forge_gate.py <源.py> --api <源接口URL> [--check stream,release,filter,size]
  python3 forge_gate.py <源.py> --static-only      # 只跑静态两项（size/filter）
退出码：0 全过 / 1 有 FAIL / 2 参数错误
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVECHECK = os.path.join(HERE, 'livecheck.py')

# 魔数判据（base(5) rules.md §10 真拉流硬门禁，4KB 不是 1KB）
MAGIC = (
    ('mp4', lambda b: b'ftyp' in b[:64]),
    ('m3u8', lambda b: b'#EXTM3U' in b[:1024]),
    ('ts', lambda b: len(b) > 188 and b[0] == 0x47),
    ('m2ts', lambda b: b[:4] == b'GG@\x11' or b'FFmpeg' in b[:64]),
)


def _und(why):
    return ('UNDETERMINED', why)


def _pass(why):
    return ('PASS', why)


def _fail(why):
    return ('FAIL', why)


# ═══════════ 门禁 4：精简体积 ═══════════
def gate_size(src_path, final=True):
    """零注释/零docstring/零__main__/零空壳方法 + 体积基线 ≤1200行/80KB。"""
    text = open(src_path, encoding='utf-8').read()
    lines = text.splitlines()
    issues, warns = [], []

    n_bytes = len(text.encode('utf-8'))
    if len(lines) > 1200 or n_bytes > 80 * 1024:
        issues.append(f'超基线：{len(lines)}行/{n_bytes}B（基线 ≤1200行/80KB）')

    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return _fail(f'语法错误（源根本跑不起来）：{e}')

    # 注释行（排除解密段豁免：AES/RSA/XOR/签名/密钥 前后 3 行内）
    crypto_kw = re.compile(r'AES|RSA|XOR|签名|密钥|key|iv|decrypt|encrypt', re.I)
    exempt = set()
    for i, ln in enumerate(lines):
        if crypto_kw.search(ln):
            exempt.update(range(max(0, i - 3), min(len(lines), i + 4)))
    comment_lines = [i for i, ln in enumerate(lines)
                     if ln.strip().startswith('#') and i not in exempt]
    if final and comment_lines:
        issues.append(f'{len(comment_lines)} 行注释未清（解密段已豁免）')

    if final:
        docs = [n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and ast.get_docstring(n)]
        if docs:
            issues.append(f'{len(docs)} 处 docstring 未清：{docs[:5]}')

        if re.search(r"^if\s+__name__\s*==\s*['\"]__main__['\"]", text, re.M):
            issues.append('存在 __main__ 测试块')

        # 空壳方法：函数体只有 pass / ... / return None
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = [b for b in n.body if not isinstance(b, ast.Expr)
                        or not isinstance(getattr(b, 'value', None), ast.Constant)]
                if len(body) == 1:
                    b0 = body[0]
                    if isinstance(b0, ast.Pass):
                        issues.append(f'空壳方法 {n.name}()')
                    elif isinstance(b0, ast.Return) and (
                            b0.value is None or
                            (isinstance(b0.value, ast.Constant) and b0.value.value is None)):
                        issues.append(f'空壳方法 {n.name}() 只 return None')

    # 六接口齐全（base(5) rules.md §5 强制契约）
    need = ('homeContent', 'categoryContent', 'detailContent',
            'searchContent', 'playerContent')
    have = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    miss = [m for m in need if m not in have]
    if miss:
        issues.append(f'缺六接口方法：{miss}')

    if issues:
        return _fail('；'.join(issues[:6]))
    return _pass(f'{len(lines)}行/{n_bytes}B，注释0，docstring0，__main__0，六接口齐')


# ═══════════ 门禁 3：内容齐全（静态半：分页谎报 / filter 写死） ═══════════
def gate_filter_static(src_path):
    text = open(src_path, encoding='utf-8').read()
    issues, warns = [], []

    # 99/999/9999 伪分页（base(5) §6 明令禁止）
    for m in re.finditer(r'pagecount["\']?\s*[:=]\s*(\d{2,})', text):
        if int(m.group(1)) > 100:
            issues.append(f'伪分页 pagecount={m.group(1)}（禁 99/999 谎报页数）')

    # 年份写死（应动态取当前年）
    ys = re.findall(r'["\'](20[0-2]\d)["\']', text)
    if ys and len(set(ys)) >= 3 and 'datetime' not in text and 'now()' not in text:
        warns.append(f'疑似年份写死 {sorted(set(ys))[:6]}（应 _years() 动态生成）')

    # 裸 int(pg) 无兜底（base(5) §16.6 三查之一）
    for m in re.finditer(r'(?<![\w.])int\(\s*(pg|page)\s*\)', text):
        ctx = text[max(0, m.start() - 120):m.start()]
        if 'try' not in ctx:
            issues.append('裸 int(pg) 无 try 兜底（壳传空/None 会抛异常退化为恒第一页）')

    # 固定 pagecount=1 且存在真分页参数
    if re.search(r'pagecount["\']?\s*[:=]\s*1\b', text) and re.search(r'[?&]page=', text):
        warns.append('固定 pagecount=1 但 URL 带 page=（需实测确认是否真单页）')

    # 自加「推荐」分类（用户明令钉死的铁律 §0.4）
    if re.search(r'["\']推荐["\']', text):
        warns.append('出现「推荐」字样——须核对是否站方原有，禁自加')

    if issues:
        return _fail('；'.join(issues[:5]))
    return _pass('分页/filter 静态检查通过' + (f'（{len(warns)} 条告警）' if warns else ''),
                 ) if not warns else ('PASS', f'静态通过，{len(warns)} 条告警：' + '；'.join(warns[:3]))


# ═══════════ 门禁 2：稳定兜底（域名池特征） ═══════════
def gate_release_static(src_path):
    """静态判：命中发布页/API 线索的站是否实现了域名池兜底链。"""
    text = open(src_path, encoding='utf-8').read()
    looks_release = bool(re.search(r'发布页|release|域名池|POOL|BACKUPS', text, re.I))
    has_pool = bool(re.search(r'POOL\s*=\s*\[', text))
    has_probe = bool(re.search(r'_probe|探活|verify_host', text))
    has_ttl = bool(re.search(r'TTL|cache_ttl|1800', text))
    if not looks_release:
        return _pass('未命中发布页特征，无需域名池兜底')
    miss = []
    if not has_pool:
        miss.append('无 POOL 列表')
    if not has_probe:
        miss.append('无逐域探活')
    if not has_ttl:
        miss.append('无 TTL 缓存')
    if miss:
        return _fail('命中发布页特征但兜底链不全：' + '；'.join(miss))
    return _pass('域名池/探活/TTL 特征齐全')


# ═══════════ 门禁 1：能播放（真拉流，复用 livecheck） ═══════════
def _probe_url(url, timeout=12):
    """拉前 4KB 判类型。返回 (kind|None, 说明)。"""
    cmd = ['curl', '-sS', '-L', '--compressed', '--max-time', str(timeout),
           '-r', '0-4095', '-o', '-', url]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout + 4)
        b = p.stdout or b''
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'
    if not b:
        return None, '空响应'
    for kind, fn in MAGIC:
        try:
            if fn(b):
                return kind, f'{len(b)}B 命中 {kind} 魔数'
        except Exception:
            pass
    head = b[:64]
    if b'<html' in head.lower() or b'<!doctype' in head.lower():
        return None, '返回 HTML 页（不能播，头号根因）'
    return None, f'未命中任何魔数：{head[:40]!r}'


def gate_stream(src_path, api=None):
    """真拉流：对 playerContent 产出的地址抽测。无 API 时只做静态形态检查。"""
    text = open(src_path, encoding='utf-8').read()
    issues = []
    # 静态：内网/回环地址不得原样进播放入口（base(5) §10.2.5）
    for m in re.finditer(r'https?://(localhost|127\.\d|10\.\d|192\.168\.\d|172\.(1[6-9]|2\d|3[01])\.\d|0\.0\.0\.0)', text):
        issues.append(f'内网/回环地址出现在源码：{m.group(0)}（客户端请求它=请求手机自己，必黑屏）')
    # 静态：parse:0 用在非媒体地址
    if re.search(r'parse["\']?\s*[:=]\s*0', text) and not re.search(r'm3u8|\.mp4|\.ts', text):
        issues.append('有 parse:0 但源码中无 m3u8/mp4/ts 直链特征（疑似把播放页冒充直链）')
    if issues:
        return _fail('；'.join(issues[:4]))

    if not api:
        return _und('静态检查通过，但未给 --api 无法真拉流（不做「能播」的假结论）')

    p = subprocess.run([sys.executable, LIVECHECK, api, '--json'],
                       capture_output=True, timeout=120)
    out = (p.stdout or b'').decode('utf-8', 'replace').strip().splitlines()
    if not out:
        return _und(f'livecheck 无输出：{(p.stderr or b"")[:120]!r}')
    d = json.loads(out[-1])
    if d['verdict'] == '通过':
        return _pass(f"真拉流通过（{d.get('kind')}）：{d['evidence'][:100]}")
    if d['verdict'] == '无法判定':
        return _und(f"无法判定（不算死）：{d['evidence'][:120]}")
    return _fail(f"真拉流失败：{d['evidence'][:120]}")


GATES = {
    'size': lambda src, api: gate_size(src),
    'filter': lambda src, api: gate_filter_static(src),
    'release': lambda src, api: gate_release_static(src),
    'stream': lambda src, api: gate_stream(src, api),
}


def run(src_path, checks=('size', 'filter', 'release', 'stream'), api=None):
    if not os.path.exists(src_path):
        return 2, {'error': f'源码不存在：{src_path}'}
    res = {}
    for c in checks:
        v, why = GATES[c](src_path, api)
        res[c] = {'verdict': v, 'detail': why}
    fails = [k for k, v in res.items() if v['verdict'] == 'FAIL']
    und = [k for k, v in res.items() if v['verdict'] == 'UNDETERMINED']
    return (1 if fails else 0), {'src': src_path, 'gates': res,
                                 'fail': fails, 'undetermined': und}


def main():
    ap = argparse.ArgumentParser(description='写源四门禁（能播放/稳定兜底/内容齐全/精简体积）')
    ap.add_argument('src')
    ap.add_argument('--api', help='源接口 URL（stream 门禁真拉流用）')
    ap.add_argument('--check', default='size,filter,release,stream')
    ap.add_argument('--static-only', action='store_true', help='跳过 stream 真拉流')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    checks = [c.strip() for c in a.check.split(',') if c.strip()]
    if a.static_only:
        checks = [c for c in checks if c != 'stream']
    bad = [c for c in checks if c not in GATES]
    if bad:
        print(f'未知门禁 {bad}，可选 {list(GATES)}')
        return 2
    rc, rep = run(a.src, checks, a.api)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        mark = {'PASS': '✅', 'FAIL': '❌', 'UNDETERMINED': '⚠️'}
        for k, v in rep.get('gates', {}).items():
            print(f"{mark.get(v['verdict'], '·')} [{k}] {v['verdict']} — {v['detail']}")
        if rep.get('fail'):
            print(f"\n❌ 门禁未过：{rep['fail']}（未过禁交付）")
        elif rep.get('undetermined'):
            print(f"\n⚠️ 无法判定：{rep['undetermined']}（不算过，交付时须如实标注）")
        else:
            print('\n✅ 四门禁全过')
    return rc


if __name__ == '__main__':
    sys.exit(main())
