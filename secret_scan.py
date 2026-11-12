#!/usr/bin/env python3
"""secret_scan.py — 520pro 明文密钥扫描（落实 core-8 规则 5「零明文凭证」）

用法: python3 secret_scan.py [--profile default|release] [--strict] [repo_root]
检测: GitHub PAT(ghp_/github_pat_)、user:pass@host、api_key/secret/password/access_key
      赋值、拼接拆解形态（"ghp_" + "AA.."）、.git/config 残留 token。
      ★ v0.8.14（工程B）补齐行业九类：私钥块/AKIA/ASIA/xox/AIza/sk-（借鉴 Memory Palace
      pre_publish_check 模式表）；新增三级判定——
        FAIL：密钥命中 / .example.json 含真实节点 id（B1/B5）
        WARN：文档个人绝对路径 / 本地 endpoint（B2/B3，--strict 升级为红，B4 分级）
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
    # ★ v0.8.14（工程B·B1）：补齐行业九类密钥形态（借鉴 Memory Palace pre_publish_check 模式表）
    re.compile(r'-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY(?: BLOCK)?-----'),
    re.compile(r'AKIA[0-9A-Z]{16}'),                       # AWS 长期凭证
    re.compile(r'ASIA[0-9A-Z]{16}'),                       # AWS 临时凭证
    re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'),           # Slack
    re.compile(r'AIza[0-9A-Za-z_\-]{35}'),                 # Google API
    re.compile(r'sk-[A-Za-z0-9]{16,}'),                    # OpenAI 风格
]
# ★ 个人绝对路径（B2·WARN 级）：换机断链的根因不是"路径写错"，是"把本机路径当地址"。
#   动态构建（借鉴 MP build_personal_path_scan_regex）：从当前环境取前缀，不写死某台机器。
def _personal_path_re():
    homes = {os.path.expanduser('~'), '/root', '/Users'}
    roots = ['/workspace', '/home'] + sorted(h for h in homes if h)
    alt = '|'.join(re.escape(r) for r in roots if r)
    return re.compile(r'(?:^|[^\w])(' + alt + r')/[^\s"\'`)>]{2,}')
PERSONAL_PATH_RE = _personal_path_re()
# ★ 本地 endpoint/key（B3·WARN 级）：127.0.0.1:端口/私网 IP:端口 出现在文档=发布面泄露
ENDPOINT_RE = re.compile(
    r'(?<![\w.])(?:https?://)?(?:127\.0\.0\.1|localhost|10\.\d{1,3}\.\d{1,3}\.\d{1,3}'
    r'|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})'
    r':\d{2,5}(?:/[^\s"\'`)>]*)?')
# ★ 模板真值（B5·FAIL 级）：.example.json 里不该出现"像真实节点 id"的值
#   （空间节点 id 实测 22 位混合大小写 base62；模板里出现=私产进了分发件）
NODE_ID_RE = re.compile(r'\b(?=[A-Za-z0-9]{22}\b)(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]{22}\b')
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
# inspect_hub.py 的对抗用例里必然含伪造密钥字面量（造脏输入），行级豁免防工具自杀
SELF_EXEMPT = {'secret_scan.py'}


def is_self_sample_line(rel, line):
    """扫描器/对抗用例必然出现 'ghp_' 之类的构造字面量；只放宽构造行/注释行。"""
    base = os.path.basename(rel)
    if base == 'secret_scan.py':
        s = line.strip()
        return (s.startswith('#')
                or 're.compile' in line
                or '"ghp_" +' in line
                or '"github_pat_" +' in line)
    if base == 'inspect_hub.py':
        s = line.strip()
        return s.startswith('#') or '"ghp_" +' in line
    return False


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
    strict = '--strict' in argv
    if strict:
        argv = [x for x in argv if x != '--strict']
        root = argv[0] if argv else "."

    pats = list(PATTERNS) + (RELEASE_PATTERNS if profile == "release" else [])
    found = []
    exempted = []
    warns = []                        # ★ B2/B3：WARN 级（发布面卫生，不阻断）
    for p in candidate_files(root):
        if not p.endswith(SCAN_EXT):
            continue
        rel = os.path.relpath(p, root).replace('\\', '/')
        try:
            lines = open(p, encoding='utf-8', errors='ignore').read().splitlines()
        except Exception:
            continue
        is_md = rel.endswith(('.md', '.txt'))
        is_tpl = rel.endswith('.example.json')
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
            # ★ B5：模板文件里出现真实节点 id 形态 → FAIL（私产随分发件泄露）
            #   只查 .example.json：模板是"给别人用的骨架"，不该带本机真实 id。
            if is_tpl:
                for m in NODE_ID_RE.finditer(line):
                    found.append((f"{rel}:{ln}", f'疑似真实节点id {mask(m.group(0))}'))
            # ★ B2/B3：文档里的个人路径与本地 endpoint → WARN（换机断链/发布面泄露）
            if is_md:
                for m in PERSONAL_PATH_RE.finditer(line):
                    warns.append(('个人绝对路径', f"{rel}:{ln}", m.group(1) + '/…'))
                    break
                for m in ENDPOINT_RE.finditer(line):
                    warns.append(('本地endpoint', f"{rel}:{ln}", m.group(0)[:40]))
                    break
    scan_gitconfig(root, found)
    if exempted:
        print(f"[豁免] 扫描器自身构造行/注释行：{', '.join(sorted(set(exempted)))}")
    if found:
        print(f"✗ 发现 {len(found)} 处疑似明文密钥 [{profile}]")
        for p, s in found[:40]:
            print(f"   {p}  ->  {s}")
        sys.exit(2)
    # ★ B4：WARN/FAIL 分级——文档卫生问题只警告，不阻断；--strict 时升级为红。
    if warns:
        by_kind = {}
        for kind, loc, sample in warns:
            by_kind.setdefault(kind, []).append((loc, sample))
        print(f"[WARN] {len(warns)} 处发布面卫生问题（不阻断；--strict 升级为红）")
        for kind, items in by_kind.items():
            print(f"   · {kind} {len(items)} 处，例：{items[0][0]} -> {items[0][1]}")
        if strict:
            print("✗ --strict：WARN 视同 FAIL")
            sys.exit(2)
    print(f"✓ 未发现明文密钥 [{profile}]（含 .git/config 复查）")
    sys.exit(0)


if __name__ == "__main__":
    main()
