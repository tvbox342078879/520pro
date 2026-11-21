#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# impl: B-11 S1  ← 每轮三问注入（后台非阻塞/禁轮询收尾纪律），孤儿闸归位
"""PreToolUse 锚点钩子：Bash 调用前，把当前仓库上一轮提交的 `Next:` 打出来。

为什么要有：会话中途最容易忘的是「下一步是什么」。`verify.sh` 只在提交时打印，
中途没有任何必经点；`docs/钩子来源判定.md` 已实证平台支持 PreToolUse——
这是唯一能在「每个动作」粒度上带出锚点的位置。

铁律（三条，缺一条就不该装）：
  ① **永不拦截**：任何异常 / 非 Bash / 非 git 仓 → exit 0 静默，绝不挡工具调用；
  ② **节流**：同一仓库 15 分钟只提示一次，避免刷屏把上下文塞满；
  ③ **只读**：除自己的状态文件外不写任何东西。

定位仓库根的三级回退（2026-11-14 实测：Bash 工具 cwd 恒为 /workspace，
不随命令里的 cd 持久化；只认 payload.cwd 会让钩子在多仓工作区永久静默）：
  ① payload.cwd 自身是 git 仓 → 用它；
  ② 从 command 里解析最后一个 `cd <绝对路径>` / `git -C <绝对路径>` → 用它；
  ③ 都不中 → 用 state 里记的 last_repo（仅当它仍是 git 仓）。

挂点与投递通道（2026-11-14 实测，别凭直觉改）：
  · **PreToolUse**：exit 0 时 stdout **不进模型上下文**——实测命中后 state 有记录、
    工具输出里却看不到 `⏭` 行。所以这个挂点只算「给用户看的 UI 提示」，不能当 AI 锚点。
  · **UserPromptSubmit**：官方文档明确 `hookSpecificOutput.additionalContext` 会注入模型
    上下文。模型侧的锚点必须走这里（每轮一次，不节流；Bash 太密才需要节流）。
  · 两者的仓库定位共用同一套三级回退，避免两套逻辑各错一半。

状态文件：~/.codebuddy/hooks/.next_anchor_state
  {"repos": {仓库根: 最后打印时间}, "last_repo": 路径, "probe": 最后一次调用快照}
  旧版扁平格式 {仓库根: 时间} 读取时自动迁移。

自检：`python3 next_anchor.py --probe` 打印最后一次调用的 event/tool/cwd/root/via/hit，
用来区分「平台没调用钩子」与「调用了但没匹配上」——没有它，生效与否永远无法判定。
"""
import json
import os
import re
import subprocess
import sys
import time

STATE = os.path.expanduser('~/.codebuddy/hooks/.next_anchor_state')
THROTTLE_SEC = 15 * 60
MAX_STATE_KEYS = 50          # 状态文件有界，防无限增长
CMD_HEAD = 80                # probe 里只留命令开头，避免存整条长命令
MAX_INFLIGHT = 20            # 在途任务台账有界，防无限增长
STALE_SEC = 30 * 60          # 在途超 30 分钟标红提醒主动查（不等用户追问）

EMPTY = {'repos': {}, 'last_repo': '', 'probe': {}, 'probe_by_event': {}, 'inflight': {}}

# ── 环境身份锚（2026-11-19 用户实证「串仓库/多版本生态分不清」）─────────────
# 根因：规则/锚点/会话都不绑身份，同一会话跨 tvbox-eco→520pro→新生态，
# 靠 last_repo 回退静默猜仓。修法：每仓根放 ENV_ID.json，SessionStart 自报
# 家门；last_repo 回退（非 payload 明确指向）打「未对齐」标记，不再静默。
# 只读 + 缺失/损坏一律降级为 None（铁律①永不拦截），不伪造身份。
ENV_ID_FILE = 'ENV_ID.json'


def env_anchor(root):
    """读仓库根 ENV_ID.json，返回身份自报字段 dict；缺失/损坏/字段不全返回 None。
    判据对象=真函数读真文件；不查源码字符串存在（病15 识别范围=对象范围）。
    """
    if not root or not os.path.isdir(root):
        return None
    fp = os.path.join(root, ENV_ID_FILE)
    if not os.path.isfile(fp):
        return None
    try:
        d = json.load(open(fp, encoding='utf-8'))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    required = ('env_id', 'role', 'version')
    if not all(str(d.get(k, '')).strip() for k in required):
        return None
    return {'env_id': str(d['env_id']).strip(),
            'role': str(d['role']).strip(),
            'version': str(d['version']).strip(),
            'repo': str(d.get('repo', '')).strip(),
            'note': str(d.get('note', '')).strip()}


