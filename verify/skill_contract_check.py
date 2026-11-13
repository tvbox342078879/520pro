#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_contract_check.py — 技能契约机检（520pro v0.8.15 · 工程C）

【为什么需要它】
520 的技能靠「description 命中触发词 → 平台路由 → 加载 SKILL.md」这条链吃饭。
链上任一环断了（description 没写清该怎么用 / 不该用在哪儿、SKILL.md 缺件、
仓里改了忘同步到安装目录、版本三处各说各话），**表现都是静默的**：
不报错，只是"这个技能最近怎么不好使了"。人眼检查 10 个技能 × 十几项，每次都漏。

本脚本把「技能该长什么样」变成机器判据。判据事实全部来自
`verify/skill_contracts.json`（唯一真源，加技能只加一行）。

【六项检查】
  C1 结构契约    required_files 逐个存在；skill 类必须有 SKILL.md + CHANGELOG.md
  C2 头部契约    front matter 有 name（== 目录名）与 version（semver）；lib 类改验 manifest.json
  C3 描述五组    must_use 触发声明 / capability 能力枚举 / entry 正门锚点 /
                 self_check 自省锚点 / negative_boundary 负边界 —— 缺任一组即 FAIL
  C4 版本四处    contracts.json == SKILL.md（lib: manifest.json）== CHANGELOG 首条 == MANIFEST 登记
  C5 镜像一致    仓内源 ↔ 安装副本逐文件 sha256；运行时态文件豁免
  C6 触发样本    有 → 查 T/N/B 三组齐备且数量达标；无 → WARN（工程D 补齐）
  C7 体积上限    SKILL.md ≤ 40KB（M-R77）；超限记 WARN 不阻断（瘦身排期归 MP-D4）——
                 SKILL.md 每次命中都要整篇进 context，超限不是"文档长"，是"每轮都在付租金" 
  C9 触发前置    description 前 40 字须有「当用户」句式、前 80 字须命中 ≥3 个触发词——
                 平台只把描述编成截断预览给模型；触发词写在尾巴上＝没写（v0.8.31）
  C10 样本词桥   触发样本 T 组每条须能在 description 里找到词桥（非泛用二字词 / 英文词）——
                 找不到说明"样本说会触发、描述里根本没这说法"，路由无依据（v0.8.31）

【状态五档（v0.8.36 起）】
  ✓ 通过 / ✗ 契约失败 / ⚠ 已登记的待办（如样本集待补）/ 
  ◐ PARTIAL 环境欠账（该修：装根在、这个技能漏装）/ 
  · SKIP 结构性不适用（lib 类无 SKILL.md、本机压根不装技能）——永远如此，不该管
  区分 ◐ 与 · 的理由：两者原先都记 '·'，看输出分不清「我该去装一下」和「这本来就不适用」。
  退出码只看 ✗：◐ 与 · 都不阻断，但它们指向的下一步动作完全不同。

用法:
  python3 verify/skill_contract_check.py [--repo <仓库根>] [--install <安装根>] [--require-mirror] [--json]
  --require-mirror  安装副本缺失即记失败（verify.sh / 装后自检用；防「没装」被当成「通过」）
