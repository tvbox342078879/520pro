# -*- coding: utf-8 -*-
"""hls_clean.py —— m3u8 广告分片净化（S225）。

## 为什么单独成一个模块，而不是塞进 quality.py 的规则表

生态原来的形态是「一堆域名正则 → 命中就删」。这条路经实测与业内做法都不成立：

1. **删分片是有协议的**。RFC 8216 §6.2.2 对直播清单下硬约束：
   - 清单 MUST 含 `EXT-X-MEDIA-SEQUENCE`；每删掉前面的分片，该值**必须 +1**，
     **不得减小、不得回绕**（`urn:ietf:params:hls:media-sequence-wraps` 有定义）。
   - 删完后清单剩余时长 **不得少于 3 倍 target duration**，否则播放器会直接判清单失效。
   - 删掉一个 `EXT-X-DISCONTINUITY` 标签，`EXT-X-DISCONTINUITY-SEQUENCE` **必须 +1**。
   天真的字符串替换三条全会破坏，症状是「去完广告整个源播不了」——
   比有广告更糟，且极难归因（用户只看到黑屏）。

2. **命中判定必须分级**。业内（uBlock / AdGuard 一类）的形态是
   Allow（明确放行）→ Block（明确拦截）→ 启发式（谨慎兜底），
   而不是单层黑名单。单层黑名单的通病是「误杀率随规则增长而失控」。

3. **指纹不能只用文件名**。同一 CDN 域名下正片与广告共存是常态，
   只看 `xxx.ts` 文件名会把正片一起删。必须用 `hostname + pathname` 全指纹。

## 本模块的落点

- `judge_segment()`：三段判定 → `('allow'|'block'|'unknown', 证据)`
- `sanitize()`：按 RFC 约束真正改写清单，产出 `SanitizeResult`
- 数据来自 `references/S225_ad_domains.json`（61 条）与本文 `RULES`（15 条原始规则）
- **未过校验不删**：任何会破坏 RFC 约束的删除，一律拒绝并如实返回 `blocked_by`

## 三态纪律（M-R60）

`skipped != dead`。`SanitizeResult.status` 的 `unsafe_skip` 表示
「想删但不敢删」，不是「没有广告」，更不是「源坏了」。
"""
import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin

HERE = os.path.dirname(os.path.abspath(__file__))
ADS_JSON = os.path.join(HERE, '..', 'references', 'S225_ad_domains.json')

