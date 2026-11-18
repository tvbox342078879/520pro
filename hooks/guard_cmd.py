#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""guard_cmd.py — 工具级硬拦截（PreToolUse·Bash 前置守卫）

为什么要有它（520 的真实软肋）:
  520 的提交闸做得很密——pre-commit 跑 secret_scan + verify、commit-msg 强制四字段，
  但这三道闸有一个共同的后门：`git commit --no-verify` 一句话全绕过。
  规则文件里写的「不许 --no-verify」只是软约束，模型想绕就绕，事后只能从 git 历史看出来。
  钩子是唯一能在**动作发生前**挡住的地方，实测有效（见下方协议注记）。

协议（实测确认，非推测）:
  PreToolUse 钩子输出 {"hookSpecificOutput":{"permissionDecision":"deny",
  "permissionDecisionReason":"..."}} 并 exit 2 → 平台直接阻断该次工具调用，
  模型收到 `PreToolUse:Bash hook blocked this tool call: <reason>`。
  2026-11-14 用临时探针实测命中一次，日志见 docs/通病台账.md 病15。

规则边界（只拦「确定有害且无正当理由」的，不拦常用操作）:
  G1 git commit/push/merge/rebase 带 --no-verify —— 绕过全部提交闸
  G2 rm -rf 目标是 / 或 ~ 或 $HOME（含 /* 变体）—— 不可逆灾难
  G3 git push --force/-f 到 main/master —— 覆盖远端历史
  G4 rm/mv/git rm 目标是双核 —— B-16 硬依赖
  G5 git add 凭据文件名 —— B-05 零明文凭证（一 add 即进永久历史）
  G6 Write/Edit 目标在 git 仓内且是凭据文件名 —— 同上，挡在「写下去」那一刻
  故意不拦：git reset --hard（常用且可恢复）、rm -rf 具体子目录（日常操作）、
            任何读操作、仓外的临时 .env（不入库就无风险，交给 G5 在 add 时兜）。
            拦太多会逼人永久关掉钩子，等于闸没了。

B-05 的凭据名单有三个来源，别写成三份：
  · secret_scan.py 的 CRED_NAMES 是「已追踪凭据文件」的真源，此处 CRED_BASENAMES 必须与它逐项相等；
    两边一致性由 test_guard_cmd.py 的对账用例守着（改了单边就红，不靠记）。
  · 本文件多出的是「入库即泄密」的同型扩展（.env / credentials.* / *.pem 等），
    secret_scan 靠内容扫描覆盖，这里靠文件名提前挡——两者互补，不是重复。

fail-open 但出声:
  守卫自身异常时放行（一个语法错误不该让整台机器干不了活），
  但把 guard_err 写进 state，`next_anchor.py --probe` 能查到——
  「静默失效」比「不设防」更危险，所以必须留痕。
"""
import argparse
import json
import os
import re
import sys

# ── B-05 凭据文件名（三条来源合一，见文件头） ──
# 前六项必须与 secret_scan.py 的 CRED_NAMES 逐项相等（对账用例守着，改单边就红）
CRED_BASENAMES = ('.gh_token', '.git-credentials', '.netrc', 'id_rsa', 'id_ed25519', '.env')
CRED_EXTRA = ('credentials.json', 'credentials.yml', 'credentials.yaml')
CRED_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.keystore')
# 模板类一律放行：写了也不含真凭据，拦它只会逼人关钩子
CRED_TEMPLATE = ('.example', '.sample', '.template', '.dist')

# G5 的判据要**贴着 git add**：中间不许跨越命令分隔符（; & | 换行）。
# 首版用「命令里有 git add」+「命令里有凭据名」两个独立条件，结果
# `git add -A && git commit -F 说明文件`（说明里提到 .env）被误拦了三次——
# 判据的对象范围是「暂存动作的实参」，识别范围却是「整条 shell 文本」，
# 正是台账病15 的形态。改成一条正则后，凭据名必须出现在 git add 后方、
# 且与 git add 之间没有分隔符，才算「真要把这个文件加进去」。
G5_PAT = (
    r'\bgit\s+add\b[^;&|\n]*?[\s/]'
    r'(?:\.env(?!\.(?:example|sample|template|dist))'
    r'|\.gh_token|\.git-credentials|\.netrc|id_rsa(?!\.pub)|id_ed25519(?!\.pub)'
    r'|credentials\.(?:json|ya?ml)'
    r'|[^\s/\'"]+\.(?:pem|key|p12|pfx|keystore)'
    r')(?=[\s;&|)"\'=.]|$)'
)

# 真源在这里；改规则先改这里，再跑 verify/tests/test_guard_cmd.py
# impl: B-05 S1   ← G5（git add 凭据名）/ G6（Write 到仓内凭据路径）
# impl: B-16 S1   ← G4（删/移双核）
# impl: B-19 S1   ← gate_target/audit_landings（落点完备性闸：裸闸 deny + audit 报红，fail-closed）
RULES = [
    {
        'id': 'G1',
        'why': '--no-verify 绕过全部提交闸（secret_scan / 提交四字段 / verify.sh）',
        'pat': r'\bgit\b[^|;&\n]*\b(commit|push|merge|rebase)\b[^|;&\n]*\s--no-verify\b',
        'fix': '去掉 --no-verify 正常提交；确有正当理由，在提交信息里写明并让人批准',
    },
    {
        'id': 'G2',
        'why': '递归删除根目录 / 家目录，不可逆',
        'pat': (r'\brm\b[^|;&\n]*\s-[a-zA-Z]*[rR][a-zA-Z]*\s+'
                r'(-[a-zA-Z]+\s+)*'
                r'(/|/\*|~|~/\*|~/|\$HOME|\$\{HOME\}|\$HOME/\*|\$\{HOME\}/\*'
                r'|\$HOME/|\$\{HOME\}/)(\s|$|["\'])'),
        'fix': '明确写出要删的具体子目录；批量删除先 --dry 列清单',
    },
    {
        'id': 'G3',
        'why': '强推 main/master 覆盖远端历史',
        # 三个条件必须同时成立、不限顺序（首版写成单条正则，把参数顺序写死了，
        # `git push origin main --force` 这种最常见写法反而溜过——已修）
        'pats': [r'\bgit\b[^|;&\n]*\bpush\b',
                 r'(?:^|\s)(?:--force-with-lease|--force|-f)(?:\s|$)',
                 r'\b(?:main|master)\b'],
        'fix': '用 hooks/git_push_safe.sh（带重试与校验）；确需强推先说明原因',
    },
    {
        'id': 'G4',
        'why': '删除/移走双核（probe-hub、tvbox-core）——B-16 硬依赖，'
               'tvbox-core/scripts/core.py 被 probe-hub import，删了或改名会全线崩',
        # 只拦「rm/mv 在前、双核在后」的组合：
        #   命中：rm -rf .../tvbox-core ｜ mv probe-hub /tmp ｜ git rm -r .../probe-hub
        #   不拦：cp -r probe-hub /tmp/bak（备份不改原件）
        #         mv /tmp/x probe-hub（往双核里塞东西，非删除）
        # 双核名后必须紧跟 / 空白 或结尾，避免误伤 tvbox-core-backup 这类备份目录
        'pats': [r'\b(?:rm|mv|git\s+rm)\b[^|;&\n]*',
                 # 双核名后允许的分隔符要写全：行尾、空白、/、;、&、|、) 、} 、引号
                 # （首版只写了 / 空白 行尾 引号，`rm -rf x/tvbox-core; echo ok`
                 #   因为后面跟 ; 而漏判——实测真删了一个测试目录才发现）
                 r'\b(?:tvbox-core|probe-hub)(?=[/\s;&|)\}"\']|$)'],
        # 豁免：双核作为 mv 的**目标**（最后一个参数）= 往双核里放东西，不是删它
        'exempt': (r'\bmv\b[^|;&\n]*\s+(?:\./)?(?:[\w./-]*/)?(?:tvbox-core|probe-hub)/?\s*$'
                   r'|/skills/(?:tvbox-core|probe-hub)/[^\s;&|]*\.[A-Za-z0-9]+\s*$'),
        'fix': '双核不得删除、改名、合并；确要动先备替代件并通过技能契约机检（C1–C6），'
               '备份请用 cp 到仓外目录',
    },
    {
        'id': 'G5',
        'why': '把凭据文件加进版本库（B-05：一 add 就进永久历史，删了也还在）',
        # 判据是**一条**正则，不是「有 git add」+「有凭据名」两个独立条件——
        # 后者会把「提交说明里提到 .env」也算违例（实测连拦三次，见上方 G5_PAT 注释）。
        # `git add -A` / `git add .` 仍不拦：不带文件名，判不了；
        # 批量 add 靠 secret_scan 的「未忽略未追踪即红」兜底，两道闸分工不同。
        'pat': G5_PAT,
        'fix': '凭据放仓外（/tmp 或 ~/.config 下 0600）并进 .gitignore；'
               '仓内只留 .env.example / credentials.example',
    },
    # B-11 硬化：前台长 sleep 是「等」本身，把回合挂死让用户插不进话（R-BG03 实测 41 次）。
    # 判据用执行事实三要素（basename=sleep + 参数=秒数），不搜命令文本里的形容词。
    {
        'id': 'G7',
        'why': '前台 sleep≥30s——「等」本身就是长任务，占死回合，用户插不进话（B-11 / R-BG03）',
        'pat': None,  # 用 _long_sleep() 做数值判定，见下
        'check': 'long_sleep',
        'fix': '长任务走后台通道 + 完成通知；取后台输出一律非阻塞（结果到了再去），禁前台 sleep 等完成',
    },
]
# impl: B-11 S1  ← G7（前台长 sleep）/ G8（工具洪水，见 check_flood）


