#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
janitor.py —— 清道夫·待删收件箱（S104）

背景（用户 2026-10-16）：
  "你删除不了的，需要我删除的统一放进一个文件内，方便我去删除，
   这个应该可以在生态里做一个新技能了，专门管整理这块。"
  ——"全量，只要你不能删除的，都放进来，不管是啥"
  ——"一个文件夹，把需要我删的统一放进去，我只管去这个文件删"

**能力边界**：云端库（WorkBuddy space）**无删除节点 API**（只有 create/rename/move/
publish/unpublish）。凡 AI 删不掉的节点 → 本技能**移动**到一个统一收件箱文件夹，
并生成《待删清单》，用户只需打开这一个文件夹按单删除。

命令：
  janitor inbox                       建/确认"🗑 待删收件箱"文件夹（幂等）
  janitor add --node ID [--reason R]  把节点移入收件箱 + 登记清单（AI 能做的最后一步）
  janitor scan                        扫全空间找"废弃/待删/🗑"标记节点（补漏登记）
  janitor list                        打印待删清单（Markdown + CSV 落盘）
  janitor move --node ID --to 父节点ID              节点移动到指定文件夹（改名/归位通用）
  janitor rename --node ID --title "新标题"         节点改名

铁律：
  · 只移动、不删除（AI 无删除权）；移动前**校验节点确实存在**。
  · 清单**永不静默丢项**：节点不存在/移动失败 → 显式告警并保留在清单（标"待人工确认"）。
  · 幂等：同一节点重复 add 不重复登记（按 node_id 去重）。
