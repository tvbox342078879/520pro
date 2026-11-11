#!/usr/bin/env python3
"""secret_scan.py — 520pro 明文密钥扫描（落实 core-8 规则 5「零明文凭证」）

用法: python3 secret_scan.py [--profile default|release] [repo_root]
检测: GitHub PAT(ghp_/github_pat_)、user:pass@host、api_key/secret/password/access_key
      赋值、拼接拆解形态（"ghp_" + "AA.."）、.git/config 残留 token。
来源: tvbox-eco/verify/secret_scan.py 迁移改造（去 kill-switch 依赖）。
设计要点:
- 只扫描 **git 视角** 下的文件（已追踪 + 未被 .gitignore 排除的未追踪文件），
  不扫运行时产物 —— 避免误拦业务数据。非 git 环境退化为全盘（跳 .git）。
- 额外强制扫 .git/config：bootstrap 曾踩 token 落 .git/config 的坑（e18514a 修复，
  此处兜底复查），该文件不在 git 视角文件列表里，必须单列。
- 不输出完整明文（仅掩码前后各 2-4 字符）。发现即 exit 2，verify.sh 据此记红。
- 三态纪律：本脚本自身可跑通才产出红/绿结论；异常退出由调用方记「无法判定」。
"""
import os
import re
import subprocess
import sys

PATTERNS = [
    re.compile(r'ghp_[A-Za-z0-9]{20,}'),
    re.compile(r'github_pat_[A-Za-z0-9_]{20,}'),
    re.compile(r'https?://[^/\s:@]+:[^/\s:@]{12,}@'),  # user:pass@host
    re.compile(r'(?i)(?:api[_-]?key|secret|password|access[_-]?key)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}'),
]
# 拼接拆解形态：k = "ghp_" + "AAAABBBB" + ...（连续明文正则漏报，针对性补强）
CONCAT_RE = re.compile(r'(?:ghp_|github_pat_)(?:"\s*\+\s*"[\w]{4,})+')
# .git/config 专用：remote URL 里夹 token（x-access-token:xxx@ / user:token@）
GITCONFIG_RE = re.compile(r'(?:x-access-token|oauth|token)\s*[:=]\s*\S{8,}|https?://[^/\s:@]+:[^/\s@]{8,}@')

# ---- 发布档（--profile release）追加模式 ----
RELEASE_PATTERNS = [
    re.compile(r'sk-[A-Za-z0-9_\-]{20,}'),                                  # OpenAI 风格
    re.compile(r'(?i)\btoken\s*[:=]\s*["\']?[A-Za-z0-9_\-\.]{20,}'),        # token=xxx
    re.compile(r'(?i)\bpass(?:word|wd)\s*[:=]\s*["\']?[A-Za-z0-9_\-\.!@#%^&*]{12,}'),
    re.compile(r'(?i)\b(?:secret|apikey|api_key|access_key|private_key)\s*[:=]\s*["\']?[A-Za-z0-9_\-\.]{16,}'),
]
RELEASE_ALLOW = re.compile(r'(?i)(your[_-]?token|xxx+|placeholder|<[^>]{2,20}>|\*\*\*|REDACTED|CHANGEME)')
SKIP_DIRS = ('.git', 'node_modules', '__pycache__')
SCAN_EXT = ('.py', '.sh', '.json', '.md', '.yml', '.yaml', '.toml', '.env', '.txt', '.cfg', '.ini')


def mask(s):
    return s[:4] + '…' + s[-2:] if len(s) > 8 else s


# ---- 自指豁免（仅构造行/注释行，非整文件）----
SELF_EXEMPT = {'secret_scan.py'}


def is_self_sample_line(rel, line):
    """扫描器自身必然出现 'ghp_' 之类的构造字面量；只放宽构造行/注释行。"""
    if rel not in SELF_EXEMPT:
        return False
    s = line.strip()
    return (s.startswith('#')
            or 're.compile' in line
            or '"ghp_" +' in line
            or '"github_pat_" +' in line)