# ── B-11/G7：前台长 sleep 的执行事实判定 ──
# 只认「sleep 命令 + 秒数参数」这个执行事实，不认命令文本里有没有「等/长任务」这类形容词
# （M-R120：判据必须是 basename+子命令+收窄参数；旧正则搜词一次没命中）。
# 病15 防护：sleep 必须处于「命令起始位」（行首或 ; && | 之后），不认 echo/字符串/参数里的 sleep 串。
# 首版只写 `(?<![\w.])sleep` 把 `echo sleep 240` / `grep "sleep 60"` 全误拦了——识别范围
# （整条文本）≠对象范围（命令位置），判据必须锚定命令边界。
# S-06（施工纪律·分步与如实/不扩大拦截）机制落点：此处命令起始位锚定 + 下组反例即
# "不自行扩大拦截范围"的可执行判据；拦截经 reason/fix 如实反馈而非静默拒绝。
SLEEP_SEC_RE = re.compile(r'(?:^|[;&|]\s*)\s*sleep\s+(\d+(?:\.\d+)?)([sm]?)\b')
SLEEP_THRESHOLD_SEC = 30  # 与 B-11「超过 30 秒必须后台」同口径


def _long_sleep(command):
    """命中返回秒数（float），否则 None。只认命令起始位的 sleep；sleep 2/0.5 不拦，30/1m 拦。"""
    for m in SLEEP_SEC_RE.finditer(str(command or '')):
        sec = float(m.group(1))
        if m.group(2) == 'm':
            sec *= 60
        if sec >= SLEEP_THRESHOLD_SEC:
            return sec
    return None


