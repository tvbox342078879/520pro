#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inspect_hub.py — 520 巡检司引擎（登记册驱动 · 八卦八门面板）

用法:
  python3 inspect_hub.py run [--target <520pro 根目录>] [--out <输出目录>]
  python3 inspect_hub.py self-check

设计四件套（继承旧监察司思想，去 TVBox 化）:
1. 登记册可成长 —— inspect_registry.json 加巡检面零改引擎；impl=null 的门=灰色在册待补。
2. 健康预检 —— 引擎/登记册/扫描器自身失灵时该门报「unknown 无法判定」，绝不装绿（三态铁律）。
3. 报告环比 —— findings_history.json 落指纹，下期自动标 🆕新增 / ✅已清零 / ♻️持续。
4. 面板即产物 —— 巡检结果注入单文件 dashboard.html（卦门合阵模板，纯 CSS 自适应，
   手机/电脑双端可开），数据内嵌零外部依赖。

两层生效判定（关键纪律）:
- 结构生效（本脚本查）: 文件在不在、指纹对不对、清点齐不齐。
- 行为生效（AI 自报对账，SKILL.md 强制流程）: 本会话技能清单/规则注入实况，
  脚本查不了，必须由 AI 在体检对话里自报并与结构层结果对账，对不上=红。
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REG_PATH = os.path.join(SCRIPT_DIR, 'inspect_registry.json')
HIST_PATH = os.path.join(SCRIPT_DIR, 'findings_history.json')
MON_PATH = os.path.join(SCRIPT_DIR, 'monitors.json')
RUNTIME_FILES = {'findings_history.json', 'monitors.json'}   # 运行时数据，不参与副本对账
# 另：*_state.json（各技能运行态登记，如 space_hub_state.json）同样排除——机制级规则，防新技能重复踩   # 运行时监测登记（与正本登记册分离：登记是运行态，不是正本知识，避免生门误报副本漂移）

ST_ORDER = {'red': 0, 'yellow': 1, 'unknown': 2, 'green': 3, 'pending': 4}
ST_LABEL = {'red': '🔴 有事', 'yellow': '🟡 观察', 'green': '🟢 正常',
            'pending': '⚪ 在册待补', 'unknown': '⚪ 无法判定'}