def env_anchor_line(a):
    """把身份字段拼成注入短句；a=None 返回空串（调用方据此降级）。"""
    if not a:
        return ''
    s = '🪪 环境身份：%s（角色 %s，版本 %s）' % (a['env_id'], a['role'], a['version'])
    if a.get('note'):
        s += ' · ' + a['note']
    return s


# 完成通知自动销账：UserPromptSubmit 的 prompt 里带 <task-notification> 块，
# 命中终态即把该 task_id 从在途台账移除——完成即销，不靠记忆/追问。
_TASK_NOTIF_RE = re.compile(r'<task-notification>(.*?)</task-notification>', re.S)
_TASK_ID_RE = re.compile(r'<task-id>\s*([^<\s]+)\s*</task-id>')
_TASK_TERM_RE = re.compile(r'<status>\s*(completed|failed|canceled|rejected)\s*</status>', re.I)


# 二进制自动出场（2026-11-18）：用户说「看某个 APK / 扒这个 so」而不报技能名时，
# 熔铸司（foundry）该出场却没出场——根因是技能被动触发、hooks/rules 零登记。
# 这里在 UserPromptSubmit 必经点加软提示（不拦截），双通道：扩展名 + 逆向动词/名词。
# 病15：识别范围=对象范围——中文目标名（如「云取」）无扩展名，故必须靠动词同伴命中，
# 不能只匹配扩展名；反过来普通文字里的 .so 片段不得误伤。纯函数供判据直喂样本。
_BINARY_EXT_RE = re.compile(r'\.(apk|dex|so|jar|bin|img|ipa|elf|aab)(?:\b|[.\s"\'，。、）])', re.I)
_BINARY_VERB_RE = re.compile(r'(逆向|脱壳|反编译|解包|扒.{0,6}(包|apk|so|dex)|类源码|jadx|smali|熔铸|出场|加载)')
_BINARY_NOUN_RE = re.compile(r'(apk|dex|so文件|\.so\b|二进制|jadx|class文件|字节码|外壳|壳|应用|安装包|程序|aab)', re.I)


def skill_health(name, skills_root=None):
    """出场前自检目标技能是否完好——云取 `PluginRuntime.healthCheck` 的 520 对应物
    （借鉴清单第1条，transcript L2565：提示去加载工具前先确认工具没坏）。

    只查「即将被提示加载的那一个技能」（病15 对象范围=识别范围），不扫全仓技能。
    纯函数、只读、可注入 root 供判据构造损坏样本。返回 (ok: bool, reason: str)。
    """
    root = skills_root or os.path.join(os.path.expanduser('~'), '.codebuddy', 'skills')
    d = os.path.join(root, name)
    if not os.path.isdir(d):
        return False, f'{name} 技能目录不存在'
    if not os.path.isfile(os.path.join(d, 'SKILL.md')):
        return False, f'{name} 缺 SKILL.md'
    scripts = os.path.join(d, 'scripts')
    if not os.path.isdir(scripts) or not os.listdir(scripts):
        return False, f'{name} 缺 scripts/ 正门'
    return True, 'ok'


def binary_hint(prompt, skills_root=None):
    """软提示：prompt 命中二进制目标 → 先自检目标技能再提示；否则空串。纯函数。

    v0.8.89 借鉴第1条：命中后不直接提示加载——先 healthCheck 目标技能（foundry），
    健康才建议加载；损坏/未装则提示先重装，杜绝「提示去加载一个坏掉的工具」。
    """
    if not prompt:
        return ''
    p = str(prompt)
    hit_ext = bool(_BINARY_EXT_RE.search(p))
    hit_verb = bool(_BINARY_VERB_RE.search(p))
    hit_noun = bool(_BINARY_NOUN_RE.search(p))
    if not (hit_ext or (hit_verb and hit_noun)):
        return ''
    ok, reason = skill_health('foundry', skills_root)
    if not ok:
        return ('｜🔨 检测到二进制/逆向目标，但熔铸司 foundry 出场自检未过（'
                f'{reason}）——建议先 bash install.sh 重装再加载，勿直接引用坏工具')
    return ('｜🔨 检测到二进制/逆向目标——建议加载熔铸司 foundry（jadx 26 工具：'
            '类源码/xref/资源解码，出场自检通过），正门 SKILL.md 先读判据再动手')