# ── B-11/G8：工具洪水（单回合连续命令占满对话） ──
# 有状态判定，不放进纯函数 check()（那条保持只读无副作用，测试全程调它）。
FLOOD_STATE = os.path.join(os.path.expanduser('~'), '.codebuddy', 'hooks', '.efficiency_guard_state')
FLOOD_WINDOW_SEC = 60      # 滑动窗口
FLOOD_THRESHOLD = 50       # 60 秒内 >50 条 Bash 调用视为洪水（并行一批 8 条属正常，不误伤）


def _read_flood():
    try:
        d = json.load(open(FLOOD_STATE, encoding='utf-8'))
        return [t for t in d.get('ts', []) if isinstance(t, (int, float))]
    except Exception:
        return []


def _write_flood(ts):
    try:
        os.makedirs(os.path.dirname(FLOOD_STATE), exist_ok=True)
        tmp = FLOOD_STATE + '.tmp'
        json.dump({'ts': ts[-FLOOD_THRESHOLD * 2:]}, open(tmp, 'w', encoding='utf-8'))
        os.replace(tmp, FLOOD_STATE)
    except Exception:
        pass  # fail-open：state 坏不阻断干活


def check_flood(now=None):
    """记一次 Bash 调用并判是否洪水。命中返回规则 dict（G8），否则 None。纯纪律闸，不改命令。"""
    t = float(now if now is not None else __import__('time').time())
    recent = [x for x in _read_flood() if t - x <= FLOOD_WINDOW_SEC]
    recent.append(t)
    _write_flood(recent)
    if len(recent) > FLOOD_THRESHOLD:
        return {'id': 'G8', 'why': '短时间 Bash 调用过多（%d 条/%ds），回合被工具洪水占满，用户插不进话' %
                (len(recent), FLOOD_WINDOW_SEC),
                'fix': '单回合探查收敛到少数几条、落文字锚点即停；读仓库交给子代理；能并行的同一条消息并发',
                'count': len(recent)}
    return None