# ---------- 工具 ----------
def md5f(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def expand(p):
    return os.path.expanduser(p)


def worst(statuses):
    return min(statuses, key=lambda s: ST_ORDER.get(s, 9)) if statuses else 'unknown'


def repo_skills(target):
    """仓库内全部技能（通用层/skills/* + 能力层/tvbox/skills/*，以 SKILL.md 为准）。"""
    out = []
    for base in ('通用层/skills', '能力层/tvbox/skills'):
        d = os.path.join(target, base)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            sk = os.path.join(d, name)
            if os.path.isfile(os.path.join(sk, 'SKILL.md')):
                out.append((name, sk))
    return out


# ---------- 检查器（与登记册 impl 字段对应） ----------
def chk_rules(target, cfg, ctx):
    items, sts = [], []
    user = expand(cfg['user_rules'])
    repo_copy = os.path.join(target, cfg['repo_copy'])
    if os.path.isfile(user):
        if os.path.isfile(repo_copy):
            if md5f(user) == md5f(repo_copy):
                items.append({'t': '【绿】用户级规则与仓库正本指纹一致', 'e': cfg['user_rules'] + ' md5=' + md5f(user)[:8], 'c': '无需处置'})
                sts.append('green')
            else:
                items.append({'t': '【红】规则副本与仓库正本指纹不一致（疑似装到旧副本）',
                              'e': user + ' md5=' + md5f(user)[:8] + ' ≠ ' + cfg['repo_copy'] + ' md5=' + md5f(repo_copy)[:8],
                              'c': '重跑 bootstrap.sh 后【开新会话】验证'})
                sts.append('red')
        else:
            items.append({'t': '【黄】仓库正本缺失，无法对账', 'e': cfg['repo_copy'] + ' 不存在', 'c': '核对登记路径'})
            sts.append('yellow')
    else:
        items.append({'t': '【红】用户级规则缺失', 'e': user + ' 不存在（规则注入无从谈起）', 'c': 'bash bootstrap.sh 补装'})
        sts.append('red')
    pdir = os.path.join(target, cfg['project_dir'])
    if os.path.isdir(pdir):
        n = len(glob.glob(os.path.join(pdir, '*.md')))
        items.append({'t': '【绿】项目级规则目录在位', 'e': cfg['project_dir'] + ' 含 ' + str(n) + ' 个规则文件', 'c': '无需处置'})
        sts.append('green')
    else:
        items.append({'t': '【黄】项目级规则目录未装（用户级模式属正常）', 'e': pdir + ' 不存在', 'c': '按部署形状确认是否需要'})
        sts.append('yellow')
    items.append({'t': '【提示】行为生效层须由 AI 自报对账', 'e': '文件在 ≠ 本会话注入发生；AI 体检时须自报当前会话可见的 520 规则清单',
                  'c': '见 SKILL.md 行为生效流程（规则只在会话构建时注入，改规则必须开新会话）'})
    return {'status': worst(sts), 'items': items}


def chk_skills(target, cfg, ctx):
    items, sts = [], []
    root = expand(cfg['install_root'])
    repo = repo_skills(target)
    if not repo:
        return {'status': 'unknown', 'items': [{'t': '【白】仓库内未发现任何技能', 'e': target, 'c': '核对 --target 是否指向 520pro 根目录'}]}
    ok_n = 0
    for name, sk in repo:
        inst = os.path.join(root, name, 'SKILL.md')
        src = os.path.join(sk, 'SKILL.md')
        if not os.path.isfile(inst):
            items.append({'t': '【红】技能未安装: ' + name, 'e': inst + ' 缺失（当前会话叫不动它）', 'c': 'bash bootstrap.sh --target ' + target})
            sts.append('red')
            continue
        if md5f(inst) != md5f(src):
            items.append({'t': '【黄】SKILL.md 副本与正本不一致: ' + name, 'e': 'install md5=' + md5f(inst)[:8] + ' repo md5=' + md5f(src)[:8], 'c': '重装该技能后开新会话'})
            sts.append('yellow')
            continue
        ok_n += 1
        # 脚本级对账（有 scripts 的技能逐个 md5）
        bad = []
        sdir = os.path.join(sk, 'scripts')
        if os.path.isdir(sdir):
            idir = os.path.join(root, name, 'scripts')
            for f in os.listdir(sdir):
                if not f.endswith(('.py', '.json')):
                    continue
                # 运行时数据不入对账（每台机器各自演化，与正本必然不同）：
                # 否则生门永久误报「副本漂移」，真漂移被假黄淹没
                if f in RUNTIME_FILES or f.endswith('_state.json'):
                    continue
                a, b = os.path.join(sdir, f), os.path.join(idir, f)
                if not os.path.isfile(b) or md5f(a) != md5f(b):
                    bad.append(f)
        if bad:
            items.append({'t': '【黄】脚本副本漂移: ' + name, 'e': ', '.join(bad) + ' 与正本不一致', 'c': '重装该技能'})
            sts.append('yellow')
        else:
            items.append({'t': '【绿】' + name + ' 安装副本全量对账一致', 'e': root + '/' + name, 'c': '无需处置'})
            sts.append('green')
    for name, _ in repo:
        for f in glob.glob(os.path.join(root, name, '**', '*.bak'), recursive=True):
            items.append({'t': '【黄】.bak 残留污染安装目录: ' + name, 'e': f, 'c': '删除 .bak（时序错位残留）'})
            sts.append('yellow')
    # 顶层 .bak* 目录/文件（bootstrap 反复安装留下的整技能备份，正本在 git 里可随时恢复）
    for f in glob.glob(os.path.join(root, '*.bak*')):
        items.append({'t': '【黄】skills 顶层残留备份: ' + os.path.basename(f), 'e': f, 'c': '删除（正本在仓库 git 里，可随时恢复）'})
        sts.append('yellow')
    return {'status': worst(sts), 'items': items, 'ok': ok_n, 'total': len(repo)}


def chk_secrets(target, cfg, ctx):
    scanner = os.path.join(target, cfg.get('scanner', 'secret_scan.py'))
    if not os.path.isfile(scanner):
        return {'status': 'unknown', 'items': [{'t': '【白】扫描器缺失，无法判定', 'e': scanner + ' 不存在', 'c': '确认 secret_scan.py 在仓库根'}]}
    try:
        r = subprocess.run([sys.executable, scanner, target], capture_output=True, text=True, timeout=120)
    except Exception as e:
        return {'status': 'unknown', 'items': [{'t': '【白】扫描器运行异常，无法判定', 'e': repr(e), 'c': '手动跑 python3 secret_scan.py 排查'}]}
    if r.returncode == 0:
        return {'status': 'green', 'items': [{'t': '【绿】' + (r.stdout or '无明文密钥').strip().splitlines()[-1], 'e': 'git 视角全文件 + .git/config', 'c': '无需处置'}]}
    if r.returncode == 2:
        lines = [l for l in r.stdout.splitlines() if l.strip().startswith(('✗', '   '))][:12]
        return {'status': 'red', 'items': [{'t': '【红】发现疑似明文密钥', 'e': '\n'.join(lines), 'c': '按清单逐条处置（删除或改环境变量）'}]}
    return {'status': 'unknown', 'items': [{'t': '【白】扫描器异常退出 ' + str(r.returncode), 'e': (r.stderr or '')[-200:], 'c': '手动排查'}]}


def chk_docsync(target, cfg, ctx):
    """景门 · 文档一致（v1.4.1 改为**集合比对**）。

    旧实现拿登记册里写死的 `declared` 常量比代码计数——代码加个子命令、没人改登记册，
    这面就永远红（2026-11-12 实测 space-hub 就是这样：登记 14、实况其实是 19）。
    假红比不查更坏：人一旦习惯"这面老是红的"，真吹牛就淹掉了。

    新判据两边都**现读**，不写死数字：
      文档侧：SKILL.md 里出现的 `<脚本名> <子命令>`（用户真能看到的那份清单）
      代码侧：`sub.add_parser('<cmd>')` / `sub.add_parser("<cmd>")`
      差异：文档有代码无 → 红（吹牛，用户照着敲会报错）
            代码有文档无 → 黄（漏写，用户不知道这命令存在）
    兼容：只配了 declared 的老登记仍可跑（但不再推荐）。
    """
    items, sts = [], []
    for d in cfg.get('declarations', []):
        script = os.path.join(target, d['script'])
        if not os.path.isfile(script):
            items.append({'t': '【黄】脚本缺失无法清点: ' + d['skill'], 'e': d['script'], 'c': '核对登记路径'})
            sts.append('yellow')
            continue
        code_txt = open(script, encoding='utf-8', errors='ignore').read()
        code_set = set(re.findall(d['regex'], code_txt))

        if not d.get('doc'):
            # 老口径（写死 declared）——保留可用，但结果只能说明"数字不等"，说不出差在哪
            n = len(re.findall(d['regex'], code_txt))
            ok = n == d['declared']
            items.append({'t': ('【绿】' if ok else '【红】') + d['skill'] + ' 声明与实况' + ('一致' if ok else '不符'),
                          'e': f'登记 {d["declared"]} vs 实读 {n}（老口径：只有数字，说不出差在哪）',
                          'c': '无需处置' if ok else '改 SKILL.md 或补实现，建议升级为 doc 口径'})
            sts.append('green' if ok else 'red')
            continue

        doc_path = os.path.join(target, d['doc'])
        if not os.path.isfile(doc_path):
            items.append({'t': '【黄】文档缺失无法对账: ' + d['skill'], 'e': d['doc'], 'c': '核对登记路径'})
            sts.append('yellow')
            continue
        doc_txt = open(doc_path, encoding='utf-8', errors='ignore').read()
        # 只在 ``` 代码块内抽命令：正文里 "probe" 常作普通词出现（实测 "probe tvbox 相关" 被误抓
        # 当成吹牛），而代码块里的才是用户会照抄的东西。无代码块时退回全文（老文档兼容）。
        blocks = re.findall(r'```[a-zA-Z]*\n(.*?)```', doc_txt, re.S)
        scope = '\n'.join(blocks) if blocks else doc_txt
        doc_set = set(re.findall(d['doc_regex'], scope))
        if not doc_set or not code_set:
            items.append({'t': f'【白】{d["skill"]} 两侧至少一侧抽不出命令，无法判定',
                          'e': f'文档 {len(doc_set)} 条 / 代码 {len(code_set)} 条——抽取为空时"一致"没有意义',
                          'c': '核对 doc_regex 是否匹配当前写法'})
            sts.append('unknown')
            continue

        ghost = sorted(doc_set - code_set)      # 文档有、代码无 = 吹牛（必查）
        missing = sorted(code_set - doc_set)    # 代码有、文档无 = 漏写（仅 check_missing 时查）
        # 为什么分级：命令极多的技能（probe-hub 26 个）文档只列主命令是**设计选择**，
        # 「没列全」报黄会变成几十条噪音，把真吹牛淹掉。而「写了个不存在的命令」
        # 一定是错——用户照文档敲会直接报错，无论文档该列几条。
        for c in ghost:
            items.append({'t': f'【红】{d["skill"]} 文档吹牛：写了 {c} 但代码没有',
                          'e': f'{d["doc"]} 列了 {c}，而 {d["script"]} 无此子命令',
                          'c': f'删掉文档里的 {c}，或补实现（用户照文档敲会直接报错）'})
            sts.append('red')
        for c in (missing if d.get('check_missing', True) else []):
            items.append({'t': f'【黄】{d["skill"]} 文档漏写子命令 {c}',
                          'e': f'代码有 {c}，{d["doc"]} 未列——用户不知道它存在',
                          'c': f'在文档命令节补一行 {c}；若是内部/废弃命令，应从代码删除而不是留着'})
            sts.append('yellow')
        if not ghost and (not d.get('check_missing', True) or not missing):
            extra = '' if d.get('check_missing', True) else f'；代码另有 {len(missing)} 条未列（不判）'
            # 标题里就要写清"只保证写了的都存在"——只写"都存在"会被读成"文档列全了"
            title = (f'【绿】{d["skill"]} 文档与代码命令集一致' if d.get('check_missing', True)
                     else f'【绿】{d["skill"]} 文档所写命令都存在（未列 {len(missing)} 条不判）')
            items.append({'t': title,
                          'e': f'文档 {len(doc_set)} 条全部命中代码 {len(code_set)} 条（现读两侧，无写死数字）{extra}',
                          'c': '无需处置'})
            sts.append('green')
    return {'status': worst(sts), 'items': items}


def chk_manifest(target, cfg, ctx):
    mp = os.path.join(target, cfg.get('manifest', 'MANIFEST.json'))
    if not os.path.isfile(mp):
        return {'status': 'red', 'items': [{'t': '【红】MANIFEST.json 缺失', 'e': mp, 'c': '结构真源不可无'}]}
    try:
        m = json.load(open(mp, encoding='utf-8'))
    except Exception as e:
        return {'status': 'unknown', 'items': [{'t': '【白】MANIFEST 解析失败，无法判定', 'e': repr(e), 'c': '修 JSON'}]}
    items, sts, total, miss = [], [], 0, 0
    for layer, body in (m.get('layers') or {}).items():
        for key in (body.get('files') or {}):
            total += 1
            p = os.path.join(target, layer, key)
            if not os.path.exists(p):
                miss += 1
                items.append({'t': '【红】登记文件缺失: ' + layer + '/' + key, 'e': 'MANIFEST 声称存在但文件不在', 'c': '补文件或改登记'})
                sts.append('red')
    ver = m.get('version', '?')
    items.insert(0, {'t': '【绿】MANIFEST 在位 v' + str(ver), 'e': '登记文件 ' + str(total) + ' 个，缺失 ' + str(miss), 'c': '缺失>0 时见红条目'})
    sts.insert(0, 'green')
    return {'status': worst(sts), 'items': items, 'total': total, 'missing': miss}


# 「下轮带过」执法判据（借 tvbox-eco verify/carryover_guard.py，去旧生态化）
OWNER_RE = re.compile(r'负责人|跟进人|owner', re.I)
DEADLINE_RE = re.compile(r'期限|截止|deadline|\d{4}[-/年]\d{1,2}([-/月]\d{1,2})?|周[一二三四五六日天]|前完成|前交付', re.I)


def _topic_of(line):
    """从【待】/【阻】行提取归一化主题（截到结构标点/负责人/期限前，用于复发判定）。"""
    m = re.search(r'【(?:待|阻)】\s*(.+)', line)
    t = m.group(1).strip() if m else line.strip()
    t = re.split(r'[（(]|负责人|跟进人|期限|，|。|；|;', t)[0]
    return re.sub(r'[\s：:]', '', t)[:20]


def chk_ledger(target, cfg, ctx):
    lp = os.path.join(target, cfg.get('ledger', 'docs/遗留登记.md'))
    if not os.path.isfile(lp):
        return {'status': 'yellow', 'items': [{'t': '【黄】遗留登记文件缺失', 'e': lp + ' 不存在（遗留无处登记就会烂尾）', 'c': '创建并登记当前待办'}]}
    items, sts, topics = [], [], {}
    n = 0
    for ln, line in enumerate(open(lp, encoding='utf-8', errors='ignore'), 1):
        s = line.strip()
        if s.startswith('- 【待】') or s.startswith('- 【阻】'):
            n += 1
            kind = '阻' if '【阻】' in s else '待'
            # 带过执法①：待办必须带负责人+期限，缺一即红（不许口头带过）
            missing = []
            if not OWNER_RE.search(s):
                missing.append('负责人')
            if not DEADLINE_RE.search(s):
                missing.append('期限')
            if missing:
                items.append({'t': '【红】带过违规 #' + str(n) + '：待办缺 ' + '/'.join(missing),
                              'e': '第' + str(ln) + '行：' + s[:60], 'c': '补「负责人：… / 期限：…」后重巡，或本轮清掉'})
                sts.append('red')
            elif kind == '阻':
                items.append({'t': '【红】阻塞项 #' + str(n), 'e': s[4:], 'c': '优先处置，阻塞项压总评分'})
                sts.append('red')
            else:
                items.append({'t': '【黄】遗留待办 #' + str(n) + '（有主有期）', 'e': s[4:], 'c': '到期未清会在后续巡检持续亮黄'})
                sts.append('yellow')
            # 带过执法②：同一主题出现 ≥2 次 => 复发，自动升红
            tp = _topic_of(s)
            topics[tp] = topics.get(tp, 0) + 1
    for tp, c in topics.items():
        if c >= 2 and tp:
            items.append({'t': '【红】复发条目：「' + tp + '」出现 ' + str(c) + ' 次',
                          'e': '同一事项反复带过 = 烂尾，必须本轮处置', 'c': '立即闭环或拆成有主有期的新待办'})
            sts.append('red')
    if n == 0:
        items.append({'t': '【绿】遗留清零', 'e': lp, 'c': '无需处置'})
        sts.append('green')
    return {'status': worst(sts), 'items': items, 'count': n}


def chk_freshness(target, cfg, ctx):
    th = ctx.get('thresholds', {})
    y, r = th.get('stale_yellow_days', 14), th.get('stale_red_days', 30)
    items, sts = [], []
    now = datetime.datetime.now()
    try:
        out = subprocess.run(['git', '-C', target, 'log', '-1', '--format=%ct'],
                             capture_output=True, text=True, timeout=15)
        days = (now.timestamp() - int(out.stdout.strip())) / 86400
        label = '【绿】' if days <= y else '【黄】'
        items.append({'t': label + '最近提交距今 ' + format(days, '.1f') + ' 天', 'e': 'git log -1', 'c': '无需处置' if days <= y else '保持节奏'})
        sts.append('green' if days <= y else 'yellow')
    except Exception:
        items.append({'t': '【白】提交时间无法判定（非 git 或命令失败）', 'e': target, 'c': '—'})
        sts.append('unknown')
    stale = []
    for name, sk in repo_skills(target):
        cl = os.path.join(sk, 'CHANGELOG.md')
        if not os.path.isfile(cl):
            continue
        days = (now.timestamp() - os.path.getmtime(cl)) / 86400
        if days > y:
            stale.append((name, days))
    if stale:
        stale.sort(key=lambda x: -x[1])
        for name, days in stale[:6]:
            sev = '【红】' if days > r else '【黄】'
            items.append({'t': sev + name + ' CHANGELOG 已 ' + format(days, '.0f') + ' 天未动（进化停滞嫌疑）', 'e': cl, 'c': '检查是否需要升级或主动封存'})
            sts.append('red' if days > r else 'yellow')
    else:
        items.append({'t': '【绿】各技能 CHANGELOG 均在阈值内', 'e': '阈值 黄>' + str(y) + '天 红>' + str(r) + '天', 'c': '无需处置'})
        sts.append('green')
    return {'status': worst(sts), 'items': items}


def chk_products(target, cfg, ctx):
    """产物纪律面（B-09 · v1.2.0 新增）：本地产物区堆积清点。

    规则真源 core-8 B-09：产出默认不落产物区。产物区文件超阈值 → 黄（提示归档，
    不判红——产物区是合法点名交付地，堆积只是纪律松弛不是事故）。
    only_when_target：产物区属于宿主工作环境，巡检对象是临时 clone 时该面无意义
    （2026-11-12 对照用例实测抓到：clone 巡检扫到宿主 /workspace 49 件 → 假黄），
    此时如实返回绿+说明，不装作查过。"""
    pz = cfg.get('product_zone') or {}
    zone = pz.get('path', '/workspace')
    th = int(pz.get('threshold', 10))
    only = pz.get('only_when_target', '')
    if only and os.path.realpath(target) != os.path.realpath(only):
        return {'status': 'green', 'items': [{'t': '【绿】产物纪律面未启用（非主仓巡检）',
                'e': f'target={target} ≠ 主仓 {only}——宿主产物区不随 clone 变化，查了也无意义',
                'c': '无需处置（主仓巡检时自动启用）'}]}
    if not os.path.isdir(zone):
        return {'status': 'green', 'items': [{'t': '【绿】产物区不存在', 'e': zone, 'c': '无需处置'}]}
    files = [f for f in sorted(os.listdir(zone)) if os.path.isfile(os.path.join(zone, f))]
    n = len(files)
    if n > th:
        return {'status': 'yellow', 'items': [{'t': f'【黄】产物区堆积 {n} 件（B-09 产物纪律）',
                'e': zone + f'（阈值 {th}）——含点名交付物，不全算违规',
                'c': '库务司 products --scan 逐件 archive 落库，或人工点名清理'}]}
    return {'status': 'green', 'items': [{'t': f'【绿】产物区 {n} 件（阈值 {th} 内）', 'e': zone, 'c': '无需处置'}]}


# ---------- 惊门（M8）· 触发词冲突（v1.4.0 转正） ----------
# 设计取舍（2026-11-12 实测得出，别推翻）:
#   平台路由靠「description 命中触发词」，所以**两个技能声明同一个词 = 用户说这话时路由二义**。
#   这条能机检，判红。
#   但「语义相近、字面不同」（learn-hub 的"整理成笔记" vs space-hub 的"整理"）字面判据抓不到；
#   试过"负边界交叉包含"（A 的触发词出现在 B 的不要用于里），实测 6 个候选**全是假阳性**——
#   中文里"归某技能管"和"不要做某事"共用同一批字面词（如 artifact-store 写"不要用于云端建库
#   （归 space-hub 库务司）"，字面包含 space-hub 的触发词"库务司"，实则是指路）。
#   故本门**只查字面**，语义冲突显式交给各技能 references/trigger-samples.md 的 N 组「应归谁」。
#   宁可查得少而准，也不报一堆假红把真冲突淹掉。
_TRIG_STOP = r'(?:。|正门[:：]|能力[:：]|★|【|不要用于|不适用于|$|等触发词)'


def _skill_desc(path):
    """取 SKILL.md frontmatter 的 description（引号 / 折叠两种写法都吃）。取不到返回 ''。"""
    try:
        t = open(path, encoding='utf-8').read()
    except Exception:
        return ''
    if not t.startswith('---'):
        return ''
    end = t.find('\n---', 3)
    if end < 0:
        return ''
    # 截到下一个顶格键：不加 (?=^[^\s]|\Z) 会贪婪到 frontmatter 末尾，
    # 把 allowed-tools 之类整行吞进 description（导出卡片时实测踩到）。
    m = re.search(r'^description:\s*(.*?)(?=^[^\s]|\Z)', t[3:end], re.M | re.S)
    if not m:
        return ''
    g = m.group(1)
    q = re.match(r'\s*"(.*?)"\s*$', g, re.S)
    return q.group(1) if q else g.strip()


def _trig_words(desc):
    """抽触发词。两种官方写法都认：
         ① `触发词：a / b / c`          ② `当用户说「a」「b」…时使用`
    都没有 → 返回 []。**空列表的意思是"没得查"，不是"没冲突"**（调用方按缺口报黄）。"""
    words = []
    m = re.search(r'触发词[:：](.*?)' + _TRIG_STOP, desc, re.S)
    if m:
        for w in re.split(r'[/／、]', m.group(1)):
            w = w.strip().strip('；;，,。 ')
            if w:
                words.append(w)
    if not words:
        words = re.findall(r'当用户说((?:「[^」]+」)+)', desc)
        # findall 只回来一串「a」「b」，再拆
        words = re.findall(r'「([^」]+)」', ''.join(words)) if words else []
    return words


def _norm_word(w):
    """归一化：只做不改变语义的处理——去括号注释、全角空格、大小写折叠、去所有空白。"""
    w = re.sub(r'[（(][^）)]*[）)]', '', w)
    w = w.replace('\u3000', ' ')
    return re.sub(r'\s+', '', w).lower()


def chk_triggers(target, cfg, ctx):
    """惊门（M8）· 触发词冲突检测器。

    能机检的三类:
      ① 跨技能同词 → 红（用户说这词，路由二义，两个技能都可能被叫起）
      ② 技能内重复登记 → 黄（清单自撞，权重失真）
      ③ 未声明触发词 → 黄（**冲突无从判定**，不是"无冲突"；三态不折叠）
    查不了的一类（必须写在面板上，不许装绿）:
      语义相近但字面不同 → 各技能 references/trigger-samples.md 的 N 组「应归谁」人工核。
    """
    skills = repo_skills(target)
    if not skills:
        return {'status': 'unknown', 'items': [{'t': '【白】未发现技能，触发词面无从判定',
                                                'e': target, 'c': '核对 --target 是否指向 520pro 根'}]}
    if len(skills) < 2:
        # 只有一个技能时"撞车"在定义上不可能发生——这时的绿是假绿（2026-11-12 反④ 用例实测抓到）
        return {'status': 'unknown', 'items': [{'t': f'【白】仅 {len(skills)} 个技能，冲突无从判定',
                   'e': '撞车是技能间的概念，样本不足 2 个时"无冲突"没有意义',
                   'c': '核对 --target 指向的目录是否完整（技能应 ≥2 个）'}]}
    owner, gaps, dups, total_words = {}, [], [], 0
    for name, sk in skills:
        ws = _trig_words(_skill_desc(os.path.join(sk, 'SKILL.md')))
        if not ws:
            gaps.append(name)
            continue
        total_words += len(ws)
        seen = set()
        for w in ws:
            k = _norm_word(w)
            if not k:
                continue
            if k in seen:
                dups.append((name, w))
            seen.add(k)
            owner.setdefault(k, []).append((name, w))
    covered = len(skills) - len(gaps)
    items, sts = [], []

    # ① 跨技能同词（红）
    cross = {k: v for k, v in owner.items() if len({n for n, _ in v}) > 1}
    for k, v in sorted(cross.items()):
        who = '、'.join(sorted({n for n, _ in v}))
        items.append({'t': '【红】触发词撞车「' + k + '」→ ' + who,
                      'e': '同一词被 ' + str(len({n for n, _ in v})) + ' 个技能声明，用户说这话时路由二义',
                      'c': '留一个最贴切的，其余改写成更具体的说法（如"整理文件"vs"整理学习资料"）'})
        sts.append('red')

    # ② 技能内重复（黄）
    for name, w in dups:
        items.append({'t': f'【黄】{name} 触发词重复登记「{w}」',
                      'e': '同一技能清单里出现两次（归一化后相同）',
                      'c': '删掉重复项，清单里一个词只出现一次'})
        sts.append('yellow')

    # ③ 未声明触发词（黄·冲突无从判定）
    if gaps:
        items.append({'t': f'【黄】{len(gaps)} 个技能未声明触发词，冲突无从判定',
                      'e': '、'.join(gaps) + f'（覆盖 {covered}/{len(skills)}）',
                      'c': '在 description 补「触发词：a / b / c」（词从 references/trigger-samples.md 的 T 组提炼，不凭空编）'})
        sts.append('yellow')

    # ④ 触发回归（D5·2026-11-13 · 工程J）：N/B 组样本的「应归谁」必须指向真实存在的技能。
    #   为什么补这一面：③ 只查 description 字面撞车；样本集里的 N 组写着"该归谁"，
    #   但没人核对那个名字是不是**真技能**——写错名字的样本等于给了个假出口，
    #   人工核的时候照着错名字找，永远找不到。
    names = {n for n, _ in skills}
    sam_total = sam_bad = 0
    for name, sk in skills:
        sp = os.path.join(sk, 'references', 'trigger-samples.md')
        if not os.path.exists(sp):
            continue
        try:
            txt = open(sp, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        for m in re.finditer(r'(?m)^#{2,4}\s*(N\d+|B\d+)[^\n]*\n([\s\S]*?)(?=\n#{2,4}\s|\Z)', txt):
            am = re.search(r'应归谁[:：]\s*([^\n]+)', m.group(2))
            sam_total += 1
            if not am:
                # 只有 N 组（反例）必须有归属；B 组（边界）的字段是「边界在哪/正确处置」，
                # 按 N 组格式去要求它 = 判据过严（2026-11-13 首跑即抓到这条假阳性）。
                if m.group(1).startswith('N'):
                    sam_bad += 1
                    items.append({'t': f'【黄】{name} {m.group(1)} 缺「应归谁」',
                                  'e': '反例没有归属，等于没写反例',
                                  'c': '补一行「应归谁：<技能名|直接改代码|不触发>」'})
                    sts.append('yellow')
                continue
            for tok in re.findall(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)+', am.group(1)):
                if tok in names or tok in ('git', 'tvbox'):
                    continue
                if tok.endswith(('-hub', '-pipeline', '-core', '-store', '-gate')):
                    sam_bad += 1
                    items.append({'t': f'【黄】{name} {m.group(1)} 归属「{tok}」不是现存技能',
                                  'e': '样本指向的技能名不存在，人工核时照错名字找不到出口',
                                  'c': f'改成实际承接方（现有：{"、".join(sorted(names))}）'})
                    sts.append('yellow')
    if sam_total:
        items.append({'t': f'【提示】触发回归：抽 {sam_total} 组 N/B 样本，归属异常 {sam_bad} 组',
                      'e': '只查「应归谁」指向的技能是否存在；语义是否真该归它，仍需人工抽核',
                      'c': '异常按提示改名字；无异常则此项为绿'})
        if sam_bad == 0:
            sts.append('green')

    # 覆盖统计与边界说明（无论红绿都要出现——否则"0 冲突"会被读成"全都健康"）
    items.append({'t': f'【提示】字面覆盖 {covered}/{len(skills)} 技能、{total_words} 个触发词（本门只查字面同词）',
                  'e': '语义相近（"整理成笔记"vs"整理"）字面判据抓不到；负边界交叉包含试过，全是假阳性故不做',
                  'c': '语义冲突靠各技能 references/trigger-samples.md 的 N 组「应归谁」人工核（E10 manual 判据）'})
    if not cross and not gaps and not dups:
        items.append({'t': '【绿】无触发词撞车', 'e': f'{len(skills)} 个技能、{total_words} 个词全量比对通过',
                      'c': '无需处置'})
        sts.append('green')
    return {'status': worst(sts), 'items': items,
            'covered': covered, 'total': len(skills), 'words': total_words}


def chk_structure(target, cfg, ctx):
    """伤门复合检查器：结构完整性（chk_manifest）+ 产物纪律（chk_products）。
    M5 一个门挂两面（八卦布局固定 8 位，新面并入既有门而非加第 9 卦）。"""
    a = chk_manifest(target, cfg, ctx)
    b = chk_products(target, cfg, ctx)
    return {'status': worst([a['status'], b['status']]),
            'items': a['items'] + b['items'],
            'count': a.get('count', 0) + b.get('count', 0)}


CHECKERS = {k: v for k, v in list(globals().items()) if k.startswith('chk_')}


# ---------- 环比 ----------
def load_history():
    try:
        return json.load(open(HIST_PATH, encoding='utf-8'))
    except Exception:
        return {'fingerprints': []}


def diff_history(cur_fps):
    hist = load_history()
    last = set(hist.get('fingerprints', []))
    cur = set(cur_fps)
    return {'new': sorted(cur - last), 'cleared': sorted(last - cur), 'persist': sorted(cur & last)}


def save_history(cur_fps):
    json.dump({'fingerprints': sorted(cur_fps),
               'last_run': datetime.datetime.now().isoformat(timespec='seconds')},
              open(HIST_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ---------- 面板 ----------
def render_dashboard(data):
    tpl_path = os.path.join(SCRIPT_DIR, 'dashboard_template.html')
    tpl = open(tpl_path, encoding='utf-8').read()
    return tpl.replace('/*__DATA__*/null', json.dumps(data, ensure_ascii=False))


# ---------- 主流程 ----------
def cmd_run(target, out_dir):
    if not os.path.isfile(REG_PATH):
        print('✗ 登记册缺失:', REG_PATH)
        return 2
    try:
        reg = json.load(open(REG_PATH, encoding='utf-8'))
    except Exception as e:
        print('✗ 登记册解析失败（引擎健康预检不过，全盘按无法判定处理）:', repr(e))
        return 2
    ctx = {'thresholds': reg.get('thresholds', {})}
    gates, all_items = [], []
    for g in reg['gates']:
        fn = g.get('impl')
        try:
            if fn and fn in CHECKERS:
                res = CHECKERS[fn](target, g.get('config', {}), ctx)
            elif fn:
                raise RuntimeError('impl 已登记但未实现: ' + fn)
            else:
                res = {'status': 'pending', 'items': [{'t': '【灰·在册待补码】' + (g.get('note') or ''), 'e': '登记册 ' + g['id'], 'c': '下个迭代补码'}]}
        except Exception as e:
            res = {'status': 'unknown', 'items': [{'t': '【白】检查器失灵，无法判定', 'e': g['id'] + ' ' + repr(e), 'c': '修引擎或登记册，绝不装绿'}]}
        res.update({'id': g['id'], 'gua': g['gua'], 'men': g['men'], 'face': g['face'], 'lp': g['lp'], 'tp': g['tp']})
        gates.append(res)
        for it in res['items']:
            all_items.append((g['id'], it['t']))
    n_red = sum(1 for g in gates if g['status'] == 'red')
    n_yel = sum(1 for g in gates if g['status'] == 'yellow')
    th = reg.get('thresholds', {})
    score = max(0, 100 - n_red * th.get('score_cost_red', 12) - n_yel * th.get('score_cost_yellow', 4))
    fps = [gid + '|' + t[:60] for gid, t in all_items]
    diff = diff_history(fps)
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    data = {'score': score, 'ts': ts, 'target': os.path.abspath(target),
            'counts': {'red': n_red, 'yellow': n_yel},
            'env': {'new': diff['new'], 'cleared': diff['cleared'], 'persist': diff['persist']},
            'gates': gates}
    out_dir = out_dir or os.path.join(target, 'docs', '巡检')
    os.makedirs(out_dir, exist_ok=True)
    html = render_dashboard(data)
    dp = os.path.join(out_dir, 'dashboard.html')
    open(dp, 'w', encoding='utf-8').write(html)
    json.dump(data, open(os.path.join(out_dir, 'findings.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    save_history(fps)
    print('==== 520 巡检（卦门合阵）====')
    for g in gates:
        icon = {'red': '🔴', 'yellow': '🟡', 'green': '🟢', 'pending': '⚪', 'unknown': '⚪'}[g['status']]
        print(icon, g['gua'] + g['men'] + '门·' + g['face'], '→', ST_LABEL[g['status']], '|', (g['items'][0]['t'] if g['items'] else ''))
    print('健康分:', score, ' 红门:', n_red, ' 黄门:', n_yel)
    print('环比: 🆕新增', len(diff['new']), ' ✅已清零', len(diff['cleared']), ' ♻️持续', len(diff['persist']))
    print('面板:', dp)
    print('提醒: 行为生效层（本会话技能/规则自报）须由 AI 对账，见 SKILL.md')
    return 0 if n_red == 0 else 1


def register_monitor(risk_face, check_type, desc='', quiet=True):
    """★ 生态监测登记门面（v0.8.4 起由本技能自持；原 tvbox-core 中转壳已删除）。

    任何技能一行调用，把「新风险面」登记进巡检登记册（登记制，先登记后补码）：
        from inspect_hub import register_monitor
        register_monitor('上游新失效模式', 'naming_compliance', '原监测四信号未覆盖时接手跟踪')

    - 幂等：同一 risk_face 重复登记不新增条目（更新描述与时间）。
    - **只写登记册，不动引擎**——登记册是成长面，补码由人决定（沿用监察司机制）。
    - 永不抛异常（登记是旁路，绝不阻断上游主流程）；quiet=True 完全静默。
    - 落点：本技能目录 `monitors.json`（**运行时数据，独立于正本登记册**——登记每台机器各自
      演化，若写进 inspect_registry.json 会让生门「副本 md5 对账」永久误报漂移）。
      需要长期保留的登记请回写仓库正本或巡检登记册。
    """
    try:
        reg = {'monitors': json.load(open(MON_PATH, encoding='utf-8'))} if os.path.exists(MON_PATH) else {'monitors': []}
        mons = reg['monitors']
        hit = [m for m in mons if m.get('face') == risk_face]
        if hit:
            hit[0].update({'type': check_type, 'desc': desc,
                           'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})
        else:
            mons.append({'face': risk_face, 'type': check_type, 'desc': desc,
                         'status': 'registered',
                         'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})
        json.dump(mons, open(MON_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        if not quiet:
            print(f'  📋 监测面已登记巡检司：{risk_face}（{check_type}）')
        return True
    except Exception as e:
        if not quiet:
            print(f'  ⚠️ 巡检司登记失败（{type(e).__name__}）：风险面「{risk_face}」未登记')
        return False


def cmd_selfcheck():
    errs = []
    try:
        reg = json.load(open(REG_PATH, encoding='utf-8'))
    except Exception as e:
        print('✗ 登记册不可解析:', repr(e))
        return 2
    ids = [g['id'] for g in reg['gates']]
    if len(ids) != 8 or len(set(ids)) != 8:
        errs.append('八门应为 8 个且不重号: ' + ','.join(ids))
    for g in reg['gates']:
        fn = g.get('impl')
        if fn and fn not in CHECKERS:
            errs.append(g['id'] + ' impl 已登记但引擎未实现: ' + fn)
        if not fn and g['id'] != 'M8':
            errs.append(g['id'] + ' 无 impl 且不在预期待补清单内')
    try:
        html = render_dashboard({'score': 0, 'ts': 'self-check', 'target': 'x', 'counts': {'red': 0, 'yellow': 0},
                                 'env': {'new': [], 'cleared': [], 'persist': []}, 'gates': []})
        if '/*__DATA__*/' in html or len(html) < 4000:
            errs.append('面板模板注入异常')
    except Exception as e:
        errs.append('模板渲染失败: ' + repr(e))
    if errs:
        for e in errs:
            print('✗', e)
        return 2
    print('✓ 登记册 8 门齐 · impl 映射一致 · 面板模板可渲染（self-check 通过）')
    return 0


# ---------- 对抗自测（借 tvbox-eco verify/adversarial_suite.py，去旧生态化） ----------
# 方法论：每个门禁必须配「篡改输入→必翻红」用例，在临时 clone 上做，不污染仓库；
# 任一用例未翻红 => exit 2（门禁失灵）。另配一组无脏对照，防止用例本身恒红。
ADVERSARIAL_CASES = [
    ('M1', 'red', '开门：改仓库正本规则 → 指纹对账必翻红',
     lambda d: open(os.path.join(d, '通用层/rules/core-8.md'), 'a').write('\n<!-- adv dirty -->\n')),
    ('M2', 'yellow', '生门：弄脏技能 SKILL.md 正本 → 副本漂移必翻黄',
     lambda d: open(os.path.join(d, '通用层/skills/learn-hub/SKILL.md'), 'a').write('\n<!-- adv dirty -->\n')),
    ('M3', 'red', '杜门：伪造明文密钥 → secret_scan 必翻红',
     lambda d: open(os.path.join(d, 'zz_adv_leak.py'), 'w').write('k = "ghp_" + "QWERTYUIOPASDFGHJKLM"\n')),
    ('M4', 'red', '景门：注入假子命令 → 文档对账必翻红',
     lambda d: _patch_space_hub(d)),
    ('M5', 'red', '伤门：藏走 MANIFEST 登记文件 → 存在性必翻红',
     lambda d: os.remove(os.path.join(d, '通用层/skills/space-hub/scripts/classify_rules.json'))),
    ('M6', 'red', '死门：登记无主无期阻塞项 → 带过执法必翻红',
     lambda d: open(os.path.join(d, 'docs/遗留登记.md'), 'a').write('- 【阻】对抗测试伪造阻塞项（无负责人无期限）\n')),
    ('M7', 'red', '休门：CHANGELOG 回拨 40 天 → 停更阈值必翻红',
     lambda d: os.utime(os.path.join(d, '通用层/skills/space-hub/CHANGELOG.md'),
                        (datetime.datetime.now().timestamp() - 40 * 86400,) * 2)),
]


def _patch_space_hub(d):
    p = os.path.join(d, '通用层/skills/space-hub/scripts/space_hub.py')
    txt = open(p, encoding='utf-8').read()
    txt = txt.replace("    rs = sub.add_parser('restore')",
                      "    rs = sub.add_parser('restore')\n    zz = sub.add_parser('zz-adv-fake')", 1)
    open(p, 'w', encoding='utf-8').write(txt)


def cmd_adversarial(target):
    import shutil
    import tempfile
    self_py = os.path.abspath(__file__)
    results = []
    for gate, expect, name, mutate in [('CTRL', None, '对照：无脏 clone → 杜门/伤门必须绿', None)] + \
            [(g, e, n, m) for g, e, n, m in ADVERSARIAL_CASES]:
        tmp = tempfile.mkdtemp(prefix='adv_520_')
        try:
            dst = os.path.join(tmp, 'clone')
            r = subprocess.run(['git', 'clone', '-q', target, dst], capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                results.append((name, False, 'clone 失败: ' + r.stderr[-120:]))
                continue
            if mutate:
                mutate(dst)
            out = os.path.join(tmp, 'out')
            r = subprocess.run([sys.executable, self_py, 'run', '--target', dst, '--out', out],
                               capture_output=True, text=True, timeout=300)
            fj = os.path.join(out, 'findings.json')
            if not os.path.isfile(fj):
                results.append((name, False, '巡检未产出 findings.json（rc=' + str(r.returncode) + '）'))
                continue
            gates = {g['id']: g['status'] for g in json.load(open(fj, encoding='utf-8'))['gates']}
            if gate == 'CTRL':
                ok = gates.get('M3') == 'green' and gates.get('M5') == 'green'
                results.append((name, ok, 'M3=' + str(gates.get('M3')) + ' M5=' + str(gates.get('M5'))))
            else:
                st = gates.get(gate)
                results.append((name, st == expect, '期望 ' + expect + ' 实得 ' + str(st)))
        except Exception as e:
            results.append((name, False, repr(e)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    fails = [x for x in results if not x[1]]
    print('==== 对抗自测（篡改必翻红）====')
    for name, ok, note in results:
        print(('  ✓ ' if ok else '  ✗ ') + name + ' | ' + note)
    print('对抗套件: ' + str(len(results) - len(fails)) + '/' + str(len(results)) + ' 通过')
    return 2 if fails else 0


def resolve_target():
    """未显式给 --target 时：从 cwd 向上找含 MANIFEST.json 的目录（SKILL.md §1 承诺的语义）。

    找不到就返回 None —— 由调用方报「无法判定」，不能退回 '.'。
    2026-11-12 实测：从安装目录 ~/.codebuddy/skills/inspect-hub/scripts 跑，
    旧实现 default='.' 会把技能目录当仓库根，开门/生门/伤门集体假红。
    """
    env = os.environ.get('INSPECT_TARGET')
    if env:
        return env
    cur = os.path.abspath(os.getcwd())
    for _ in range(8):
        if os.path.isfile(os.path.join(cur, 'MANIFEST.json')):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def require_target(target):
    """仓库根定不下来时按三态铁律报「无法判定」，不产出假红假黄。"""
    if target and os.path.isfile(os.path.join(target, 'MANIFEST.json')):
        return target
    print('==== 520 巡检（卦门合阵）====')
    print('⚪ 无法判定 | 未定位到 520pro 仓库根（向上未找到 MANIFEST.json）')
    print('   处置：cd 到 520pro 仓库根再跑，或 --target <520pro根>')
    return None


def main():
    ap = argparse.ArgumentParser(description='inspect-hub 520 巡检司')
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run', help='跑全量巡检并产出面板')
    r.add_argument('--target', default=resolve_target())
    r.add_argument('--out', default=None)
    sub.add_parser('self-check', help='引擎/登记册/模板健康预检')
    av = sub.add_parser('adversarial', help='对抗自测：逐门造脏断言必翻红（临时 clone，不污染仓库）')
    av.add_argument('--target', default=resolve_target())
    a = ap.parse_args()
    if a.cmd == 'self-check':
        sys.exit(cmd_selfcheck())
    if a.cmd == 'adversarial':
        t = require_target(a.target)
        sys.exit(2 if not t else cmd_adversarial(t))
    t = require_target(a.target)
    sys.exit(2 if not t else cmd_run(t, getattr(a, 'out', None)))


if __name__ == '__main__':
    main()