def autoclose_inflight(prompt, inflight):
    """返回 (剩余台账, 本次自动销掉的 id 列表)。纯函数，供 selftest 直喂样本。"""
    if not prompt or not inflight:
        return inflight, []
    done = set()
    for blk in _TASK_NOTIF_RE.findall(prompt):
        tid = _TASK_ID_RE.search(blk)
        st = _TASK_TERM_RE.search(blk)
        if tid and st:
            done.add(tid.group(1).strip())
    closed = [k for k in inflight if k in done]
    return {k: v for k, v in inflight.items() if k not in done}, closed


def _read_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return dict(EMPTY)
    if not isinstance(d, dict):
        return dict(EMPTY)
    if 'repos' not in d:                                # 旧扁平格式迁移
        repos = {k: v for k, v in d.items() if isinstance(v, (int, float))}
        return {'repos': repos, 'last_repo': '', 'probe': {}, 'probe_by_event': {}}
    d.setdefault('repos', {})
    d.setdefault('last_repo', '')
    d.setdefault('probe', {})
    d.setdefault('probe_by_event', {})                   # L3：按事件留痕槽（不互相覆盖）
    d.setdefault('inflight', {})
    if not isinstance(d['inflight'], dict):
        d['inflight'] = {}
    return d


def _write_state(d):
    try:
        repos = d.get('repos') or {}
        if len(repos) > MAX_STATE_KEYS:                 # 按时间留最近的
            keep = sorted(repos.items(), key=lambda kv: kv[1], reverse=True)[:MAX_STATE_KEYS]
            d['repos'] = dict(keep)
        inf = d.get('inflight') or {}
        if len(inf) > MAX_INFLIGHT:                     # 台账有界
            keep = sorted(inf.items(), key=lambda kv: kv[1].get('ts', 0), reverse=True)[:MAX_INFLIGHT]
            d['inflight'] = dict(keep)
        tmp = STATE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        os.replace(tmp, STATE)                          # 原子替换（同 save_state 的做法）
    except Exception:
        pass


def _payload():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _repo_root(cwd):
    try:
        r = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _norm_abs(p):
    """只接受已存在的绝对路径（含 ~ 展开）。相对路径 / 命令替换 / 引号残留一律丢。"""
    p = (p or '').strip().strip('"').strip("'")
    if not p:
        return ''
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        return ''
    p = os.path.normpath(p)
    return p if os.path.isdir(p) else ''


def _cmd_candidates(command):
    """从命令文本里挖候选目录：cd 目标与 git -C 目标，取最后一次出现。"""
    if not command:
        return []
    out = []
    for pat in (r'(?<![\w.-])cd\s+([^\s;&|()]+)', r'\bgit\s+-C\s+([^\s;&|()]+)'):
        found = [_norm_abs(m) for m in re.findall(pat, command)]
        found = [p for p in found if p]
        if found:
            out.append(found[-1])
    return out