# 写文件类规则的「规则体」，判据在 check_write()（要看路径，不是命令串）
WRITE_RULE = {
    'id': 'G6',
    'why': '在 git 仓库内写凭据文件（B-05：写下去那一刻就等着被 add）',
    'fix': '凭据写仓外并 0600；仓内只放模板（.env.example 等）；'
           '确需仓内占位，先确认 .gitignore 已覆盖',
}


def _in_git_repo(path):
    """路径的最近存在祖先里有没有 .git——纯文件系统检查，不跑 git 命令。

    为什么不用 git rev-parse：钩子在每次 Write 前都会跑，起子进程太贵；
    且新文件的目录可能还不存在，rev-parse 会直接失败（误判为「不在仓内」而放行）。
    """
    try:
        d = os.path.dirname(os.path.abspath(os.path.expanduser(str(path))))
    except Exception:
        return False
    while d and d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, '.git')):
            return True
        d = os.path.dirname(d)
    return False


def check_write(path):
    """Write/Edit 目标是不是「仓内凭据文件」。返回规则 dict 或 None。

    仓外不管：/tmp 里的 .env 不入库就无风险，硬拦只会误伤调试；
    真正入库的动作由 G5（git add）在那一刻挡。
    """
    p = str(path or '').strip()
    if not p:
        return None
    base = os.path.basename(p.rstrip('/\\'))
    low = base.lower()
    if any(low.endswith(t) for t in CRED_TEMPLATE):
        return None
    if not (low in CRED_BASENAMES or low in CRED_EXTRA or low.endswith(CRED_SUFFIXES)):
        return None
    return WRITE_RULE if _in_git_repo(p) else None


def check(command):
    """返回命中的规则 dict，未命中返回 None。"""
    if not command:
        return None
    cmd = str(command)
    for r in RULES:
        if r.get('exempt') and re.search(r['exempt'], cmd):
            continue
        # 执行事实型判据（G7）：自定义函数返回命中细节，挂到规则上带出去
        if r.get('check') == 'long_sleep':
            sec = _long_sleep(cmd)
            if sec is not None:
                return dict(r, sec=sec)
            continue
        if r.get('pats'):
            if all(re.search(p, cmd) for p in r['pats']):
                return r
        elif r.get('pat'):
            if re.search(r['pat'], cmd):
                return r
    return None


def _repo_root():
    d = os.getcwd()
    while True:
        if os.path.exists(os.path.join(d, '.git')):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            return os.getcwd()
        d = nd


def _disease_hint(rule_id):
    """经验闭环闸1：拦截即递病号修法（读映射表，失败降级为空）。"""
    try:
        import json as _j
        root = _repo_root()
        mp = _j.load(open(os.path.join(root, 'verify', '病号映射表.json'), encoding='utf-8'))
        for g, d in mp.get('guard_rules', {}).items():
            if rule_id.startswith(g) or g in rule_id:
                for dz in mp['diseases']:
                    if dz['id'] == d:
                        return f"📚 同型病历 {dz['id']}·{dz['name']}｜修法：{dz['fix']}"
        return ''
    except Exception:
        return ''  # 降级：映射缺失不阻断主闸功能


