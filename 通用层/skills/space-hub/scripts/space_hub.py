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
  janitor render                      把清单重写进收件箱内的说明文档
  janitor move --node ID --to 父节点ID              节点移动到指定文件夹（改名/归位通用）
  janitor rename --node ID --title "新标题"         节点改名

铁律：
  · 只移动、不删除（AI 无删除权）；移动前**校验节点确实存在**。
  · 清单**永不静默丢项**：节点不存在/移动失败 → 显式告警并保留在清单（标"待人工确认"）。
  · 幂等：同一节点重复 add 不重复登记（按 node_id 去重）。
"""
import os, sys, json, argparse, subprocess, time, re

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
    'tBlgSL4SPEFMrsyTBTg03c': ('tvbox-janitor', '🗑 待删收件箱'),
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
    """
    try:
        with open(STATE, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
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
    st = load_state()
    iid = st.get('inbox') or _find_inbox()[0]
    if not iid:
        print('❌ 收件箱未建，先跑 janitor inbox'); return 1
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
            print(f'  🛑 拒收：{title}（{nid}）**非空**（{len(_kids_now)} 个子节点）——'
                  f'收件箱是待删暂存，非空容器进去就有被整批删掉的风险')
            print('     → 真要投递请先手动清空，或加 --force 明确承担后果')
            return 4
        if _name_hit:
            print(f'  🛑 拒收：{title}（{nid}）空夹但名字像备份/库——**空不等于该删**'
                  f'（可能正在写入或内容在别处）')
            print('     → 确认真的废弃再加 --force')
            return 4
    # 幂等
    if any(x['id'] == nid for x in st['items']):
        print(f'ℹ️ 已在清单：{title}'); return 0
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
    st['items'].append({
        'id': nid, 'title': title, 'kind': node.get('kind', ''),
        'reason': a.reason or '（未注明）',
        'moved': ok, 'added': time.strftime('%Y-%m-%d %H:%M'),
        'origin_parent': origin,
    })
    save_state(st)
    print(f'  {"✅ 已移入收件箱" if ok else "⚠️ 移动失败（清单仍登记）"}：{title}（{nid}）')
    if not ok and mv:
        print(f'     原因：{str(mv.get("error"))[:120]}')
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


def _probe_empty_databases(items, control_id='Xjqn2Wf5EKPSGIXqQ2K6Dc'):
    """对清单里的 database 项逐个直连核实：真的空，还是只是读不到。

    返回 {'lines': [头部说明行], 'by_id': {id: 每项结论短语}}

    ★ 判据来自 `database/get_database_content.py`：它返回的 `content` 是 CSV 文本，
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
    try:
        # ★ 显式路径，不靠调用者预先污染 sys.path。
        #   实测教训：经 `tvbox janitor list` 跑时成功，直接 `import janitor` 调则
        #   ModuleNotFoundError——因为 core 在 source-hub/scripts，而 tvbox 入口
        #   恰好先 import 过它。**依赖调用者的副作用 = 换个入口就变行为**。
        _hub_scripts = os.path.expanduser('~/.codebuddy/skills/space-hub/scripts')  # 旧 tvbox-source-hub 已并入 tvbox-core/库务司
        if _hub_scripts not in sys.path:
            sys.path.insert(0, _hub_scripts)
        import core as _core
    except Exception as e:
        out['lines'] = [f'> ⚠️ 数据库核实跳过：无法加载 library core（{type(e).__name__}）——'
                        f'**下列数据库是否为空未经验证**，删除前请自行确认。']
        return out

    def _rows(did):
        ok, so, se = _core._run_lib('database/get_database_content.py', '--database-id', did)
        if not ok:
            return None, (se or 'run_lib 失败')[:80]
        try:
            c = json.loads(so).get('content') or ''
        except Exception as e:
            return None, f'返回解析失败 {type(e).__name__}'
        return len([x for x in c.split('\n') if x.strip()]), ''

    ctl, ctl_err = _rows(control_id)
    trusted = bool(ctl and ctl > 1)
    if trusted:
        out['lines'] = [f'> **数据库类 {len(dbs)} 项已逐个直连核实**（对照组 `账房·总账` 读出 '
                        f'{ctl - 1} 条记录，证明该通路能读到数据，不是"读不到一律算空"）。'
                        f'删库**不可逆**，故单列依据。']
    else:
        out['lines'] = [f'> ⚠️ **数据库核实不可信**：对照组只读出 {ctl} 行（应为 >1），'
                        f'{ctl_err or "通路可能读不到数据"}——'
                        f'下方各库的"空"**不能作为删除依据**，请手工确认。']

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
                out['by_id'][x['id']] = '（⚠️ 读到 0 条，但对照组也读不到，**无法判定**）'
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


def cmd_render(a):
    """把清单重写进收件箱内的说明文档（需知道文档 node-id）。"""
    print('（render：清单文档由 list 生成 Markdown，可用 create-doc 手动更新收件箱说明）')
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
    """反查节点的真实父节点。node-info 的 parentNodeId 实测恒为 None（不可信），
    故走全树遍历 _find_parent。返回 '' 表示查不到（调用方必须显式报，不许当"根"）。"""
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
        print(f'❌ 节点不存在或不可读（{nid}）——不移动（M-R60 如实报）')
        return 1
    tinfo = _space('space.workspace.node-info', node_id=target) if target else None
    tnode = ((tinfo or {}).get('data') or {}).get('node') or {}
    if not tnode.get('id') and not tnode.get('title'):
        print(f'❌ 目标父节点不存在（{target}）——不移动')
        return 1
    if tnode.get('kind') and tnode.get('kind') != 'folder':
        print(f'❌ 目标不是文件夹（{target} kind={tnode.get("kind")}）——不移动')
        return 1
    src = _node_parent(nid)
    mv = _space('space.workspace.move-node', node_id=nid, target_parent_id=target)
    if not mv or mv.get('error'):
        print(f'❌ 移动失败：{str((mv or {}).get("error"))[:160] or "无响应"}')
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
        print(f'⚠️ 服务端回报成功，但目标文件夹 {target} 下**未枚举到** {nid}'
              f'——疑似索引延迟或移动未落地，请复核（不当作成功）')
        return 3
    print(f'✅ 已移动：{title}（{nid}）\n   从 {src or "（未知，全树未反查到）"} → {target}')
    return 0


def cmd_rename(a):
    """★ 节点改名（v1.2.0）：移后回读标题，改不动不许说改好了。"""
    nid = a.node
    new = (a.title or '').strip()
    if not new:
        print('❌ 新标题不能为空'); return 1
    info = _space('space.workspace.node-info', node_id=nid)
    node = ((info or {}).get('data') or {}).get('node') or {}
    old = node.get('title') or ''
    if not old:
        print(f'❌ 节点不存在或不可读（{nid}）——不改名')
        return 1
    r = _space('space.workspace.rename-node', node_id=nid, title=new)
    if not r or r.get('error'):
        print(f'❌ 改名失败：{str((r or {}).get("error"))[:160] or "无响应"}')
        return 1
    back = _space('space.workspace.node-info', node_id=nid)
    now = (((back or {}).get('data') or {}).get('node') or {}).get('title') or ''
    if now != new:
        print(f'⚠️ 服务端未报错，但回读标题仍是「{now}」（期望「{new}」）'
              f'——不当作成功，请复核')
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


def _index_add(db_id, name, cat, date, source, note):
    """写一条索引记录（library 正本 batch_add_database_records）+ 回读容错。"""
    rec = [{'名称': {'text': name}, '类别': {'text': cat}, '日期': {'text': date},
            '来源': {'text': source}, '说明': {'text': note}}]
    r = subprocess.run([sys.executable, f'{LIB}/database/batch_add_database_records.py',
                        '--database-id', db_id, '--records', json.dumps(rec, ensure_ascii=False)],
                       capture_output=True, text=True)
    out = (r.stdout or '') + (r.stderr or '')
    if 'error' in out.lower() and 'KS_' not in out:
        print(f'  ⚠️ 索引记录写入疑似失败（文件本体已落库）：{out[:160]}')
        return False
    return True


def cmd_archive(a):
    """★ 产物落库正门（B-09）：上传「📦 产物归档」夹 + 写索引记录 + 本地清理。

    流程全走 library 正门（create_folder / upload_drive_file / create_database /
    batch_add_database_records），每步写后回读；落库成功后本地文件默认删除
    （产物区不再堆积），--keep 显式保留。"""
    resolve_space()
    p = os.path.abspath(os.path.expanduser(a.file))
    if not os.path.isfile(p):
        print(f'❌ 文件不存在：{p}'); return 1
    name = os.path.basename(p)
    cat = a.category or _guess_cat(name)
    fid = _ensure_archive_folder()
    if not fid:
        print('❌ 产物归档夹不可用'); return 2
    # ① 传文件（独立 drive 节点，import-local-file 正门）
    r = subprocess.run([sys.executable, f'{LIB}/drive/upload_drive_file.py',
                        p, '--parent-id', fid, '--space-id', SPACE],
                       capture_output=True, text=True)
    out = (r.stdout or '') + (r.stderr or '')
    node_id = ''
    for ln in out.splitlines():
        if 'KS_DRIVE_UPLOAD_OK' in ln or 'KS_IMPORT' in ln:
            payload = ln.split('\t', 1)[1] if '\t' in ln else ln.split(' ', 1)[1]
            try:
                j = json.loads(payload)
                node_id = j.get('node_id') or j.get('node_block_id') or j.get('nodeId') or ''
            except Exception:
                pass
    if not node_id:
        # 输出可能就是一段 JSON（无 KS 行）
        try:
            j = json.loads(out.strip().splitlines()[-1])
            node_id = j.get('node_id') or j.get('node_block_id') or j.get('nodeId') or ''
        except Exception:
            pass
    # 写后回读：归档夹枚举中必须见到该节点。
    # ★S200 同款：新建节点后服务端目录索引有传播延迟（实测首查即 miss）——
    #   带间隔重试 3 次（3s/档），再失败才按未落库处理，不静默、不瞎删本地。
    kids_ids = set()
    for _i in range(3):
        kids_ids = {n.get('id') for n in _kids(fid)}
        if node_id and node_id in kids_ids:
            break
        time.sleep(3)
    if not node_id or node_id not in kids_ids:
        print(f'❌ 上传失败或回读不符（按未落库处理，本地文件保留）：{out[:200]}')
        return 2
    print(f'  ✅ 文件已落库并回读确认：{name}（{node_id}）')
    # ② 索引记录
    db_id = _ensure_index_db(fid)
    st = load_state()
    entry = {'name': name, 'cat': cat, 'node_id': node_id, 'db': db_id,
             'date': time.strftime('%Y-%m-%d'), 'source': a.source or '（未注明）',
             'note': a.category and '' or ''}
    if db_id:
        entry['indexed'] = _index_add(db_id, name, cat, entry['date'],
                                      entry['source'], a.source and '' or '')
    # ③ 登记历史（搜索框数据源）+ ④ 本地处置
    st.setdefault('archive_log', []).append(entry)
    save_state(st)
    if a.keep:
        print('  📎 --keep：本地文件保留')
    else:
        try:
            os.remove(p)
            print(f'  🧹 本地已清理（产物区不再堆积）：{p}')
        except Exception as e:
            print(f'  ⚠️ 本地清理失败（{type(e).__name__}）——文件已落库，可手动删：{p}')
    print(f'{{已存至 {SPACE_TITLE_OR_FALLBACK()}/{ARCHIVE_TITLE}/{name}}}')
    return 0


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
    """汇总产物索引：已落库（archive_log）+ 本地产物区现存（OUT_DIR 顶层文件）。"""
    st = load_state()
    rows = [{'name': x.get('name', ''), 'cat': x.get('cat', ''), 'date': x.get('date', ''),
             'source': x.get('source', ''), 'where': '已落库',
             'id': x.get('node_id', '')} for x in (st.get('archive_log') or [])]
    for fn in sorted(os.listdir(OUT_DIR)):
        p = os.path.join(OUT_DIR, fn)
        if os.path.isfile(p):
            sz = os.path.getsize(p)
            rows.append({'name': fn, 'cat': _guess_cat(fn), 'date': time.strftime(
                '%Y-%m-%d', time.localtime(os.path.getmtime(p))), 'source': '本地产物区',
                'where': f'本地 {sz}B', 'id': ''})
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
        fid = _find_folder_by_title('', t)
        if not fid:
            fid = _create_folder(t, '')
            if not fid:
                print(f'⚠️ 目标夹「{t}」创建失败 → 该组 {len(items)} 项**保持原位**（不漏项，铁律2）')
                continue
        for nid, title in items:
            rc = cmd_move(argparse.Namespace(node=nid, to=fid))
            if rc == 0:
                moved += 1
    print(f'✅ 归纳完成：移动 {moved}/{sum(len(v) for v in plan.values())} 项')
    return 0


def _create_db_api(sc):
    """调 library 建库正本（create_database.py --stdin）+ 多行 JSON 解析 + 父容器回读。
    返回 (db_id, err)。M-R38 单一实现：cmd_create_db 与 _ensure_index_db 共用（B-08 不自造）。"""
    r = subprocess.run([sys.executable, f'{LIB}/database/create_database.py', '--stdin'],
                       input=json.dumps(sc, ensure_ascii=False), capture_output=True, text=True)
    out = (r.stdout or '').strip()
    # 正本输出可能是多行 pretty JSON——整体解析，失败再退化到逐行找首个完整 '{' 块
    try:
        j = json.loads(out)
    except Exception:
        buf, j = '', None
        for ln in out.splitlines():
            if ln.strip().startswith('{') and not buf:
                buf = ln
            elif buf:
                buf += '\n' + ln
            if buf:
                try:
                    j = json.loads(buf)
                    break
                except Exception:
                    continue
        j = j or {}
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
    print(f'   → 后续写记录走 library 正本：database/batch_add_database_records.py')
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
    sub.add_parser('render')
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
    ar.add_argument('--keep', action='store_true', help='保留本地文件（默认落库成功后删除本地）')
    pr = sub.add_parser('products', help='★产物盘点+搜索框（B-09 配套）')
    pr.add_argument('--scan', action='store_true', help='盘点已落库+本地产物区现存（只打印不落盘）')
    pr.add_argument('--search-box', action='store_true', dest='search_box',
                    help='生成单文件 HTML 搜索框（点名交付物）')
    a = ap.parse_args(argv)
    if a.cmd not in ('init', 'local-rm', 'products'):
        resolve_space(quiet=True)   # 除 init / local-rm / products（纯本地账，不依赖云端）外，先过四层空间解析
    return {'init': cmd_init, 'classify': cmd_classify, 'create-db': cmd_create_db,
            'inbox': cmd_inbox, 'add': cmd_add, 'scan': cmd_scan,
            'list': cmd_list, 'render': cmd_render, 'census': cmd_census,
            'restore': cmd_restore, 'move': cmd_move, 'rename': cmd_rename,
            'local-rm': cmd_local_rm, 'archive': cmd_archive,
            'products': cmd_products}[a.cmd](a)


def dispatch(argv=None):
    """供调度器 tvbox 在同进程内直接调用（与 blk/evolve/link 同契约）。"""
    return main(list(argv or []))


if __name__ == '__main__':
    raise SystemExit(main())
