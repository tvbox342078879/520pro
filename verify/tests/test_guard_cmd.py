#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""guard_cmd.py · 回归测试（工具级硬拦截是否真在守）

判据三件套：
  ① 造违例：`git ... --no-verify` / `rm -rf /` / 强推 main 三类必须被拦
  ② 具体判据：命中哪条规则（G1/G2/G3）必须报出来，不能只说"拦了"
  ③ 元变异：把规则表清空后违例必须溜过（自证判据真在守，不是永远返回 deny）

另加两条"接得上"的检查（闸写了但没挂 = 等于没写）：
  ④ next_anchor.py 的 PreToolUse 分支真的调了 guard_cmd
  ⑤ 安装副本与仓库真源逐 sha 一致（否则改仓不生效，是本项目反复踩过的病11）
"""
# impl: B-19 S5   ← 步骤4 落点完备性判据（audit 裸闸 + 元变异，非自报）
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, 'hooks')
GUARD = os.path.join(SCRIPTS, 'guard_cmd.py')
fails = []


N = [0]   # 例数由 check 自增；手工偏移量迟早对不上真实用例数（4 个测试文件同病）


def check(name, cond, detail=''):
    N[0] += 1
    if not cond:
        fails.append(name)
        print(f'  ✗ {name}  {detail}')
    else:
        print(f'  ✓ {name}')


def load(path):
    spec = importlib.util.spec_from_file_location('guard_t', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


G = load(GUARD)

# 危险命令样例在运行时拼接，避免本文件自身成为"含危险串的样本"被静态扫描误报
NV = '--no-' + 'verify'


def deny(cmd):
    hit = G.check(cmd)
    return (hit or {}).get('id')


# ── ① 违例必须被拦，② 且报的出是哪条 ──
cases = [
    (f'git commit -m x {NV}', 'G1'),
    (f'git -C /w commit {NV} -m y', 'G1'),
    (f'git push origin main {NV}', 'G1'),
    ('rm -rf /', 'G2'),
    ('rm -rf ~', 'G2'),
    ('rm -rf $HOME', 'G2'),
    ('git push origin main --force', 'G3'),
    ('git push -f origin main', 'G3'),
    ('git push --force-with-lease origin master', 'G3'),
]
for cmd, want in cases:
    got = deny(cmd)
    check(f'拦 {want}: {cmd[:38]}', got == want, f'实际={got}')

# ── 反例：常用操作不许误伤（误伤会逼人永久关钩子，等于闸没了） ──
ok_cases = [
    'git commit -m "feat: x"',
    'git push origin main',
    'git push origin dev --force',
    'rm -rf /tmp/build',
    'rm -rf ./out',
    'git log --oneline -1',
    'grep -rn "no-verify" docs/',
    'echo hello',
]
for cmd in ok_cases:
    got = deny(cmd)
    check(f'放行: {cmd[:38]}', got is None, f'误拦={got}')

# ── 阻断载荷格式（协议字段名错一个就静默失效） ──
hit = G.check('git push origin main --force')
p = G.deny_payload(hit)
hso = p.get('hookSpecificOutput') or {}
check('载荷含 permissionDecision=deny', hso.get('permissionDecision') == 'deny', str(p)[:120])
check('载荷含 hookEventName=PreToolUse', hso.get('hookEventName') == 'PreToolUse', str(p)[:120])
check('载荷含拒绝理由', bool(hso.get('permissionDecisionReason')), str(p)[:120])

# ── ③ 元变异：规则表清空，违例必须溜过 ──
src = open(GUARD, encoding='utf-8').read()
mut = re.sub(r'^RULES = \[.*?^\]\n', 'RULES = []\n', src, flags=re.S | re.M)
check('变异真的落盘', 'RULES = []' in mut)
td = tempfile.mkdtemp()
mp = os.path.join(td, 'guard_mutated.py')
open(mp, 'w', encoding='utf-8').write(mut)
Gm = load(mp)
check('规则清空后强推溜过', Gm.check('git push origin main --force') is None)
check('规则清空后 --no-verify 溜过', Gm.check(f'git commit {NV}') is None)
# G7 元变异：数值判定函数失效后，前台长 sleep 必须溜过（自证判据真在守）
mut2 = re.sub(r'def _long_sleep\(command\):.*?(?=\n\n\n#)', 'def _long_sleep(command):\n    return None', src, flags=re.S)
mp2 = os.path.join(td, 'guard_nosleep.py')
open(mp2, 'w', encoding='utf-8').write(mut2)
Gm2 = load(mp2)
check('数值判定失效后 sleep 240 溜过（G7 非假绿）', Gm2.check('sleep 240') is None)

# ── ⑥ G4 双核保护（B-16：删/移 probe-hub、tvbox-core 必须拦）──
# 名字同样运行时拼接，避免本文件被自己扫成违例样本
CORE = 'tvbox' + '-core'
HUB = 'probe' + '-hub'

g4_hit = [
    (f'rm -rf {CORE}', '直接删双核目录'),
    (f'rm -rf skills/{CORE}; echo ok', '双核名后跟分号（首版漏判的真实场景）'),
    (f'rm -rf {CORE}/scripts | tee log', '双核后跟管道'),
    (f'mv {HUB} /tmp/bak', '把双核移走=改名'),
    (f'git rm -r {HUB}', 'git rm 删双核'),
]
for cmd, why in g4_hit:
    h = G.check(cmd)
    check(f'G4 拦下：{why}', h is not None and h['id'] == 'G4',
          f'实际={h["id"] if h else "放行"}')

g4_pass = [
    (f'cp -r {HUB} /tmp/bak', '备份不改原件'),
    (f'mv /tmp/newcore skills/{CORE}', '双核是目标不是被删对象'),
    (f'rm -rf /tmp/{CORE}-backup', '名字前缀相同但不是双核本体'),
    (f'ls {HUB}', '只读不拦'),
    ('git status --short', '无关命令'),
]
for cmd, why in g4_pass:
    h = G.check(cmd)
    check(f'G4 放行：{why}', h is None, f'误拦={h["id"] if h else ""}')

# ── ⑦ B-05 零明文凭证：G5（git add 凭据）/ G6（写仓内凭据）──
g5_hit = [
    ('git add .env', '最常见的一条'),
    ('git add .env.local', '多环境写法（首版前瞻漏了 `.`，实测漏判）'),
    ('git add config/credentials.json', '子目录里的凭据'),
    ('git add ~/.ssh/id_rsa', '私钥'),
    ('git add deploy/server.pem', '证书私钥'),
    ('git add -- .env', '带 -- 分隔符'),
]
for cmd, why in g5_hit:
    h = G.check(cmd)
    check(f'G5 拦下：{why}', h is not None and h['id'] == 'G5',
          f'实际={h["id"] if h else "放行"}')

g5_pass = [
    ('git add -A', '批量 add 不含文件名，判不了（交给 secret_scan 兜）'),
    ('git add .env.example', '模板不含真凭据'),
    ('git add .env.sample', '同上'),
    ('git add id_rsa.pub', '公钥可以进库'),
    ('git add src/app.py', '普通文件'),
    # 以下是首版判据的真实误伤（连拦我三次）：批量 add 与提交说明分处两段，
    # 说明里提到 `.env` 只是文档，不该算「要把凭据加进库」。
    ('git add -A && git commit -q -F /tmp/msg.txt', '批量 add + 说明文件（说明里可能提到凭据名）'),
    ('git add -A && git commit -m "docs: mention .env handling"', '提交说明里提到凭据名'),
    ('cd repo && git add src/ && git commit -m "x"', '先 cd 再提交'),
]
for cmd, why in g5_pass:
    h = G.check(cmd)
    check(f'G5 放行：{why}', h is None, f'误拦={h["id"] if h else ""}')

# ── ⑧ B-11/G7 前台长 sleep：执行事实判定（basename+秒数），正反样本抄真实教训 ──
g7_hit = [
    ('sleep 30', '阈值边界（含等号）'),
    ('sleep 240', 'R-BG03 实测最长 240s 的前台 sleep'),
    ('sleep 1m', '分钟单位换算成 60s'),
    ('sleep 120 && echo done', '带后续命令仍命中'),
]
for cmd, why in g7_hit:
    h = G.check(cmd)
    check(f'G7 拦下：{why}', h is not None and h['id'] == 'G7',
          f'实际={h["id"] if h else "放行"}')

g7_pass = [
    ('sleep 1', '短 sleep 属正常（探活/节流）'),
    ('sleep 0.5', '亚秒级不拦'),
    ('echo sleep 240', '命令文本里出现 sleep 串但不是 sleep 命令——判据必须看执行事实'),
    ('grep -rn "sleep 60" hooks/', '搜索文本含 sleep，不拦'),
    ('git log --oneline -1', '无关命令'),
]
for cmd, why in g7_pass:
    h = G.check(cmd)
    check(f'G7 放行：{why}', h is None, f'误拦={h["id"] if h else ""}')

# S-06（施工纪律·不扩大拦截范围）：复用上面 g7_pass 的反例断言——
# echo/grep 文本含 sleep 串不是命令，必须放行；误拦即 S-06 违例。
for cmd, why in g7_pass[:4]:
    check(f'S-06 不扩大拦截：{cmd}', G.check(cmd) is None, '文本串误判为命令')

# ── ⑨ B-11/G8 工具洪水：滑动窗口计数，抄真实「41 次 sleep / 工具洪水占满回合」 ──
G.FLOOD_STATE = os.path.join(tempfile.mkdtemp(), 'flood_state.json')  # 测试隔离，不污染真 state
json.dump({'ts': []}, open(G.FLOOD_STATE, 'w'))  # 真清空，不靠 check_flood 记一条来"清"
base = 1000.0
for i in range(G.FLOOD_THRESHOLD):
    h = G.check_flood(now=base + i + 1)
check('G8 阈值内放行（正常一批请求）', h is None, f'误拦={h}')
h = G.check_flood(now=base + G.FLOOD_THRESHOLD + 1)
check('G8 超阈值命中（工具洪水）', h is not None and h['id'] == 'G8', f'实际={h}')
h2 = G.check_flood(now=base + G.FLOOD_WINDOW_SEC + G.FLOOD_THRESHOLD + 5)
check('G8 窗口外计数滑出后放行', h2 is None, f'误拦={h2}')

# ── 思考闸门：UserPromptSubmit 必须注入三问（写进册子≠改行为，靠必经点注入） ──
na_src = open(os.path.join(SCRIPTS, 'next_anchor.py'), encoding='utf-8').read()
check('思考闸门注入：定性一问', '定性' in na_src and '零探查' in na_src)
check('思考闸门注入：探查走子代理一问', '子代理' in na_src and '主会话不连发' in na_src)
check('思考闸门注入：收尾非阻塞一问', '禁 block' in na_src and '禁轮询' in na_src)
check('B-12 回合收敛软层注入：三要素每轮可见（S6 非硬闸，仅守在册）',
      'B-12' in na_src and '做了什么' in na_src and '凭什么' in na_src and '下一步' in na_src)
check('G8 洪水闸接进 next_anchor 执行路径', 'check_flood' in na_src)

# ── 在途任务跟踪：完成通知自动销账 + 台账 CLI + 超阈值标红（真 import 测函数，非读源码）──
NA = load(os.path.join(SCRIPTS, 'next_anchor.py'))
_inf = {'t1': {'desc': 'push', 'ts': 1}, 't2': {'desc': 'verify', 'ts': 2}}
_done = '<task-notification><task-id>t1</task-id><status>completed</status></task-notification>'
_l, _c = NA.autoclose_inflight(_done, _inf)
check('在途-完成通知自动销账', list(_l) == ['t2'] and _c == ['t1'], f'left={list(_l)} closed={_c}')
check('在途-working 不销', NA.autoclose_inflight(
    '<task-notification><task-id>t1</task-id><status>working</status></task-notification>', _inf)[1] == [])
check('在途-无关消息不销', NA.autoclose_inflight('普通消息', _inf)[1] == [])
check('在途-四种终态全认', all(
    't2' in NA.autoclose_inflight(
        '<task-notification><task-id>t2</task-id><status>%s</status></task-notification>' % st, _inf)[1]
    for st in ('completed', 'failed', 'canceled', 'rejected')))
check('在途-台账注入接进执行路径', 'autoclose_inflight' in na_src and '🔄 在途任务' in na_src)
check('在途-超阈值标红接进执行路径', 'STALE_SEC' in na_src and '⛔' in na_src)

g6_hit = [os.path.join(ROOT, '.env'),
          os.path.join(ROOT, 'deploy', 'server.pem'),
          os.path.join(ROOT, 'credentials.json')]
for p_ in g6_hit:
    h = G.check_write(p_)
    check(f'G6 拦下：{os.path.relpath(p_, ROOT)}', h is not None and h['id'] == 'G6',
          f'实际={h["id"] if h else "放行"}')

g6_pass = [(os.path.join(ROOT, '.env.example'), '模板'),
           ('/tmp/.env', '仓外临时文件（不入库就无风险）'),
           (os.path.join(ROOT, 'src', 'app.py'), '普通源文件')]
for p_, why in g6_pass:
    h = G.check_write(p_)
    check(f'G6 放行：{why}', h is None, f'误拦={h["id"] if h else ""}')

# 凭据名单两份必须一致：secret_scan.py 的 CRED_NAMES 是「已追踪凭据」的真源，
# guard_cmd 的 CRED_BASENAMES 是它的镜像。改了单边就红——不靠「记得改两处」。
SS = load(os.path.join(ROOT, 'secret_scan.py'))
check('G5 基础名单与 secret_scan.CRED_NAMES 逐项一致',
      tuple(SS.CRED_NAMES) == tuple(G.CRED_BASENAMES),
      f'secret_scan={SS.CRED_NAMES} vs guard={G.CRED_BASENAMES}')

# install.sh 必须真的把 Write|Edit 那条注册进去（写了脚本但没挂 = 等于没写）
instsh = open(os.path.join(ROOT, 'install.sh'), encoding='utf-8').read()
check("install.sh 声明 Write|Edit 注册", "'Write|Edit'" in instsh)

# ── ④ 闸必须真的挂在执行路径上 ──
na = open(os.path.join(SCRIPTS, 'next_anchor.py'), encoding='utf-8').read()
check('next_anchor 调用 guard_cmd', 'import guard_cmd' in na and 'guard_cmd.check(' in na)
check('next_anchor 调用 check_write（G6 走的就是这条路）', 'guard_cmd.check_write(' in na)
check('next_anchor 命中后返回非零', re.search(r'guard_cmd\.deny_payload.*\n.*return 2', na) is not None
      or re.search(r'deny_payload\(_hit\).*?\n.*?return 2', na, re.S) is not None)
check('守卫故障留痕（fail-open 不静默）', 'guard_err' in na)

# ── ⑪ 步骤4 落点完备性闸（非自报：落点真源=用例存在性，裸闸即红）─────────
# 判据对象=全部能拦人的规则（RULES + WRITE_RULE + G8），真函数真读判据文件，
# 不读 guard_rules 映射（病15：识别范围≠对象范围）。
_audit = G.audit_landings()
check('步骤4/audit_landings 有全部规则（含 G8，不漏拦截规则）',
      all(r in _audit['rules'] for r in ('G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8')))
check('步骤4/真实态无裸闸（bare 为空）', _audit['bare'] == [], f"bare={_audit['bare']}")
for _rid, _land in _audit['rules'].items():
    _lf = os.path.join(ROOT, _land.split('#')[0]) if _land else ''
    check(f'步骤4/{_rid} 落点文件真实存在且带专属锚点',
          bool(_land) and ('#%s' % _rid) in _land and os.path.isfile(_lf),
          f'landing={_land}')
# 元变异（自证判据真在守，非假绿）：复制判据文件到临时 HOME，抹掉 G7 断言锚点，
# 让 gate_target 的 root 指向它——G7 必须变 None、audit 必须报裸闸。
import shutil as _shutil
_td4 = tempfile.mkdtemp(prefix='gate_landing_')
try:
    _fake_root = os.path.join(_td4, 'repo')
    os.makedirs(os.path.join(_fake_root, 'verify', 'tests'))
    _src4 = open(os.path.join(ROOT, 'verify', 'tests', 'test_guard_cmd.py'), encoding='utf-8').read()
    # 抹掉所有 G7 字面量（用例锚点消失）= 造裸闸
    _mut4 = re.sub(r"['\"]G7['\"]", "'GX7MUT'", _src4)
    open(os.path.join(_fake_root, 'verify', 'tests', 'test_guard_cmd.py'), 'w',
         encoding='utf-8').write(_mut4)
    _oldcwd4 = os.getcwd()
    os.chdir(_fake_root)
    try:
        check('步骤4/元变异：抹掉 G7 用例锚点后 gate_target(G7) 转 None',
              G.gate_target('G7') is None)
        check('步骤4/元变异：裸闸被 audit_landings 报出（fail-closed）',
              'G7' in G.audit_landings()['bare'])
    finally:
        os.chdir(_oldcwd4)
finally:
    _shutil.rmtree(_td4)
# deny_payload 对裸闸仍 fail-closed deny（缺落点不放行），reason 标注裸闸。
# 病15 防护：id 必须运行时动态生成——若写死字面量在判据文件里，gate_target
# 按"源码含该字面量"判锚点会把判据自己写的 id 当真用例（假绿，本步骤实测踩过）。
_dyn_id = 'G-NOLAND-' + str(os.getpid())
_pay4 = G.deny_payload({'id': _dyn_id, 'why': 't', 'fix': 'f'})
check('步骤4/裸闸仍 deny 且 reason 标注（不静默放行）',
      _pay4['hookSpecificOutput']['permissionDecision'] == 'deny'
      and '⚠裸闸' in _pay4['hookSpecificOutput']['permissionDecisionReason'],
      _pay4['hookSpecificOutput']['permissionDecisionReason'][:120])

# ── 步骤5 复发记账真源统一（修 15/16 分叉：写侧与读侧同真源）─────────────
# 病15 防护：判据对象是「记账真文件」，用 CODEBUDDY_EXP_HOME mock 隔离，
# 真跑 _bump 到用户级 mock，验：①写用户级 ②仓内种子不污染 ③同分钟去重仍在。
import shutil as _sh5
_td5 = tempfile.mkdtemp()
try:
    _seed5 = os.path.join(ROOT, 'experience_recurrence.json')
    _live5 = os.path.join(_td5, 'experience_recurrence.json')
    _sh5.copy(_seed5, _live5)
    _d = json.load(open(_live5, encoding='utf-8'))
    _bid5 = '病TEST5-' + str(os.getpid())
    _d['counters'][_bid5] = {'count': 0, 'events': [], 'last_ts': '', 'status': 'active'}
    json.dump(_d, open(_live5, 'w', encoding='utf-8'), ensure_ascii=False)

    _saved_home = os.environ.get('CODEBUDDY_EXP_HOME')
    os.environ['CODEBUDDY_EXP_HOME'] = _td5
    try:
        # 真函数：_live_rec_path 用户级优先（识别范围=对象范围：账本路径本身）
        check('步骤5/_live_rec_path 用户级优先（真函数）',
              G._live_rec_path(ROOT) == _live5)
        # 真跑 bump（写用户级 mock）
        G._bump_recurrence(_bid5, coord='步骤5 判据验证')
        _d1 = json.load(open(_live5, encoding='utf-8'))['counters'][_bid5]
        check('步骤5/bump 记到用户级（count 0→1、events 1 条）',
              _d1['count'] == 1 and len(_d1['events']) == 1, str(_d1)[:100])
        # 仓内种子未被污染（分叉已消除：写侧不再碰仓内）
        _seed_after = json.load(open(_seed5, encoding='utf-8'))['counters']
        check('步骤5/bump 不污染仓内种子（读侧同真源）', _bid5 not in _seed_after)
        # 同分钟去重仍在（不因换路径丢失去重语义）
        G._bump_recurrence(_bid5, coord='步骤5 判据验证-同分钟')
        _d2 = json.load(open(_live5, encoding='utf-8'))['counters'][_bid5]
        check('步骤5/同分钟去重保留（不重复计数）', _d2['count'] == 1)
    finally:
        if _saved_home is None:
            os.environ.pop('CODEBUDDY_EXP_HOME', None)
        else:
            os.environ['CODEBUDDY_EXP_HOME'] = _saved_home
finally:
    _sh5.rmtree(_td5)

# ── ⑤ 安装副本与仓库真源一致 ──
def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest() if os.path.exists(p) else None

inst = os.path.expanduser('~/.codebuddy/hooks')
if os.path.isdir(inst):
    for f in ('next_anchor.py', 'guard_cmd.py'):
        a, b = sha(os.path.join(SCRIPTS, f)), sha(os.path.join(inst, f))
        check(f'安装副本一致: {f}', a == b, '改仓后忘了同步 → 钩子跑的是旧逻辑')
else:
    check('安装根不存在时跳过镜像比对', True)

print('test_guard_cmd：%d 例，失败 %d' % (N[0], len(fails)))
sys.exit(1 if fails else 0)


# G4 豁免2（v0.8.64 经验闭环轮）：副本文件删除放行、真源与目录仍拦（病15 修法回归固化）
# 注：本用例数据含删除类文本，故以文件形式固化而非命令行内嵌——正文提到≠要执行，
# 但 PreToolUse 只能扫文本，触发组合必须离开命令行（G5 教训同款处置）。
def test_g4_exempt2():
    import sys
    sys.path.insert(0, '/workspace/520pro/hooks')
    import guard_cmd as gc
    cases = [
        ("rm -rf /workspace/520pro/能力层/tvbox/skills/tvbox-core", True),
        ("rm -rf x/tvbox-core; echo ok", True),
        ("rm -rf /root/.codebuddy/skills/probe-hub", True),
        ("rm /root/.codebuddy/skills/probe-hub/some.json", False),
    ]
    bad = 0
    for cmd, want in cases:
        hit = gc.check(cmd)
        got = bool(hit and hit.get('id') == 'G4')
        assert got == want, f"G4豁免2回归失败: {cmd} want={want} got={got}"
    return True