def _bump_recurrence(rule_id, coord=None):
    """经验闭环闸2：拦截/Lesson 记病即复发计数+1（机器记账，失败静默，同分钟去重）。

    v0.8.66：coord 可选（Lesson 复发时传「Lesson 复发 病N 第K次」，与 guard 拦截区分来源）。"""
    try:
        import json as _j, datetime as _dt
        root = _repo_root()
        fp = os.path.join(root, 'experience_recurrence.json')
        d = _j.load(open(fp, encoding='utf-8')) if os.path.exists(fp) else {'counters': {}}
        mp_path = os.path.join(root, 'verify', '病号映射表.json')
        mp = _j.load(open(mp_path, encoding='utf-8')) if os.path.exists(mp_path) else {}
        gr = mp.get('guard_rules', {})
        rid0 = rule_id.split(' ')[0]
        dis = gr.get(rid0) or next((v for k, v in gr.items() if not k.startswith('_') and rid0.startswith(k)), rid0)
        now = _dt.datetime.now()
        c = d['counters'].setdefault(dis, {'count': 0, 'events': [], 'last_ts': '', 'status': 'active'})
        minute_key = now.strftime('%Y%m%d%H%M')
        if c['events'] and c['events'][-1].get('min') == minute_key:
            return  # 同分钟同规则去重（一次会话内反复试错只记 1 次复发）
        c['count'] += 1
        c['last_ts'] = now.strftime('%Y-%m-%d')
        c['events'].append({'ts': now.strftime('%Y-%m-%d %H:%M'), 'coord': coord or f'guard拦截 {rule_id}',
                            'by': 'hook', 'min': minute_key})
        tmp = fp + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            _j.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, fp)
    except Exception:
        pass  # 记账失败不阻断主闸


def gate_target(rule_id):
    """经验闭环闸4（动作前硬闸）：规则→固化经验的**实证落点**，供拦截 reason 机器喂正门。

    步骤4（落点完备性闸，v0.8.83）从根修一处病15：
      旧实现拿 `guard_rules` 映射当前置门槛——G7/G8 无映射 → gate_target 返回 None
      （实测裸闸），且末尾 `return land` 兜底一个不带锚点的裸文件名（脏落点）。
      识别范围（guard_rules 映射）≠对象范围（判据用例是否真实存在）：一条规则该不该
      带落点，取决于它的回归用例是否真实在册，而不是病号表里有没有一行映射。
      新实现：唯一落点真源=用例存在性——test_guard_cmd.py 里有该规则的断言字面量
      才带 `文件#规则id`；没有就 None（裸闸，交给 audit_landings 报红）。

    为什么不取 exp_entries 的 fixed_path（实测否决，病15 反面）：
      · 拿规则 why/命令文本去 exp_probe.gate() 做模糊匹配 → G1..G7 全不命中（文本不是症状）；
      · 走 guard_rules→病号→exp_entries.fixed_path → 命中的是 MANIFEST.json / archive_ledger.json
        这类 commit 改动文件，与"该规则的修复"无关——脏落点，喂给模型比不带更糟。
    正确锚点：该规则的回归判据文件 test_guard_cmd.py + 专属锚点 "#<规则id>"（如 G5→
    "test_guard_cmd.py#G5"）——真实存在、与规则强相关（改坏规则对应用例翻红）、可核实。
    无用例规则返回 None（真裸闸，不硬塞落点）；异常降级 None（不阻断主闸）。
    """
    try:
        root = _repo_root()
        rid0 = str(rule_id).split(' ')[0]
        land = os.path.join('verify', 'tests', 'test_guard_cmd.py')
        if not os.path.isfile(os.path.join(root, land)):
            return None
        # 病15 防护：锚点必须是本规则真实存在的用例，不能凭空造，也不给裸文件名兜底。
        # 判据文件 cases 里 (命令, want) 的 want、或 G7/G8 的 h['id']=='Gx' 断言，
        # 都会以 'Gx' 字面量出现——存在才带落点，不存在即裸闸（None）。
        try:
            _src = open(os.path.join(root, land), encoding='utf-8').read()
            if ("'%s'" % rid0) in _src or ('"%s"' % rid0) in _src:
                return land + '#' + rid0
        except Exception:
            pass
        return None
    except Exception:
        return None


def audit_landings():
    """步骤4落点完备性自检：遍历全部拦截规则，凡 gate_target 为 None 即裸闸。

    返回 {'rules': {规则id: 落点或None}, 'bare': [裸闸规则id]}。
    真源=RULES + WRITE_RULE（对象范围），不读 guard_rules 映射（避免病15 假绿）：
    以后新增规则若没配套回归用例，裸闸清单立即非空 → verify 报红（非 Agent 自报）。
    """
    rules = [r['id'] for r in RULES] + [WRITE_RULE['id']]
    # G8 是 check_flood 动态返回的拦截规则（不在 RULES 表里，但同样能 deny），
    # 必须纳入自检对象范围，否则"能拦人的规则"与"被自检的规则"不一致（病15）。
    rules.append('G8')
    result = {rid: gate_target(rid) for rid in rules}
    bare = [rid for rid in rules if not result[rid]]
    return {'rules': result, 'bare': bare}