# ═══════════════════════════════════════════════════════
# 一、规则库：base(5) EXTRA.rules 15 条原样搬入（未改写未增补）
# ═══════════════════════════════════════════════════════
# 每条规则的 `hosts` 是**域名/路径特征**（子串匹配，不是精确域名），
# `regex` 是在清单文本上做的匹配特征。原壳的做法是「命中即删」，
# 本模块保留特征但把「删」改成「判」——是否真删由 `sanitize()` 的三段式决定。
RULES = [
    {'name': 'proxy', 'hosts': ['stream-link.org']},
    {'name': '量子广告', 'hosts': ['vip.lz', 'hd.lz', '.cdnlz'], 'regex': [
        r'#EXT-X-DISCONTINUITY\r*\n*#EXTINF:6\.666667,[\s\S]*?#EXT-X-DISCONTINUITY',
        r'#EXTINF.*?\s+.*?1o.*?\.ts\s+']},
    {'name': '非凡广告', 'hosts': ['vip.ffzy', 'hd.ffzy'], 'regex': [
        '20.52',
        r'#EXT-X-DISCONTINUITY\r*\n*#EXTINF:7\.400000,[\s\S]*?#EXT-X-DISCONTINUITY',
        r'#EXTINF.*?\s+.*?1170(20|32).*?\.ts\s+',
        r'#EXTINF.*?\s+.*?116977.*?\.ts\s+']},
    {'name': '索尼广告', 'hosts': ['suonizy'], 'regex': [
        r'#EXT-X-DISCONTINUITY\r*\n*#EXTINF:1\.000000,[\s\S]*?#EXT-X-DISCONTINUITY',
        r'#EXTINF.*?\s+.*?p1ayer.*?\.ts\s+',
        r'#EXTINF.*?\s+.*?\/video\/original.*?\.ts\s+']},
    {'name': '暴风广告', 'hosts': ['bfzy', 'bfbfvip'], 'regex': [
        r'#EXTINF.*?\s+.*?adjump.*?\.ts\s+']},
    {'name': '星星广告', 'hosts': ['aws.ulivetv.net'], 'regex': [
        r'#EXT-X-DISCONTINUITY\r*\n*#EXTINF:8,[\s\S]*?#EXT-X-DISCONTINUITY']},
    {'name': '快看广告', 'hosts': ['kuaikan'], 'regex': [
        r'#EXT-X-KEY:METHOD=NONE\r*\n*#EXTINF:5,[\s\S]*?#EXT-X-DISCONTINUITY',
        r'#EXT-X-KEY:METHOD=NONE\r*\n*#EXTINF:2\.4,[\s\S]*?#EXT-X-DISCONTINUITY']},
    {'name': '夜市', 'hosts': ['yeslivetv.com'], 'script': [
        "document.getElementsByClassName('vjs-big-play-button')[0].click()"]},
    {'name': '毛驢', 'hosts': ['www.maolvys.com'], 'script': [
        "document.getElementsByClassName('swal-button swal-button--confirm')[0].click()"]},
    {'name': '磁力广告', 'hosts': ['magnet'], 'regex': [
        '更多', '请访问', 'example', '社 區', 'x u u', '直 播', '更 新', '社 区',
        '有趣', '有 趣', '英皇体育', '全中文AV在线', '澳门皇冠赌场', '哥哥快来',
        '美女荷官', '裸聊', '新片首发', 'UUE29']},
    {'name': '一起看广告', 'hosts': ['yqk88'], 'regex': [
        '18.4', '15.1666', '16.5333',
        r'#EXT-X-DISCONTINUITY\r*\n*[\s\S]*?#EXT-X-CUE-IN']},
    {'name': '火山嗅探', 'hosts': ['huoshan.com'], 'regex': ['item_id=']},
    {'name': '抖音嗅探', 'hosts': ['douyin.com'], 'regex': ['is_play_url=']},
    {'name': 'proxy', 'hosts': [
        'raw.githubusercontent.com', 'googlevideo.com', 'cdn.v82u1l.com',
        'cdn.iz8qkg.com', 'cdn.kin6c1.com', 'c.biggggg.com', 'c.olddddd.com',
        'haiwaikan.com', 'www.histar.tv', 'youtube.com', 'uhibo.com',
        '.*boku.*', '.*nivod.*', '*.t4tv.hz.cz', '.*ulivetv.*']},
    {'name': '农民嗅探', 'hosts': ['toutiaovod.com'], 'regex': ['video/tos/cn']},
]

# **明确放行**：这些域名是合法 CDN / 公共基础库，命中即 allow，不再走启发式。
# 为什么需要 Allow 层：`cdn.bootcss.com`、`raw.githubusercontent.com` 出现在
# 广告清单里是因为「站点引了它们的统计/推广位」，但这两个域本身承载大量正片与
# 公共 JS。直接按黑名单拦会把正片一起干掉。uBlock 的做法也是先划 Allow。
ALLOW_HOSTS = (
    'cdn.jsdelivr.net', 'unpkg.com', 'cdnjs.cloudflare.com',
    'raw.githubusercontent.com', 'gitee.com', 'cdn.bootcdn.net',
)


def load_ads():
    """读广告域名黑名单 → (hosts 集合, 说明)。文件缺失返回空集，不编造。"""
    try:
        with open(ADS_JSON, encoding='utf-8') as f:
            d = json.load(f)
        raw = d.get('hosts') or []
    except Exception as e:
        return set(), f'黑名单文件读取失败：{e}'
    out = set()
    for h in raw:
        h = (h or '').strip().lower()
        if not h:
            continue
        if '://' in h:
            h = urlparse(h).netloc or h.split('://', 1)[1].split('/')[0]
        else:
            h = h.split('/')[0]
        if h:
            out.add(h)
    return out, f'载入 {len(out)} 个广告域名（原始 {len(raw)} 条，已去重/去协议）'


ADS, ADS_NOTE = load_ads()


# ═══════════════════════════════════════════════════════
# 二、清单解析：只认我们真正需要的结构，不引 m3u8 第三方库
# ═══════════════════════════════════════════════════════
@dataclass
class Segment:
    """一个分片（含它前面那段 #EXTINF / #EXT-X-KEY 等标签）。"""
    uri: str = ''
    duration: float = 0.0
    tags: list = field(default_factory=list)      # 紧邻该分片的标签行（#EXTINF 之后）
    pre_tags: list = field(default_factory=list)  # #EXTINF 之前的标签（KEY/DISCONTINUITY…）
    raw: str = ''                                 # 原始整块文本，回写用

    @property
    def abs_url(self):
        return self.uri