退出码: 0 无 FAIL（WARN/SKIP 不阻断） / 2 有 FAIL / 1 自身异常
"""
import os
import re
import sys
import json
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = os.path.dirname(HERE)
DEFAULT_INSTALL = os.path.join(os.path.expanduser('~'), '.codebuddy', 'skills')

SEMVER = re.compile(r'\bv?(\d+\.\d+\.\d+)\b')
# ★ v0.8.22（工程J·M-R77 借用）：SKILL.md 体积上限。判 WARN 不判 FAIL——
#   体积超标不破坏功能，只是每次加载都吃 context；先让它可见，瘦身按 MP-D4 排期。
#   技能可在 contracts.json 用 skill_size_limit_kb 单独放宽（须写理由，M7）。
SKILL_SIZE_LIMIT_KB = 40
SKIP_DIRS = {'__pycache__', '.git', 'node_modules', '.pytest_cache'}
SKIP_EXT = {'.pyc', '.pyo', '.swp'}

# 颜色只在终端里给：输出被重定向/管道时自动无色，否则调用方 grep 不到判据行（实测假绿过一次）
USE_COLOR = sys.stdout.isatty() and not os.environ.get('NO_COLOR')

results = []   # (check_id, skill, level, msg)   level: ✓ / ✗ / ⚠ / ·
# 五档（v0.8.36）：✓ 通过 / ✗ 契约失败 / ⚠ 已登记的待办 / ◐ PARTIAL（环境欠账，该修）/
# · SKIP（结构性不适用，永远如此，不该管）。原来是四档，'·' 同时承担「没装」和
# 「lib 类不适用」——看输出分不清是欠账还是本就不该管，等于把两类结论折叠成一个数。
counts = {'ok': 0, 'fail': 0, 'warn': 0, 'partial': 0, 'skip': 0}


def rec(cid, skill, level, msg):
    results.append((cid, skill, level, msg))
    counts[{'✓': 'ok', '✗': 'fail', '⚠': 'warn', '◐': 'partial', '·': 'skip'}[level]] += 1
    icon = {'✓': '\033[32m✓\033[0m', '✗': '\033[31m✗\033[0m',
            '⚠': '\033[33m⚠\033[0m', '◐': '\033[36m◐\033[0m',
            '·': '\033[90m·\033[0m'}[level] if USE_COLOR else level
    print(f'  {icon} [{cid}] {skill}: {msg}')


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def read(p):
    return open(p, encoding='utf-8', errors='ignore').read()


def front_matter(text):
    """取 YAML front matter 正文；无则返回 ''。"""
    if not text.startswith('---'):
        return ''
    end = text.find('\n---', 3)
    return text[3:end] if end > 0 else ''


def fm_get(fm, key):
    """从 front matter 取字段，兼容三种写法：`k: "多行"` / `k: >-` 折叠块 / `k: 单行`。"""
    m = re.search(rf'^{key}:[ \t]*(.*)$', fm, re.M)
    if not m:
        return ''
    first = m.group(1).strip()
    if first.startswith('"'):
        # 双引号跨行：从冒号后一直取到下一个 ^key: 或结尾，再剥引号
        tail = fm[m.end():]
        nxt = re.search(r'^\w[\w\-]*:', tail, re.M)
        body = tail[:nxt.start()] if nxt else tail
        return ' '.join((first[1:] + ' ' + body).replace('"', ' ').split())
    if first in ('>-', '>', '|', '|-'):
        tail = fm[m.end():]
        nxt = re.search(r'^\w[\w\-]*:', tail, re.M)
        body = tail[:nxt.start()] if nxt else tail
        return ' '.join(body.split())
    return ' '.join(first.split())


def changelog_version(path):
    """CHANGELOG 首条版本号：兼容 `## v2.6.0` / `## 1.4.0` / `## 2026-10-25 v1.3.7`。"""
    if not os.path.exists(path):
        return None
    for line in read(path).splitlines()[:40]:
        if line.startswith('## '):
            m = SEMVER.search(line)
            return m.group(1) if m else None
    return None


def walk_files(base, skip_names, skip_dirs=()):
    """列相对路径（跳过缓存/临时/运行时态）。

    skip_dirs 来自 contracts.json 的 runtime_dirs（不硬编码在脚本里，保持单一真源）：
    运行时目录随使用增长，源仓与装副本必然不同，参与比对只会产生假阳。
    """
    out = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and d not in skip_dirs]
        for f in files:
            if os.path.splitext(f)[1] in SKIP_EXT or f in skip_names or '.bak' in f:
                continue
            out.append(os.path.relpath(os.path.join(root, f), base))
    return sorted(out)


# ────────────────────────── C1 结构契约 ──────────────────────────
def check_structure(name, spec, base):
    missing = [f for f in spec.get('required_files', []) if not os.path.exists(os.path.join(base, f))]
    if missing:
        rec('C1', name, '✗', f'缺件 {missing}（登记于 contracts.json.required_files）')
    else:
        rec('C1', name, '✓', f'结构齐备（{len(spec["required_files"])} 件）')


# ────────────────────────── C2 头部契约 ──────────────────────────
def check_meta(name, spec, base):
    if spec['kind'] == 'lib':
        mp = os.path.join(base, 'manifest.json')
        if not os.path.exists(mp):
            rec('C2', name, '✗', 'lib 缺 manifest.json（版本真源无处可取）')
            return
        v = (json.load(open(mp, encoding='utf-8')).get('version') or '').strip()
        rec('C2', name, '✓' if SEMVER.fullmatch(v) else '✗',
            f'lib manifest.json version={v or "空"}')
        return
    sk = os.path.join(base, 'SKILL.md')
    if not os.path.exists(sk):
        rec('C2', name, '✗', '缺 SKILL.md（平台不注册路由，等于技能不存在）')
        return
    fm = front_matter(read(sk))
    nm, ver = fm_get(fm, 'name'), fm_get(fm, 'version')
    bad = []
    if nm != name:
        bad.append(f'name={nm or "空"}≠目录名 {name}')
    if not SEMVER.fullmatch(ver):
        bad.append(f'version={ver or "缺"}（非 semver，三件套无法对账）')
    desc = fm_get(fm, 'description')
    if len(desc) < 40:
        bad.append(f'description 仅 {len(desc)} 字（太短，平台无法判断何时用）')
    rec('C2', name, '✗' if bad else '✓', '；'.join(bad) if bad else f'front matter 正常（v{ver}，desc {len(desc)} 字）')


# ────────────────────────── C3 描述五组 ──────────────────────────
DESC_RULES = [
    ('D1 must_use', r'当用户|触发词|适用于', '没写"什么时候该用我"，平台路由无依据'),
    ('D2 capability', r'①|能力：|能力:', '没枚举能力清单，用户看不出能干啥'),
    ('D5 negative_boundary', r'不要用于|不适用于|【边界】|边界：|别用于', '没写负边界（不要用于…），误触发无人拦'),
]
SELF_CHECK = r'不许看见脚本|先读|判据|先加载|先查|先跑'


def check_desc(name, spec, base, desc, body):
    bad = []
    for tag, pat, why in DESC_RULES:
        if not re.search(pat, desc):
            bad.append(f'{tag} 缺（{why}）')
    # D3 entry 正门锚点：登记了正门就必须真存在，且 description 得让人知道从哪儿进
    entry = spec.get('entry', '')
    if entry:
        if not os.path.exists(os.path.join(base, entry)):
            bad.append(f'D3 entry 登记 {entry} 但文件不存在')
        else:
            stem = os.path.basename(entry)
            if not (stem in desc or '正门' in desc or '入口' in desc or entry in desc):
                bad.append(f'D3 正门锚点缺（desc 未提 {stem} / 正门 / 入口）')
    # D4 self_check 自省锚点：正文须有"先读/不许直接跑"这类自省话
    if not re.search(SELF_CHECK, body):
        bad.append('D4 自省锚点缺（正文无"先读/不许直接跑/判据"类约束）')
    rec('C3', name, '✗' if bad else '✓', '；'.join(bad) if bad else 'D1-D5 五组齐备')


# ────────────────────────── C4 版本三处 ──────────────────────────
def manifest_version(repo, name, layer):
    """MANIFEST 里该技能的登记版本（四处对账的第四处）。lite 形状无 MANIFEST 时返回 None。"""
    mp = os.path.join(repo, 'MANIFEST.json')
    if not os.path.exists(mp):
        return None
    try:
        m = json.load(open(mp, encoding='utf-8'))
    except Exception:
        return 'BAD_JSON'
    cands = [f'skills/{name}/SKILL.md', f'skills/{name}/', f'tvbox/skills/{name}/', f'tvbox/skills/{name}/SKILL.md']
    for ln, ld in (m.get('layers') or {}).items():
        for k, v in ((ld.get('files') or {}).items()):
            if k in cands and ln == layer:
                return (v.get('version') or '').strip() or None
    return None


def check_version(name, spec, base, repo):
    if spec['kind'] == 'lib':
        mp = os.path.join(base, 'manifest.json')
        sk_ver = json.load(open(mp, encoding='utf-8')).get('version', '') if os.path.exists(mp) else ''
    else:
        sk_ver = fm_get(front_matter(read(os.path.join(base, 'SKILL.md'))), 'version')
    cl_ver = changelog_version(os.path.join(base, 'CHANGELOG.md'))
    reg_ver = spec.get('version', '')
    mans = manifest_version(repo, name, spec['layer'])
    trio = {'contracts.json': reg_ver, 'SKILL/manifest': sk_ver, 'CHANGELOG': cl_ver,
            'MANIFEST': mans if mans is not None else '（未登记）'}
    if mans == 'BAD_JSON':
        rec('C4', name, '✗', 'MANIFEST.json 解析失败——版本无从对账（禁止当"未登记"放过）')
        return
    vals = set(v for k, v in trio.items() if v and k != 'MANIFEST')
    if cl_ver is None:
        rec('C4', name, '⚠', f'CHANGELOG 首条无版本号（{trio}）——无法对账，建议首条写 `## vX.Y.Z`')
    elif len(vals) > 1:
        rec('C4', name, '✗', f'版本不一致：{trio}')
    elif mans not in (None, reg_ver):
        rec('C4', name, '✗', f'MANIFEST 登记 v{mans} ≠ 实际 v{reg_ver}（分发元数据过期）')
    elif mans is None:
        rec('C4', name, '⚠', f'版本三处一致 v{reg_ver}，但 MANIFEST 未登记（lite 形状可忽略）')
    else:
        rec('C4', name, '✓', f'四处一致 v{reg_ver}（contracts/SKILL/CHANGELOG/MANIFEST）')


# ────────────────────────── C5 镜像一致 ──────────────────────────
def check_mirror(name, spec, base, install_root, runtime, required=False, skip_dirs=()):
    dst = os.path.join(install_root, name)
    if not os.path.isdir(dst):
        if required:
            # 变异测试实证：整块 SKIP 时若仍 exit 0，在未安装的机器上就是假绿。
            rec('C5', name, '✗', f'安装副本不存在（{dst}）——--require-mirror 下记失败（未装或装错位置）')
        elif os.path.isdir(install_root):
            # 装根在、这个技能不在 = 漏装了一件。这是「该修」，不是「不该管」。
            rec('C5', name, '◐', f'安装副本缺失（{dst}）——装根存在但本技能未装，属漏装')
        else:
            # 装根整体不存在 = 这台机器压根不装技能（CI / 换机检出 / --repo-only）。
            rec('C5', name, '·', f'安装根不存在（{install_root}）——本机不装技能，不适用')
        return
    src_files = walk_files(base, runtime, skip_dirs)
    dst_files = walk_files(dst, runtime, skip_dirs)
    diffs, missing, extra = [], [], []
    for rel in src_files:
        dp = os.path.join(dst, rel)
        if not os.path.exists(dp):
            missing.append(rel)
        elif sha256(os.path.join(base, rel)) != sha256(dp):
            diffs.append(rel)
    for rel in dst_files:
        if rel not in src_files:
            extra.append(rel)
    bad = []
    if diffs:
        bad.append(f'{len(diffs)} 件内容不同（改仓后未重装？）{diffs[:3]}')
    if missing:
        bad.append(f'{len(missing)} 件装副本缺失 {missing[:3]}')
    if extra:
        bad.append(f'{len(extra)} 件装副本多余（残留/私产）{extra[:3]}')
    rec('C5', name, '✗' if bad else '✓',
        '；'.join(bad) if bad else f'镜像一致（{len(src_files)} 件逐 sha 相同）')


# ────────────────────────── C6 触发样本 ──────────────────────────
SAMPLE_MIN = {'T': 8, 'N': 6, 'B': 3}


def check_samples(name, spec, base):
    rel = spec.get('trigger_samples', '')
    if not rel:
        rec('C6', name, '·', '未登记触发样本（lib 类不适用）')
        return
    p = os.path.join(base, rel)
    if not os.path.exists(p):
        rec('C6', name, '⚠', f'无触发样本 {rel}（工程D 补齐；反例无人管"不该触发乱触发"）')
        return
    txt = read(p)
    got = {}
    for g in ('T', 'N', 'B'):
        # 认 `## T 组` / `### T1` / `T1.` / `- [T1]` 等写法
        got[g] = len(re.findall(rf'(?m)^[#\-\*\s]*(?:\[|\()?{g}\d', txt))
    short = [f'{g}{got[g]}/{SAMPLE_MIN[g]}' for g in ('T', 'N', 'B') if got[g] < SAMPLE_MIN[g]]
    if short:
        rec('C6', name, '✗', f'样本分组不足 {" ".join(short)}（阈值 T≥8 N≥6 B≥3）')
        return
    # ★ 只数条数是不够的：T 组样本若只写 prompt 不写「预期第一动作」，
    #   就只能证明"该触发"，证明不了"触发后做对"——那正是这类样本集的核心价值。
    #   N 组同理，必须写「应归谁」，否则"不该触发"没有落点。
    blocks = re.split(r'(?m)^#{2,4}\s*(T\d+|N\d+)', txt)
    miss_t, miss_n = [], []
    for i in range(1, len(blocks) - 1, 2):
        sid, body = blocks[i], blocks[i + 1]
        if sid.startswith('T') and '预期第一动作' not in body:
            miss_t.append(sid)
        if sid.startswith('N') and '应归谁' not in body:
            miss_n.append(sid)
    if miss_t or miss_n:
        detail = []
        if miss_t:
            detail.append(f'T 组缺「预期第一动作」：{", ".join(miss_t)}')
        if miss_n:
            detail.append(f'N 组缺「应归谁」：{", ".join(miss_n)}')
        rec('C6', name, '✗', '；'.join(detail) + '（只写 prompt 的样本证明不了触发后做对）')
        return
    rec('C6', name, '✓', f'样本齐备 T{got["T"]}/N{got["N"]}/B{got["B"]}（T 均带第一动作、N 均带归属）')


def check_size(name, spec, base):
    """C7（工程J）：SKILL.md 体积——超 40KB 记 WARN。

    为什么计量而不是看感觉：SKILL.md 是"每次命中都整篇注入"的文件，
    体积直接等于每轮 context 租金。probe-hub 52KB 这种量级，人眼只觉得"文档挺全"，
    装到手机上就是每轮多烧一万多 token——必须有数、有阈值。
    """
    p = os.path.join(base, 'SKILL.md')
    if not os.path.exists(p):
        return
    kb = os.path.getsize(p) / 1024.0
    lim = int(spec.get('skill_size_limit_kb', SKILL_SIZE_LIMIT_KB))
    if kb > lim:
        rec('C7', name, '⚠', f'SKILL.md {kb:.1f}KB > 上限 {lim}KB'
                          f'（M-R77：每次加载都是常驻 context 成本；瘦身见 MP-D4）')
    else:
        rec('C7', name, '✓', f'SKILL.md {kb:.1f}KB ≤ {lim}KB')


# ───────────────── C9/C10 触发可命中性（v0.8.31·借 Memory Palace）─────────────────
# 为什么要有这两条：C1–C7 只证明「技能长得对」，证明不了「用户说人话时它会被想起来」。
# 平台把 name+description 编成技能清单给模型看，描述被截成前段预览（实测约 120–250 字，
# 长度随条目浮动）→ 触发词写在尾巴上等于没写；样本里的话在描述里找不到词，也等于路由无依据。
# 判据只做两件事：触发语义必须在最前；每条该触发的样本必须能在描述里找到词桥。
FRONT_WINDOW = 40          # 前 40 字内必须出现「当用户」
FRONT_HITS = 3             # 前 80 字内至少命中 3 个触发词
BRIDGE_WINDOW = 80
GENERIC_BG = {
    '用户', '时间', '文件', '数据', '问题', '已经', '还是', '就是', '现在', '可以',
    '我们', '你们', '他们', '这个', '那个', '一下', '帮我', '什么', '怎么',
}
STOP_ASCII = {'the', 'and', 'for', 'with', 'json'}


def desc_tokens(desc):
    """触发词 = 「」引号词 ∪ 触发词清单（两种写法都认）。"""
    toks = set(re.findall(r'「(.+?)」', desc))
    m = re.search(r'触发词[:：](.*?)(?:不要用于|不适用于|【边界】|$)', desc)
    if m:
        toks |= {x.strip() for x in re.split(r'[／/、，,]', m.group(1)) if len(x.strip()) >= 2}
    return {t for t in toks if len(t) >= 2}


def check_frontload(desc):
    """C9：触发语义前置。返回 (ok, msg)。"""
    if not desc:
        return False, 'description 为空'
    if not re.search(r'当用户', desc[:FRONT_WINDOW]):
        pos = desc.find('当用户')
        return False, (f'前 {FRONT_WINDOW} 字内无「当用户」句式'
                       f'（当前在第 {pos} 位）——描述被截断后触发语义丢失')
    # 只看「触发词：」清单之前的前段——清单本身也算前 80 字时会把判据测成假绿
    head = desc[:BRIDGE_WINDOW]
    cut = head.find('触发词')
    if cut > 0:
        head = head[:cut]
    hit = [t for t in desc_tokens(desc) if t in head]
    if len(hit) < FRONT_HITS:
        return False, f'前 {BRIDGE_WINDOW} 字仅命中 {len(hit)} 个触发词（需 ≥{FRONT_HITS}）：{hit}'
    return True, f'触发前置 ✓（前 {BRIDGE_WINDOW} 字命中 {len(hit)}：{" / ".join(hit[:4])}…）'


def parse_t_prompts(text):
    """取触发样本 T 组的 (编号, prompt)。"""
    out, cur = [], None
    for ln in text.splitlines():
        m = re.match(r'###\s+(T\d+)', ln)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r'\s*-\s*Prompt[：:]\s*`?(.+?)`?\s*$', ln)
        if m and cur:
            out.append((cur, m.group(1).strip('`')))
            cur = None
    return out


def check_bridge(desc, sample_text):
    """C10：样本 ↔ description 词桥。返回 (ok, uncovered[(id,prompt)])。"""
    uncovered = []
    low = desc.lower()
    for pid, pr in parse_t_prompts(sample_text):
        bgs = {pr[i:i + 2] for i in range(max(len(pr) - 1, 0))}
        bgs = {b for b in bgs
               if re.fullmatch(r'[\u4e00-\u9fa5]{2}', b) and b not in GENERIC_BG}
        ok = any(b in desc for b in bgs)
        if not ok:
            en = [w for w in re.findall(r'[A-Za-z0-9_%.]{2,}', pr)
                  if w.lower() not in STOP_ASCII]
            ok = any(w.lower() in low for w in en)
        if not ok:
            uncovered.append((pid, pr))
    return (not uncovered), uncovered


def check_frontload_rec(name, desc):
    ok, msg = check_frontload(desc)
    rec('C9', name, '✓' if ok else '✗', msg)


def check_bridge_rec(name, spec, base, desc):
    rel = spec.get('trigger_samples')
    if not rel:
        rec('C10', name, '·', '无触发样本——词桥无从对，不折算通过')
        return
    p = os.path.join(base, rel)
    if not os.path.exists(p):
        rec('C10', name, '✗', f'登记了样本 {rel} 但文件不存在')
        return
    ok, unc = check_bridge(desc, read(p))
    if ok:
        rec('C10', name, '✓', '样本全部能在描述里找到词桥（说人话也能路由到）')
    else:
        detail = '；'.join(f'{i}:{p[:18]}' for i, p in unc[:3])
        rec('C10', name, '✗',
            f'{len(unc)} 条样本在 description 里找不到任何词桥（{detail}）'
            f'——要么把这些说法写进描述，要么改样本')


# ────────────────────────── 主流程 ──────────────────────────
def main(argv):
    repo, install, as_json, require_mirror = DEFAULT_REPO, DEFAULT_INSTALL, False, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--repo':
            repo = argv[i + 1]; i += 2
        elif a == '--install':
            install = argv[i + 1]; i += 2
        elif a == '--json':
            as_json = True; i += 1
        elif a == '--require-mirror':
            require_mirror = True; i += 1
        elif a in ('-h', '--help'):
            print(__doc__); return 0
        else:
            print(f'未知参数: {a}'); return 1

    cpath = os.path.join(repo, 'verify', 'skill_contracts.json')
    if not os.path.exists(cpath):
        print(f'✗ 缺契约登记表 {cpath}')
        return 1
    try:
        reg = json.load(open(cpath, encoding='utf-8'))
    except Exception as e:
        print(f'✗ 契约登记表解析失败（{type(e).__name__}）——禁止当"无技能需检查"处理')
        return 1

    runtime = set(reg.get('runtime_files', []))
    skills = reg.get('skills', {})
    print(f'【技能契约机检】repo={repo}')
    print(f'  登记 {len(skills)} 个技能 · 安装根 {install}')
    print()

    for name, spec in skills.items():
        base = os.path.join(repo, spec['path'])
        if not os.path.isdir(base):
            rec('C1', name, '✗', f'技能目录不存在：{spec["path"]}')
            continue
        check_structure(name, spec, base)
        check_meta(name, spec, base)
        if spec['kind'] == 'skill':
            sk = os.path.join(base, 'SKILL.md')
            body = read(sk) if os.path.exists(sk) else ''
            desc = fm_get(front_matter(body), 'description')
            check_desc(name, spec, base, desc, body)
            check_size(name, spec, base)
            check_frontload_rec(name, desc)
            check_bridge_rec(name, spec, base, desc)
        else:
            rec('C3', name, '·', 'lib 类：不注册路由，desc 五组契约不适用')
        check_version(name, spec, base, repo)
        check_mirror(name, spec, base, install, runtime, require_mirror,
                     tuple(reg.get('runtime_dirs') or ()))
        check_samples(name, spec, base)
        print()

    print('─' * 60)
    print(f'结果：{counts["ok"]} ✓ ｜ {counts["fail"]} ✗ ｜ {counts["warn"]} ⚠ ｜ '
          f'{counts["partial"]} ◐（环境欠账）｜ {counts["skip"]} ·（不适用）')
    if counts['partial']:
        print(f'◐ {counts["partial"]} 项环境欠账（该修：漏装副本等），不计入通过也不算仓库坏')
    if counts['skip']:
        print(f'· {counts["skip"]} 项结构性不适用（lib 类无 SKILL.md / 本机不装技能）——永远如此，不该管')
    if counts['fail']:
        print('✗ 存在契约失败项（见上）；修完重跑，全绿才算完成')
    elif counts['warn']:
        print('⚠ 无失败项，但有 WARN（不阻断）：样本集待工程D 补齐 / 版本号待规范')
    else:
        print('✓ 全部契约通过')
    if as_json:
        print(json.dumps({'counts': counts,
                          'items': [{'check': c, 'skill': s, 'level': l, 'msg': m} for c, s, l, m in results]},
                         ensure_ascii=False))
    return 2 if counts['fail'] else 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        print(f'✗ 检查器自身异常：{type(e).__name__}: {e}')
        sys.exit(1)