def deny_payload(rule):

    """PreToolUse 的阻断载荷（协议已实测）。

    步骤4：落点是硬要求——命中规则但 gate_target 为 None（裸闸）时，仍 fail-closed
    照常 deny（绝不因缺落点就放行），但 reason 明确标注 ⚠裸闸 + 自检命令，
    让"缺判据落点"可见、可修；正常规则带真实判据落点（机器喂正门）。
    """
    reason = f"⛔ [{rule['id']}] {rule['why']}｜正门：{rule['fix']}" + _disease_hint(rule['id'])
    _t = gate_target(rule['id'])
    if _t:
        reason += f"｜🔒判据落点：{_t}（改坏规则此测试翻红，先看它再动手）"
    else:
        reason += ("｜⚠裸闸缺判据落点：该规则无回归用例锚点，"
                   "跑 python3 hooks/guard_cmd.py --audit-landings 查裸闸清单并补用例")
    return {
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': reason,
        }
    }


def main():
    ap = argparse.ArgumentParser(description='工具级硬拦截（PreToolUse 守卫：命令 + 写入路径）')
    ap.add_argument('--check', metavar='CMD', help='只判定一条命令，打印结果（调试/测试用）')
    ap.add_argument('--check-write', metavar='PATH', help='只判定一个写入路径（调试/测试用）')
    ap.add_argument('--list', action='store_true', help='列出全部规则')
    ap.add_argument('--audit-landings', action='store_true',
                    help='步骤4自检：全部拦截规则的判据落点完备性，有裸闸则 exit 2')
    ap.add_argument('--bump', metavar='病号ID', help='Lesson 复发记账（commit-msg 调用）：复发计数+1')
    ap.add_argument('--coord', metavar='说明', help='--bump 的事件说明（默认 guard拦截）')
    a = ap.parse_args()

    if a.audit_landings:
        _audit = audit_landings()
        print(json.dumps(_audit, ensure_ascii=False))
        return 2 if _audit['bare'] else 0   # 有裸闸即红，fail-closed on evidence

    if a.list:
        for r in RULES:
            pat = r.get('pat') or ' && '.join(r.get('pats') or [])
            print(f"{r['id']}  {r['why']}\n     {r['fix']}\n     {pat}")
        print(f"{WRITE_RULE['id']}  {WRITE_RULE['why']}\n     {WRITE_RULE['fix']}\n     "
              f"文件名 ∈ {CRED_BASENAMES + CRED_EXTRA} 或后缀 ∈ {CRED_SUFFIXES}，且路径在 git 仓内")
        return 0

    if a.check is not None:
        hit = check(a.check)
        print(json.dumps({'deny': bool(hit), 'rule': hit['id'] if hit else None,
                          'why': hit['why'] if hit else None}, ensure_ascii=False))
        return 2 if hit else 0

    if a.bump is not None:
        _bump_recurrence(a.bump, coord=a.coord)
        print(json.dumps({'bumped': a.bump, 'coord': a.coord or 'guard拦截'}, ensure_ascii=False))
        return 0

    if a.check_write is not None:
        hit = check_write(a.check_write)
        print(json.dumps({'deny': bool(hit), 'rule': hit['id'] if hit else None,
                          'why': hit['why'] if hit else None}, ensure_ascii=False))
        return 2 if hit else 0

    # 钩子模式：从 stdin 读 payload
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    ti = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
    tool = (data.get('tool_name') or data.get('toolName') or '').lower()
    if tool in ('write', 'edit', 'multiedit', 'notebookedit'):
        fp = ti.get('file_path') or ti.get('path') or ti.get('notebook_path') or ''
        hit = check_write(fp)
    else:
        cmd = data.get('command') or ti.get('command') or ''
        hit = check(cmd)
    if hit:
        _bump_recurrence(hit['id'])
        print(json.dumps(deny_payload(hit), ensure_ascii=False))
        return 2
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)          # fail-open，绝不因守卫自身故障卡住干活