def candidate_files(root):
    """优先 git 视角(已追踪 + 未忽略未追踪), 退化为全盘(非 git 环境)。

    必须用 `-z` + core.quotePath=false：默认 git ls-files 会给非 ASCII 路径
    加引号转八进制，导致中文名文件全部被静默跳过（tvbox-eco 2026-11-06 实测教训）。
    """
    try:
        files = set()
        base = ['git', '-C', root, '-c', 'core.quotePath=false', 'ls-files', '-z']
        r1 = subprocess.run(base, capture_output=True, text=True, timeout=30)
        r2 = subprocess.run(base + ['--others', '--exclude-standard'],
                            capture_output=True, text=True, timeout=30)
        if r1.returncode == 0:
            for line in r1.stdout.split('\0'):
                if line.strip():
                    files.add(os.path.normpath(os.path.join(root, line)))
        if r2.returncode == 0:
            for line in r2.stdout.split('\0'):
                if line.strip():
                    files.add(os.path.normpath(os.path.join(root, line)))
        if files:
            return files
    except Exception:
        pass
    files = set()
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            files.add(os.path.join(dp, fn))
    return files


def is_placeholder_concat(line):
    """判断拼接构造是否为文档示例。

    注意必须对【整行】做引号分段：CONCAT_RE 从 ghp_ 中段起匹配，会把引号
    序列截歪（"ghp_" 的左引号被吃掉），在匹配片段上分段会漏判真实泄漏
    （2026-11-12 实测：k = "ghp_" + "QWERTYUIOPASDFGH" 被误判为示例）。
    规则：整行所有引号段都 <=8 字符且字符种类 <=2 → 示例，不计泄漏。
    """
    segs = re.findall(r'"([^"]*)"', line)
    if not segs:
        return False
    return all(len(x) <= 8 and len(set(x)) <= 2 for x in segs)


def scan_gitconfig(root, found):
    """兜底复查 .git/config（bootstrap token 落盘坑的防线，单列不在 git 视角内）。"""
    gc = os.path.join(root, '.git', 'config')
    if not os.path.isfile(gc):
        return False
    try:
        lines = open(gc, encoding='utf-8', errors='ignore').read().splitlines()
    except Exception:
        return False
    hit = False
    for ln, line in enumerate(lines, 1):
        if '${' in line:  # ${VAR} 是变量展开模板，非明文（bootstrap 文档化写法）
            continue
        for m in GITCONFIG_RE.finditer(line):
            found.append((f".git/config:{ln}", mask(m.group(0))))
            hit = True
    return hit


def main():
    argv = sys.argv[1:]
    profile = "default"
    if "--profile" in argv:
        i = argv.index("--profile")
        if i + 1 >= len(argv):
            print("用法: secret_scan.py [--profile default|release] [repo_root]", file=sys.stderr)
            sys.exit(2)
        profile = argv[i + 1]
        del argv[i:i + 2]
    if profile not in ("default", "release"):
        print(f"未知 profile: {profile}（可选 default|release）", file=sys.stderr)
        sys.exit(2)
    root = argv[0] if argv else "."

    pats = list(PATTERNS) + (RELEASE_PATTERNS if profile == "release" else [])
    found = []
    exempted = []
    for p in candidate_files(root):
        if not p.endswith(SCAN_EXT):
            continue
        rel = os.path.relpath(p, root).replace('\\', '/')
        try:
            lines = open(p, encoding='utf-8', errors='ignore').read().splitlines()
        except Exception:
            continue
        for ln, line in enumerate(lines, 1):
            if is_self_sample_line(rel, line):
                if any(x in line for x in ('ghp_', 'github_pat_')) and rel not in exempted:
                    exempted.append(rel)
                continue
            for pat in pats:
                for m in pat.findall(line):
                    s = m if isinstance(m, str) else m[0]
                    if '${' in s:  # ${...} 变量展开模板非明文
                        continue
                    if profile == "release" and RELEASE_ALLOW.search(s):
                        continue
                    found.append((f"{rel}:{ln}", mask(s)))
            for cm in CONCAT_RE.finditer(line):
                seg = cm.group(0)
                if is_placeholder_concat(line):
                    continue
                found.append((f"{rel}:{ln}", mask(seg)))
    scan_gitconfig(root, found)
    if exempted:
        print(f"[豁免] 扫描器自身构造行/注释行：{', '.join(sorted(set(exempted)))}")
    if found:
        print(f"✗ 发现 {len(found)} 处疑似明文密钥 [{profile}]")
        for p, s in found[:40]:
            print(f"   {p}  ->  {s}")
        sys.exit(2)
    print(f"✓ 未发现明文密钥 [{profile}]（含 .git/config 复查）")
    sys.exit(0)


if __name__ == "__main__":
    main()