"""
import os, sys, json, argparse, subprocess, time, re, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.expanduser('~/.codebuddy/skills/library')   # 平台标准路径，HOME 自适应
# ★★★ 空间解析四层（v2.0.0 起**禁止写死 space id**——旧版绑死账号，换号即残废；实测教训：
#   旧 ID 8w5cnq… 随空间重建 role=invalid，清道夫整条链路瘫痪）：
#   ① 显式 --space-id / 环境变量 SPACE_HUB_SPACE_ID
#   ② space_hub_state.json 登记值（init 时写入）
#   ③ 动态发现：list-user-spaces 按 space_title 匹配且 role∈{owner,admin}
#   ④ 显式报错并列出全部可用空间，提示跑 `init` 登记——**绝不猜、不静默用错空间**
PREF_TITLE = 'TVBox 生态空间'      # 动态发现的默认标题（init --title 可改）
SPACE = None                        # 运行时由 resolve_space() 填充（禁止模块级写死）
# 收件箱挂「我的资料」根目录（S196 用户 2026-10-21 21:27 指示：以后待删放根目录，一眼可见）
PARENT = None                       # = SPACE，由 resolve_space() 一并填充
# ★ 全局扫描根 = 空间根（S158 定案）：`--parent-node-id ""`（**空字符串，不是省略也不是 'root'**）
#   即可枚举空间顶层。旧超根 gZ4x…（探源司·总库）随旧空间消亡已不存在——**节点 id 一律不写死**。
SPACE_ROOT = ''                    # ★ 空间真根（实测唯一可用写法）
ROOTS = [SPACE_ROOT]               # 扫描起点集合：空间根已覆盖全部子树
# ★ 垃圾判定关键词（标题命中即判垃圾，自动投递）。扩展覆盖各类废弃标记；
#   刻意**不含**「库/总库/源库」等正常词，避免误伤活跃库。
KW = ('废弃', '已废弃', '失效', '作废', '请删', '待删', '🗑', '空壳', '勿用',
      '测试', 'test', '重复', '弃用', '临时', 'temp', 'backup',
      'draft', '旧版', '垃圾', '（旧', '_old', '弃')
# ★ 注：「归档」**不**作为废弃标记——正常业务表（如 S103「产出json·归档表」）
#   标题常含"归档"，会误判。废弃判定只认显式废弃标记词（见上 KW），不泛化到"归档"。
INBOX_TITLE = '🗑 待删收件箱（库务司·按单删即可）'
STATE = os.path.join(HERE, 'space_hub_state.json')
CLASSIFY_RULES = os.path.join(HERE, 'classify_rules.json')
OUT_DIR = '/workspace'

# ★ S158：空文件夹 ≠ 垃圾。这两类空夹**永远不投**：
#   · 名字像备份/库/归档 —— 可能是"内容在别处"或"还没写完"（备份夹实测就是空壳）
#   · 名字像运维/入口 —— 是结构性容器，不承载内容
#   事故链见 cmd_add 护栏注释：一次 scan 差点把 77 个附件的备份夹当空夹投掉。
EMPTY_KEEP = ('备份', 'backup', '归档', '库', '运维', '入口', '总库', '收件箱', '手册')

# ★ S179（M-R125）：上面这层保护**方向是错的**——它挂在"名字"上。
#
#   实测（见 ecosys-conductor/docs/M-R125_evidence.md）：
#     · node-info 字段全集 16 个，**没有任何附件字段**；
#     · api-manifest 41 个接口，**没有 attachment-list**；
#     · get-doc-review 正文对"有 81 个附件"与"真空"返回完全同形；
#     · 同一批 14 个备份夹，list-nodes 全返回 0 子节点，而 backup_state 记着 81 件已上传。
#
#   所以「子节点数 == 0」**不是弱证据，是不成立的证据**：接口返回的 0 是真值，
#   只是它回答的不是"这里有没有东西"。既然如此，靠 EMPTY_KEEP 关键词兜底就等于
#   **用命名习惯替代判据**——夹叫 `20261020_eco` 而不是 `20261020_生态备份` 就失守。
#
#   改为：**空夹一律不按"空"投递**，只登记为待人工核对的候选（nocontent），
#   并显式写清"AI 无法判定"。宁可少投（用户照 list 删即可），不可误投（附件的夹删了就没）。
#   EMPTY_KEEP 保留但降级为"排序权重"，不再承担安全职责。
EMPTY_NEVER_AUTOPOST = True

# ★ S179：结构性容器词——标题含这些词时，即便同时命中废弃标记也不自动投递（须人工裁决）。
#   理由同 EMPTY_KEEP 降级：一个"库/归档/总库"被整批搬走，损失远大于少投一条。
#   ★ 单字词必须带否定前瞻，否则子串误命中：
#     实测「🗄️ 待清·DmaxPro908（已入库待删）」——"入库"里含"库"，被判成结构性容器，
#     而它明明是"已入库**待删**"的待清项，本该投递。故 `库` 后面紧跟"存/房/内"时不认。
STRUCT_KEEP = ('归档', '总库', '备份', '运维', '入口', '手册', '收件箱')
_STRUCT_RE = re.compile(r'(?<!入)库(?!存|房|内)')


def _struct_hits(t):
    """标题命中的结构性容器词（`库` 用前瞻排除"入库/库存"等动词用法）。"""
    out = [k for k in STRUCT_KEEP if k in t]
    if _STRUCT_RE.search(t):
        out.append('库')
    return out

# ★ S158：同父同名去重的**默认阈值**。>该值才把多余副本投进收件箱（保留最早一份）。
#   为什么默认不是 0：实测根层级「生态遗留趋势留档（跨设备）」×23、
#   「生态1015_遗留问题监测报告」×19 —— 这些不是"两份不同内容的留档"，
#   而是同一个脚本每轮新建一份的产物。**不设默认值 = 问题永远只被报出来、永远不被处理**
#   （用户原话："我强调几遍依然没动作"）。2 是保守值：允许正常保留 2 份（现行 + 上一版）。
#   要"只告警不动手"显式传 `--dedup 0`。
DEFAULT_DEDUP = 2

# ★ S158 新增：大生态/小生态分层普查（census）
#   痛点：清道夫只会「按关键词找垃圾」，但用户真正问的是「**这块归谁管**」——
#   关键词判定回答不了归属，于是每次都要人临场翻。census 补上「归属」这一维：
#   输出每个节点属于哪个技能的责任田（L1），不属任何责任田的即为「缝」（L0 无主区）。
#   权威定义见 ecosys-conductor/references/eco_layers.md（单一事实源，禁在别处另立一套）。
#   责任田登记：节点 id → (技能, 说明)。**只登记技能能自己写东西的容器**，
#   不登记"只是路过读一下"的库——登记了就等于声称对它负责。
TERRITORY = {
    # ── 空间根层级锚点 ──
    'Xjqn2Wf5EKPSGIXqQ2K6Dc': ('eco-ledger', '📒 账房·总账'),
    '6cQgwWQqqKoeFAiTcb08Cx': ('eco-ledger', '📒 账房·账户'),
    'gZ4xP6kXXeCpTlsH2CN9tJ': ('tvbox-source-hub', '📦 探源司·总库'),
    'elOV0tlJ4gcTF3atBay2nS': ('ecosys-conductor', '📁 入口·常用入口索引'),
    'qBQcYoVTqg7v3NAYBa4eSF': ('skill-evolution', '🥋 通用招式库'),
    'MrJdROzysspCyWo0L3F32z': ('ecosys-conductor', '用户术语库'),
    'kqNrwHd53K9qr1DFBUPglZ': ('ecosys-conductor', '用户需求事件库'),
    # ── 探源司子树内的关键库 ──
    'GCLJWbFGS1BmYbj6JCX9it': ('tvbox-interface', '📁 底包·底包总库'),
    'pNwZ9uBOTz6FzRuvu8nryI': ('tvbox-source-hub', '探源司·线路源库'),
    '8JBrhSwsJ3pnPYtoGLo9XV': ('tvbox-source-hub', '探源司·成品源库'),
    'aCSvley568A0aW3sggzJwA': ('probe-hub', '上游仓库监测册'),
    'khHl458xi8qK15lVaYfbvU': ('probe-hub', '探源司·搜索候选册'),
    'E5I6T2UXIS7CB5r0AkimRl': ('probe-hub', '探源司·采集候选册'),
    'hGwE41OpJDOR8CW0sLUwRx': ('tvbox-source-blacklist', '探源司·失信host库'),
    # ── 生态四库（资料库侧）──
    'T4kODtANe7rSrtZTu4sIND': ('ecosys-conductor', '🧩 TVBox技能生态登记库'),
    'XTuuj8mKtqnZSolDdeDxkq': ('unfinished-audit', '📚 资料库操作经验库'),
    # ── 收件箱 ──
    'tBlgSL4SPEFMrsyTBTg03c': ('space-hub', '🗑 待删收件箱'),  # 历史名 tvbox-janitor，S104 建
}
# 空间根与收件箱不在 census 里当"缝"统计：前者是全体，后者是待删暂存
_NOT_GAP = {'', 'tBlgSL4SPEFMrsyTBTg03c'}

# ══ 归属真源合并（S158 修·本轮最严重的一次自打脸）═══════════════════════════
# **事故**：S158 我写了 `ecosys-conductor/scripts/zone_registry.json`，14 个区逐个指派
# owner，报告里写"覆盖全部 315 个缝节点，11 已指派"。但 `census` **只读本文件的
# TERRITORY**，从不读 zone_registry —— 于是缝占比一动不动，还是 71%（317/441）。
# 我指派的 8 个已指派区 node_id **一个都不在 TERRITORY 里**，那张表是死表。
#
# **这正是我本轮批判过的缺陷原样重演**：两处各存一份"归属"，互不相认，
# 而且两边都不报错——一边说"我指派了"，另一边说"还是没人管"，同时成立。
#
# **修法（M-R85 单一事实源）**：
#   · `zone_registry.json` 是**跨技能归属的主源**（含 owner/why/plan，属治理决策）；
#   · `TERRITORY` 只保留**技能自有锚点**（那些不在 registry 里的库/容器）；
#   · census 启动时**合并两者**，registry 优先（治理决策 > 代码默认）。
#   读不到 registry 时必须**显式告警**，不许静默只用 TERRITORY 假装覆盖完整。
ZONE_REGISTRY = os.path.join(HERE, 'space_hub_zones.json')  # 归属登记册（本地可选件，缺省告警不致命）


def load_territory():
    """合并归属真源：TERRITORY（技能锚点） + zone_registry（治理指派）。

    返回 (merged, problems, prefix_rules)。problems 非空表示**覆盖不完整**，调用方必须报出来。

    ★ S158 一次读、两处用：原先这段读了 registry **两遍**，第二遍 `except: pass`。
      于是 registry 损坏时：第一遍报 problems，第二遍把前缀规则静默吞成空——
      **4 个根层级散落区的归属无声消失，而 problems 里看不到任何相关提示**。
      这正是本轮批判的 `except: pass` 原样重演，已改为单次读取。
    """
    merged = dict(TERRITORY)          # 先放技能锚点
    problems = []
    pref_rules = []
    try:
        reg = json.load(open(ZONE_REGISTRY, encoding='utf-8'))
        zones = reg.get('zones') or []
        for z in zones:
            nid = (z.get('node_id') or '').strip()
            owner = z.get('owner')
            pref = z.get('match_prefix') or []
            # 两种挂法：容器型 node_id / 根层级散落组 match_prefix。
            # 只有**两者都没有**才算登记不全（那说明这个区在表里只是个说法）。
            if not nid and not pref:
                problems.append(f'区「{z.get("top")}」既无 node_id 也无 match_prefix，无法参与归属判定')
                continue
            if not owner:
                continue                  # 待裁定区：仍算缝，但要单独报出来
            if nid:
                # registry 覆盖同名锚点：治理指派优先于技能自报（后写覆盖先写）
                merged[nid] = (owner, z.get('top') or '')
            if pref:
                pref_rules.append((tuple(pref), owner, z.get('top') or ''))
    except FileNotFoundError:
        problems.append(f'zone_registry 不存在：{ZONE_REGISTRY}——**归属只含技能锚点，'
                        f'治理指派的那批区会全部计为缝**（不是"没有缝"）')
    except Exception as e:
        problems.append(f'zone_registry 读取失败（{type(e).__name__}: {e}）——'
                        f'归属不完整，缝占比会偏高（无法判定，不是"没问题"）')
    return merged, problems, pref_rules

sys.path.insert(0, LIB)


def _space(api, **kw):
    args = [sys.executable, f'{LIB}/space_api.py', api]
    for k, v in kw.items():
        args += [f'--{k.replace("_", "-")}', str(v)]
    r = subprocess.run(args, capture_output=True, text=True)
    s = (r.stdout or '').strip()
    for ln in s.splitlines():
        ln = ln.strip()
        if ln.startswith('{'):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return None


# ══════════════ 数据保全（v2.6.0 · 机制借鉴 Memory Palace snapshot.py / write_lane）══════════════
# 现场证据（2026-11-12）：
#   ① 安装副本与仓副本 state 各写各的，无快照无回滚——改坏了只能瞪眼；
#   ② 两会话并发跑 space-hub 存在 state 竞态；
#   ③ 产物区合并用了 --force，事后无留痕，谁也不记得当时为什么放行。
# 四件套：写前快照（幂等）/ 原子写 / 轮换 GC / 索引自愈；外加迁移锁与 force 审计。
SNAP_DIR = os.path.join(HERE, 'snapshots')
SNAP_INDEX = os.path.join(SNAP_DIR, 'index.json')
SNAP_KEEP = max(0, int(os.getenv('SPACE_HUB_SNAPSHOT_KEEP', '20') or '20'))  # 0=关轮换
_ENSURE_LOCK = os.path.join(HERE, '.ensure.lock')
_ENSURE_LOCK_TIMEOUT = max(5.0, float(os.getenv('SPACE_HUB_ENSURE_LOCK_TIMEOUT', '60') or '60'))
_AUDIT_MAX = 50                     # 审计节上限（防 state 无限膨胀）
_SNAPPED = set()                    # 本进程已拍过的资源名（幂等：同资源同进程只拍一次）
_CUR_SNAP = None                    # 当前进程刚拍的快照文件名——轮换**绝不碰它**


def _atomic_write(path, data_bytes):
    """原子写：同目录临时文件 + fsync + os.replace（借鉴 MP _write_bytes_atomic）。

    半截写的后果：state 是唯一账本，截断 json 会让下一次 load_state 直接 SystemExit(2)。
    os.replace 在同一文件系统内是原子的——读者要么看到旧整份，要么看到新整份。
    """
    d = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(prefix='.tmp_', dir=d)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_json(path, obj):
    _atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8'))


def _load_snap_index():
    """快照索引：损坏时**从快照文件自愈重建**（MP _rebuild_manifest_from_resources 同构）。

    与 M-R60"状态损坏不折叠"不冲突：那条说**不许把损坏当空**；这里更进一步——
    索引层坏了就重建索引层，快照数据本体还在，一个都不丢，但必须大声说出来。
    """
    os.makedirs(SNAP_DIR, exist_ok=True)
    try:
        d = json.load(open(SNAP_INDEX, encoding='utf-8'))
        if isinstance(d, dict) and isinstance(d.get('entries'), list):
            return d
    except FileNotFoundError:
        return {'entries': []}
    except Exception:
        pass
    print('  ⚠️ 快照索引损坏——已从快照文件自愈重建（数据本体未丢，只修了目录）')
    entries = []
    for fn in sorted(os.listdir(SNAP_DIR)):
        if fn.endswith('.json') and fn != 'index.json':
            try:
                entries.append({'file': fn, 'bytes': os.path.getsize(os.path.join(SNAP_DIR, fn))})
            except OSError:
                continue
    return {'entries': entries, 'rebuilt': True}


def _snapshot_state(prefix='pre_write'):
    """写前快照：把**即将被覆盖**的 state 拍进 snapshots/。

    幂等（MP 语义）：同资源同进程只拍一次——一次命令里 save_state 十次，快照只有第一份
    「写前原貌」，拍多了反而找不到"改动前"的干净基线。
    """
    global _CUR_SNAP
    if _prefix_key(prefix) in _SNAPPED:
        return None
    if not os.path.exists(STATE):
        return None                      # 首次建账，无旧可拍
    try:
        data = open(STATE, 'rb').read()
    except OSError as e:
        print(f'  ⚠️ 快照读取失败（{e}）——继续写，但本次无快照可回滚')
        return None
    fn = f'{time.strftime("%Y%m%d_%H%M%S")}_{os.getpid()}_{_snap_seq()}_{prefix}.json'
    fp = os.path.join(SNAP_DIR, fn)
    try:
        os.makedirs(SNAP_DIR, exist_ok=True)
        _atomic_write(fp, data)
    except OSError as e:
        print(f'  ⚠️ 快照写盘失败（{e}）——继续写，但本次无快照可回滚')
        return None
    _SNAPPED.add(_prefix_key(prefix))
    _CUR_SNAP = fn
    idx = _load_snap_index()
    idx['entries'].append({'file': fn, 'bytes': len(data),
                           'at': time.strftime('%Y-%m-%d %H:%M:%S')})
    _atomic_json(SNAP_INDEX, idx)
    _gc_snapshots(idx)
    return fp


def _prefix_key(prefix):
    return f'{os.getpid()}:{prefix}'


_SNAP_SEQ = [0]


def _snap_seq():
    """快照文件名序号：同 pid 同秒多次快照也不重名（实测 T4：同秒覆盖会丢基线）。"""
    _SNAP_SEQ[0] += 1
    return f'{_SNAP_SEQ[0]:02d}'


def _gc_snapshots(idx=None):
    """机会式轮换（MP _garbage_collect_sessions 同构）：超 KEEP 删最旧。

    · KEEP=0 → 轮换关闭（一个不删）；
    · 当前进程刚拍的快照**绝不碰**（GC 撞上正在用的快照等于自毁回滚能力）；
    · 只删快照文件本身，索引条目同步摘除。
    """
    if SNAP_KEEP <= 0:
        return
    idx = idx if isinstance(idx, dict) else _load_snap_index()
    try:
        files = sorted(fn for fn in os.listdir(SNAP_DIR)
                       if fn.endswith('.json') and fn != 'index.json')
    except OSError:
        return
    excess = len(files) - SNAP_KEEP
    if excess <= 0:
        return
    removed = set()
    for fn in files:
        if excess <= 0:
            break
        if fn == _CUR_SNAP:
            continue                     # 当前会话快照永不清
        try:
            os.unlink(os.path.join(SNAP_DIR, fn))
            removed.add(fn)
            excess -= 1
        except OSError:
            continue
    if removed:
        idx['entries'] = [e for e in idx['entries'] if e.get('file') not in removed]
        _atomic_json(SNAP_INDEX, idx)


def _ensure_lock():
    """迁移锁（借鉴 MP DB_MIGRATION_LOCK）：跨进程 flock，超时报**结构化**错误。

    为什么不报通用错：调用方（install.sh / 手机指令）需要按机器码分支处理，
    'ensure_lock_timeout' 是契约，不是给人看的散文（E9 错误 reason 机器码）。
    """
    import fcntl
    f = open(_ENSURE_LOCK, 'w')
    deadline = time.time() + _ENSURE_LOCK_TIMEOUT
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except OSError:
            if time.time() >= deadline:
                f.close()
                raise SystemExit(json.dumps(
                    {'error': 'ensure_lock_timeout', 'lock': _ENSURE_LOCK,
                     'timeout_sec': _ENSURE_LOCK_TIMEOUT}, ensure_ascii=False))
            time.sleep(0.5)


_JSON_MODE = os.environ.get('SPACE_HUB_JSON', '') not in ('', '0', 'false', 'False')


def _reject(code, reason, target='', method='', human=''):
    """★ E3/E9（工程E）：拒收/失败的**结构化契约**——`{error, reason, target, method}`。

    为什么必须结构化：调用方（上层技能、子代理、手机通道）拿到的如果只有一句
    "🛑 拒收"，它唯一能做的动作是**换个参数重试**——而重试同一道闸正是 B-10 禁的事。
    给出四个字段，动作才能从"猜"变成"按提示走"：
      - `error`  机器码，可被分支（如 guard_nonempty_container / target_not_folder）
      - `reason` 人读原因（为什么拦）
      - `target` 建议去哪儿（下一步该做什么，不是"目标节点"）
      - `method` 具体能跑的命令模板（含占位符，不许含糊说"请人工处理"）

    两种输出形态：
      - 默认：人类文案 + 末行 `↳ {json}`（grep '↳ {' 即可取）
      - `SPACE_HUB_JSON=1`：人类文案走 stderr，stdout **只有**一行 JSON（供程序解析）
    """
    payload = {'error': code, 'reason': reason, 'target': target, 'method': method}
    if human:
        print(human, file=sys.stderr) if _JSON_MODE else print(human)
    print(json.dumps(payload, ensure_ascii=False) if _JSON_MODE
          else '     ↳ ' + json.dumps(payload, ensure_ascii=False))
    return payload


def _audit_force(action, detail, reason):
    """--force 审计留痕：谁在何时对什么强行绕过了什么护栏、凭什么理由。

    只写最后 _AUDIT_MAX 条，防 state 无限膨胀。
    """
    st = load_state()
    st.setdefault('audit', []).append({
        'at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'action': action, 'detail': detail,
        'reason': (reason or '').strip() or '（未注明）',
    })
    st['audit'] = st['audit'][-_AUDIT_MAX:]
    save_state(st)


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding='utf-8'))
        except Exception as e:
            print(f'  ⚠️ 收件箱状态损坏（{type(e).__name__}）——禁止当"空收件箱"（M-R60）')
            raise SystemExit(2)
    return {'inbox': '', 'items': []}


def save_state(d):
    """★ S156 招式 T-I 落地：写后回读验证（写了 ≠ 写成了）。

    **为什么清道夫尤其需要**：`STATE` 是「待删收件箱」的唯一账本——哪些节点已投递、
    哪些已删、哪些还等着人工处理，全在这一个 json 里。原先它是**裸写**：
    `json.dump(d, open(...'w'))` 之后没有任何证据说明写成功了。
    写坏的后果不是"这一条没记住"，而是**整队丢了**：下一次 `scan` 读到残缺 json →
    `load_state` 抛 SystemExit(2) → 收件箱直接不可用；而如果截断后恰好仍能解析
    （比如只少了末尾几条），更糟——**没人知道少哪几条**。

    三态（M-R60）：写入失败 / 回读解析失败 / 回读条目数不符 —— 分别报原因并**抛错退出**，
    绝不静默继续（继续就会拿"假状态"去决定删不删节点）。

    v2.6.0 增补：写前快照（可回滚）+ 原子写（tmpfile+fsync+os.replace，半截写不可能落盘）。
    """
    _snapshot_state('pre_write')
    payload = json.dumps(d, ensure_ascii=False, indent=2).encode('utf-8')
    try:
        _atomic_write(STATE, payload)
    except Exception as e:
        raise SystemExit(f'❌ 收件箱状态写入失败（{type(e).__name__}: {str(e)[:100]}）——'
                         f'拒绝继续（后续动作会基于错误状态决定删不删节点）')
    try:
        back = json.load(open(STATE, encoding='utf-8'))
    except Exception as e:
        raise SystemExit(f'❌ 收件箱状态写后回读**解析失败**（{type(e).__name__}: {str(e)[:100]}）'
                         f'——文件已写坏，请检查 {STATE}')
    n_w, n_r = len((d or {}).get('items') or []), len((back or {}).get('items') or [])
    if n_w != n_r:
        raise SystemExit(f'❌ 收件箱状态回读条数不符：写入 {n_w} 条，回读到 {n_r} 条'
                         f'——内容被截断/覆盖，拒绝继续')
    if (d or {}).get('inbox', None) != (back or {}).get('inbox', None):
        raise SystemExit('❌ 收件箱状态回读：inbox 字段与写入值不符——状态已串')


def _kids(pid):
    """列某节点的子节点。**pid 为空串 = 空间顶层**（S158 实测：唯一可用写法）。

    实测过的三种写法：
      · parent_node_id='root' → `11510 block not found`（不行）
      · parent_node_id=<spaceId> → `11510 block not found`（不行）
      · parent_node_id=''      → 正常返回，total=76（**可行**）
    另：limit=200 单页可能被服务端截断，故带 offset 翻页到底。
    """
    out = []
    off = 0
    for _ in range(20):                      # 上限 20 页（4000 节点），防死循环
        d = _space('space.workspace.list-nodes', space_id=SPACE,
                   parent_node_id=pid, limit=200, offset=off)
        if not isinstance(d, dict) or d.get('error'):
            break
        data = d.get('data') or {}
        batch = data.get('nodes') or []
        out += batch
        if not data.get('hasMore') or not batch:
            break
        off += len(batch)
    return out


def _find_parent(nid, skip_inbox=True):
    """从空间超根递归反查 nid 的父节点 id（默认跳过收件箱子树）。

    为什么不用 node-info 的 parentNodeId？那字段实测恒为 None（不可信）。
    故用全树遍历反查——供 cmd_add 在移动前记录原父节点、误投后 restore 一键回退。

    ★2026-11-12 修：v2.0.0 改 ROOTS 时此处残留 `walk(ROOT)` → NameError，
    cmd_add 在「记录原父位」一步即崩、节点从未移动（今日实测投递现场踩到）。"""
    st = load_state()
    inbox = st.get('inbox')
    seen = set()

    def walk(pid):
        if pid in seen:
            return None
        seen.add(pid)
        if skip_inbox and inbox and pid == inbox:
            return None
        for n in _kids(pid):
            cid = n.get('id') or n.get('nodeId')
            if cid == nid:
                return pid
            if n.get('kind') == 'folder':
                r = walk(cid)
                if r:
                    return r
        return None

    for root in ROOTS:          # ★ 修：遍历起点集合（原残留单数 ROOT → NameError）
        r = walk(root)
        if r:
            return r
    return None


def _find_inbox():
    """在 PARENT 下找已存在的收件箱文件夹（按标题前缀匹配）。
    ★ S196：PARENT=空间根时必须用 _kids('')（空串=空间顶层唯一可行写法，见 _kids docstring；
      _kids(SPACE) 报 11510——当晚实测因此没认出已搬根目录的老箱，重复建了一个）。"""
    kids = _kids('') if PARENT == SPACE else _kids(PARENT)
    for n in kids:
        if n.get('kind') == 'folder' and '待删收件箱' in (n.get('title') or ''):
            return n.get('id'), n.get('title')
    return '', ''


def cmd_inbox(a):
    st = load_state()
    iid, ititle = _find_inbox()
    if iid:
        st['inbox'] = iid
        save_state(st)
        print(f'✅ 收件箱已存在：{ititle}（{iid}）')
        return 0
    r = subprocess.run([sys.executable, f'{LIB}/manage/create_folder.py',
                        '--title', INBOX_TITLE, '--space-id', SPACE, '--parent-id', PARENT],
                       capture_output=True, text=True)
    out = (r.stdout or '').strip()
    # 返回形如：KS_FOLDER_CREATE\t<id>\t<title>
    iid = ''
    for ln in out.splitlines():
        if 'KS_FOLDER_CREATE' in ln:
            parts = ln.split('\t')
            if len(parts) >= 2:
                iid = parts[1].strip()
    if not iid:
        print(f'❌ 建收件箱失败：{out[:200]}{r.stderr[:200]}')
        return 1
    st['inbox'] = iid
    save_state(st)
    print(f'✅ 收件箱已创建：{INBOX_TITLE}（{iid}）')
    return 0


def cmd_add(a):
    # ★ v2.6.0（A6）：--force 必须带 reason——绕护栏是要留痕的（放在**一切云端调用之前**，
    #   参数校验不过连空间都不用碰）。无 reason 的 force 等于"偷偷绕闸"，直接拒绝。
    if getattr(a, 'force', False) and not (getattr(a, 'reason', '') or '').strip():
        _reject(
            'force_requires_reason',
            '--force 必须配 --reason：绕过护栏的动作要写进审计，后人要能查到"当时为什么放行"',
            target='补上原因再重跑；不愿写原因说明这个绕行本身没想清楚',
            method=f'add --node {getattr(a, "node", "<ID>")} --force --reason "<为什么该投>"',
            human='  ❌ --force 必须配 --reason：绕过护栏的动作要写进审计，后人要能查到"当时为什么放行"',
        )
        return 2
    st = load_state()
    iid = st.get('inbox') or _find_inbox()[0]
    if not iid:
        _reject('inbox_missing', '收件箱未建，投递无处可去',
                target='先建收件箱（幂等，重复跑不会建第二个）',
                method='space_hub.py inbox',
                human='❌ 收件箱未建，先跑 janitor inbox')
        return 1
    nid = a.node
    # 校验节点存在 + 取标题
    info = _space('space.workspace.node-info', node_id=nid)
    node = ((info or {}).get('data') or {}).get('node') or {}
    title = node.get('title') or ''
    if not title:
        print(f'  ⚠️ 节点不存在或不可读（{nid}）——登记但标"待人工确认"')
        title = '（节点不可读）'
    # ★ S158 新增护栏：**不许把有内容的节点投进收件箱**。
    #   事故（S158 实测发现，G10）：`conductor backup` 把每天的备份夹建在了收件箱里；
    #   `janitor scan` 的空文件夹规则（folder 无子节点→垃圾）在第一轮把「1017_S125_三层联动首备」
    #   （77 个附件）判成垃圾 —— 因为它当时确实还没传完，是空夹。
    #   **扫描器看的是"此刻有没有子节点"，而一个正在写入的容器此刻一定是空的。**
    #   收件箱是"待删"的地方，进去的东西默认会被用户整批删掉；
    #   没有这道护栏，一次 scan 就能把备份连根拔了。
    #   判据取"有没有子节点 + 名字像不像备份"，宁可漏投也不误杀。
    if not getattr(a, 'force', False):
        _kids_now = _kids(nid)
        _name_hit = any(k in title for k in ('备份', 'backup', '归档', '快照', '库'))
        if _kids_now:
            _reject(
                'guard_nonempty_container',
                f'非空容器（{len(_kids_now)} 个子节点）不得进待删收件箱：收件箱会被整批删',
                target='先人工确认内容归属；确认整夹该删再加 --force 承担后果',
                method=f'add --node {nid} --force --reason "<为什么整夹该删>"',
                human=(f'  🛑 拒收：{title}（{nid}）**非空**（{len(_kids_now)} 个子节点）——'
                       f'收件箱是待删暂存，非空容器进去就有被整批删掉的风险\n'
                       f'     → 真要投递请先手动清空，或加 --force 明确承担后果'),
            )
            return 4
        if _name_hit:
            _reject(
                'guard_container_like_name',
                '空夹但名字含备份/库/归档类词：空不等于该删（可能正在写入，或内容在别处）',
                target='确认真的废弃再加 --force；只是位置不对则走 classify 归位（不删）',
                method=f'add --node {nid} --force --reason "<为什么该删>"  ｜  classify --dry-run',
                human=(f'  🛑 拒收：{title}（{nid}）空夹但名字像备份/库——**空不等于该删**'
                       f'（可能正在写入或内容在别处）\n'
                       f'     → 确认真的废弃再加 --force'),
            )
            return 4
    # ★ v2.7.2（闭环「回执≠回读」·2026-11-13 空间重置实战）：登记册命中 ≠ 节点真在收件箱。
    #   实锤过程：第一轮投递全败（收件箱夹被用户删掉，服务端 12607），失败项**也进了登记册**；
    #   重建收件箱后重投，49 项全部撞这条旧短路直接 return 0——回执「成功 32」，回读落地 0。
    #   修法：命中后回读收件箱一层核实；节点确在才算真幂等，否则清掉过期记录放行重投。
    if any(x['id'] == nid for x in st['items']):
        _landed = any((n.get('id') or n.get('nodeId')) == nid for n in _kids(iid))
        if _landed:
            print(f'ℹ️ 已在清单（回读核实：节点确在收件箱）：{title}'); return 0
        print(f'⚠️ 登记册过期（有记录但节点不在收件箱一层）——清掉过期记录，重新投递：{title}')
        st['items'] = [x for x in st['items'] if x['id'] != nid]
        save_state(st)
    # ★ 移动前记录原父节点（node-info.parentNodeId 不可信，用全树反查），
    #   供误投后 `janitor restore` 一键退回原位（v1.1.7）。
    origin = _find_parent(nid) or ''
    # 移动入收件箱（AI 能做的最后一步）
    mv = _space('space.workspace.move-node', node_id=nid, target_parent_id=iid)
    # ★ S200 补护栏（P067·L244）：收件箱夹为本次新建时，首投可能撞 12607
    #   permission denied（新建夹权限/索引传播延迟，非真权限问题——实测同参数
    #   几分钟后重试 7/7 全过）。对 12607 带间隔重试一次，再失败才如实登记。
    if mv and mv.get('error') and '12607' in str(mv.get('error')):
        time.sleep(5)
        mv = _space('space.workspace.move-node', node_id=nid, target_parent_id=iid)
    ok = bool(mv and not mv.get('error'))
    # ★ v2.7.2（闭环「回执≠回读」）：回执成功 ≠ 落地。cmd_move 早有 readback_mismatch
    #   先例，add 却一直只看回执。移动回执成功后再回读收件箱一层，确有该节点才算真落地；
    #   不符时按「未落地」登记（moved=False，rc=3），不当作成功——疑似索引延迟时
    #   等待复投即可，幂等核实（修①）保证重投不会重复登记。
    if ok:
        ok = any((n.get('id') or n.get('nodeId')) == nid for n in _kids(iid))
        if not ok:
            _reject(
                'readback_mismatch',
                f'移动回执成功，但收件箱一层未枚举到 {nid}（疑似索引延迟/未落地）',
                target='等待 1-2 分钟复核后重投；幂等核实已保证重投不重复登记',
                method=f'add --node {nid} --force --reason "复核后重投"',
                human=(f'⚠️ 移动回执成功，但收件箱下**未枚举到** {nid}'
                       f'——疑似索引延迟或未落地，**不当作成功**，请复核后重投'),
            )
    st['items'].append({
        'id': nid, 'title': title, 'kind': node.get('kind', ''),
        'reason': a.reason or '（未注明）',
        'moved': ok, 'added': time.strftime('%Y-%m-%d %H:%M'),
        'origin_parent': origin,
    })
    save_state(st)
    if getattr(a, 'force', False):
        _audit_force('add --force', f'{title}（{nid}）', a.reason)
    print(f'  {"✅ 已移入收件箱" if ok else "⚠️ 移动失败（清单仍登记）"}：{title}（{nid}）')
    if not ok and (mv or {}).get('error'):
        # v2.7.2 注：回执成功但回读不符的情形已在上面按 readback_mismatch 报过，
        # 这里只报「服务端明确拒绝」——两种失败混在一个文案里会把索引延迟误读成权限问题。
        _reject(
            'move_rejected',
            f'服务端拒绝移动：{str((mv or {}).get("error"))[:120] or "无响应"}',
            target='清单仍保留该行（"该删"这个事实为真）；查权限/节点状态后重试，或改用 move 指定父夹',
            method=f'move --node {nid} --to {iid}',
        )
    # **S156 修：返回码必须反映「移动」有没有真成，不能一律 0。**
    # 事故：旧版无论成败都 return 0 → `auto_file`(→True) → `core.file_to_janitor`(→True)
    # → 调用方以为投递成功。而清单里躺着的是 `moved=False` 的记录：
    # **清单显示 40 项，收件箱实际只有 18 个**，差的那 22 项从来没离开原地。
    # 登记保留是合理的（"该删"这个事实为真），但**返回值必须说真话**，
    # 否则调用方永远收不到失败信号，假账会一直长下去。
    return 0 if ok else 3


def cmd_scan(a):
    """★ 全局扫描：从空间超根递归，识别**所有垃圾**（废弃标记/空文件夹/重复节点）
    并**发现即自动投递**收件箱（除非 --dry-run 仅预览）。覆盖范围=整个空间。

    判定规则（多维，覆盖"所有的垃圾"，不止空文件夹）：
      1) 标题命中 KW 关键词 → 废弃类垃圾；
      2) 空文件夹（folder 无子节点）→ 冗余容器垃圾；
      3) 同父同名重复节点 → **默认仅告警不投**（防误删，留人工裁决）；
         加 `--dedup N` 可把「同名且 >N 份」的**多出来的副本**投递（保留最早一份）。
         这条是 S158 加的：根层级实测有 26 份同名「生态遗留趋势留档（跨设备）」，
         旧行为一直只告警不投 → 越积越多 → 用户看到的是一片乱。

    ★ S158：扫描起点改为 `ROOTS`（含空间真根）。旧版从探源司·总库子树起扫，
    **空间根层级那 60+ 个散落 doc 从来没被看见**，于是一直报「✅ 未发现垃圾」。
    排除：收件箱自身及其子树（已在箱/是箱，不扫不投）。
    """
    from collections import Counter
    st = load_state()
    inbox = st.get('inbox') or _find_inbox()[0]
    dry = bool(getattr(a, 'dry_run', False))
    dedup_n = int(getattr(a, 'dedup', 0) or 0)
    seen, hits, dup_groups = set(), [], {}
    nocontent = []      # ★ S179（M-R125）：0 子节点的夹——**不投递**，只登记待人工核对

    def walk(pid, depth=0):
        if pid in seen or depth > 12:
            return
        seen.add(pid)
        if inbox and pid == inbox:
            return  # 不进入收件箱子树
        kids = _kids(pid)
        cnt = Counter((k.get('title') or '').strip() for k in kids if k.get('title'))
        for n in kids:
            nid = n.get('id') or n.get('nodeId')
            kind = n.get('kind')
            t = (n.get('title') or '').strip()
            if not nid or (inbox and nid == inbox):
                continue
            # 重复检测（同父同名，>1）：组登记，仅告警不投
            if t and cnt.get(t, 0) > 1:
                dup_groups.setdefault((pid, t), []).append(nid)
            reason = None
            kw = next((k for k in KW if k in t), None)
            # ★ S179：标题同时含「废弃标记」与「结构性容器词」时，**不自动投递**。
            #   实测「📁 归档·废弃归档库」两边都命中（KW=废弃/弃，STRUCT=归档/库）。
            #   这类名字无法从标题判断意图（是把整个归档库废了？还是这个库里装着废弃件？），
            #   自动搬走一个"库"的代价远大于少投一条。改为登记候选、交人裁决。
            _struct = _struct_hits(t)
            if kw and _struct:
                nocontent.append({'id': nid, 'title': t, 'looks_like_keep': True,
                                  'verdict': f'标题双义（废弃标记「{kw}」+ 容器词「{_struct[0]}」）——须人工裁决'})
                if kind == 'folder':
                    walk(nid, depth + 1)
                continue
            if kw:
                reason = f'标题含废弃标记「{kw}」'
            elif kind == 'folder' and not _kids(nid):
                # ★ S179（M-R125）：空夹**不再自动投递**。
                #   原实现在这里 `reason = '空文件夹（无子节点）'` → 直接进 hits → 被 scan 搬走。
                #   判据错：附件不占目录树槽位，0 子节点与"有 81 个附件"并存（实测）。
                #   现改为只登记为候选、显式标注"AI 无法判定"，由 list 交给用户核对。
                _keepish = bool(_struct_hits(t)) or any(k in t for k in EMPTY_KEEP)
                _cand = {'id': nid, 'title': t, 'looks_like_keep': _keepish,
                         'verdict': 'AI 无法判定（附件不可见）'}
                if EMPTY_NEVER_AUTOPOST:
                    nocontent.append(_cand)
                else:
                    reason = '空文件夹（无子节点·仅此一项判据，可能误判）'
                    hits.append((nid, kind, t, reason))
            if reason:
                hits.append((nid, kind, t, reason))
            if kind == 'folder':
                walk(nid, depth + 1)

    for _r in ROOTS:
        walk(_r)
    # ★ S158（G2 根因）：**统一去重**。旧版只在单次 walk 的"同一父节点"内比同名，
    #   而"生态遗留趋势留档（跨设备）"这类堆积恰恰是**每轮都往同一个父节点新建一份**——
    #   同父同名确实能抓到（实测 ×23），但旧行为默认 `--dedup 0` = 只告警不投，
    #   于是检测到了却什么也不做，越积越多。这不是"检测不到"，是**检测到了不处理**。
    #   新口径：不传 --dedup 时自动取 DEFAULT_DEDUP（>该值的多余副本才投），
    #   传 0 才表示"只告警不动手"。
    if not dedup_n:
        dedup_n = DEFAULT_DEDUP
    print(f'═══ 全局扫描 {len(seen)} 个容器（起点={ROOTS}｜去重阈值 >{dedup_n} 份投递）═══')
    # ★ S179（M-R125）：先交代"有多少夹我看着是空的，但我不能据此说它是垃圾"。
    #   这一段的用词必须守住三态：**不出现"空夹/可删"**，只说"从接口看不到内容"。
    if nocontent:
        _keepn = sum(1 for c in nocontent if c['looks_like_keep'])
        print(f'\n  ℹ️ {len(nocontent)} 个文件夹从接口看不到子节点——**不等于空**，本工具不投递它们：')
        for c in nocontent[:10]:
            hint = '（名字像结构性容器）' if c['looks_like_keep'] else ''
            print(f'     {c["id"]}  {c["title"]}{hint}  → {c["verdict"]}')
        if len(nocontent) > 10:
            # ★ S179：原来只写"另有 N 个，详见清单"——但清单(`list`)里并没有这一段，
            #   用户根本找不到。宁可多打几行，也别让"详见"指向不存在的地方。
            #   ★ 且必须与上面 10 条**同格式**（含 hint）——首版漏了 hint，
            #   于是同名的 4 个备份夹看起来"没被识别为结构性容器"，白白多查一轮。
            print(f'     …其余 {len(nocontent) - 10} 个：')
            for c in nocontent[10:]:
                hint = '（名字像结构性容器）' if c['looks_like_keep'] else ''
                print(f'     {c["id"]}  {c["title"]}{hint}  → {c["verdict"]}')
        print(f'     为什么不能判空：附件不占目录树槽位，`list-nodes` 恒返回 0（M-R125）。'
              f'要核实请到客户端看附件列表。')
    if not hits and not dup_groups:
        print('  ✅ 未发现新的垃圾节点' + ('（但上面那些夹需人工核对）' if nocontent else ''))
        return 0
    auto = 0
    for nid, kind, t, reason in hits:
        tag = '（预览·未移动）' if dry else ''
        print(f'  [{kind:8s}] {nid}  {t}')
        print(f'        └ 理由：{reason} {tag}')
        if not dry:
            rc = cmd_add(argparse.Namespace(node=nid, reason=reason, force=False))
            auto += 1 if rc == 0 else 0
    print(f'\n  命中待投递：{len(hits)} 项'
          + ('（仅预览，未移动）' if dry else f'（已自动投递 {auto} 项，其余为已在清单跳过）'))
    if dup_groups:
        # S158：把超过 dedup_n 份的同名节点的**多余副本**投递（保留最早一份）。
        # 「最早」按 title 相同组内 nodes 返回顺序（服务端按 created 排序）取第一个。
        # 注意 cmd_add 的护栏会二次把关：非空容器与"像备份"的名字一律拒收（返回 4），
        # 所以即使误入去重名单也不会被真的搬走——**两道闸，不靠单点判断**。
        _dup_dropped, _dup_blocked = 0, 0
        print(f'\n  ⚠️ 发现 {len(dup_groups)} 组重复节点（同目录同名）：')
        for (pid, t), ids in dup_groups.items():
            if len(ids) > dedup_n:
                keep, drop = ids[0], ids[1:]
                # ★ S179：先按**同一判据**预筛，别把注定被护栏拒收的项也说成"投递"。
                #   实测「20261020_生态备份」×13 属同父同名，原逻辑直接打印"投递 12 份副本"，
                #   而 cmd_add 的护栏会把这 12 个全拒（名字像备份）——于是屏幕上写着投递 12，
                #   清单里一条没有。这不是护栏没生效，是**输出在替事实撒谎**（M-R117）。
                _pre = [d for d in drop if not any(k in t for k in STRUCT_KEEP)]
                _hold = len(drop) - len(_pre)
                print(f'    · 目录 {pid} 下「{t}」×{len(ids)} → 保留 {keep}，'
                      f'可投递 {len(_pre)} 份副本'
                      + (f'，{_hold} 份因名字属结构性容器**不动**' if _hold else '')
                      + ('（预览，未移动）' if dry else ''))
                if not dry:
                    for d in drop:
                        if d not in _pre:
                            _dup_blocked += 1
                            continue
                        rc = cmd_add(argparse.Namespace(
                            node=d, force=False,
                            reason=f'同目录同名重复（{t}）第 {ids.index(d)+1}/{len(ids)} 份'))
                        if rc == 0:
                            _dup_dropped += 1
                        else:
                            _dup_blocked += 1      # 二道闸拦下，也要计数（不藏）
            else:
                print(f'    · 目录 {pid} 下「{t}」×{len(ids)}：保留（≤{dedup_n} 份视为正常留档）')
        print(f'  重复副本：实际投递 {_dup_dropped} 份'
              + (f'，被护栏/结构性容器拦下 {_dup_blocked} 份（**未移动**）' if _dup_blocked else '')
              + ('（预览）' if dry else ''))
    return 0


def _prune_stale(items, inbox, check=True):
    """★ S158 修（清单陈旧项）：剔除「清单里还挂着，但早已不在收件箱」的项。

    **事故**：`T7Bd0ukQ4dnnTAYMy2ktLq` / `xEiZLGulVg80N1jKfamb7B` 两个备份夹
    在 G10 修复时被 `restore` 迁回了「🗄 生态备份区」，parentId 已确认是备份区；
    但清单项没被移除，于是 `list` 仍然把它们列成"待删"。
    用户照单去收件箱找，**找不到**；更糟的是它造成"备份区的东西被列入待删"的错觉。

    **根因**：state 是"我以为它在该删箱里"，服务端才是"它实际在哪"。
    清单若只信 state，就永远不知道自己过期了。这正是 G9「死坐标」的同一个病。

    判据：逐项查服务端 parentId；**不是收件箱 → 从清单移除并报告**。
    查不到（网络/节点已删）→ **保留**并标"无法确认"，不擅自删项（误删清单比留脏更危险）。
    """
    if not check or not items:
        return items, []
    keep, stale, unknown = [], [], 0
    for x in items:
        ok, pid, why = _parent_of(x['id'])
        if not ok:
            x['_verify'] = f'无法确认位置（{why}）'
            keep.append(x); unknown += 1
        elif pid == inbox:
            keep.append(x)
        else:
            stale.append((x, pid))
    return keep, stale


def _parent_of(node_id):
    """查服务端真实父节点。返回 (ok, parentId, why)。**失败不折成"不在"。**"""
    import subprocess as _sp
    try:
        r = _sp.run([sys.executable, f'{LIB}/space_api.py',
                     'space.workspace.node-info', '--node-id', node_id],
                    capture_output=True, text=True, timeout=60)
    except Exception as e:
        return False, None, type(e).__name__
    for ln in (r.stdout or '').splitlines():
        ln = ln.strip()
        if ln.startswith('{'):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            node = (d.get('data') or {}).get('node') or {}
            if node:
                return True, node.get('parentId'), ''
            return False, None, str(d.get('error') or 'node 为空')[:40]
    return False, None, '未返回 JSON'


def _probe_empty_databases(items, control_id=None):
    """对清单里的 database 项逐个直连核实：真的空，还是只是读不到。

    返回 {'lines': [头部说明行], 'by_id': {id: 每项结论短语}}

    ★ 判据来自 `db_query.py --ask csv`：它返回的 `content` 是 CSV 文本，
      首行永远是表头。**非空行数 == 1 表示 0 条记录**，>1 表示有数据。
    ★ 对照组（`control_id`=账房总账，已知有数据）必须先读出 >1 行，
      否则说明"这条通路读不到数据"，此时所有「空」都不可采信 → 一律标「无法判定」。
      没有对照的"全部为空"是假绿：读失败和真空长得一模一样。
    ★ 任何一项读失败 → 标「无法判定」，**不折叠成"空"**（M-R60）。
    """
    dbs = [x for x in items if (x.get('kind') == 'database')]
    out = {'lines': [], 'by_id': {}}
    if not dbs:
        return out
    # ★ v0.8.4：对照组不再硬编码（旧 id `Xjqn2Wf5…` 随空间重建失效，实测 permission denied）。
    #   解析顺序：显式入参 → 环境变量 SPACE_HUB_CONTROL_DB → state.control_db → 无对照。
    #   无有效对照组时**绝不把"读不到"当"空库"**（M-R60），全项如实标无法判定。
    if not control_id:
        control_id = (os.environ.get('SPACE_HUB_CONTROL_DB') or '').strip() \
            or (load_state().get('control_db') or '').strip()
    def _rows(did):
        j, raw = _db_query(did, 'csv')
        c = j.get('content')
        if not isinstance(c, str):
            return None, f'读库失败（db_query --ask csv 无 content）：{raw[:80]}'
        return len([x for x in c.split('\n') if x.strip()]), ''

    if not control_id:
        ctl, ctl_err = None, ''
        out['lines'] = ['> ⚠️ **未配置对照组数据库**：显式传 control_id 或设 '
                        '`SPACE_HUB_CONTROL_DB`（一个已知有数据的库 id）后才可核实。'
                        '无对照的"全为空"不可采信（读失败与真空长得一样）——'
                        '下方各库一律标「无法判定」，删库前请手工确认。']
        trusted = False
    else:
        ctl, ctl_err = _rows(control_id)
        trusted = bool(ctl and ctl > 1)
        if trusted:
            out['lines'] = [f'> **数据库类 {len(dbs)} 项已逐个直连核实**（对照组 `{control_id[:10]}…` 读出 '
                            f'{ctl - 1} 条记录，证明该通路能读到数据，不是"读不到一律算空"）。'
                            f'删库**不可逆**，故单列依据。']
        elif ctl is None:
            out['lines'] = [f'> ⚠️ **数据库核实不可信**：对照组 `{control_id[:10]}…` 读取失败'
                            f'（{ctl_err or "通路异常"}）——下方各库的"空"**不能作为删除依据**，请手工确认。']
        else:
            out['lines'] = [f'> ⚠️ **数据库核实不可信**：对照组只读出 {ctl} 行（应为 >1，'
                            f'该库可能已清空或 id 已失效）——下方各库的"空"**不能作为删除依据**，请手工确认。']

    empty_n = unk_n = data_n = 0
    for x in dbs:
        n, err = _rows(x['id'])
        if n is None:
            out['by_id'][x['id']] = f'（⚠️ 无法判定：{err}）'
            unk_n += 1
        elif n <= 1:
            if trusted:
                out['by_id'][x['id']] = '（✅ 已核实：仅表头，0 条记录）'
                empty_n += 1
            else:
                _why = '未配置对照组，无对照的"空"不可采信' if not control_id else '对照组未证明通路可用'
                out['by_id'][x['id']] = f'（⚠️ 读到 0 条，但{_why}，**无法判定**）'
                unk_n += 1
        else:
            out['by_id'][x['id']] = f'（🔴 **有 {n - 1} 条记录**，不是空的，删前务必确认）'
            data_n += 1

    if trusted:
        out['lines'].append(f'> 核实结果：确认空 **{empty_n}** ｜ 仍有数据 **{data_n}** ｜ '
                            f'无法判定 **{unk_n}**')
    else:
        out['lines'].append(f'> 核实结果（不可信）：读到空 {empty_n} ｜ 有数据 {data_n} ｜ '
                            f'无法判定 {unk_n}')
    if data_n:
        out['lines'].append('> 🔴 **有数据库不为空**，它们不该按"废弃"直接删——见下表红标。')
    return out


def cmd_list(a):
    st = load_state()
    items = st.get('items') or []
    inbox = st.get('inbox')
    # ★ S158：先剔除陈旧项（清单挂着、人早已不在收件箱），再出单
    items, stale = _prune_stale(items, inbox, check=not getattr(a, 'no_verify', False))
    if stale:
        print(f'🧹 剔除 {len(stale)} 项陈旧清单项（已不在收件箱，清单过期）：')
        for x, pid in stale:
            print(f'   · {x["title"][:36]}（现父节点 {pid}）')
        st['items'] = [x for x in (st.get('items') or [])
                       if x['id'] not in {s[0]['id'] for s in stale}]
        st['pruned'] = st.get('pruned', []) + [
            {'id': x['id'], 'title': x['title'], 'reason': '移出收件箱后清单未同步',
             'actual_parent': pid, 'at': time.strftime('%Y-%m-%d %H:%M')}
            for x, pid in stale]
        save_state(st)
    lines = ['# 🗑 待删清单（清道夫 · 需人工删除）', '',
             f'> 生成时间：{time.strftime("%Y-%m-%d %H:%M")} ｜ 共 **{len(items)}** 项',
             '> 云端无删除 API —— 请**打开收件箱文件夹**，按下表逐项删除即可。', '']
    # ★ S158 三补：数据库类必须当场核实「是否真的空」。
    #   删库不可逆，而清单原先只给「标题含废弃标记」——名字里有"废弃"不等于里面没数据。
    #   更要命的是：上一轮我把核实结论**手写补进 md**，下一轮 `list` 重跑就整段冲掉了，
    #   等于没修。核实必须长在生成流程里，不能贴在产物上。
    db_probe = _probe_empty_databases(items)
    if db_probe['lines']:
        lines += db_probe['lines'] + ['']
    lines += ['| # | 标题 | 类型 | 节点ID | 原因 | 已移入收件箱 |',
              '|---|---|---|---|---|---|']
    for i, x in enumerate(items, 1):
        mv = '✅' if x.get('moved') else '⚠️ 未移动'
        reason = x.get('reason', '')
        _pb = db_probe['by_id'].get(x['id'])
        if _pb:
            reason = f'{reason} {_pb}'
        lines.append(f"| {i} | {x['title']} | {x.get('kind','')} | `{x['id']}` | "
                     f"{reason} | {mv} |")
    md = '\n'.join(lines) + '\n'
    # 规则51 命名合规：类别标签 + MMDD 日期段 + 描述（避免 watchdog M08 判遗留）
    _mmdd = time.strftime('%m%d')
    base = f'待删清单_{_mmdd}'
    p_md = os.path.join(OUT_DIR, base + '.md')
    open(p_md, 'w', encoding='utf-8').write(md)
    # CSV
    import csv
    p_csv = os.path.join(OUT_DIR, base + '.csv')
    with open(p_csv, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['序号', '标题', '类型', '节点ID', '原因', '已移入收件箱'])
        for i, x in enumerate(items, 1):
            w.writerow([i, x['title'], x.get('kind', ''), x['id'],
                        x.get('reason', ''), '是' if x.get('moved') else '否'])
    print(f'📄 待删清单已落盘：{p_md}')
    print(f'📄 CSV：{p_csv}')
    # **S156 修：摘要不许只报总数。**
    # 「共 40 项」这句话害人不浅——它把「已真的移进收件箱」和「登记了但没移动」
    # 混成一个数字，于是 40 项里只有 18 个真在收件箱这件事，谁也看不出来。
    # **清单条数 ≠ 收件箱条数**，两者必须分开报，否则待删清单会变成自我安慰的假账。
    _moved = sum(1 for x in items if x.get('moved'))
    _not = len(items) - _moved
    print(f'   共 {len(items)} 项 ｜ 已移入收件箱 {_moved} ｜ ⚠️ 未移动 {_not}')
    if _not:
        print(f'   （未移动项 = 登记了但没挪进收件箱，见清单末列「⚠️ 未移动」）')
    # ★ 本地欠账（v2.1.0）：本地残留与云端收件箱分开出单——云端项有陈旧剔除
    #   （不在收件箱即剔），本地路径混进去必被误剔，所以单独成节、不受那道闸管。
    pend = st.get('local_pending') or []
    if pend:
        lines += ['', '## 本地欠账（文件系统残留，直接 rm；处置后 `local-rm` 销账）', '',
                  '| # | 路径 | 原因 | 登记 |', '|---|---|---|---|']
        for i, x in enumerate(pend, 1):
            lines.append(f"| {i} | `{x.get('path', '')}` | {x.get('reason', '')} | {x.get('added', '')} |")
        md = '\n'.join(lines) + '\n'
        open(p_md, 'w', encoding='utf-8').write(md)
        print(f'   📒 另有本地欠账 {len(pend)} 条（清单已追加「本地欠账」节）')
    return 0


def cmd_census(a):
    """★ S158 大生态/小生态分层普查：回答「这块归谁管」，而不只是「这块是不是垃圾」。

    **为什么需要它**：`scan` 用的是关键词判定（废弃/测试/重复…），它回答的是
    「这个节点像不像垃圾」；但用户真正反复问的是「**图中这个归谁管**」——
    归属这件事，关键词永远答不上来。于是每次都要人临场翻 SKILL.md、翻坐标表，
    翻完就散，下一轮再翻一遍。本命令把「归属」变成一次扫描即可回答的问题。

    判定法（与 `references/eco_layers.md` 的三层一缝严格对齐）：
      · 从上往下走，一旦进入 `TERRITORY` 登记的容器，**整棵子树**计为该技能的责任田（L1）；
      · 走完整棵树仍没进任何责任田的节点 → 「缝」（L0 无主区）；
      · 缝按 **顶层分区** 聚合，因为「治理单位」就是分区，不是单个节点——
        一个 232 节点的裸文件夹，逐个列出来没人看得懂，必须先给出"哪个区没人管"。

    输出：控制台分区表 + JSON 明细（--json）。
    """
    from collections import Counter
    st = load_state()
    inbox = st.get('inbox') or _find_inbox()[0]
    rows, seen = [], set()
    # ★ S158 修：归属从**合并真源**取，不再只用 TERRITORY（否则 zone_registry 是死表）
    _territory, _tprob, _pref_rules = load_territory()


    def _by_prefix(title):
        """根层级散落组：按标题前缀判定归属（容器型挂法挂不住这类节点）。"""
        for _p, _o, _n in _pref_rules:
            if title.startswith(_p):
                return _o, _n
        return None
    for _pb in _tprob:
        print(f'   ⚠️ 归属真源不完整：{_pb}')

    def walk(pid, path, owner, note, depth=0):
        if pid in seen or depth > 12:
            return
        seen.add(pid)
        if inbox and pid == inbox and depth > 0:
            return  # 收件箱子树不普查（它本身就是待删暂存）
        kids = _kids(pid)
        if not kids and depth > 0:
            return
        cnt = Counter((k.get('title') or '').strip() for k in kids if k.get('title'))
        for n in kids:
            nid = n.get('id') or n.get('nodeId')
            if not nid or nid == inbox:
                continue
            t = (n.get('title') or '').strip()
            k = n.get('kind') or ''
            # 进入登记容器 → 整棵子树归该技能
            cur_owner, cur_note = owner, note
            if nid in _territory:
                cur_owner, cur_note = _territory[nid]
            elif cur_owner is None:
                # ★ S158：根层级散落组（同名文档堆）不会进容器，只能靠前缀认领
                _hit = _by_prefix(t)
                if _hit:
                    cur_owner, cur_note = _hit
            rows.append({
                'id': nid, 'title': t, 'kind': k,
                'path': '/'.join(path + [t]),
                'depth': depth, 'owner': cur_owner, 'owner_note': cur_note,
                # ★ S158：原先写 `nid in TERRITORY`，registry 指派的区会一律 False
                #   → JSON 明细对外断言"这里不是归属入口"，与 owner 字段自相矛盾。
                'entered_here': cur_owner is not None and (nid in _territory),
                'dup_in_parent': cnt.get(t, 0),
                'updatedAt': n.get('updatedAt'),
            })
            if k == 'folder':
                walk(nid, path + [t], cur_owner, cur_note, depth + 1)

    walk('', [], None, None)

    if not rows:
        print('❌ 普查结果为空——**无法判定**（不是"空间是空的"，M-R60）：'
              'list-nodes 全部失败，请先查 library 授权/网络')
        return 2

    gaps = [r for r in rows if not r['owner']]
    owned = [r for r in rows if r['owner']]
    # 缝按顶层分区聚合
    zone_cnt = Counter()
    for r in gaps:
        zone_cnt[r['path'].split('/')[0]] += 1

    print(f'═══ 大生态分层普查（L0 全空间）═══')
    print(f'节点合计 {len(rows)} ｜ L1 责任田内 {len(owned)} ｜ '
          f'缝（无主）{len(gaps)}（{100*len(gaps)//max(1,len(rows))}%）')
    print(f'按类型：{dict(Counter(r["kind"] for r in rows))}')
    print()
    print('── 缝（L0 无主区）按顶层分区 ──')
    print(f'{"节点数":>6}  顶层分区')
    for z, c in zone_cnt.most_common():
        print(f'{c:6d}  {z[:56]}')
    print()
    print('── 责任田覆盖 ──')
    oc = Counter(r['owner'] for r in owned)
    for s, c in oc.most_common():
        print(f'{c:6d}  {s}')
    print()
    # 缝里最扎眼的两类：重复堆积 + 根层级散落
    root_gap = [r for r in gaps if r['depth'] == 0]
    if root_gap:
        print(f'── 根层级无主节点 {len(root_gap)} 个（这就是"资料库看起来很乱"的直接来源）──')
        for r in sorted(root_gap, key=lambda x: (x['kind'], x['title'])):
            d = f' ×{r["dup_in_parent"]}' if r['dup_in_parent'] > 1 else ''
            print(f'  [{r["kind"]:8s}] {r["title"][:50]}{d}')
        print()
    dup = [r for r in rows if r['dup_in_parent'] > 1]
    if dup:
        print(f'── 同父同名重复 {len(dup)} 个节点 / '
              f'{len(set((r["path"].rsplit("/",1)[0], r["title"]) for r in dup))} 组 ≥2 份 ──')
        for (pz, t), c in Counter((r['path'].rsplit('/', 1)[0], r['title']) for r in dup).most_common(12):
            print(f'  ×{c:3d}  {t[:46]:48s} @ {pz.split("/")[0][:28]}')
        print()
    if getattr(a, 'json', False):
        p = os.path.join(OUT_DIR, '库务普查.json')
        json.dump({'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                   'total': len(rows), 'owned': len(owned), 'gaps': len(gaps),
                   'rows': rows}, open(p, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f'📄 明细已落盘：{p}')
    return 0


def _node_parent(nid):
    """反查节点的真实父节点 id。

    ★ 2026-11-12 修（工程G 实测踩到）：原实现只走全树遍历 `_find_parent`，
      对 `kind=database` 的节点**恒返回空串**——因为数据库节点挂在 space 下，
      不进 root 的子节点枚举链。而调用方把空串当"不在收件箱"，于是
      「add 报成功 → 回读说不在箱」自相矛盾（本次两个测试库就是这样对不上的）。
      注意 docstring 里"不可信"的是 `parentNodeId`（恒 None），不是 `parentId`；
      `parentId` 实测准。故改为：**node-info 的 parentId 优先，遍历兜底**。
    返回 '' 表示查不到（调用方必须显式报，不许当"根"）。"""
    try:
        info = _space('space.workspace.node-info', node_id=nid)
        pid = (((info or {}).get('data') or {}).get('node') or {}).get('parentId')
        if pid:
            return pid
    except Exception:
        pass
    try:
        return _find_parent(nid, skip_inbox=False) or ''
    except Exception:
        return ''


def cmd_move(a):
    """★ 节点移动（v1.2.0）：把任意节点挪到指定父节点下。

    为什么归清道夫：本技能已是全生态**唯一**常驻持有 space.move-node 的地方
    （add/restore 两条路径都靠它）。此前「节点移动改名」提案长期挂着，
    真实原因是**没有统一入口**——各处零散调用 move-node，没人做「移前校验存在 +
    移后回读确认」。本命令把这两条做成硬门。

    三态（M-R60）：
      移前：节点不存在 / 目标父不存在 → 直接拒，不动；
      移中：move-node 返回 error / status=pending（跨空间异步）→ 如实报，不假装成功；
      移后：**回读**（再查一次 node-info 的 parentId + 遍历确认目标下确有该节点），
            回读不符 → 退出码 3，明说"服务端说成功但位置不符，疑似索引延迟，请复核"。
    """
    nid = a.node
    target = a.to
    info = _space('space.workspace.node-info', node_id=nid)
    node = ((info or {}).get('data') or {}).get('node') or {}
    title = node.get('title') or ''
    if not title:
        _reject('node_unreadable', f'节点不存在或不可读（{nid}）',
                target='先确认节点 id 与当前空间归属（换空间后 id 会失效）',
                method='census --json  ｜  init --list',
                human=f'❌ 节点不存在或不可读（{nid}）——不移动（M-R60 如实报）')
        return 1
    tinfo = _space('space.workspace.node-info', node_id=target) if target else None
    tnode = ((tinfo or {}).get('data') or {}).get('node') or {}
    if not tnode.get('id') and not tnode.get('title'):
        _reject('target_missing', f'目标父节点不存在（{target}）',
                target='先枚举目标父夹确认 id；不要用标题猜 id',
                method='census --json',
                human=f'❌ 目标父节点不存在（{target}）——不移动')
        return 1
    if tnode.get('kind') and tnode.get('kind') != 'folder':
        _reject('target_not_folder', f'目标不是文件夹（{target} kind={tnode.get("kind")}）',
                target='换成目标节点的**父文件夹** id 再移',
                method=f'move --node {nid} --to <父文件夹ID>',
                human=f'❌ 目标不是文件夹（{target} kind={tnode.get("kind")}）——不移动')
        return 1
    src = _node_parent(nid)
    mv = _space('space.workspace.move-node', node_id=nid, target_parent_id=target)
    if not mv or mv.get('error'):
        _reject('move_rejected',
                f'服务端拒绝移动：{str((mv or {}).get("error"))[:160] or "无响应"}',
                target='查目标夹权限与节点状态；同名/跨空间限制也会走到这里',
                method=f'move --node {nid} --to {target}',
                human=f'❌ 移动失败：{str((mv or {}).get("error"))[:160] or "无响应"}')
        return 1
    data = mv.get('data') or {}
    st = data.get('status') or ''
    if st == 'pending':
        tid = data.get('taskId') or ''
        print(f'⏳ 跨空间移动已受理，异步进行中（taskId {tid}）——'
              f'**尚未落地**，请用 move-node-progress 跟踪后再确认')
        return 3
    # 移后回读：目标下确有该节点
    landed = any((n.get('id') or n.get('nodeId')) == nid for n in _kids(target))
    if not landed:
        _reject('readback_mismatch',
                f'服务端回报成功，但目标文件夹 {target} 下未枚举到 {nid}',
                target='疑似索引延迟：等 1-2 分钟再用 census/node-info 复核；仍不符按"未落地"处理',
                method=f'census --json  ｜  move --node {nid} --to {target}  # 复核后重试',
                human=(f'⚠️ 服务端回报成功，但目标文件夹 {target} 下**未枚举到** {nid}'
                       f'——疑似索引延迟或移动未落地，请复核（不当作成功）'))
        return 3
    print(f'✅ 已移动：{title}（{nid}）\n   从 {src or "（未知，全树未反查到）"} → {target}')
    return 0


def cmd_rename(a):
    """★ 节点改名（v1.2.0）：移后回读标题，改不动不许说改好了。"""
    nid = a.node
    new = (a.title or '').strip()
    if not new:
        _reject('empty_title', '新标题不能为空',
                target='给出非空标题；只是想去掉空格不算改名',
                method=f'rename --node {nid} --title "<新标题>"',
                human='❌ 新标题不能为空')
        return 1
    info = _space('space.workspace.node-info', node_id=nid)
    node = ((info or {}).get('data') or {}).get('node') or {}
    old = node.get('title') or ''
    if not old:
        _reject('node_unreadable', f'节点不存在或不可读（{nid}）',
                target='先确认节点 id 与当前空间归属',
                method='census --json',
                human=f'❌ 节点不存在或不可读（{nid}）——不改名')
        return 1
    r = _space('space.workspace.rename-node', node_id=nid, title=new)
    if not r or r.get('error'):
        _reject('rename_rejected',
                f'服务端拒绝改名：{str((r or {}).get("error"))[:160] or "无响应"}',
                target='查重名/权限限制；同名节点改名可能被拒',
                method=f'rename --node {nid} --title "{new}"',
                human=f'❌ 改名失败：{str((r or {}).get("error"))[:160] or "无响应"}')
        return 1
    back = _space('space.workspace.node-info', node_id=nid)
    now = (((back or {}).get('data') or {}).get('node') or {}).get('title') or ''
    if now != new:
        _reject('readback_mismatch',
                f'服务端未报错，但回读标题仍是「{now}」（期望「{new}」）',
                target='不当作成功：稍后回读复核，仍不符就重跑一次或人工确认',
                method=f'rename --node {nid} --title "{new}"',
                human=(f'⚠️ 服务端未报错，但回读标题仍是「{now}」（期望「{new}」）'
                       f'——不当作成功，请复核'))
        return 3
    print(f'✅ 已改名：{old} → {now}（{nid}）')
    return 0


def cmd_restore(a):
    """★ 误投回退（v1.1.7）：把节点从收件箱移回原位，并从清单移除。

    原位 = add 时记录的 origin_parent（全树反查所得，不依赖 node-info）。
    旧版清单项（v1.1.6 前投递）无 origin_parent 记录 → 需 --target 手动指定回退目标。
    """
    st = load_state()
    nid = a.node
    item = next((x for x in st['items'] if x['id'] == nid), None)
    if not item:
        print(f'  ⚠️ 节点不在待删清单：{nid}'); return 1
    target = (getattr(a, 'target', None) or '').strip() or item.get('origin_parent') or ''
    if not target:
        print(f'  ⚠️ 无原位记录（该项为旧版投递，未存 origin_parent）。')
        print(f'     请指定回退目标：janitor restore --node {nid} --target <父节点ID>')
        return 1
    mv = _space('space.workspace.move-node', node_id=nid, target_parent_id=target)
    ok = bool(mv and not mv.get('error'))
    if ok:
        st['items'] = [x for x in st['items'] if x['id'] != nid]
        save_state(st)
        print(f'  ✅ 已移回原位 {target}：{item.get("title")}（{nid}）')
    else:
        print(f'  ❌ 移回失败：{str(mv.get("error"))[:160] if mv else "无响应"}')
    # 返回值必须说真话（S156 教训）
    return 0 if ok else 3


def auto_file(node_id, reason, quiet=False):
    """★ 生态联动便捷入口（供其他技能 import 调用）：
    把单个节点移入收件箱并登记清单。**永不抛异常**——清理是"尽力而为"的旁路，
    绝不因投递失败而阻断上游主流程（但失败会显式打印告警，不静默）。

    用法（其他技能里）：
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 自身目录（旧 tvbox-janitor 已更名）
        import janitor; janitor.auto_file(nid, '建库失败残留')
    """
    try:
        iid = load_state().get('inbox') or _find_inbox()[0]
        if not iid:
            # 收件箱未建 → 尝试建
            if not _try_inbox() and not quiet:
                print(f'  ⚠️ 清道夫收件箱不可用，节点 {node_id} 未投递（请人工删）')
            iid = load_state().get('inbox') or _find_inbox()[0]
        if not iid:
            return False
        return _try_add(node_id, reason, quiet)
    except Exception as e:
        if not quiet:
            print(f'  ⚠️ 清道夫投递异常（{type(e).__name__}）：节点 {node_id} 未入收件箱，请人工删')
        return False


def _try_inbox():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest='cmd'); sub.add_parser('inbox')
    return cmd_inbox(ap.parse_args(['inbox'])) == 0


def _try_add(node_id, reason, quiet):
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest='cmd')
    ad = sub.add_parser('add'); ad.add_argument('--node', required=True)
    ad.add_argument('--reason', default=''); ad.add_argument('--force', action='store_true')
    a = ap.parse_args(['add', '--node', node_id, '--reason', reason or '（未注明）'])
    return cmd_add(a) == 0


def auto_file_local(path, reason, quiet=False):
    """★ 生态联动便捷入口·本地欠账（2026-11-12 v2.1.0 新增）：

    把「本地文件系统里删不决的残留」登记进**本地欠账清单**（state 的
    local_pending 列表）——**不碰云端、不移动节点、不需要收件箱存在**。

    为什么必须有它（实证）：learn-hub 曾把本地残留路径投进 `auto_file`（云端通道），
    被 S156 node_id 护栏拒收 → 门面名义联动，投递从未成功。而清道夫的设计哲学
    本来就是「云端节点走收件箱，**本地文件 AI 自己能删**」——本地残留缺的只是
    一个「删不决时有人记账」的去处。本入口补上这一块：
      · 上游技能一行调用：`space_hub.auto_file_local(residue_path, 'intake 半成品，需人工确认后删')`
      · 记账不删账：只有用户跑 `local-rm --path <前缀>` 确认处置后才销账；
      · `list` 出单时本地欠账单独成节，与云端收件箱项不混（云端项有陈旧剔除逻辑，
        本地路径过不了那道校验，混在一起会被误剔）。

    永不抛异常（旁路铁律）；写账走 save_state 的写后回读闸。
    """
    try:
        p = str(path or '').strip()
        if not p:
            if not quiet:
                print('  ⚠️ 本地欠账登记被拒：path 为空')
            return False
        st = load_state()
        pend = st.setdefault('local_pending', [])
        if any(x.get('path') == p for x in pend):
            if not quiet:
                print(f'  ℹ️ 本地欠账已在册：{p}')
            return True
        pend.append({'path': p, 'reason': reason or '（未注明）',
                     'added': time.strftime('%Y-%m-%d %H:%M')})
        save_state(st)
        if not quiet:
            print(f'  📒 本地欠账已登记：{p}（{reason}）——`list` 出单可见，`local-rm` 处置后销账')
        return True
    except Exception as e:
        if not quiet:
            print(f'  ⚠️ 本地欠账登记失败（{type(e).__name__}）：{path} 未记账，请人工处理')
        return False


# 云端 node id 形态：16–32 位 base62（实测如 tBlgSL4SPEFMrsyTBTg03c = 22 位）
_NODE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{16,32}$')


def file_to_janitor(node_id, reason='', quiet=True):
    """★ 生态投递门面（v2.3.0 起由本技能自持；原 tvbox-core 中转壳已删除）。

    任何技能一行调用（投递是旁路，永不阻断主流程）：
        from space_hub import file_to_janitor
        file_to_janitor(nid, '建库失败残留节点')

    **为什么门面住这里**（v0.8.4 架构重规划）：投递目标就是本技能的收件箱/欠账清单，
    门面与收件箱同一文件——改名/换目录一起走，从结构上消灭「改名断链」这类事故
    （2026-11-12 实查：清道夫改名 space-hub 后 core 中转壳仍写死旧名，import 必失败，
    投递恒 False 且静默）。

    **入参分流**（S156 护栏保留）：
      · 真云端 node_id（16–32 位 base62）→ auto_file，移入「🗑 待删收件箱」
      · 本地路径（/ 或 ~ 开头，或绝对路径）→ auto_file_local，登记本地欠账
      · 其他（描述文字、数据库记录）→ **拒收并显式告警**，绝不记假账
        （事故：blk.py 曾传 '源总库·整域拉黑孤儿 host=x' → 清单虚高 40 项、收件箱只有 18 个）
    """
    nid = str(node_id or '').strip()
    if not nid:
        print('  ❌ 投递被拒：入参为空')
        return False
    if nid.startswith(('/')) or nid.startswith('~'):
        return bool(auto_file_local(nid, reason, quiet=quiet))
    if not _NODE_ID_RE.match(nid):
        # 不是 node id 就别记假账——记了只会让清单虚高、掩盖"没投递"这件事实。
        # quiet 也拦不住：**参数错了是调用方的 bug，必须先让人看见**。
        print(f'  ❌ 投递被拒：入参不是云端 node_id 也不是本地路径 → {nid[:70]!r}')
        print('     （node_id 形如 tBlgSL4SPEFMrsyTBTg03c；数据库记录/描述文字请走数据库删除或登记欠账）')
        return False
    return bool(auto_file(nid, reason, quiet=quiet))


def cmd_local_rm(a):
    """销账：本地残留已人工处置，从欠账清单移除（前缀匹配，--all 全清）。"""
    st = load_state()
    pend = st.get('local_pending') or []
    if not pend:
        print('ℹ️ 本地欠账清单为空，无账可销'); return 0
    if getattr(a, 'all', False):
        n = len(pend)
        st['local_pending'] = []
        save_state(st)
        print(f'✅ 已销账 {n} 条本地欠账（--all）'); return 0
    pfx = (a.path or '').strip()
    hit = [x for x in pend if x.get('path', '').startswith(pfx)] if pfx else []
    if not hit:
        print(f'🛑 未命中任何欠账条目（前缀 {pfx!r}）——不销不存在的账'); return 2
    st['local_pending'] = [x for x in pend if not x.get('path', '').startswith(pfx)]
    save_state(st)
    for x in hit:
        print(f'  ✅ 销账：{x["path"]}（{x.get("reason", "")}）')
    print(f'共销 {len(hit)} 条'); return 0


# ══ 产物纪律（B-09 · v2.2.0）：产物落库正门 + 索引库 + 搜索框 ═══════════════
# 规则真源：通用层/rules/core-8.md B-09——产出默认不落产物区，除非用户点名；
# 需留档的经本正门归类落云端资料库。交互型面板（必须落盘才能预览）属点名例外。

ARCHIVE_TITLE = '📦 产物归档'
INDEX_DB_TITLE = '📦 产物索引'
CAT_MAP = [('.html', '面板'), ('.md', '文档'), ('.csv', '清单'), ('.json', '数据'),
           ('.png', '图片'), ('.jpg', '图片'), ('.jpeg', '图片'), ('.pdf', '文档')]


def _guess_cat(name):
    low = (name or '').lower()
    for ext, c in CAT_MAP:
        if low.endswith(ext):
            return c
    return '其他'


def _ensure_archive_folder():
    """幂等定位/创建「📦 产物归档」根夹。state 登记后每次回读验证（防夹被删后记死账）。"""
    st = load_state()
    fid = st.get('archive_folder', '')
    if fid and _find_folder_by_title('', ARCHIVE_TITLE) == fid:
        return fid
    fid = _find_folder_by_title('', ARCHIVE_TITLE)
    if not fid:
        fid = _create_folder(ARCHIVE_TITLE, '')
        if not fid:
            return ''
    st['archive_folder'] = fid
    save_state(st)
    return fid


def _ensure_index_db(fid):
    """幂等定位/创建「📦 产物索引」库（挂归档夹内）。五字段：名称/类别/日期/来源/说明。"""
    st = load_state()
    db_id = st.get('index_db', '')
    kids = {n.get('id'): n for n in _kids(fid)}
    if db_id and db_id in kids:
        return db_id
    for nid, n in kids.items():
        if n.get('kind') == 'database' and (n.get('title') or '').strip() == INDEX_DB_TITLE:
            st['index_db'] = nid
            save_state(st)
            return nid
    sc = {'title': INDEX_DB_TITLE, 'space_id': SPACE, 'parent_id': fid,
          'properties': [
              {'name': '名称', 'config': {'text': ''}},
              {'name': '类别', 'config': {'select': {'options': [
                  {'text': '面板'}, {'text': '文档'}, {'text': '清单'},
                  {'text': '数据'}, {'text': '图片'}, {'text': '其他'}]}}},
              {'name': '日期', 'config': {'date': {}}},
              {'name': '来源', 'config': {'text': ''}},
              {'name': '说明', 'config': {'text': ''}},
          ]}
    db_id, err = _create_db_api(sc)
    if not db_id:
        print(f'❌ 产物索引库创建失败：{err}')
        return ''
    st['index_db'] = db_id
    save_state(st)
    print(f'  ✅ 产物索引库已建并回读确认（{db_id}）')
    return db_id


def _db_schema(db_id):
    """读库字段结构 {字段名: {'type':..., 'options':[...]}}。None=无法判定。"""
    j, _ = _db_query(db_id, 'schema')
    props = j.get('properties')
    if not isinstance(props, list):
        return None
    out = {}
    for prop in props:
        cfg = prop.get('config') or {}
        out[prop.get('name')] = {
            'type': prop.get('type') or 'text',
            'options': [o.get('text') for o in (cfg.get('options') or [])]}
    return out


def _index_add(db_id, name, cat, date, source, note, path=''):
    """写一条索引记录（library 正本 db_edit.py --op set-records）。

    ★ 按字段真实类型写 oneof（2026-11-12 实测）：select 字段写 {"text":...} 会被
      **静默丢弃**（记录建了、类别为空，不报错）。所以先读 schema 再决定值形态；
      类别不在 select 选项里 → 降级"其他"并把真类别写进说明，不丢信息、不整批失败。
    """
    schema = _db_schema(db_id) or {}

    def val(field, text):
        t = (schema.get(field) or {}).get('type', 'text')
        if t == 'select':
            opts = (schema.get(field) or {}).get('options') or []
            if text in opts:
                return {'select': text}
            fallback = '其他' if '其他' in opts else (opts[0] if opts else text)
            return {'select': fallback}
        if t == 'multi_select':
            return {'multi_select': [text]}
        return {'text': text}

    real_note = note
    opts = (schema.get('类别') or {}).get('options') or []
    if cat not in opts and (schema.get('类别') or {}).get('type') == 'select':
        real_note = (f'类别:{cat}｜' + note) if note else f'类别:{cat}'
    rec = [{'名称': val('名称', name), '类别': val('类别', cat), '日期': {'date': date},
            '来源': val('来源', source), '说明': val('说明', real_note),
            '落点路径': val('落点路径', path)}]
    ok, tag, pl, raw = _db_add_records(db_id, rec)
    if ok == len(rec):
        return True
    why = pl.get('error') or pl.get('code') or raw[:160]
    print(f'  ⚠️ 索引记录写入失败 {len(rec) - ok}/{len(rec)}（文件本体已落库）：{tag or "无状态行"} {why}')
    return False


def _artifact_rules():
    """汇总所有技能的产出声明（artifacts[].match/target/category/source）。

    **这就是"以后加能力自动跟着归类"的实现**：规则不在清道夫里，而在各技能自己的
    artifacts.json。新增技能 = 新增一个文件，清道夫无需改动；没声明的产出走
    「未归类」兜底并在归档时提示，不静默乱堆。
    """
    rules = []
    if not os.path.isdir(SKILLS_DIR):
        return rules
    for name in sorted(os.listdir(SKILLS_DIR)):
        fp = os.path.join(SKILLS_DIR, name, 'artifacts.json')
        if not os.path.isfile(fp):
            continue
        try:
            d = json.load(open(fp, encoding='utf-8'))
        except Exception:
            continue
        for r in (d.get('artifacts') or []):
            if isinstance(r, dict) and r.get('match'):
                r = dict(r)
                r['_from'] = name
                rules.append(r)
    return rules


def _match_rule(path):
    """按产出文件名匹配声明规则；无命中返回 None（走兜底，不猜）。"""
    name = os.path.basename(path)
    for r in _artifact_rules():
        if any(m and str(m) in name for m in (r.get('match') or [])):
            return r
    return None


def _ensure_path(path_str):
    """按「根/子/孙」路径定位夹，缺的建（每步回读）。返回末级 id，失败 ''。"""
    cur = ''
    for seg in [x.strip() for x in str(path_str or '').split('/') if x.strip()]:
        nid = _find_folder_by_title(cur, seg)
        if not nid:
            nid = _create_folder(seg, cur)
            if not nid:
                return ''
        cur = nid
    return cur


def _upload_any(p, parent_id, title=None):
    """按类型选正门上传。返回 (node_id, err_text)；node_id 为空时 err_text 说明原因。

    ★ 实测（2026-11-12）：drive 上传 .md 直接被拒——{"error":"该文件类型不走网盘上传，
      请使用对应资料库模块"}。归档必须分流：md → doc/create_doc（文档节点），
      其余（csv/json/png/pdf/zip/txt）→ drive 网盘。**html 走 page 导入**（本轮未接，
      走网盘会明确报错，不静默当成功）。
    """
    ext = os.path.splitext(p)[1].lower()
    name = os.path.basename(p)
    if ext in ('.md', '.markdown'):
        # 标题用记录名（v0.8.12）：学习成品的主文档文件叫 index.md，用文件名当标题
        # 会在云端出现一堆叫「index」的文档，等于没归档（实测）。
        title = (title or '').strip() or os.path.splitext(name)[0]
        r = subprocess.run([sys.executable, f'{LIB}/doc/create_doc.py',
                            '--title', title,
                            '--space-id', SPACE, '--parent-id', parent_id,
                            '--content-file', p],
                           capture_output=True, text=True)
        out = (r.stdout or '') + (r.stderr or '')
        for ln in out.splitlines():
            if ln.startswith('KS_DOC_CREATE'):
                parts = ln.split('\t')
                if len(parts) >= 2 and parts[1].strip():
                    return parts[1].strip(), ''
        return '', out[:200]
    r = subprocess.run([sys.executable, f'{LIB}/drive/upload_drive_file.py',
                        p, '--parent-id', parent_id, '--space-id', SPACE],
                       capture_output=True, text=True)
    out = (r.stdout or '') + (r.stderr or '')
    for ln in out.splitlines():
        if 'KS_DRIVE_UPLOAD_OK' in ln or 'KS_IMPORT' in ln:
            payload = ln.split('\t', 1)[1] if '\t' in ln else ln.split(' ', 1)[1]
            try:
                j = json.loads(payload)
                nid = j.get('node_id') or j.get('node_block_id') or j.get('nodeId') or ''
                if nid:
                    return nid, ''
            except Exception:
                pass
    try:
        j = json.loads(out.strip().splitlines()[-1])
        nid = j.get('node_id') or j.get('node_block_id') or j.get('nodeId') or ''
        if nid:
            return nid, ''
    except Exception:
        pass
    return '', out[:200]


def _archive_file(p, category='', source='', note='', keep=False, quiet=False,
                  name=None, write_index=True, target=None):
    """归档单个文件：上传「📦 产物归档/<类别>/」+ 写索引 + 本地处置。

    返回 (ok, info)：ok=True → info=node_id；ok=False → info=失败原因。
    **回读确认是唯一判据**（S169/S200）：API 说成功不算，父夹枚举里见到才算。

    name        —— 记录名（v0.8.12）。学习成品是**目录名**，主文档文件叫 index.md，
                   不传就会把索引记成 index.md，找不回是哪个成品。
    write_index —— False 时只上传、不单独建索引（v0.8.12）。一份成品由「主文档 + 整包
                   zip」两个节点组成，索引只该有一条；zip 仍进 archive_log 以便追溯。
    target      —— 显式落点（v0.8.12），优先于 artifacts.json 声明。成品目录名通常
                   不含"学习"这类关键词，靠 match 匹配不到，必须由调用方直接指定。
    """
    say = (lambda *x: None) if quiet else print
    if not os.path.isfile(p):
        return False, '文件不存在'
    # 防御：内部调用方（能力层 import）可能没走过 main 的空间解析
    if not SPACE:
        resolve_space(quiet=True)
    if not SPACE:
        return False, '空间未解析（无法判定落到哪个空间，已记 pending）'
    name = (name or '').strip() or os.path.basename(p)
    # ★ 先看能力层的产出声明：命中就用它指定的落点/类别/来源（"归类整理"的真身）。
    rule = _match_rule(p) or {}
    cat = category or rule.get('category') or _guess_cat(name)
    source = source or rule.get('source') or '（未注明）'
    note = note or ''
    fid = _ensure_archive_folder()
    if not fid:
        return False, '产物归档夹不可用'
    target = (target or '').strip() or (rule.get('target') or '').strip()
    if target:
        cfid = _ensure_path(target)
        if not cfid:
            return False, f'落点「{target}」不可用'
    else:
        # 未声明：落「📦 产物归档/未归类」（蓝图保证存在），并在日志里点名是谁没声明
        cfid = _ensure_path(f'{ARCHIVE_TITLE}/未归类')
        if not cfid:
            return False, '未归类夹不可用'
        if not quiet:
            print(f'  ⚠️ 产出未声明 artifacts.json（{rule.get("_from") or "来源未知"}）'
                  f'→ 已落「{ARCHIVE_TITLE}/未归类」，可在该技能加声明自动归类')
    node_id, uerr = _upload_any(p, cfid, title=name)
    out = uerr or ''
    # 写后回读：新建节点服务端目录索引有传播延迟（S200 实测首查即 miss）→ 3 次重试
    kids_ids = set()
    for _i in range(3):
        kids_ids = {n.get('id') for n in _kids(cfid)}
        if node_id and node_id in kids_ids:
            break
        time.sleep(3)
    if not node_id or node_id not in kids_ids:
        return False, f'上传失败或回读不符：{out[:180]}'
    say(f'  ✅ 文件已落库并回读确认：{name}（{node_id}）')
    # ② 索引记录（write_index=False 的附件不单独建索引，只进 archive_log）
    db_id = _ensure_index_db(fid) if write_index else ''
    st = load_state()
    landing = (target or f'{ARCHIVE_TITLE}/未归类')
    entry = {'name': name, 'cat': cat, 'node_id': node_id, 'db': db_id,
             'space': SPACE, 'date': time.strftime('%Y-%m-%d'),
             'source': source, 'note': note,
             'path': f'{landing}/{name}'}
    if db_id and write_index:
        entry['indexed'] = _index_add(db_id, name, cat, entry['date'],
                                      entry['source'], entry['note'], entry['path'])
    elif not write_index:
        entry['indexed'] = '（附件·随主记录）'
    st.setdefault('archive_log', []).append(entry)
    save_state(st)
    # ③ 本地处置：落库成功才清理；失败路径根本走不到这里
    if keep:
        say('  📎 --keep：本地文件保留')
    else:
        try:
            os.remove(p)
            say(f'  🧹 本地已清理：{p}')
        except Exception as e:
            say(f'  ⚠️ 本地清理失败（{type(e).__name__}）——文件已落库，可手动删：{p}')
    return True, node_id


def cmd_archive(a):
    """★ 产物落库正门（B-09）：上传「📦 产物归档/<类别>/」+ 写索引 + 本地清理。"""
    resolve_space()
    p = os.path.abspath(os.path.expanduser(a.file))
    if not os.path.isfile(p):
        print(f'❌ 文件不存在：{p}'); return 1
    ok, info = _archive_file(p, a.category, a.source, a.note, a.keep)
    if not ok:
        print(f'❌ 归档失败：{info}（本地文件保留）'); return 2
    rule = _match_rule(p) or {}
    landing = (rule.get('target') or f'{ARCHIVE_TITLE}/未归类')
    print(f'{{已存至 {SPACE_TITLE_OR_FALLBACK()}/{landing}/{os.path.basename(p)}}}')
    return 0


def _pending_artifact(path, reason):
    """待归档产物记账：与本地欠账同一账本，kind 区分（list 出单时分开看）。"""
    try:
        st = load_state()
        pend = st.setdefault('local_pending', [])
        for x in pend:
            if x.get('path') == path:
                x['reason'], x['kind'] = reason, '待归档'
                save_state(st)
                return
        pend.append({'path': path, 'reason': reason, 'kind': '待归档',
                     'added': time.strftime('%Y-%m-%d %H:%M')})
        save_state(st)
    except Exception:
        pass


def archive_out(path, source='', category='', note='', keep=False, quiet=False,
                name=None, write_index=True, target=None):
    """★ 能力层出口门面（v2.4.0）：先自举库房，再归档。**永不抛异常**。

    为什么不让能力层自己判断库在不在：测活/学习资料的作者不该知道库务司存在。
    调用方一行 `space_hub.archive_out(report, source='探源司·测活', note='…')`，
    库里就多一条可检索的记录——这就是"能力层产出在资料库有体现"。

    失败语义（三态）：False + info 说清原因，本地文件保留并记 pending；
    绝不把"没落库"说成"已归档"。

    name / write_index（v0.8.12）：见 _archive_file 同名参数——一份学习成品是
    「主文档（写索引）+ 整包 zip（不写索引）」两个节点，靠这两个参数区分。
    """
    try:
        p = os.path.abspath(os.path.expanduser(str(path or '')))
        if not p or not os.path.isfile(p):
            return False, '文件不存在'
        # ★ 空间必须先解析（v0.8.12 修）：archive_out 是被能力层 import 调用的，
        #   不走 main 的统一 resolve_space。而下面"当天已自举就跳过 ensure"的分支
        #   不会顺带解析——实测：次日/新进程里 SPACE 仍是 None，建夹时
        #   subprocess 收到 None 抛 TypeError，归档全挂（v0.8.11 潜伏缺陷）。
        if not SPACE:
            resolve_space(quiet=True)
        # 每天首次归档做一次全量收敛（自愈：夹被误删也能补回）；当天后续跳过，
        # 避免每条产出都跑一遍枚举+建库检查（实测每次 3–5s，批量产出时很可观）。
        st = load_state()
        if (st.get('blueprint') or {}).get('ensured_at', '')[:10] != time.strftime('%Y-%m-%d'):
            ensure_library(quiet=True)
        ok, info = _archive_file(p, category, source, note, keep, quiet=quiet,
                                 name=name, write_index=write_index, target=target)
        if not ok:
            _pending_artifact(p, f'归档失败：{info}')
        return ok, info
    except SystemExit as e:
        _pending_artifact(str(path), f'库房自举失败（退出码 {e.code}）')
        return False, f'库房自举失败（退出码 {e.code}）'
    except Exception as e:
        _pending_artifact(str(path), f'{type(e).__name__}: {str(e)[:60]}')
        return False, f'{type(e).__name__}: {str(e)[:80]}'


def SPACE_TITLE_OR_FALLBACK():
    """落点回执用的空间名：优先 state 登记的标题，取不到就退化为 space id 前 8 位。"""
    try:
        t = (load_state().get('space_title') or '').strip()
        if t:
            return t
        return (SPACE or '空间')[:8]
    except Exception:
        return '空间'


def _products_index():
    """汇总产物索引：已落库（archive_log）+ 待归档（pending）+ 本地可识别产物。

    ★ 本地部分只收「能被 artifacts.json 声明识别」的文件——早先扫 OUT_DIR 全盘，
      把 50+ 个无关 md 都算成"产物"，盘点结果没法看（实测）。识别不了的本来就不该
      叫产物；真要收，让它的技能补一条声明。
    """
    st = load_state()
    rows = [{'name': x.get('name', ''), 'cat': x.get('cat', ''), 'date': x.get('date', ''),
             'source': x.get('source', ''), 'where': '已落库',
             'id': x.get('node_id', '')} for x in (st.get('archive_log') or [])]
    for x in (st.get('local_pending') or []):
        if x.get('kind') == '待归档':
            rows.append({'name': os.path.basename(x.get('path', '')), 'cat': '待归档',
                         'date': (x.get('added') or '')[:10],
                         'source': x.get('reason', '')[:40], 'where': '待归档',
                         'id': x.get('path', '')})
    for fn in sorted(os.listdir(OUT_DIR)):
        p = os.path.join(OUT_DIR, fn)
        if os.path.isfile(p) and _match_rule(p):
            sz = os.path.getsize(p)
            rows.append({'name': fn, 'cat': _guess_cat(fn), 'date': time.strftime(
                '%Y-%m-%d', time.localtime(os.path.getmtime(p))), 'source': '本地·可识别待归档',
                'where': f'本地 {sz}B', 'id': p})
    return rows


def cmd_products(a):
    """★ 产物盘点 + 搜索框（B-09 产物纪律的配套入口）。

    --scan       盘点：已落库索引 + 本地产物区现存，直接打印（不落盘）。
    --search-box 生成单文件 HTML 搜索框（内嵌索引、零依赖）——属用户点名交付物。"""
    rows = _products_index()
    if a.scan:
        print(f'产物盘点：共 {len(rows)} 件（已落库 {sum(1 for x in rows if x["where"] == "已落库")} '
              f'｜ 本地产物区 {sum(1 for x in rows if x["where"] != "已落库")}）')
        for x in rows:
            print(f'  · [{x["cat"]}] {x["name"][:44]:44} {x["date"]}  {x["where"]}  {x["source"][:20]}')
        return 0
    if getattr(a, 'retry', False):
        pend = [x for x in (load_state().get('local_pending') or [])
                if x.get('kind') == '待归档']
        if not pend:
            print('✅ 无待归档产物'); return 0
        done = 0
        for x in pend:
            pth = x.get('path', '')
            if not os.path.isfile(pth):
                print(f'  ⚠️ 文件已不在：{pth}'); continue
            o, info = archive_out(pth, quiet=True)
            print(('  ✅ 补投成功：' if o else '  ❌ 仍失败：') + f'{os.path.basename(pth)}（{info}）')
            done += 1 if o else 0
        if done:
            st = load_state()
            st['local_pending'] = [x for x in (st.get('local_pending') or [])
                                   if not (x.get('kind') == '待归档' and not os.path.isfile(x.get('path', '')))]
            save_state(st)
        print(f'补投完成：成功 {done} / {len(pend)}')
        return 0 if done == len(pend) else 2
    if a.search_box:
        payload = json.dumps(rows, ensure_ascii=False)
        html = _SEARCH_BOX_TPL.replace('__PAYLOAD__', payload).replace(
            '__GEN_TIME__', time.strftime('%Y-%m-%d %H:%M'))
        out = os.path.join(OUT_DIR, '产物搜索框.html')
        open(out, 'w', encoding='utf-8').write(html)
        print(f'🔎 产物搜索框已生成（{len(rows)} 件可搜）：{out}')
        return 0
    print('用法：--scan 盘点 ｜ --search-box 生成搜索框'); return 1


_SEARCH_BOX_TPL = '''<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>产物搜索框</title>
<style>
  :root{--bg:#0b1020;--card:#141b33;--fg:#e8ecf8;--mut:#8b93b8;--acc:#6ea8fe;--ok:#4ade80}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;padding:20px}
  h1{font-size:18px;margin-bottom:4px} .sub{color:var(--mut);font-size:12px;margin-bottom:14px}
  #q{width:100%;padding:12px 16px;font-size:16px;border-radius:12px;border:1px solid #2a3560;background:var(--card);color:var(--fg);outline:none}
  #q:focus{border-color:var(--acc)}
  .stats{color:var(--mut);font-size:12px;margin:10px 2px}
  .card{background:var(--card);border-radius:12px;padding:10px 14px;margin:8px 0;border-left:3px solid #2a3560}
  .card.hit{border-left-color:var(--ok)}
  .nm{font-weight:600;word-break:break-all} .mt{color:var(--mut);font-size:12px;margin-top:2px}
  .tag{display:inline-block;background:#1e2a52;color:var(--acc);border-radius:6px;padding:0 8px;font-size:12px;margin-right:6px}
  .empty{color:var(--mut);text-align:center;padding:30px 0}
</style></head><body>
<h1>🔎 产物搜索框</h1>
<div class="sub">生成时间 __GEN_TIME__ ｜ 数据内嵌 · 零依赖 ｜ 产物纪律 B-09：新产物经库务司 archive 落库</div>
<input id="q" placeholder="搜名称 / 类别 / 日期 / 来源…" autofocus>
<div class="stats" id="st"></div>
<div id="list"></div>
<script>
const DATA = __PAYLOAD__;
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function render(q){
  q = (q||'').trim().toLowerCase();
  const hits = !q ? DATA : DATA.filter(x =>
    [x.name,x.cat,x.date,x.source,x.where].join(' ').toLowerCase().includes(q));
  document.getElementById('st').textContent = `共 ${DATA.length} 件 ｜ 命中 ${hits.length} 件`;
  document.getElementById('list').innerHTML = hits.length ? hits.map(x =>
    `<div class="card hit"><div class="nm"><span class="tag">${esc(x.cat)}</span>${esc(x.name)}</div>
     <div class="mt">${esc(x.date)} · ${esc(x.where)} · ${esc(x.source)}</div></div>`).join('')
    : '<div class="empty">没有命中的产物</div>';
}
const q = document.getElementById('q');
q.addEventListener('input', () => render(q.value));
render('');
</script></body></html>
'''


def _list_spaces():
    """列出当前账号可访问的全部空间（list-user-spaces，无需任何写死 id）。"""
    d = _space('space.workspace.list-user-spaces')
    if not d or 'data' not in (d or {}):
        print(f'❌ list-user-spaces 失败：{json.dumps(d or {}, ensure_ascii=False)[:200]}')
        print('   → 请检查 library 技能授权/网络（授权问题找用户，不猜）')
        raise SystemExit(2)
    return (d['data'] or {}).get('spaces') or []


def resolve_space(explicit=None, quiet=False):
    """四层解析目标空间并填充全局 SPACE/PARENT。返回 space_id；失败显式报错退出。

    三态（M-R60）：解析失败≠"空间为空"——直接退出，绝不带错坐标干活。"""
    global SPACE, PARENT
    st = load_state()
    cand = (explicit or os.environ.get('SPACE_HUB_SPACE_ID', '')
            or st.get('space_id', '')).strip()
    how = '显式指定' if explicit else ('环境变量' if os.environ.get('SPACE_HUB_SPACE_ID') else
          ('state 登记' if cand else ''))
    if not cand:
        # 第③层：动态发现（按标题，role 必须可写）
        title_pref = (st.get('space_title') or PREF_TITLE).strip()
        spaces = _list_spaces()
        matches = [s for s in spaces
                   if (s.get('title') or '').strip() == title_pref
                   and s.get('role') in ('owner', 'admin')]
        if len(matches) == 1:
            cand = matches[0]['spaceId']
            how = f'动态发现（标题={title_pref}）'
        elif len(matches) > 1:
            print(f'❌ 按标题「{title_pref}」匹配到 {len(matches)} 个可写空间，歧义：')
            for s in matches:
                print(f'   · {s["spaceId"]}  role={s.get("role")}  url={s.get("url","")}')
            print('   → 用 init --space-id <ID> 显式登记一个')
            raise SystemExit(2)
        else:
            print(f'❌ 四层解析全部落空：无环境变量、无 state 登记、'
                  f'当前账号没有标题为「{title_pref}」且可写（owner/admin）的空间。')
            print('   当前账号可访问的空间：')
            for s in spaces:
                print(f'   · {s["spaceId"]}  role={s.get("role")}  title={ (s.get("title") or "(无标题)")[:30] }')
            print(f'   → 跑 python3 {os.path.basename(__file__)} init --space-id <ID> 登记，'
                  f'或 init --title "<标题>" 按标题登记')
            raise SystemExit(2)
    SPACE = cand
    PARENT = cand
    if st.get('space_id') != cand:
        st['space_id'] = cand
        if st.get('space_title') is None:
            st['space_title'] = PREF_TITLE
        save_state(st)
    if not quiet:
        print(f'✓ 目标空间：{SPACE}（{how}）')
    return SPACE


def cmd_init(a):
    """登记/查看目标空间（换账号后的第一条命令）。"""
    spaces = _list_spaces()
    if a.list:
        print(f'当前账号可访问 {len(spaces)} 个空间：')
        for s in spaces:
            mark = ' ←当前登记' if s['spaceId'] == load_state().get('space_id') else ''
            print(f'  · {s["spaceId"]}  role={s.get("role")}  '
                  f'title={(s.get("title") or "(无标题)")[:40]}{mark}')
        return 0
    if a.space_id:
        hit = [s for s in spaces if s['spaceId'] == a.space_id]
        if not hit:
            print(f'❌ space_id {a.space_id} 不在当前账号可访问列表里——拒绝登记（防写错）')
            for s in spaces:
                print(f'   · {s["spaceId"]}  role={s.get("role")}  title={(s.get("title") or "")[:30]}')
            return 1
        st = load_state()
        st['space_id'] = a.space_id
        st['space_title'] = (hit[0].get('title') or '').strip() or PREF_TITLE
        save_state(st)
        print(f'✅ 已登记目标空间：{a.space_id}（title={st["space_title"]}，role={hit[0].get("role")}）')
        return 0
    if a.title:
        hits = [s for s in spaces if (s.get('title') or '').strip() == a.title.strip()]
        writable = [s for s in hits if s.get('role') in ('owner', 'admin')]
        if len(writable) == 1:
            return cmd_init(argparse.Namespace(list=False, space_id=writable[0]['spaceId'], title=None))
        print(f'❌ 按标题「{a.title}」未唯一命中可写空间（命中 {len(hits)} 个，可写 {len(writable)} 个）。')
        for s in hits:
            print(f'   · {s["spaceId"]}  role={s.get("role")}')
        return 1
    print('用法：init --list | init --space-id <ID> | init --title "<标题>"')
    return 1


def _classify_rules():
    if not os.path.exists(CLASSIFY_RULES):
        print(f'❌ 归纳登记册不存在：{CLASSIFY_RULES}——加分类规则只改登记册，零改代码')
        raise SystemExit(2)
    try:
        rules = json.load(open(CLASSIFY_RULES, encoding='utf-8'))
    except Exception as e:
        print(f'❌ 归纳登记册损坏（{type(e).__name__}）——禁止当空规则（M-R60）')
        raise SystemExit(2)
    if not rules.get('rules'):
        print('❌ 归纳登记册 rules 为空——先补登记册再跑 classify')
        raise SystemExit(2)
    return rules


def _find_folder_by_title(pid, title):
    for n in _kids(pid):
        if n.get('kind') == 'folder' and (n.get('title') or '').strip() == title:
            return n.get('id')
    return ''


def _create_folder(title, parent_id):
    # 守卫（v0.8.12）：SPACE 为 None 时 subprocess 会在 _fork_exec 抛
    # "expected str, bytes or os.PathLike object, not NoneType"——栈指向 subprocess，
    # 极难反查到"空间没解析"。这里直接拦住并说清原因。
    if not SPACE:
        resolve_space(quiet=True)
    if not SPACE:
        print('❌ 空间未解析——无法建夹（请先跑 init 或检查授权）')
        return ''
    r = subprocess.run([sys.executable, f'{LIB}/manage/create_folder.py',
                        '--title', title, '--space-id', SPACE, '--parent-id', parent_id],
                       capture_output=True, text=True)
    for ln in (r.stdout or '').splitlines():
        if 'KS_FOLDER_CREATE' in ln:
            parts = ln.split('\t')
            if len(parts) >= 2:
                fid = parts[1].strip()
                back = _find_folder_by_title(parent_id, title)   # 写后回读（S156 招式 T-I）
                if back != fid:
                    print(f'❌ 建夹回读不符：API 返回 {fid}，服务端枚举到 {back or "(无)"}——拒绝使用')
                    raise SystemExit(2)
                return fid
    print(f'❌ 建夹失败：{(r.stdout or "")[:150]}{(r.stderr or "")[:150]}')
    return ''


def cmd_classify(a):
    """归纳：把空间根散落的文档按登记册规则归入目标文件夹（dry-run 预览 / --yes 执行）。"""
    resolve_space()
    rules = _classify_rules()
    inbox_id, _ = _find_inbox()
    plan, skipped = {}, []
    for n in _kids(''):
        nid, title, kind = n.get('id'), (n.get('title') or '').strip(), n.get('kind')
        if kind == 'folder' or nid == inbox_id or not nid:
            continue
        if any(kw in title for kw in KW):
            skipped.append((nid, title, '命中废弃标记 → 归 scan 管辖，classify 不抢'))
            continue
        target = ''
        for r in rules['rules']:
            if any(kw in title for kw in r.get('match', [])):
                target = r.get('target', '')
                break
        if not target:
            skipped.append((nid, title, '无规则命中 → 保持原位'))
            continue
        plan.setdefault(target, []).append((nid, title))
    if not plan:
        print('✅ 根层级散落文档均无规则命中（或全部交给 scan），无需归纳。')
    else:
        print(f'归纳方案（{sum(len(v) for v in plan.values())} 项 → {len(plan)} 个目标夹）：')
        for t, items in plan.items():
            print(f'  📁 {t}  ← {len(items)} 项')
            for nid, title in items:
                print(f'     · {nid[:12]}  {title[:44]}')
    if skipped:
        print(f'  ⏭ 跳过 {len(skipped)} 项（无规则命中/归 scan 管辖）——三态如实列出，不假装"全处理了"')
        if a.show_skipped:
            for nid, title, why in skipped:
                print(f'     · {nid[:12]}  {title[:40]}  [{why}]')
    if a.dry_run or not plan:
        print('（预览模式，未做任何移动——加 --yes 才执行）')
        return 0
    if not a.yes:
        print('❌ 执行需显式 --yes（归纳会移动节点，不可静默发生）')
        return 1
    moved = 0
    for t, items in plan.items():
        # target 是路径（v0.8.12）：与 archive 共用 _ensure_path 逐级定位，
        # 不再在根层级建同名夹——否则「📦 产物归档/文档」之外又多一套「归档·报告」。
        fid = _ensure_path(t)
        if not fid:
            print(f'⚠️ 目标夹「{t}」创建失败 → 该组 {len(items)} 项**保持原位**（不漏项，铁律2）')
            continue
        for nid, title in items:
            rc = cmd_move(argparse.Namespace(node=nid, to=fid))
            if rc == 0:
                moved += 1
    print(f'✅ 归纳完成：移动 {moved}/{sum(len(v) for v in plan.values())} 项')
    return 0


def _first_json_object(text):
    """从任意前缀文本里摘出第一个可解析的 JSON 对象，找不到返回 {}。

    平台正本会输出 `KS_XXX_OK\\t{json}` 这类带状态前缀的行（2026-11-13 实测
    db_create.py），JSON 不在行首——按行首判 '{' 会漏。这里逐个 '{' 试解析。
    """
    for i, ch in enumerate(text or ''):
        if ch != '{':
            continue
        try:
            obj = json.loads(text[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return {}


# ── library database 正本适配层（v0.8.33）──────────────────────────────────
# 平台 2026-11 把 database 层重构成 db_create / db_query / db_edit / db_delete，
# 旧脚本名（get_database_schema / batch_add_database_records / …）整层消失。
# 本层只做两件事：旧调用 → 新正本的参数映射、`KS_XXX_OK\t{json}` 状态行解析成三态。
# **不自造写入通道**：每次都 exec 正本脚本，删记录仍然只走 db_delete 的二段式。
_DB_QUERY = f'{LIB}/database/db_query.py'
_DB_EDIT = f'{LIB}/database/db_edit.py'


def _db_call(script, argv, stdin=None, timeout=90):
    """跑正本脚本 → (tag, payload, raw)。tag='' = 没拿到状态行（无法判定）。"""
    p = subprocess.run([sys.executable, script] + argv, input=stdin,
                       capture_output=True, text=True, timeout=timeout)
    text = (p.stdout or '') + '\n' + (p.stderr or '')
    tag = ''
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith('KS_'):
            tag = s.split('\t')[0].strip()
            break
    return tag, _first_json_object(text), text


def _db_query(db_id, ask, **kw):
    """读库。ask ∈ schema / records / record / stats / csv。返回 (payload, raw)。"""
    argv = ['--target', db_id, '--target-kind', 'id', '--ask', ask]
    for k, v in kw.items():
        if v not in (None, ''):
            argv += ['--' + k.replace('_', '-'), str(v)]
    tag, pl, raw = _db_call(_DB_QUERY, argv)
    if tag != 'KS_DB_QUERY_OK':
        return {}, raw          # 空 dict = 读不到，不折叠成「空库」
    return pl, raw


def _db_add_records(db_id, records, timeout=180):
    """追加记录（等价旧的 batch_add_database_records.py）。返回 (ok 条数, tag, payload, raw)。

    语义差异必须知道：旧正本 `results[].success` 只代表**服务端接受**；
    新正本 KS_DB_EDIT_OK 是**逐条回读确认后**才发，UNVERIFIED 会带 failed_add_indices。
    所以这里的 ok 是「回读确认成功」的条数，比旧口径严。
    """
    n = len(records)
    tag, pl, raw = _db_call(
        _DB_EDIT, ['--database-id', db_id, '--op', 'set-records', '--stdin'],
        stdin=json.dumps({'records': records}, ensure_ascii=False), timeout=timeout)
    if tag == 'KS_DB_EDIT_OK':
        return n, tag, pl, raw
    failed = pl.get('failed_add_indices')
    if isinstance(failed, list):
        return max(n - len(failed), 0), tag, pl, raw
    return 0, tag, pl, raw


def _create_db_api(sc):
    """调 library 建库正本（db_create.py --stdin）+ 多行 JSON 解析 + 父容器回读。
    返回 (db_id, err)。M-R38 单一实现：cmd_create_db 与 _ensure_index_db 共用（B-08 不自造）。

    v0.8.32（2026-11-13 实测）：平台 library 把 create_database.py 重构为
    db_create.py，字段键 properties → fields（db_create.py:450 读 payload["fields"]）。
    键名适配放在这里、三处调用点继续传 properties，避免同一件事改三遍漏一处。
    """
    payload = dict(sc)
    if 'properties' in payload and 'fields' not in payload:
        payload['fields'] = payload.pop('properties')
    r = subprocess.run([sys.executable, f'{LIB}/database/db_create.py', '--stdin'],
                       input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True)
    out = (r.stdout or '').strip()
    # 正本输出形态：v0.8.32 实测为 `KS_DB_CREATE_OK\t{...}`——JSON 与状态前缀同行，
    # 行首不是 '{'，旧的「逐行找 '{' 开头」会漏掉。改为从每个 '{' 位置试解析到末尾。
    j = _first_json_object(out)
    db_id = j.get('database_id', '')
    if not db_id:
        return '', f'{out[:200]}{(r.stderr or "")[:200]}'
    # 写后回读：在父容器枚举中确认该 id 真实存在
    kids_ids = {n.get('id') for n in _kids(sc.get('parent_id') or '')}
    if db_id not in kids_ids:
        return '', f'回读不符：API 返回 {db_id}，但父容器枚举未见该节点——按未建成处理（S169）'
    return db_id, ''


def cmd_create_db(a):
    """建库：薄封装 library/database/create_database.py（正本入口，不重写 HTTP 层）。

    schema JSON：{"title":"库名","properties":{"字段名":{"type":"text|number|select|date|..."}}}
    纪律：建后必须回读（枚举父容器确认节点在）——成功返回≠真的建成（S169 教训）。"""
    import tempfile
    schema = ''
    if a.schema_file:
        try:
            schema = open(a.schema_file, encoding='utf-8').read()
        except Exception as e:
            print(f'❌ schema 文件读取失败：{e}'); return 1
    elif a.schema:
        schema = a.schema
    elif a.stdin:
        schema = sys.stdin.read()
    else:
        print('❌ 缺 schema：用 --schema-file <路径> / --schema \'<JSON>\' / --stdin 三选一'); return 1
    try:
        sc = json.loads(schema)
        props = (sc or {}).get('properties')
        # 正本原生格式（B-08 不自造）：properties 为列表 [{name, config:{类型key:配置}}]
        if not isinstance(sc, dict) or 'title' not in sc or not isinstance(props, list) or not props:
            raise ValueError('schema 须为 {"title":库名, "properties":[{"name":字段名,'
                             '"config":{"text":""}}…]}（正本原生格式，见 library/database/entry.md）')
        bad = [p for p in props if not (isinstance(p, dict) and p.get('name')
               and isinstance(p.get('config'), dict))]
        if bad:
            raise ValueError(f'{len(bad)} 个字段缺 name/config：{[p if isinstance(p,dict) else "?" for p in bad][:3]}')
    except Exception as e:
        print(f'❌ schema 校验失败：{e}'); return 1
    sc.setdefault('space_id', SPACE)
    parent = a.parent
    if parent:
        sc['parent_id'] = parent
    if a.dry_run:
        print('（预览）将创建库：', json.dumps(sc, ensure_ascii=False)[:300])
        print('（预览）未调用 API——去掉 --dry-run 并加 --yes 才真建')
        return 0
    if not a.yes:
        print('❌ 建库是写动作，须显式 --yes（防静默写云端）')
        return 1
    db_id, err = _create_db_api(sc)
    if not db_id:
        print(f'❌ 建库失败：{err}'); return 1
    print(f'✅ 库已建成并回读确认：{sc["title"]}（{db_id}，{len(sc["properties"])} 字段）')
    print('   → 后续写记录走 library 正本：db_edit.py --op set-records（一次调用完成写入+回读）')
    return 0


# ══════════════════ 库房自举（v2.4.0）：按蓝图收敛，不是"一次建库" ══════════════════
# 为什么要它（分发场景）：别人拿到生态时，云端什么都没有。让他先跑 init、再 create-db
# 是不现实的——他根本不知道库务司存在。正确形态是：**能力层第一次产出时，库已经在**。
# 于是把"该有什么"写成蓝图（base_blueprint.json + 各技能 artifacts.json 的 blueprint 分片），
# ensure 做 diff：认领已有的（绝不重建）、补建缺的（绝不删）、每步回读。
BASE_BLUEPRINT = os.path.join(HERE, 'base_blueprint.json')
SKILLS_DIR = os.path.expanduser('~/.codebuddy/skills')
# 索引库字段类型：日期用 date，其余一律 text。
# ★ 为什么"类别"不再用 select：add_database_field 只能加列、**不能改 select 选项**，
#   新能力带来的新类别（视频/压缩包/代码）会直接写不进去——库结构成了扩展瓶颈，
#   而"以后加能力自动跟随"正是本机制存在的理由。text + artifacts.json 软约束才留得出路。
def _field_cfg(name):
    return {'date': {}} if name == '日期' else {'text': ''}


def _skill_shards():
    """扫所有已装技能的 artifacts.json，返回 [(路径, blueprint 分片)]。

    扫描而非中心表：**加技能即跟随**。新技能只要带 artifacts.json 就自动纳入，
    清道夫零改动；没带也不影响安装（产出落「未归类」并在归档时提示）。
    """
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    for name in sorted(os.listdir(SKILLS_DIR)):
        p = os.path.join(SKILLS_DIR, name, 'artifacts.json')
        if not os.path.isfile(p):
            continue
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception as e:
            # 三态：分片损坏 ≠ 分片不存在。跳过但必须让人看见。
            print(f'  ⚠️ 分片损坏已跳过：{p}（{type(e).__name__}）')
            continue
        bp = (d or {}).get('blueprint')
        if isinstance(bp, dict):
            out.append((p, bp))
    return out


def _merge_blueprint():
    """base 蓝图 + 全部技能分片 → 合并后的总蓝图（同名根合并子夹，冲突显式报错）。

    冲突不静默：两个技能给同一根声明了不同索引库 → 停，先统一。
    静默取其一会让"库里有东西但没人知道属于谁"——比报错难查得多。
    """
    if not os.path.exists(BASE_BLUEPRINT):
        print(f'❌ 基础蓝图不存在：{BASE_BLUEPRINT}——库房自举无法进行')
        raise SystemExit(2)
    try:
        bp = json.load(open(BASE_BLUEPRINT, encoding='utf-8'))
    except Exception as e:
        print(f'❌ 基础蓝图损坏（{type(e).__name__}）——禁止当空蓝图（M-R60）')
        raise SystemExit(2)
    shards = _skill_shards()
    roots, order = {}, []

    def _take(r, src):
        t = (r.get('title') or '').strip()
        if not t:
            return
        if t not in roots:
            roots[t] = {'title': t, 'children': [], 'index_db': None,
                        'declared_by': [src], 'doc': r.get('doc', '')}
            order.append(t)
        elif src not in roots[t]['declared_by']:
            roots[t]['declared_by'].append(src)
        for c in (r.get('children') or []):
            if c not in roots[t]['children']:
                roots[t]['children'].append(c)
        db = r.get('index_db')
        if isinstance(db, dict) and db.get('title'):
            old = roots[t]['index_db']
            if old and old.get('title') != db.get('title'):
                print(f'❌ 蓝图冲突：根「{t}」的索引库被多处声明为不同标题 '
                      f'（{old.get("title")} vs {db.get("title")}，来源 {roots[t]["declared_by"]}）'
                      f'——先统一分片再跑')
                raise SystemExit(2)
            roots[t]['index_db'] = db

    for r in (bp.get('roots') or []):
        _take(r, 'base_blueprint.json')
    for p, shard in shards:
        for r in (shard.get('roots') or []):
            _take(r, p)
    bp['roots'] = [roots[t] for t in order]
    bp['_shard_count'] = len(shards)
    return bp


def _writable_spaces():
    return [s for s in _list_spaces() if s.get('role') in ('owner', 'admin')]


def ensure_space(title):
    """解析可写空间；**仅当账号下一个可写空间都没有**时才自动建。

    边界（很重要）：账号里已有可写空间但没登记 → 报错让人选。
    绝不能因为别人装了生态就往他账号里乱建空间——那是替他做决定。
    """
    global SPACE, PARENT
    st = load_state()
    cand = (os.environ.get('SPACE_HUB_SPACE_ID', '') or st.get('space_id', '')).strip()
    writable = _writable_spaces()
    if cand and any(s.get('spaceId') == cand for s in writable):
        SPACE = PARENT = cand
        return cand, 'state 登记'
    if len(writable) == 1:
        SPACE = PARENT = writable[0]['spaceId']
        st['space_id'], st['space_title'] = SPACE, writable[0].get('title') or title
        save_state(st)
        return SPACE, '唯一可写空间'
    if not writable:
        r = subprocess.run([sys.executable, f'{LIB}/space_api.py',
                            'space.workspace.create-space', '--title', title],
                           capture_output=True, text=True)
        out = (r.stdout or '') + (r.stderr or '')
        sid = ''
        for ln in out.splitlines():
            ln = ln.strip()
            if ln.startswith('{'):
                try:
                    j = json.loads(ln)
                    sid = ((j.get('data') or {}).get('space') or {}).get('spaceId', '')
                except Exception:
                    continue
        if not sid:
            print(f'❌ 自动建空间失败：{out[:200]}')
            print('   → 也可手动建一个空间后跑 init --space-id <ID>')
            raise SystemExit(2)
        SPACE = PARENT = sid
        st['space_id'], st['space_title'] = sid, title
        save_state(st)
        print(f'  + 已自动建空间「{title}」（{sid}）——新机首次落地即可用')
        return sid, '自动新建'
    print(f'❌ 当前账号有 {len(writable)} 个可写空间但未登记，不替你选：')
    for s in writable:
        print(f'   · {s["spaceId"]}  {(s.get("title") or "(无标题)")[:30]}')
    print('   → python3 space_hub.py init --space-id <ID>')
    raise SystemExit(2)


def _db_fields(db_id):
    """读库字段名列表。返回 None = 无法判定（读失败），空列表 = 真的没有字段。"""
    j, _ = _db_query(db_id, 'schema')
    props = j.get('properties')
    if not isinstance(props, list):
        return None
    return [p.get('name') for p in props]


def _ensure_db_fields(db_id, fields, quiet=False):
    """已有的库补缺列（幂等）。只加不删、不改类型——不碰用户已有数据。"""
    say = (lambda *x: None) if quiet else print
    have = _db_fields(db_id)
    if have is None:
        say(f'  ⚠️ 字段无法判定（schema 读取失败），跳过补列：{db_id}')
        return
    for f in fields:
        if f in have:
            continue
        tag, pl, raw = _db_call(
            _DB_EDIT, ['--database-id', db_id, '--op', 'add-field',
                       '--payload', json.dumps({'name': f, 'config': _field_cfg(f)},
                                               ensure_ascii=False)])
        if tag == 'KS_DB_EDIT_OK':
            say(f'  + 补列「{f}」✅')
        elif tag:
            why = str(pl.get('error') or pl.get('code') or '')[:100]
            say(f'  + 补列「{f}」⚠️ 失败：{tag} {why}')
        else:
            say(f'  + 补列「{f}」⚠️ 无法判定（无状态行）：{raw[:120]}')


def _ensure_root(r, dry, quiet=False):
    """收敛一个根：认领或新建根夹 → 子夹 → 索引库。返回 (根 id, 新建数, 认领数)。"""
    say = (lambda *x: None) if quiet else print
    title = r['title']
    created = claimed = 0
    rid = _find_folder_by_title('', title)
    if rid:
        claimed += 1
        say(f'  · 认领根「{title}」')
    elif dry:
        say(f'  + 将建根「{title}」及 {len(r.get("children") or [])} 个子夹'
            f'{"、1 个索引库" if r.get("index_db") else ""}')
        return '', 1 + len(r.get('children') or []) + (1 if r.get('index_db') else 0), 0
    else:
        rid = _create_folder(title, '')
        if not rid:
            raise SystemExit(2)
        created += 1
        say(f'  + 新建根「{title}」')

    for c in (r.get('children') or []):
        cid = _find_folder_by_title(rid, c)
        if cid:
            claimed += 1
        elif dry:
            say(f'  + 将建子夹 {title}/{c}')
            created += 1
        else:
            cid = _create_folder(c, rid)
            if not cid:
                raise SystemExit(2)
            created += 1
            say(f'  + 新建子夹 {title}/{c}')

    db = r.get('index_db')
    if db:
        dbid = ''
        for n in _kids(rid):
            if n.get('kind') == 'database' and (n.get('title') or '').strip() == db['title']:
                dbid = n.get('id')
                break
        if dbid:
            claimed += 1
            say(f'  · 认领库「{db["title"]}」')
            if not dry:
                _ensure_db_fields(dbid, db.get('fields') or [], quiet=quiet)
        elif dry:
            say(f'  + 将建库「{db["title"]}」')
            created += 1
        else:
            props = [{'name': f, 'config': _field_cfg(f)} for f in (db.get('fields') or [])]
            dbid, err = _create_db_api({'title': db['title'], 'space_id': SPACE,
                                        'parent_id': rid, 'properties': props})
            if not dbid:
                print(f'❌ 建库失败「{db["title"]}」：{err}')
                raise SystemExit(2)
            created += 1
            say(f'  + 新建库「{db["title"]}」')
    return rid, created, claimed


def ensure_library(dry=False, quiet=False, space_title=None):
    """★ 库房自举：把当前空间收敛到蓝图形态。幂等，可反复跑。

    返回 dict：{'space': id, 'created': n, 'claimed': n, 'roots': {标题: id}}。
    失败（蓝图损坏/建夹建库失败/空间解析不了）→ 抛 SystemExit(2)，**不留半套还报成功**。
    """
    bp = _merge_blueprint()
    sid, how = ensure_space(space_title or bp.get('space_title') or '我的资料库')
    if not quiet:
        print(f'空间：{sid}（{how}）｜蓝图 v{bp.get("blueprint_version")}'
              f'｜分片 {bp.get("_shard_count")} 份｜根 {len(bp["roots"])}')
    created = claimed = 0
    root_ids = {}
    for r in bp['roots']:
        rid, c, k = _ensure_root(r, dry, quiet=quiet)
        root_ids[r['title']] = rid
        created += c
        claimed += k
    if not dry:
        st = load_state()
        st['blueprint'] = {'version': bp.get('blueprint_version'), 'roots': root_ids,
                           'ensured_at': time.strftime('%Y-%m-%d %H:%M')}
        save_state(st)
    if not quiet:
        print(f'{"（预览）" if dry else ""}收敛完成：新建 {created} ｜ 认领 {claimed}')
    return {'space': sid, 'created': created, 'claimed': claimed, 'roots': root_ids}


# ══════════════════ 账号接管 adopt（v0.8.12）══════════════════
# 同一个入口要对付三种账号：
#   · 新账号 —— 云端什么都没有，按蓝图建齐（17 个单元）；
#   · 老账号 —— 一堆历史夹/文档/库，**先接管再接新产出**，不重建、不搬、不删；
#   · 别人的空间 —— 不是本生态的，不能往里建任何东西。
# 判据必须是**可实证的指纹**，不能拿"节点数 > 0"猜：那会把别人正常的空间当老账号，
# 然后往人家根层级建一整套夹——这比不建更糟。
FINGERPRINT_TITLES = ('📦 产物归档', '🗑 待删收件箱')


def _norm_title(t):
    """标题归一化：去 emoji / 空白 / 常见分隔符 / 全角括号。跨账号比对只认归一化标题，不认 id。"""
    t = re.sub(r'[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]', '', t or '')
    return re.sub(r'[\s·・_\-（）()【】\[\]。、]', '', t).strip()


def _nodes_or_none(pid):
    """列子节点；**失败返回 None**（与"真·空"严格区分）。

    _kids() 失败时返回 []，和"空空间"长得一模一样——用它判账号形态，
    授权失效会被误判成新账号，然后一次建 17 个单元全失败（三态塌陷）。
    """
    # ★ v2.7.2：补翻页。服务端单页实测上限 50（请求 200 也会截断），>单页的容器
    #   会被漏读——2026-11-13 空间重置实测顶层 130 项，单页枚举漏 81 项。
    #   「失败→None」语义不变（与 _kids 的「失败→[]」区分，三态不塌）。
    out, off = [], 0
    for _ in range(20):                      # 上限 20 页（约 1000 节点/层），防死循环
        d = _space('space.workspace.list-nodes', space_id=SPACE,
                   parent_node_id=pid, limit=200, offset=off)
        if not isinstance(d, dict) or d.get('error'):
            return None
        data = d.get('data') or {}
        batch = data.get('nodes') or []
        out += batch
        if not data.get('hasMore') or not batch:
            break
        off += len(batch)
    return out


def detect_mode():
    """判账号形态 → (mode, info)。mode ∈ fresh / hybrid / foreign / unknown。

    unknown **不许折叠**成 fresh：枚举失败只能报"无法判定"，不能当空账号去建库。
    """
    roots = _nodes_or_none('')
    if roots is None:
        return 'unknown', {'reason': '顶层节点枚举失败（授权/网络）'}
    if not roots:
        return 'fresh', {'nodes': 0, 'fingerprint': []}
    titles = {_norm_title(n.get('title')) for n in roots if n.get('kind') == 'folder'}
    fp = [t for t in FINGERPRINT_TITLES if _norm_title(t) in titles]
    if (load_state().get('space_id') or '') == SPACE:
        fp.append('state.space_id')
    if fp:
        return 'hybrid', {'nodes': len(roots), 'fingerprint': fp}
    return 'foreign', {'nodes': len(roots), 'fingerprint': []}


def _walk_tree(max_depth=3):
    """递归枚举 → [(depth, node, 父链)]。限深防爆（实测本账号 240 节点 / 深 3 到底）。"""
    out = []

    def rec(pid, d, chain):
        if d > max_depth:
            return
        for n in _kids(pid):
            out.append((d, n, tuple(chain)))
            if n.get('kind') == 'folder':
                rec(n.get('id'), d + 1, chain + [(n.get('title') or '').strip()])

    rec('', 0, [])
    return out


def _similar_pair(a, b):
    """两个夹名是否"疑似同一套体系的两种叫法"（产物区 vs 📦 产物归档）。"""
    import difflib
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb or na[0] != nb[0]:
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.5


def _cat_of_node(kind, title):
    """存量节点的**类别**（索引 select 的 6 个值之一）。

    ★ 类别回答"这东西是什么"（文档/清单/数据/图片/面板），不回答"属于哪个业务板块"。
      早先把业务分类（报告与交付）直接当类别写，9 个值里 8 个不在 select 选项内，
      全部降级成"其他"，类别列等于废了（实测 14 条清一色"其他"）。
      业务分类改写到「说明」里，检索靠「来源」列区分新产出与存量。
    """
    if kind == 'doc':
        return '文档'
    if kind == 'web':
        return '面板'
    if kind == 'database':
        return '数据'
    ext = os.path.splitext(title or '')[1].lower()
    if ext in ('.md', '.markdown', '.txt', '.pdf', '.docx'):
        return '文档'
    if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'):
        return '图片'
    if ext in ('.csv', '.json', '.xlsx', '.xls', '.sql', '.py', '.sh', '.js', '.ts', '.zip'):
        return '数据'
    return '其他'


def _adopt_stock(dry=False, quiet=False):
    """接管存量：登记，不搬运。返回统计 dict。

    ★ 为什么不搬：云端文档被网页/台账引用的是 node_id，一搬老账号里的既有链接全断。
      "归位"只写进索引的落点列，物理移动留给用户显式 classify --yes。
    """
    bp = _merge_blueprint()
    claim_norm = {_norm_title(r['title']) for r in bp['roots']}
    tree = _walk_tree(3)
    roots = [n for d, n, c in tree if d == 0]
    rules = (_classify_rules() or {}).get('rules') or []

    claimed, external = [], []
    for n in roots:
        if n.get('kind') != 'folder':
            continue
        t = (n.get('title') or '').strip()
        if _norm_title(t) in claim_norm:
            claimed.append(t)
        elif any(kw in t for kw in KW):
            # 收件箱/已标废弃的夹属本生态治理面（归 scan 管），不算"用户自有体系"
            continue
        else:
            external.append(t)

    # dry-run 一律不写：只找不建（_ensure_archive_folder 会建夹，干跑时不能用）
    fid = (_find_folder_by_title('', ARCHIVE_TITLE) or '') if dry else _ensure_archive_folder()
    db_id = (_ensure_index_db(fid) if fid else '') if not dry else ''
    st = load_state()
    ad = st.setdefault('adopted', {})
    reg_ids = set(ad.get('registered_ids') or [])

    to_reg, obsolete, already = [], [], 0
    for d, n, chain in tree:
        if d != 0 or n.get('kind') == 'folder':
            continue
        nid, title = n.get('id'), (n.get('title') or '').strip()
        if nid in reg_ids:
            already += 1
            continue
        if any(kw in title for kw in KW):
            obsolete.append((nid, title))
            continue
        hit = next((r for r in rules if any(kw in title for kw in (r.get('match') or []))), None)
        to_reg.append((nid, title, n.get('kind'), hit))

    if not dry and db_id:
        for nid, title, kind, hit in to_reg:
            cat = _cat_of_node(kind, title)
            biz = (hit or {}).get('category') or ''
            tgt = (hit or {}).get('target') or ''
            note = '存量接管｜原位保留｜类型 ' + (kind or '?')
            if biz:
                note += f'｜业务分类 {biz}'
            if tgt:
                note += f'｜建议落点 {tgt}'
            else:
                note += '｜未归类（无规则命中）'
            if _index_add(db_id, title, cat, time.strftime('%Y-%m-%d'), '存量接管',
                          note, ''):          # 落点列留空：它还没被搬，写假路径就是骗人
                reg_ids.add(nid)
            else:
                print(f'  ⚠️ 存量登记失败（索引写入未成功）：{title[:36]}')
    elif dry:
        reg_ids |= {x[0] for x in to_reg}

    suspects = [(e, c) for e in external for c in claimed if _similar_pair(e, c)]

    if not dry:
        ad.update({
            'at': time.strftime('%Y-%m-%d %H:%M'), 'mode': 'hybrid',
            'nodes': len(tree), 'registered': len(reg_ids),
            'skipped_obsolete': len(obsolete), 'external_roots': external,
            'claimed_roots': claimed, 'suspect_pairs': suspects,
            'registered_ids': sorted(reg_ids)})
        save_state(st)

    if not quiet:
        print(f'全树 {len(tree)} 节点（深 ≤3）')
        print(f'  认领蓝图根 {len(claimed)}：{"、".join(claimed) or "（无）"}')
        print(f'  保留自有体系 {len(external)}（原位不动）：{"、".join(external) or "（无）"}')
        print(f'  存量登记 {len(to_reg)} 条'
              f'（定位到建议落点 {sum(1 for x in to_reg if x[3])} / 未归类 '
              f'{sum(1 for x in to_reg if not x[3])}）')
        print(f'  跳过已标废弃 {len(obsolete)}（归 scan 管辖）'
              f'{"｜此前已登记 " + str(already) + " 条" if already else ""}')
        if suspects:
            print(f'  ⚠️ 疑似两套体系（不自动合并，需你定）：'
                  + '；'.join(f'「{e}」≈「{c}」' for e, c in suspects))
    return {'nodes': len(tree), 'claimed': claimed, 'external': external,
            'registered': len(to_reg), 'obsolete': len(obsolete), 'suspects': suspects,
            'db': db_id}


def adopt(dry=False, quiet=False, space_title=None, force=False):
    """★ 统一入口：判形态 → 分派 fresh/hybrid/foreign。返回 dict。"""
    mode, info = detect_mode()
    if mode == 'unknown':
        print(f'❌ 无法判定账号形态：{info.get("reason")}——不建、不搬、不动')
        raise SystemExit(2)
    if mode == 'foreign' and not force:
        print(f'❌ 这个空间不像本生态的（顶层 {info["nodes"]} 节点，无生态指纹）。')
        print('   为免在别人的空间里建一整套夹，已停止。确认要接管请加 --force。')
        raise SystemExit(3)
    if mode in ('fresh', 'foreign'):
        print(f'账号形态：{"fresh（新账号，全空白）" if mode == "fresh" else "foreign（--force 接管）"}')
        r = ensure_library(dry=dry, quiet=quiet, space_title=space_title)
        r['mode'] = mode
        return r
    print(f'账号形态：hybrid（老账号，顶层 {info["nodes"]} 节点，'
          f'指纹 {"、".join(info["fingerprint"])}）')
    r = ensure_library(dry=dry, quiet=quiet, space_title=space_title)
    stock = _adopt_stock(dry=dry, quiet=quiet)
    r.update({'mode': 'hybrid', 'stock': stock})
    return r


def cmd_adopt(a):
    # ★ v2.6.0（A6）：adopt --force 同样必须带 reason——强行接管是本脚本最大的写动作，必须留痕。
    if getattr(a, 'force', False) and not (getattr(a, 'reason', '') or '').strip():
        print('  ❌ adopt --force 必须配 --reason：强行接管要写进审计，后人要能查到"当时为什么放行"')
        return 2
    rc = 0
    try:
        adopt(dry=a.dry_run, space_title=a.space_title, force=a.force)
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 2
    if getattr(a, 'force', False):
        try:
            _audit_force('adopt --force', f'space_title={a.space_title or "(动态发现)"}', a.reason)
        except SystemExit:
            pass                      # 审计写不进去不改变主流程结果，但主流程自己已报过
    return rc
    return 0


def cmd_ensure(a):
    # ★ v2.6.0（A5）：迁移锁——两会话并发跑 ensure 会撞出半成品蓝图（MP DB_MIGRATION_LOCK 形态）。
    try:
        _lock = _ensure_lock()
    except SystemExit as e:
        print(f'  ⛔ 另一个 ensure/adopt 正在执行（锁超 {_ENSURE_LOCK_TIMEOUT:.0f}s）——已拒绝：{e}')
        return 2
    try:
        ensure_library(dry=a.dry_run, space_title=a.space_title)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    finally:
        try:
            import fcntl
            fcntl.flock(_lock, fcntl.LOCK_UN)
        except Exception:
            pass
        _lock.close()
    return 0


# ══════════════════ 生态演化台账（v2.4.0）══════════════════
# 固定分类「🧬 生态演化」在 base_blueprint.json 里声明，新机首次 ensure 即带。
# 这里只负责"往里写一条"：哪一版、哪天、增加了什么、证据在哪——可逐版追溯。
# 数据源全部是可实证的：VERSION / MANIFEST.changelog_<ver> / 已装技能快照。
EVOLVE_ROOT = '🧬 生态演化'
EVOLVE_DB = '版本演化台账'


def _repo_version(explicit=''):
    """版本号：显式 > 部署标记（install.sh 写入）> 当前目录 VERSION > 仓库 VERSION。"""
    if explicit:
        return explicit.strip()
    for p in (os.path.expanduser('~/.codebuddy/.520_state/version'),
              os.path.join(os.getcwd(), 'VERSION'),
              os.path.join(HERE, '..', '..', '..', '..', 'VERSION')):
        try:
            v = open(p, encoding='utf-8').read().strip()
            if v:
                return v
        except Exception:
            continue
    return ''


def _skills_snapshot():
    """已装技能快照 {技能目录名: 版本}。版本读 SKILL.md frontmatter。

    为什么要快照而不是只看 VERSION：VERSION 只说明"生态整体到哪一版"，
    回答不了"这版增加了哪些能力"。快照做差集才是用户真正问的那句"增加了啥"。
    """
    snap = {}
    if not os.path.isdir(SKILLS_DIR):
        return snap
    for n in sorted(os.listdir(SKILLS_DIR)):
        p = os.path.join(SKILLS_DIR, n, 'SKILL.md')
        v = ''
        if os.path.isfile(p):
            try:
                head = open(p, encoding='utf-8', errors='ignore').read(800)
                m = re.search(r'^version:\s*"?([^"\n]+)"?', head, re.M)
                v = m.group(1).strip() if m else ''
            except Exception:
                v = ''
        snap[n] = v or '未知'
    return snap


def _snap_hash(snap):
    raw = json.dumps(snap, ensure_ascii=False, sort_keys=True)
    import hashlib
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]


def _manifest_changelog(ver, manifest=''):
    """从 MANIFEST.json 取 changelog_<ver 下划线化>，取不到返回 ''。

    注意：MANIFEST 里只到某几版有键（实测 0.8.10 无键）——取不到就如实留空，
    绝不用"暂无更新说明"这种听起来像结论的空话填。
    """
    cands = [manifest] if manifest else []
    cands += [os.path.join(os.getcwd(), 'MANIFEST.json'),
              os.path.join(HERE, '..', '..', '..', '..', 'MANIFEST.json')]
    key = 'changelog_' + (ver or '').replace('.', '_')
    for p in cands:
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        v = d.get(key)
        if isinstance(v, list):
            return '；'.join(str(x) for x in v)[:900]
        if isinstance(v, str):
            return v[:900]
    return ''


def _root_id(title):
    st = load_state()
    rid = ((st.get('blueprint') or {}).get('roots') or {}).get(title, '')
    if rid and _find_folder_by_title('', title) == rid:
        return rid
    return _find_folder_by_title('', title)


def _cloud_versions(db_id):
    """云端台账已有版本集合。None = 读不到（无法判定，不折叠为空集）。"""
    j, _ = _db_query(db_id, 'csv')
    csv = j.get('content')
    if not isinstance(csv, str):
        return None
    lines = [x for x in csv.splitlines() if x.strip()]
    if not lines:
        return set()
    out = set()
    for row in lines[1:]:
        v = row.split(',')[0].strip().strip('"')
        if v:
            out.add(v)
    return out


def cmd_evolve_log(a):
    """写一条演化记录。同版本 + 同技能快照不重复写（反复安装不算演化）。"""
    ensure_library(quiet=True)          # 固定分类必须先在：这是"新机落地即带"的落实点
    rid = _root_id(EVOLVE_ROOT)
    if not rid:
        print(f'❌ 演化根「{EVOLVE_ROOT}」不存在且自举未建成——先跑 ensure 看过错原因')
        return 2
    dbid = ''
    for n in _kids(rid):
        if n.get('kind') == 'database' and (n.get('title') or '').strip() == EVOLVE_DB:
            dbid = n.get('id')
            break
    if not dbid:
        print(f'❌ 台账库「{EVOLVE_DB}」不存在——先跑 ensure')
        return 2

    ver = _repo_version(a.version)
    if not ver:
        print('❌ 版本号无法判定（无 --version、无部署标记、无 VERSION 文件）——拒绝写空版本记录')
        return 2
    # ★ 去重以**云端台账**为准，不能只看本地 state：换机/重装后 state 是空的，
    #   只看本地会把同一版本重复记成"首次落地"（实测踩到：两份 state 各记一条 0.8.10）。
    cloud_vers = _cloud_versions(dbid)
    if cloud_vers is None:
        print('  ⚠️ 云端台账读取失败（无法判定是否已记）——本次按新记录写入')
    elif ver in cloud_vers:
        print(f'ℹ️ {ver} 已在云端台账（{dbid}），不重复记')
        return 0
    snap = _skills_snapshot()
    h = _snap_hash(snap)
    st = load_state()
    last = st.get('evolve_last') or {}
    logs = st.setdefault('evolve_log', [])
    # 去重：版本 + 快照都没变 → 这不算一次演化
    if any(x.get('version') == ver and x.get('hash') == h for x in logs):
        print(f'ℹ️ {ver}（快照 {h}）已在台账，重复安装不重复记')
        return 0

    prev = (last.get('skills') or {})
    added = [k for k in snap if k not in prev]
    removed = [k for k in prev if k not in snap]
    changed = [f'{k} {prev[k]}→{snap[k]}' for k in snap
               if k in prev and prev[k] != snap[k]]
    if not prev:
        kind = '首次落地'
        delta = f'首装 {len(snap)} 个技能'
    else:
        kind = a.type or '升级'
        parts = []
        if added:
            parts.append('新增 ' + '、'.join(added))
        if removed:
            parts.append('移除 ' + '、'.join(removed))
        if changed:
            parts.append('升级 ' + '、'.join(changed))
        delta = '；'.join(parts) or '技能面未变'

    summary = a.summary or _manifest_changelog(ver, a.manifest)
    if not summary:
        summary = '（本版无登记摘要，可 `evolve-log --summary` 补一条）'
    evidence = a.evidence or f'VERSION={ver} · 技能快照 {h} · 技能 {len(snap)} 个'
    date = time.strftime('%Y-%m-%d')

    rec = [{'版本': {'text': ver}, '日期': {'date': date}, '类型': {'text': kind},
            '新增能力': {'text': delta}, '变更摘要': {'text': summary},
            '证据': {'text': evidence}}]
    ok, tag, pl, raw = _db_add_records(dbid, rec)
    if ok != len(rec):
        why = pl.get('error') or pl.get('code') or raw[:240]
        print(f'❌ 台账写入失败：{tag or "无状态行"} {why}')
        return 2
    logs.append({'version': ver, 'hash': h, 'date': date, 'kind': kind,
                 'delta': delta, 'db': dbid})
    st['evolve_last'] = {'version': ver, 'hash': h, 'skills': snap,
                         'at': time.strftime('%Y-%m-%d %H:%M')}
    save_state(st)
    print(f'✅ 演化已记账：{ver}｜{kind}｜{delta}')
    print(f'   → {EVOLVE_ROOT}/{EVOLVE_DB}（{dbid}）')
    return 0


def cmd_evolve_view(a):
    """打印演化时间线（本地账 + 云端台账对照）。--md 生成文档落演化根。"""
    st = load_state()
    logs = st.get('evolve_log') or []
    if not logs:
        print('ℹ️ 本地无演化记录（还没跑过 evolve-log）')
        return 0
    print(f'🧬 生态演化（{len(logs)} 条，来自本地账）')
    for x in logs:
        print(f'  · {x.get("date","")}  {x.get("version",""):8}  [{x.get("kind","")}]  {x.get("delta","")}')
    if getattr(a, 'md', False):
        rid = _root_id(EVOLVE_ROOT)
        if not rid:
            print('❌ 演化根不存在，无法落盘'); return 2
        md = ['# 🧬 生态演化台账', '',
              f'生成时间：{time.strftime("%Y-%m-%d %H:%M")}', '',
              '| 日期 | 版本 | 类型 | 增加了什么 |', '|---|---|---|---|']
        for x in logs:
            md.append(f'| {x.get("date","")} | {x.get("version","")} | {x.get("kind","")} | {x.get("delta","")} |')
        p = os.path.join(OUT_DIR, f'生态演化_{time.strftime("%Y%m%d")}.md')
        open(p, 'w', encoding='utf-8').write('\n'.join(md) + '\n')
        print(f'📄 已生成：{p}（可用 archive --file 落库）')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='space_hub.py')
    sub = ap.add_subparsers(dest='cmd', required=True)
    ini = sub.add_parser('init', help='★登记/查看目标空间（换账号后的第一条命令）')
    ini.add_argument('--list', action='store_true', help='列出当前账号可访问的全部空间')
    ini.add_argument('--space-id', default='', help='显式登记 space id（校验必须在可访问列表内）')
    ini.add_argument('--title', default='', help='按标题登记（须唯一命中可写空间）')
    cl = sub.add_parser('classify', help='★归纳：根层级散落文档按登记册归入目标夹')
    cl.add_argument('--dry-run', action='store_true', dest='dry_run', help='仅预览方案，不移动')
    cl.add_argument('--yes', action='store_true', help='确认执行（移动节点，不可静默）')
    cl.add_argument('--show-skipped', action='store_true', help='列出跳过项及原因')
    db = sub.add_parser('create-db', help='★建库：薄封装 library 建库正本（schema JSON）+ 写后回读')
    db.add_argument('--schema-file', default='', help='schema JSON 文件路径')
    db.add_argument('--schema', default='', help='schema JSON 字面量')
    db.add_argument('--stdin', action='store_true', help='从 stdin 读 schema JSON')
    db.add_argument('--parent', default='', help='父节点 id（缺省=空间根）')
    db.add_argument('--dry-run', action='store_true', dest='dry_run', help='仅校验 schema 并预览，不写')
    db.add_argument('--yes', action='store_true', help='确认执行写动作')
    sub.add_parser('inbox')
    ad = sub.add_parser('add')
    ad.add_argument('--node', required=True)
    ad.add_argument('--reason', default='')
    ad.add_argument('--force', action='store_true',
                    help='跳过"非空/像备份"保护（S158 护栏）。**明确承担被整批删除的风险**')
    sc = sub.add_parser('scan')
    sc.add_argument('--dry-run', action='store_true', dest='dry_run',
                    help='仅预览候选垃圾，不实际移动到收件箱')
    sc.add_argument('--dedup', type=int, default=0, metavar='N',
                    help='把「同父同名且份数>N」的多余副本投递收件箱（保留最早一份）。'
                         '默认 0=只告警不投。S158 加：根层级有 26 份同名留档文档，'
                         '旧行为永远只告警，越积越乱')
    _lp = sub.add_parser('list')
    _lp.add_argument('--no-verify', dest='no_verify', action='store_true',
                     help='跳过服务端位置校验（默认逐项核 parentId，剔除已迁出的陈旧项）')
    cs = sub.add_parser('census')
    cs.add_argument('--json', action='store_true',
                    help='额外落盘 JSON 明细（/workspace/S158_大生态分层普查.json）')
    rs = sub.add_parser('restore')
    rs.add_argument('--node', required=True)
    rs.add_argument('--target', default='', help='无原位记录时，手动指定回退到的父节点ID')
    mo = sub.add_parser('move')
    mo.add_argument('--node', required=True)
    mo.add_argument('--to', required=True, help='目标父文件夹节点 ID')
    rn = sub.add_parser('rename')
    rn.add_argument('--node', required=True)
    rn.add_argument('--title', required=True)
    lr = sub.add_parser('local-rm', help='★销账：本地欠账已人工处置，从清单移除（--path 前缀 / --all 全清）')
    lr.add_argument('--path', default='', help='按路径前缀匹配销账')
    lr.add_argument('--all', action='store_true', help='销全部本地欠账')
    ar = sub.add_parser('archive', help='★产物落库正门（B-09）：上传📦产物归档夹+写索引+本地清理')
    ar.add_argument('--file', required=True, help='本地产物文件路径')
    ar.add_argument('--category', default='', help='类别（缺省按扩展名猜：面板/文档/清单/数据/图片）')
    ar.add_argument('--source', default='', help='来源说明（哪个技能/任务产出）')
    ar.add_argument('--note', default='', help='说明（批次/条数/结论等，进索引"说明"列）')
    ar.add_argument('--keep', action='store_true', help='保留本地文件（默认落库成功后删除本地）')
    pr = sub.add_parser('products', help='★产物盘点+搜索框（B-09 配套）')
    pr.add_argument('--scan', action='store_true', help='盘点已落库+本地产物区现存（只打印不落盘）')
    pr.add_argument('--search-box', action='store_true', dest='search_box',
                    help='生成单文件 HTML 搜索框（点名交付物）')
    pr.add_argument('--retry', action='store_true',
                    help='★补偿通道：把 pending 里的待归档产物重新提交归档（断网/失败后补齐）')
    en = sub.add_parser('ensure', help='★库房自举：按蓝图收敛（认领已有 + 补建缺失 + 回读），幂等')
    en.add_argument('--dry-run', action='store_true', help='只打印将建什么，不写云端')
    en.add_argument('--space-title', default='', help='蓝图缺省空间标题（仅自动建空间时用）')
    ad_ = sub.add_parser('adopt', help='★账号接管：判 fresh/hybrid/foreign → 建齐 或 接管存量（登记不搬）')
    ad_.add_argument('--dry-run', action='store_true', help='只报告，不写入（不建夹/不建库/不登记）')
    ad_.add_argument('--force', action='store_true', help='空间不像本生态时仍强行接管（默认拒绝）')
    ad_.add_argument('--reason', default='', help='--force 时必填：强行接管的理由，写进审计')
    ad_.add_argument('--space-title', default='', help='蓝图缺省空间标题（仅自动建空间时用）')
    eg = sub.add_parser('evolve-log', help='★演化记账：写一条版本演化记录（版本/日期/类型/新增能力/摘要/证据）')
    eg.add_argument('--version', default='', help='版本号（缺省读部署标记/VERSION）')
    eg.add_argument('--type', default='', help='类型（缺省按有无上次快照判：首次落地/升级）')
    eg.add_argument('--summary', default='', help='变更摘要（缺省从 MANIFEST.changelog_<ver> 取）')
    eg.add_argument('--evidence', default='', help='证据（提交号/文件/链接）')
    eg.add_argument('--manifest', default='', help='MANIFEST.json 路径（缺省自动找）')
    ev = sub.add_parser('evolve-view', help='★演化时间线（本地账汇总；--md 另出文档）')
    ev.add_argument('--md', action='store_true', help='生成 md 到产物区（可再用 archive 落库）')
    a = ap.parse_args(argv)
    # ensure / evolve-* 自己处理空间（ensure 会在"零可写空间"时自动建），不能预跑解析
    if a.cmd not in ('init', 'local-rm', 'products', 'ensure', 'evolve-log', 'evolve-view'):
        resolve_space(quiet=True)   # 除纯本地账与自举类命令外，先过四层空间解析
    return {'init': cmd_init, 'classify': cmd_classify, 'create-db': cmd_create_db,
            'inbox': cmd_inbox, 'add': cmd_add, 'scan': cmd_scan,
            'list': cmd_list, 'census': cmd_census,
            'restore': cmd_restore, 'move': cmd_move, 'rename': cmd_rename,
            'local-rm': cmd_local_rm, 'archive': cmd_archive,
            'products': cmd_products, 'ensure': cmd_ensure, 'adopt': cmd_adopt,
            'evolve-log': cmd_evolve_log, 'evolve-view': cmd_evolve_view}[a.cmd](a)


def dispatch(argv=None):
    """供调度器 tvbox 在同进程内直接调用（与 blk/evolve/link 同契约）。"""
    return main(list(argv or []))


if __name__ == '__main__':
    raise SystemExit(main())