def _next_line(root):
    """取最近一条提交里以 Next: 开头的行（commit-msg 闸保证格式：做什么—起点—完成判据）。"""
    try:
        r = subprocess.run(['git', '-C', root, 'log', '-1', '--format=%B'],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith('Next: '):
                return line[6:].strip()
    except Exception:
        pass
    return ''


def _save(d, probe, hit=False):
    probe['hit'] = bool(hit)
    d['probe'] = probe                                   # 兼容：最后一次调用快照
    # L3：按事件分槽——否则 Stop 时 d['probe'] 恒为最后一次 PreToolUse，
    # SessionStart/UserPromptSubmit 的留痕被覆盖，verdict 恒 unknown，硬闸失效（病15 识别范围≠对象范围）。
    ev = str(probe.get('event') or 'unknown')
    if ev in ('SessionStart', 'UserPromptSubmit'):
        d.setdefault('probe_by_event', {})[ev] = dict(probe)
    _write_state(d)


def _resolve_root(d, cwd, command, probe):
    r = _repo_root(cwd)
    if r:
        probe['via'] = 'cwd'
        return r
    for cand in _cmd_candidates(command):
        r = _repo_root(cand)
        if r:
            probe['via'] = 'command'
            return r
    last = d.get('last_repo') or ''
    if last and os.path.isdir(last):
        r = _repo_root(last)
        if r:
            # 环境身份锚：last_repo 回退是「静默猜仓」的根源，打显式标记，
            # 让下游注入能提示「本轮未从 payload 定位到本仓，身份可能错位」。
            probe['via'] = 'last_repo'
            probe['unaligned'] = True
            return r
    probe['via'] = 'none'
    return ''


def _exp_paths(repo_root):
    """经验闭环 v3 步骤3：经验数据/脚本路径不依赖 git root / last_repo。
    用户级 ~/.codebuddy/experience/ 优先（跨项目/跨会话共享），仓内 repo_root 作种子兜底。
    返回 (experience_recurrence.json 路径, 病号映射表.json 路径, exp_probe 所在目录, 来源标记)。
    """
    home_dir = os.path.join(os.path.expanduser('~'), '.codebuddy', 'experience')
    env_dir = os.environ.get('CODEBUDDY_EXP_HOME')
    candidates = ([env_dir] if env_dir else []) + [home_dir]
    for d in candidates:
        rec = os.path.join(d, 'experience_recurrence.json')
        if os.path.isfile(rec):
            mp = os.path.join(d, '病号映射表.json')
            return rec, (mp if os.path.isfile(mp) else os.path.join(repo_root, 'verify', '病号映射表.json')), d, 'user'
    # 用户级无副本 → 仓内种子（换仓/新沙箱首次，尚未 install 时）
    return (os.path.join(repo_root, 'experience_recurrence.json'),
            os.path.join(repo_root, 'verify', '病号映射表.json'),
            os.path.join(repo_root, 'verify'), 'repo-seed')


def main():
    if '--probe' in sys.argv[1:]:
        p = _read_state().get('probe') or {}
        print(json.dumps(p, ensure_ascii=False, indent=2) if p else '（无调用记录）')
        return 0

    # ---- 在途任务台账 CLI（发后台任务登记 / 完成销账 / 回读验证）----
    argv = sys.argv[1:]
    if '--task-list' in argv:
        print(json.dumps(_read_state().get('inflight') or {}, ensure_ascii=False, indent=2))
        return 0
    if '--task-add' in argv:
        i = argv.index('--task-add')
        parts = argv[i + 1:]
        if len(parts) >= 2:
            d = _read_state()
            d['inflight'][parts[0]] = {'desc': ' '.join(parts[1:])[:80], 'ts': int(time.time())}
            _write_state(d)
            print('[task-add] %s' % parts[0])
        return 0
    if '--task-done' in argv:
        i = argv.index('--task-done')
        if i + 1 < len(argv):
            d = _read_state()
            removed = d['inflight'].pop(argv[i + 1], None)
            _write_state(d)
            print('[task-done] %s %s' % (argv[i + 1], '✓' if removed else '(不在台账)'))
        return 0

    data = _payload()
    event = data.get('hook_event_name') or ''
    tool = data.get('tool_name') or data.get('toolName') or ''
    cwd = data.get('cwd') or data.get('workingDirectory') or os.getcwd()
    ti = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
    command = data.get('command') or ti.get('command') or ''

    d = _read_state()
    probe = {'ts': int(time.time()), 'event': event, 'tool': tool, 'cwd': cwd,
             'cmd': str(command)[:CMD_HEAD], 'root': '', 'via': 'none', 'hit': False}

    # ---- 模型侧锚点：UserPromptSubmit 注入 additionalContext（每轮一次，不节流）----
    if event == 'UserPromptSubmit':
        root = _resolve_root(d, cwd, command, probe)
        probe['root'] = root
        nxt = _next_line(root) if root else ''
        if not nxt:
            probe['via'] += '+no-next'
            _save(d, probe)
            return 0
        d['last_repo'] = root
        _save(d, probe, hit=True)
        msg = '⏭ 上一轮定的下一步（%s）：%s' % (os.path.basename(root), nxt[:400])
        # 环境身份锚：报家门 + last_repo 回退显式标未对齐（不再静默串仓）。
        _ea = env_anchor(root)
        if _ea:
            msg += '\n' + env_anchor_line(_ea)
        if probe.get('unaligned'):
            msg += '\n⚠ 身份未对齐：本轮未从 payload 定位到本仓（回退 last_repo），动手前先核对 env_id 是否匹配当前任务。'
        # 经验闭环闸3：按 Next 任务类型注入同型病号（读映射表+复发计数，降级静默）
        try:
            import json as _jj, re as _re, os as _os2
            _rec_path, _mp_path, _vdir, _src = _exp_paths(root)
            if not _os2.path.isfile(_rec_path) or not _os2.path.isfile(_mp_path):
                print('  ⚠ 经验数据未就绪（rec=%s, map=%s，来源=%s）——先跑 install.sh 装用户级副本'
                      % (_rec_path, _mp_path, _src), file=sys.stderr)
            _mp = _jj.load(open(_mp_path, encoding='utf-8')) if _os2.path.isfile(_mp_path) else {}
            _rec = _jj.load(open(_rec_path, encoding='utf-8')) if _os2.path.isfile(_rec_path) else {}
            _cnt = _rec.get('counters', {})
            _hits = []
            _nxt_low = nxt.lower()
            for _dz in _mp.get('diseases', []):
                if _dz.get('status') != 'active':
                    continue
                _tags = _dz.get('tags', [])
                if any(_tg in nxt or _tg in _nxt_low for _tg in _tags):
                    _n = _cnt.get(_dz['id'], {}).get('count', 0)
                    _hits.append((_n, _dz))
            if _hits:
                _hits.sort(key=lambda x: -x[0])
                _top = _hits[0][1]
                msg += '｜📚 本轮同型坑 %s·%s：%s' % (_top['id'], _top['name'], _top['fix'][:60])
                # S-02 机制解决（施工纪律·条件触发喂判据问句）：命中同型坑时当场问
                # "打补丁还是改真源"——不每轮念（会 habituate 成噪音），只在遇到
                # 具体坑、有据可查时提醒。不做机检、不进 Stop（做事态度机器判会误伤）。
                msg += '｜🔧 S-02：这坑这次是打补丁绕过，还是从机制/真源上解决？'
            # 经验闭环 v2 · ④呈现：注入经验池里的**具体条目**（不再只有坑名），
            # 按当前 Next 的 tags 命中同病号 → 带出 lesson/reuse 经验原文（可核实 evidence）。
            # 真源=exp_entries（exp_distill.py 从台账+commit 派生的可重建视图）。
            _es = _rec.get('exp_entries') or []
            if _es:
                _rels = [e for e in _es
                         if (_top and e.get('source_commit') and e.get('kind') == 'lesson'
                             and _top['id'] in (e.get('text') or ''))]
                _rels = _rels[:2]  # 最多 2 条，不刷屏（R-BG03 防洪水）
                for _e in _rels:
                    msg += ('｜💡经验 %s：%s（据 %s）'
                            % (_e['id'], (_e.get('text') or '')[:55], _e.get('evidence', '')[:18]))
                # 经验闭环 v3 · 直达：命中「已固化途径」的条目，注入解法落点（第二次不用重查）
                # fixed_path 由 exp_distill 从 commit 真实改动文件派生。
                # 修假账（v0.8.83）：注入=提示，只调 match 只读查询，**不在此记账**。
                # 把"看到经验"当"用了经验"是旧 bug——reuse_count 因此虚高但模型仍靠自觉。
                # 真复用改为显式闸：exp_probe.gate(symptom)（命中才 hit，返 reason/target/method）。
                _fp_entries = [e for e in _es if e.get('fixed_path')]
                for _fp_e in _fp_entries[:1]:  # 最多 1 条直达，防刷屏
                    try:
                        import sys as _sys3
                        if _vdir not in _sys3.path:
                            _sys3.path.insert(0, _vdir)
                        import exp_probe as _ep
                        _hit = _ep.match(nxt, rec=_rec)  # 只读查询，不记账
                        if _hit:
                            # 注入层不报落点（实测 fixed_path 49 条里 48 条是 .json/.md 脏落点，
                            # 无一条可执行代码）——只报命中+证据，真用走闸 exp_probe.gate()
                            # 取可信落点；唯一落点真源是拦截时 guard_cmd.gate_target(规则id)。
                            msg += '｜💡经验命中 %s（据 %s，命中度%s）｜真用先走闸 exp_probe.gate(症状)' % (
                                _hit['id'], str(_hit.get('evidence', ''))[:18], _hit['score'])
                    except Exception:
                        pass
        except Exception:
            pass  # 经验注入失败不影响主提醒
        # v0.8.67 批3：落库欠账注入——「该产未产」每轮红着给模型看，销账才消红。
        # 与上方落库提醒分层：提醒是"今天还没落库"，欠账是"某个 commit 的产出欠着"。
        try:
            import os as _osd
            _dp = _osd.path.join(root, 'verify', 'delivery_debt.json')
            if _osd.path.isfile(_dp):
                _dd = json.load(open(_dp, encoding='utf-8'))
                _op = [x for x in (_dd.get('debts') or []) if x.get('status') == 'open']
                if _op:
                    _thr = (_dd.get('thresholds') or {}).get('red_age_commits', 3)
                    _mx = max((x.get('age_commits') or 0) for x in _op)
                    _lvl = '⛔' if _mx > _thr else '⚠️'
                    _head = '，'.join('%s(%s←%s)' % (x.get('id', ''),
                                                    (x.get('folder', '').split('/')[-1]),
                                                    x.get('commit', '')) for x in _op[:3])
                    msg += ('｜%s 落库欠账 %d 条（最老 %d commit）%s%s——应产：%s；落库后自动销账'
                            % (_lvl, len(_op), _mx, '：' if _head else '', _head,
                               (_op[0].get('expect') or '')[:30]))
        except Exception:
            pass  # 欠账注入失败不影响主提醒
        # 思考闸门（防阻塞+效率 S6 纪律层，2026-11-15）：把「简单化」做成每轮必注入的
        # 三问，不靠模型临场自觉（M-R121：写进册子≠改掉行为）。挂在 UserPromptSubmit
        # 这个必经点——任何一轮都过，模型侧 additionalContext 实测能进上下文。
        msg += ('｜🧠 思考闸：①定性——要方案就零探查零施工直接出，要施工才动手；'
                '②探查——查类指令先扫会话记录/transcript（S-09），再查仓库丢子代理，主会话不连发命令；'
                '③收尾——后台非阻塞取（禁 block 等/禁轮询/禁前台 sleep），一目标收敛即停')
        # S-04 简洁输出（施工纪律·用户级，2026-11-17）：结论前置、文字压缩、不客套、不追加提问。
        msg += ('｜✂️ S-04：结论前置、一句讲清不拆段；去客套/开场白/多余总结；'
                '只答当前提问，不主动追加拓展提问')
        # B-12 回合收敛（v0.8.82 增量·软层硬化）：把「每轮末尾收敛三件」写进每轮必经
        # 注入点。平台 Stop payload 只给 last_assistant_message，无「回合内调用数」，
        # 「攒十几条调用不落回报」无法机检（B-02 无法判定，不装假闸）；能做的是让
        # 三要素每轮可见——S6 自觉提升到必经点，仍不算硬闸（不冒充已装）。
        msg += ('｜🔒 B-12：每轮回复末尾收敛三件——做了什么 / 凭什么（文件·行号·rc） / 下一步；'
                '一阶段完工即落回报，不把多个半成品堆一轮')
        # 二进制自动出场软提示（2026-11-18）：命中 prompt 里的 APK/dex/so 或逆向意图即提示
        # 加载熔铸司——只注入不拦截，卦在 UserPromptSubmit 必经点（永不拦截铁律不变）。
        try:
            _bh = binary_hint(data.get('prompt') or data.get('message') or '')
            if _bh:
                msg += _bh
        except Exception:
            pass  # 出场提示失败不影响主提醒（永不拦截）
        # S-09 会话证据「丑喂」（施工纪律闭环后硬化）：查类指令不再靠模型记得去扫
        # 会话——hook 主动从会话 jsonl 检索相关历史片段连行号注入，模型不必回想。
        # 只注入不拦截；模块加载/检索失败静默降级（永不拦截铁律），但写 probe 留痕。
        try:
            _prompt = str(data.get('prompt') or data.get('message') or '')
            _se_path = os.path.join(root, 'verify', 'session_evidence.py') if root else ''
            if _se_path and os.path.isfile(_se_path) and _prompt.strip():
                import importlib.util as _iu
                _spec = _iu.spec_from_file_location('_session_evidence', _se_path)
                _se = _iu.module_from_spec(_spec)
                _spec.loader.exec_module(_se)
                _ev = _se.inject(_prompt)
                if _ev:
                    msg += _ev
        except Exception:
            pass  # 检索失败静默降级——永不拦截，也不因留痕失败影响注入主流程
        # 在途任务跟踪（2026-11-15）：后台任务发时 --task-add 登记，完成通知到了自动
        # 销账（扫本轮 prompt 的 <task-notification>），每轮显示剩余清单——超 STALE_SEC
        # 标红提醒主动查。不再靠记忆/用户追问跟踪"完成了没"（用户实证痛点）。
        try:
            _inf = d.get('inflight') or {}
            if _inf:
                _prompt = str(data.get('prompt') or data.get('message') or '')
                _inf, _closed = autoclose_inflight(_prompt, _inf)
                if _closed:                              # 完成即销账，落 state
                    d['inflight'] = _inf
                    _write_state(d)
                if _inf:
                    _now = int(time.time())
                    _parts = []
                    for _tid, _tv in sorted(_inf.items(), key=lambda kv: kv[1].get('ts', 0)):
                        _age = max(0, _now - int(_tv.get('ts', _now)))
                        _flag = '⛔' if _age > STALE_SEC else '🔄'
                        _parts.append('%s%s(%s·%d分)' % (_flag, _tid,
                                      str(_tv.get('desc', ''))[:24], _age // 60))
                    msg += ('｜🔄 在途任务 %d 个：%s——完成即 --task-done 销账，⛔ 超 30 分钟主动查'
                            % (len(_inf), '，'.join(_parts[:5])))
        except Exception:
            pass  # 在途注入失败不影响主提醒（永不拦截铁律）
        # v0.8.64 方案v3 梯度③：交付落库提醒（520进化论·每轮必落库）——只提示不拦截，
        # 硬对账在 verify/gate_archive_ledger.py（梯度④），提醒与闸分层。
        import os as _os
        _led = _os.path.join(root, 'archive_ledger.json')
        if _os.path.isfile(_led):
            try:
                _d = json.load(open(_led, encoding='utf-8'))
                _last = (_d.get('entries') or [{}])[-1]
                _lt = (_last.get('ts') or '')[:10]
                if _lt != time.strftime('%Y-%m-%d'):
                    msg += '｜📦 提醒：archive_ledger 今日无落库回执——本轮交付完成后走 space-hub archive 正门落库'
            except Exception:
                pass
        print(json.dumps({'continue': True,
                          'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                                 'additionalContext': msg}},
                         ensure_ascii=False))
        return 0

    # ---- B-07 换模型对账：SessionStart 开机注入 handoff 首段（v0.8.66 批1-⑤）----
    # 判据（B-07 悬挂项实测）：新会话首轮出现 handoff 首段且 via 含 handoff。
    # 首段=「## 1. 当前主线」段（主线/习惯/业务上下文三项之首）；读不到明说，不装懂。
    if event == 'SessionStart':
        root = _resolve_root(d, cwd, command, probe)
        probe['root'] = root
        probe['via'] = 'session-start'
        hf = os.path.join(root, 'docs', 'handoff_latest.md') if root else ''
        seg = ''
        if hf and os.path.isfile(hf):
            try:
                t = open(hf, encoding='utf-8', errors='ignore').read(8000)
                m = re.search(r'## 1\. 当前主线[^\n]*\n+(.{0,500})', t, re.S)
                seg = (m.group(1).strip() if m else t.strip()[:400])
            except Exception:
                seg = ''
        if not seg:
            probe['via'] += '+no-handoff'
            _save(d, probe)
            print(json.dumps({'continue': True,
                              'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                                     'additionalContext':
                                                         '⚠ B-07：本会话未对齐——docs/handoff_latest.md 不存在或无首段，'
                                                         '先读交接摘要再动手。'}},
                             ensure_ascii=False))
            return 0
        probe['via'] += '+handoff'
        _save(d, probe, hit=True)
        msg = '🤝 B-07 交接对齐（%s）——当前主线：%s' % (os.path.basename(root), seg[:400])
        msg += '｜（全文：docs/handoff_latest.md，先读三项再动手）'
        # 环境身份锚：开机即自报家门，跨会话/跨仓第一眼分清是哪个生态。
        _ea = env_anchor(root)
        if _ea:
            msg += '\n' + env_anchor_line(_ea)
        else:
            msg += '\n⚠ 本仓无 ENV_ID.json：身份未登记，跨仓任务请先核对 env_id。'
        print(json.dumps({'continue': True,
                          'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                                 'additionalContext': msg}},
                         ensure_ascii=False))
        return 0

    # ---- 写文件类硬拦截：Write/Edit 目标在仓内且是凭据文件 → 挡在写下去那一刻 ----
    #   为什么挂这里：settings.json 里本脚本已有一条 matcher='Bash' 的注册，
    #   再加一条 matcher='Write|Edit' 即可复用同一份 deny 协议，不必让 guard_cmd
    #   同时当「库」和「注册钩子」（那会让 hook-probe 的依赖库豁免规则失效）。
    if tool and tool != 'Bash':
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import guard_cmd
            fp = ti.get('file_path') or ti.get('path') or ti.get('notebook_path') or ''
            # B-05 自动挡：把写入内容一起送进守卫——明文密钥字面量写进仓内普通文件
            # 也要在「写下去那一刻」挡住（Write=content / Edit=new_string）。
            _content = ti.get('content') if ti.get('content') is not None else ti.get('new_string')
            _w = guard_cmd.check_write(fp, _content)
            if _w:
                probe['via'] = 'write-guard:' + _w['id']
                _save(d, probe, hit=True)               # 命中守卫也算 hit（否则 probe 看着像没干活）
                print(json.dumps(guard_cmd.deny_payload(_w, payload=data), ensure_ascii=False))
                return 2
        except Exception as _e:
            probe['guard_err'] = ('%s: %s' % (type(_e).__name__, _e))[:120]
        probe['via'] = 'skip-tool'                      # 锚点提示仍只挂 Bash（Edit/Write 太频繁）
        _save(d, probe)
        return 0

    # ---- 工具级硬拦截：危险命令在**执行前**挡住（逻辑真源 hooks/guard_cmd.py）----
    #   协议实测（2026-11-14）：deny JSON + exit 2 → 平台直接阻断该次调用，
    #   模型侧看到 `PreToolUse:Bash hook blocked this tool call: <reason>`。
    #   fail-open：守卫自身坏了放行，但把 guard_err 写进 state（--probe 可查），
    #   不许静默失效——静默失效比不设防更危险。
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import guard_cmd
        _hit = guard_cmd.check(command)
        # B-11/G8 工具洪水计数（只 stats 留痕；超阈值才 deny，正常一批<50 条不误伤）
        if not _hit:
            _flood = guard_cmd.check_flood()
            if _flood:
                _hit = _flood
        if _hit:
            probe['via'] += '+guard:' + _hit['id']
            _save(d, probe, hit=True)                   # 同上：拦下来就是命中了
            print(json.dumps(guard_cmd.deny_payload(_hit, payload=data), ensure_ascii=False))
            return 2
    except Exception as _e:
        probe['guard_err'] = ('%s: %s' % (type(_e).__name__, _e))[:120]

    if not os.path.isdir(cwd):
        probe['via'] = 'bad-cwd'
        _save(d, probe)
        return 0

    root = _resolve_root(d, cwd, command, probe)
    probe['root'] = root
    if not root:
        _save(d, probe)
        return 0

    nxt = _next_line(root)
    if not nxt:
        probe['via'] += '+no-next'
        _save(d, probe)
        return 0
    if time.time() - float(d['repos'].get(root, 0) or 0) < THROTTLE_SEC:
        probe['via'] += '+throttled'
        _save(d, probe)
        return 0

    d['repos'][root] = time.time()
    d['last_repo'] = root
    _save(d, probe, hit=True)
    print('⏭ 上一轮 Next（%s）: %s' % (os.path.basename(root), nxt))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:                                   # 永不拦截：任何异常都放行
        sys.exit(0)