def _hdr_value(text, name):
    m = re.search(r'^#%s:(.*)$' % re.escape(name), text, re.M)
    return m.group(1).strip() if m else None


def _dur(tag):
    m = re.search(r'#EXTINF:\s*([0-9.]+)', tag)
    try:
        return float(m.group(1)) if m else 0.0
    except ValueError:
        return 0.0


def parse_playlist(text):
    """→ (header_lines, segments, footer_lines, info)。

    只处理主清单（媒体清单）。多码率主清单（含 #EXT-X-STREAM-INF）原样返回，
    `info['master']=True`，调用方不得净化——删子清单行没有意义且会破坏 ABR。
    """
    lines = (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    info = {
        'master': any('#EXT-X-STREAM-INF' in ln for ln in lines),
        'target_duration': None,
        'media_sequence': None,
        'discontinuity_sequence': None,
        'endlist': False,
    }
    td = _hdr_value(text, 'EXT-X-TARGETDURATION')
    ms = _hdr_value(text, 'EXT-X-MEDIA-SEQUENCE')
    ds = _hdr_value(text, 'EXT-X-DISCONTINUITY-SEQUENCE')
    info['target_duration'] = float(td) if td and re.match(r'^[0-9.]+$', td) else None
    info['media_sequence'] = int(ms) if ms and ms.isdigit() else None
    info['discontinuity_sequence'] = int(ds) if ds and ds.isdigit() else None
    info['endlist'] = '#EXT-X-ENDLIST' in text

    header, segs, footer = [], [], []
    pending = []          # 已读到的标签，等下一个 URI
    cur_inf = ''          # 当前 #EXTINF 行
    buf = []              # 当前分片整块文本
    in_seg = False        # 是否已进入分片区（出现第一个 #EXTINF 之后）

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith('#'):
            if s.startswith('#EXT-X-ENDLIST'):
                footer.append(ln)
                continue
            # ★ 关键：头部与分片区的分界就是第一条 #EXTINF。
            #   第一版写成「有 cur_inf 才进 buf，否则进 header」，结果 #EXTINF 之前
            #   的 #EXT-X-DISCONTINUITY / #EXT-X-KEY 全被塞进 header，
            #   回写时它们会跑到清单最前面 —— 已用「头部只收 in_seg 之前的标签」修正。
            if s.startswith('#EXTINF'):
                in_seg = True
                cur_inf = ln
                buf.append(ln)
                continue
            if in_seg:
                pending.append(ln)
                buf.append(ln)
            else:
                header.append(ln)
            continue
        # URI 行
        duration = _dur(cur_inf)
        seg = Segment(uri=s, duration=duration, pre_tags=list(pending),
                      raw='\n'.join(buf + [ln]))
        segs.append(seg)
        pending, cur_inf, buf = [], '', []
    return header, segs, footer, info


# ═══════════════════════════════════════════════════════
# 三、判定：Allow → Block → 启发式（三段式，缺一层就会失控）
# ═══════════════════════════════════════════════════════
def _fp(url):
    """全指纹：hostname + pathname。只用文件名会把正片误杀（同域名下共存是常态）。"""
    try:
        u = urlparse(url)
        return (u.hostname or '').lower(), (u.path or '')
    except Exception:
        return '', ''


def _name_hits(host, rule):
    for h in rule.get('hosts') or []:
        h = h.lower().lstrip('*.')
        if h.startswith('.*') or h.endswith('.*'):
            h = h.strip('.*')
        if h and h in host:
            return h
    return ''


def judge_segment(seg_url, *, seg_index, total, baseline_hosts, base_url=''):
    """单分片判定 → (verdict, why)。verdict ∈ allow / block / unknown。

    `baseline_hosts` 是本清单里**出现次数最多**的域名集合——正片所在 CDN。
    这是「无规则时的兜底」：不在任何规则里、但域名和主 CDN 不同的分片，
    判 unknown 而不是 block（三态：判不了就是判不了，不许猜成广告）。
    """
    if not seg_url:
        return 'unknown', '空 URI'
    if '://' not in seg_url:
        seg_url = urljoin(base_url or '', seg_url)
    host, path = _fp(seg_url)

    # ① Allow：先放行，再谈拦截
    for a in ALLOW_HOSTS:
        if host == a or host.endswith('.' + a):
            return 'allow', f'Allow 层：{a} 是公共 CDN'

    # ② Block：域名黑名单（61 条，命中即拦）
    if host in ADS:
        return 'block', f'命中广告域名黑名单：{host}'

    # ③ Block：规则库域名特征
    for rule in RULES:
        h = _name_hits(host, rule)
        if h:
            return 'block', f'命中规则「{rule["name"]}」域名特征：{h}'

    # ④ 启发式：非常规路径词（ad/jump/promo），且必须**同一清单里确实存在别的域名**
    #    单域名清单里出现 /ad/ 多半是站点自己的路径，不要动
    low_path = path.lower()
    # ★ 必须同时覆盖两种位置，`/ad/` 只写一种是不够的：
    #   ① 广告词当目录名：`/ad/x.ts`、`/adjump/1.ts`
    #   ② 广告词当文件名：`/xx/promo.ts`、`/promo.ts`
    #   只写 `/(?:ad)/` 时 ② 会整类漏判（实测就是这一步挂了）。
    part = re.search(r'/([^/]+)$', low_path)
    stem = (part.group(1) if part else '').split('.')[0]
    adword = re.search(r'(?:^|/)(?:adjump|advert|promo|gg|tui)(?:/|$)', low_path) or \
        re.match(r'^(?:adjump|advert|promo|gg|tui)', stem)
    if adword:
        if host not in baseline_hosts:
            return 'block', f'启发式：路径含广告词且不在主 CDN（{host}）'
        return 'unknown', f'启发式：路径含广告词但同属主 CDN，不动（{host}）'

    return 'unknown', ''


# ═══════════════════════════════════════════════════════
# 四、净化：真正改写，且每一步都过 RFC 校验
# ═══════════════════════════════════════════════════════
@dataclass
class SanitizeResult:
    status: str = 'unchanged'        # cleaned / unchanged / unsafe_skip / master_skip / invalid
    text: str = ''
    removed: int = 0
    kept: int = 0
    blocked_by: str = ''             # status 非 cleaned 时的原因（不许空着糊过去）
    blocked: list = field(default_factory=list)   # [(uri, why)]
    warnings: list = field(default_factory=list)

    def as_dict(self):
        return {
            'status': self.status, 'removed': self.removed, 'kept': self.kept,
            'blocked_by': self.blocked_by, 'blocked': self.blocked[:20],
            'warnings': self.warnings[:10],
        }


MIN_RATIO = 3.0   # RFC 8216 §6.2.2：剩余时长不得少于 3× target duration


def sanitize(text, base_url='', *, dry_run=False):
    """净化 m3u8 → SanitizeResult。

    ★ 核心安全策略：**要么整份改对，要么一个字都不改**。
      任何一个删除若会让清单违反 RFC 约束，整体回退 `unsafe_skip`，
      不做「删一半」——部分改写的清单是最难排查的故障形态。
    """
    res = SanitizeResult(text=text)
    if not text or '#EXTM3U' not in text:
        res.status, res.blocked_by = 'invalid', '不是 m3u8（无 #EXTM3U）'
        return res

    header, segs, footer, info = parse_playlist(text)
    if info['master']:
        res.status, res.blocked_by = 'master_skip', '多码率主清单，不净化（删 STREAM-INF 会破坏 ABR）'
        return res
    if not segs:
        res.status, res.blocked_by = 'invalid', '无分片行'
        return res

    # 主 CDN：出现次数最多的 host 集合（可能有多个并列）
    cnt = {}
    for s in segs:
        h, _ = _fp(urljoin(base_url or '', s.uri))
        if h:
            cnt[h] = cnt.get(h, 0) + 1
    top = max(cnt.values()) if cnt else 0
    baseline = {h for h, c in cnt.items() if c == top} if top else set()

    verdicts = []
    for i, s in enumerate(segs):
        v, why = judge_segment(urljoin(base_url or '', s.uri), seg_index=i,
                               total=len(segs), baseline_hosts=baseline,
                               base_url=base_url)
        verdicts.append((v, why, s))

    blocked = [s for v, _, s in verdicts if v == 'block']
    if not blocked:
        res.status, res.kept = 'unchanged', len(segs)
        if ADS_NOTE.startswith('黑名单文件读取失败'):
            res.warnings.append(ADS_NOTE)
        return res

    # ── RFC 预检：删了会不会把清单弄坏 ──
    keep = [s for v, _, s in verdicts if v != 'block']
    td = info['target_duration'] or 0.0
    if not td:
        # 无 TARGETDURATION 时用最大分片时长当上界（保守）
        td = max((s.duration for s in segs), default=0.0)
    keep_dur = sum(s.duration for s in keep)
    if td and keep_dur < MIN_RATIO * td:
        res.status = 'unsafe_skip'
        res.blocked_by = (f'删后剩余 {keep_dur:.1f}s < {MIN_RATIO}×target({td:.1f}s)='
                          f'{MIN_RATIO * td:.1f}s，违反 RFC 8216 §6.2.2，拒绝删')
        res.blocked = [(s.uri, why) for v, why, s in verdicts if v == 'block']
        res.removed, res.kept = 0, len(segs)
        return res
    if len(keep) == 0:
        res.status, res.blocked_by = 'unsafe_skip', '全部命中广告，删完无分片'
        res.blocked = [(s.uri, why) for v, why, s in verdicts if v == 'block']
        return res

    # ── 生成新清单文本 ──
    removed_n = len(blocked)
    head_n = 0
    for v, _, s in verdicts:
        if v == 'block':
            head_n += 1
        else:
            break
    removed_disc = sum(1 for v, _, s in verdicts if v == 'block'
                       for t in s.pre_tags if 'EXT-X-DISCONTINUITY' in t)

    out = []
    for ln in header:
        if ln.strip().startswith('#EXT-X-MEDIA-SEQUENCE') and info['media_sequence'] is not None:
            out.append(f'#EXT-X-MEDIA-SEQUENCE:{info["media_sequence"] + head_n}')
        elif ln.strip().startswith('#EXT-X-DISCONTINUITY-SEQUENCE') and removed_disc:
            base = info['discontinuity_sequence'] or 0
            out.append(f'#EXT-X-DISCONTINUITY-SEQUENCE:{base + removed_disc}')
        else:
            out.append(ln)
    # 头部原本没有 MEDIA-SEQUENCE（点播清单常见）→ 不擅自加，VOD 不需要
    # ★ 分片回写：必须「pre_tags + #EXTINF 行 + URI 行」三样都写回。
    #   第一版只写了最后一行（URI），#EXTINF 被吞掉 —— 回读解析出 0 个分片、
    #   总时长归零，被 _verify 抓住（这就是回读校验存在的意义）。
    prev_kept = False
    for v, why, s in verdicts:
        if v == 'block':
            prev_kept = False
            continue
        pending_tags = list(s.pre_tags)
        # 删广告后前后两段直接拼接：若拼接口两侧都没有 DISCONTINUITY 语义，
        # 残留的单个 DISCONTINUITY 会让播放器重新初始化解码器（表现为卡一下）。
        # 但**不能无脑删**——两段编码参数真不同时它必须留。故只在「本次因删广告
        # 才产生的拼接点」上去掉，且计数已在 removed_disc 里补偿 SEQUENCE。
        if prev_kept and pending_tags:
            pending_tags = [t for t in pending_tags if 'EXT-X-DISCONTINUITY' not in t]
        for t in pending_tags:
            out.append(t)
        out.append(f'#EXTINF:{s.duration:.6f},')
        out.append(s.uri)
        prev_kept = True
    out.extend(footer)
    new_text = '\n'.join(out) + '\n'

    if dry_run:
        res.status = 'cleaned'
        res.removed, res.kept = removed_n, len(keep)
        res.blocked = [(s.uri, why) for v, why, s in verdicts if v == 'block']
        res.warnings.append('dry_run：仅报告，未产出文本')
        return res

    # ── 回读校验：改完再解析一遍，对不上就整体回退 ──
    ok, why = _verify(new_text, segs, keep, info, head_n)
    if not ok:
        res.status, res.blocked_by = 'unsafe_skip', f'回读校验失败：{why}（已回退原文）'
        res.blocked = [(s.uri, w) for v, w, s in verdicts if v == 'block']
        res.removed, res.kept = 0, len(segs)
        return res

    res.status, res.text = 'cleaned', new_text
    res.removed, res.kept = removed_n, len(keep)
    res.blocked = [(s.uri, why) for v, why, s in verdicts if v == 'block']
    return res


def _verify(new_text, old_segs, keep, info, head_n):
    """回读校验：结构可解析 + 分片数对 + MEDIA-SEQUENCE 只增不减 + 时长非零。"""
    h2, s2, _, i2 = parse_playlist(new_text)
    if len(s2) != len(keep):
        return False, f'分片数 {len(s2)} ≠ 预期 {len(keep)}'
    if not s2:
        return False, '改完没有分片'
    if sum(x.duration for x in s2) <= 0:
        return False, '改完总时长归零'
    if info['media_sequence'] is not None:
        if i2['media_sequence'] is None:
            return False, 'MEDIA-SEQUENCE 丢失'
        if i2['media_sequence'] != info['media_sequence'] + head_n:
            return False, (f'MEDIA-SEQUENCE {i2["media_sequence"]} ≠ '
                           f'{info["media_sequence"]}+{head_n}')
        if i2['media_sequence'] < info['media_sequence']:
            return False, 'MEDIA-SEQUENCE 减小（RFC 禁止）'
    return True, ''


# ═══════════════════════════════════════════════════════
# 五、CLI：给人看，也给自检用
# ═══════════════════════════════════════════════════════
def main(argv=None):
    import sys
    ap_argv = list(argv if argv is not None else sys.argv[1:])
    if not ap_argv or ap_argv[0] in ('-h', '--help'):
        print('用法：')
        print('  hls_clean.py <file.m3u8> [--base URL] [--dry-run] [--json]')
        print('  hls_clean.py --selftest            # 跑内置正/负/错域样本')
        print('  hls_clean.py --ads                 # 看黑名单载入情况')
        return 0
    if ap_argv[0] == '--ads':
        print(ADS_NOTE)
        for h in sorted(ADS)[:10]:
            print(' ', h)
        print(f'  …共 {len(ADS)} 条')
        return 0
    if ap_argv[0] == '--selftest':
        return selftest()

    path = ap_argv[0]
    base = ''
    dry = '--dry-run' in ap_argv
    as_json = '--json' in ap_argv
    if '--base' in ap_argv:
        base = ap_argv[ap_argv.index('--base') + 1]
    text = open(path, encoding='utf-8', errors='replace').read()
    r = sanitize(text, base, dry_run=dry)
    if as_json:
        print(json.dumps(r.as_dict(), ensure_ascii=False, indent=1))
    else:
        print(f'状态：{r.status}  删 {r.removed} 留 {r.kept}')
        if r.blocked_by:
            print(f'原因：{r.blocked_by}')
        for u, w in r.blocked[:10]:
            print(f'  - {u}  ← {w}')
    if r.status == 'cleaned' and not dry:
        print('-------- 净化后清单 --------')
        print(r.text)
    return 0


# ═══════════════════════════════════════════════════════
# 六、自检：每条规则必须同时有 正样本 / 负样本 / 错域负样本
# ═══════════════════════════════════════════════════════
# 为什么必须三样本：只有正样本的规则无法证明「不会误杀」。
# 业内上线去广告规则的硬门槛就是这一条——错域负样本专门验
# 「同样文件名换到正片 CDN 上，不得被判广告」。
_SAMPLES = [
    # (名字, 期望 verdict, uri, base_url, 说明)
    ('量子上广告分片', 'block', 'https://vip.lz-cdn.com/xx/1o.ts',
     'https://vip.lz-cdn.com/xx/index.m3u8', '规则域名特征 vip.lz'),
    ('量子正片分片', 'unknown', 'https://cdn.lziapi.com/xx/1001.ts',
     'https://cdn.lziapi.com/xx/index.m3u8', '同站正片 CDN，不带规则特征'),
    ('统计域名', 'block', 'https://hm.baidu.com/hm.gif',
     'https://cdn.lziapi.com/xx/index.m3u8', '黑名单精确域名'),
    ('公共 CDN', 'allow', 'https://cdn.jsdelivr.net/npm/x/a.ts',
     'https://cdn.lziapi.com/xx/index.m3u8', 'Allow 层优先于黑名单'),
    ('错域负样本', 'unknown', 'https://cdn.lziapi.com/ad/promo.ts',
     'https://cdn.lziapi.com/xx/index.m3u8', '路径含广告词但属主 CDN，不得删'),
    ('异域广告词', 'block', 'https://ad.other-cdn.com/promo.ts',
     'https://cdn.lziapi.com/xx/index.m3u8', '路径含广告词且不在主 CDN'),
]


def _mk_m3u8(uris, dur=6.0, td=6, media_seq=None):
    """造测试清单。`dur` 可为单个时长或与 uris 等长的列表。

    ★ 测试清单必须够长：RFC 要求删后剩余 ≥3×target duration，
      若只造 3 个 6s 分片（共 18s），删任何一个都只剩 12s < 18s，
      时长保护必然触发 —— 那样测的就不是「删得对不对」而是「保护生效没」。
      故默认造 10 条。
    """
    durs = dur if isinstance(dur, (list, tuple)) else [dur] * len(uris)
    head = ['#EXTM3U', f'#EXT-X-TARGETDURATION:{td}', '#EXT-X-VERSION:3']
    if media_seq is not None:
        head.append(f'#EXT-X-MEDIA-SEQUENCE:{media_seq}')
    body = []
    for u, d in zip(uris, durs):
        body += [f'#EXTINF:{d:.6f},', u]
    body.append('#EXT-X-ENDLIST')
    return '\n'.join(head + body) + '\n'


def selftest():
    fails = []
    base = 'https://cdn.lziapi.com/xx/index.m3u8'
    for name, want, uri, b, note in _SAMPLES:
        v, why = judge_segment(uri, seg_index=0, total=10,
                               baseline_hosts={'cdn.lziapi.com'}, base_url=b)
        ok = 'OK ' if v == want else 'FAIL'
        if v != want:
            fails.append(f'{name}: 期望 {want} 实得 {v}')
        print(f'[{ok}] {name:12s} {v:8s} {why or note}')

    # 场景 1：删掉中间一段广告，MEDIA-SEQUENCE 不变（没删头部）
    uris = [f'https://cdn.lziapi.com/xx/{1000 + i}.ts' for i in range(10)]
    uris[5] = 'https://vip.lz-cdn.com/xx/1o.ts'
    m = _mk_m3u8(uris, dur=6, td=6, media_seq=100)
    r = sanitize(m, base)
    _chk(fails, '中间插广告', r.status == 'cleaned' and r.removed == 1,
         f'状态 {r.status} 删 {r.removed}')
    _chk(fails, '中间插广告·序列不变', '#EXT-X-MEDIA-SEQUENCE:100' in r.text,
         '头部未删，序列应保持 100')

    # 场景 2：删头部 → MEDIA-SEQUENCE 必须 +1
    uris2 = [f'https://cdn.lziapi.com/xx/{1000 + i}.ts' for i in range(10)]
    uris2[0] = 'https://vip.lz-cdn.com/xx/1o.ts'
    m2 = _mk_m3u8(uris2, dur=6, td=6, media_seq=100)
    r2 = sanitize(m2, base)
    _chk(fails, '头部广告', r2.status == 'cleaned', f'状态 {r2.status}')
    _chk(fails, 'MEDIA-SEQUENCE +1', '#EXT-X-MEDIA-SEQUENCE:101' in r2.text,
         [x for x in r2.text.splitlines() if 'MEDIA-SEQUENCE' in x])

    # 场景 3：只剩 2 个分片，删一个会跌破 3×td → 必须拒绝
    m3 = _mk_m3u8(['https://vip.lz-cdn.com/xx/1o.ts',
                   'https://cdn.lziapi.com/xx/1.ts',
                   'https://cdn.lziapi.com/xx/2.ts'], dur=6, td=6, media_seq=1)
    r3 = sanitize(m3, base)
    _chk(fails, '时长保护', r3.status == 'unsafe_skip',
         f'状态 {r3.status}：{r3.blocked_by}')
    _chk(fails, '时长保护·原文不变', r3.text == m3, 'unsafe_skip 时不得改写')

    # 场景 4：多码率主清单不净化
    mast = ('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nlow.m3u8\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=2000000\nhigh.m3u8\n')
    r4 = sanitize(mast, base)
    _chk(fails, '主清单跳过', r4.status == 'master_skip', f'状态 {r4.status}')

    print()
    if fails:
        print(f'✗ {len(fails)} 项失败：')
        for f in fails:
            print('  -', f)
        return 1
    print(f'✓ 全部通过（{len(_SAMPLES)} 条判定样本 + 4 个净化场景）')
    return 0


def _chk(fails, name, cond, detail=''):
    if cond:
        print(f'[OK ] {name}')
    else:
        print(f'[FAIL] {name}  {detail}')
        fails.append(f'{name}（{detail}）')


if __name__ == '__main__':
    raise SystemExit(main())
