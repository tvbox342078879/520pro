#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_gate_scan.py — verify/gate_scan.py 的三件套测试（病10 / 病13）

三条件（判据才算判据）：
  ① 能造违例：裸 git diff --cached / 缺 --probe 的钩子 → 红
  ② 具体判据拦下：红项理由指向预期原因（病号 + 文件）
  ③ 把判据改坏能溜过：元变异——把 QUOTEPATH 常量改坏后，违例文件能穿过（自证判据真在守）

退出码 0 全通 / 1 有用例未按预期。
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCAN = os.path.join(ROOT, 'verify', 'gate_scan.py')

fails = []


N = [0]   # 例数由 check 自增；手工偏移量迟早对不上真实用例数（4 个测试文件同病）


def check(name, cond, detail=''):
    N[0] += 1
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


def run(args, cwd=None):
    r = subprocess.run([sys.executable, SCAN] + args, capture_output=True, text=True,
                       timeout=60, cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w', encoding='utf-8').write(text)


# ── ① 正向：真源仓库三 gate 全绿 ──
# 用合成 settings 而非宿主机那份：判据本身要能跨机器复现，
# 不能让「本机装没装钩子」决定测试红绿（那测的是环境，不是判据）。
# ★ v0.8.80 机制级修（病15 第 19 例升级为模式）：fixture 条目不再手写——
#   直接用 gate_scan.declared_events 从 install.sh 提取「脚本→事件」声明自动生成注册，
#   与 hook-registered 同一条提取逻辑。真源每加一个钩子，fixture 自动跟上，
#   彻底断「静态清单随真源扩展脱钩 → 声明一致用例恒红」这一类红。
def _fake_settings(path, drop=None, hollow=None):
    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, 'verify'))
    from gate_scan import declared_events
    decl = declared_events(open(os.path.join(ROOT, 'install.sh'),
                                encoding='utf-8').read())
    cfg = {'hooks': {}}
    for script, events in decl.items():
        entry = {'matcher': 'Bash|Write|Edit|TaskOutput|Agent|Task',
                 'hooks': [{'type': 'command', 'command': 'python3 /x/' + script}]}
        for ev in events:
            cfg['hooks'].setdefault(ev, []).append(entry)
    # next_anchor 挂两条 matcher（Bash 与 Write|Edit），声明提取只到事件级——补齐
    pre = cfg['hooks'].get('PreToolUse', [])
    for e in list(pre):
        if 'next_anchor.py' in e['hooks'][0]['command']:
            pre.append(dict(e))
            break
    if drop:
        cfg['hooks'].pop(drop, None)
    if hollow:
        cfg['hooks'][hollow] = []
    open(path, 'w', encoding='utf-8').write(json.dumps(cfg, ensure_ascii=False))
    return path


_td0 = tempfile.mkdtemp()
SET_OK = _fake_settings(os.path.join(_td0, 'ok.json'))
rc, out = run(['--root', ROOT, '--settings', SET_OK])
check('真源全绿 rc=0', rc == 0, out[-200:])
check('输出含五闸标记（impl-reconcile 是 · 不是 ✓）',
      all(('[%s] 全绿' % g) in out
          for g in ('quotepath', 'hook-probe', 'hook-registered', 'case-count'))
      and '[impl-reconcile]' in out,
      out[-300:])

# ── ② 造违例：quotepath ──
with tempfile.TemporaryDirectory() as td:
    w(os.path.join(td, 'scripts', 'bad.sh'),
      'files=$(git diff --cached --name-only)\n')
    rc, out = run(['--gate', 'quotepath', '--root', td])
    check('裸 diff --cached 被拦 rc=2', rc == 2, out[-200:])
    check('红项指向 bad.sh 且带病号', 'bad.sh' in out and '病10' in out, out[-200:])

    w(os.path.join(td, 'scripts', 'bad.sh'),
      'files=$(git -c core.quotepath=false diff --cached --name-only)\n')
    rc, out = run(['--gate', 'quotepath', '--root', td])
    check('带 -c 后放行 rc=0', rc == 0, out[-200:])

    w(os.path.join(td, 'scripts', 'bad.sh'),
      '# 仅注释：git diff --cached --name-only\n')
    rc, out = run(['--gate', 'quotepath', '--root', td])
    check('注释行豁免 rc=0', rc == 0, out[-200:])

    w(os.path.join(td, 'scripts', 'bad.sh'),
      'n=$(git -C "$T" ls-files | wc -l)\n')
    rc, out = run(['--gate', 'quotepath', '--root', td])
    check('裸 ls-files 同样被拦', rc == 2 and '病10' in out, out[-200:])

# ── ③ 造违例：hook-probe ──
with tempfile.TemporaryDirectory() as td:
    w(os.path.join(td, 'install.sh'),
      'cp "$ROOT/hooks/na.py" "$HOME/.codebuddy/hooks/na.py"\n')
    w(os.path.join(td, 'hooks', 'na.py'),
      "if '--probe' in sys.argv: ...\nprobe = {'hit': False, 'via': 'none'}\n")
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('合规平台钩子放行 rc=0', rc == 0, out[-200:])

    w(os.path.join(td, 'hooks', 'na.py'), "if '--probe' in sys.argv: ...\n")
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('缺 hit/via 被拦', rc == 2 and 'via' in out and '病13' in out, out[-200:])

    os.remove(os.path.join(td, 'hooks', 'na.py'))
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('注册但文件不存在被拦', rc == 2 and '不存在' in out, out[-200:])

    # v0.8.55：被 import 的依赖库不要求自带 --probe（观测由调用方 probe['via'] 承担），
    # 但不能是空文件——空库装上去就是个静默失效的钩子依赖。
    w(os.path.join(td, 'install.sh'),
      'cp "$ROOT/hooks/main.py" "$HOME/.codebuddy/hooks/main.py"\n'
      'cp "$ROOT/hooks/lib.py" "$HOME/.codebuddy/hooks/lib.py"\n')
    w(os.path.join(td, 'hooks', 'main.py'),
      "if '--probe' in sys.argv: ...\nimport lib\nprobe = {'hit': False, 'via': 'none'}\n")
    w(os.path.join(td, 'hooks', 'lib.py'), 'def check(c):\n    return None\n')
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('被 import 的依赖库不要求 --probe', rc == 0, out[-200:])

    w(os.path.join(td, 'hooks', 'lib.py'), '\n\n')
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('空依赖库被拦', rc == 2 and '空文件' in out, out[-200:])

    w(os.path.join(td, 'install.sh'), 'echo nothing-here\n')
    rc, out = run(['--gate', 'hook-probe', '--root', td])
    check('install.sh 无注册被拦', rc == 2 and '提取不到' in out, out[-200:])

# ── ④ 元变异：把判据改坏，违例必须溜过（自证判据真在守） ──
with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as vd:
    vdir = os.path.join(vd, 'scripts')
    w(os.path.join(vdir, 'bad.sh'), 'f=$(git diff --cached --name-only)\n')
    src = open(SCAN, encoding='utf-8').read()
    mutated = src.replace("QUOTEPATH = 'core.quotepath=false'",
                          "QUOTEPATH = 'X-MUTATED-NOT-EXIST'")
    check('变异真的落盘', 'X-MUTATED-NOT-EXIST' in mutated)
    mpath = os.path.join(td, 'scan_copy.py')
    open(mpath, 'w', encoding='utf-8').write(mutated)
    r = subprocess.run([sys.executable, mpath, '--gate', 'quotepath', '--root', vdir],
                       capture_output=True, text=True, timeout=60)
    check('判据改坏后违例溜过 rc=0', r.returncode == 0, (r.stdout + r.stderr)[-200:])

# ── ⑤ verify.sh 必须真的挂了这道闸（防"测试绿但段被删"） ──
vsh = open(os.path.join(ROOT, 'verify.sh'), encoding='utf-8').read()
check('verify.sh 注册 gate_scan 调用', 'gate_scan.py' in vsh)

# ── ⑥ hook-registered：脚本合格 ≠ 钩子挂上（病13 的另一半） ──
# 典型事故：stop_guard.py 在盘上、--probe 齐全、cp 那行还在 install.sh 里，
# 但 settings.json 的 Stop 段被删/被覆盖 → 钩子一次都不跑，而闸全绿。
with tempfile.TemporaryDirectory() as td:
    p = _fake_settings(os.path.join(td, 's.json'))
    rc, out = run(['--gate', 'hook-registered', '--root', ROOT, '--settings', p])
    check('声明与实况一致时放行 rc=0', rc == 0 and '全绿' in out, out[-200:])

    p = _fake_settings(os.path.join(td, 's_drop.json'), drop='Stop')
    rc, out = run(['--gate', 'hook-registered', '--root', ROOT, '--settings', p])
    check('删掉 Stop 段被拦', rc == 2 and 'stop_guard.py' in out and 'hooks.Stop' in out, out[-200:])

    p = _fake_settings(os.path.join(td, 's_hollow.json'), hollow='Stop')
    rc, out = run(['--gate', 'hook-registered', '--root', ROOT, '--settings', p])
    check('Stop 段为空数组同样被拦', rc == 2 and 'stop_guard.py' in out, out[-200:])

    # 同一个脚本挂两个事件（next_anchor：PreToolUse + UserPromptSubmit），
    # 只摘掉其中一个也要红——否则「挂了一半」会被当成挂上了。
    import copy as _copy
    cfg = json.load(open(_fake_settings(os.path.join(td, 's_u.json')), encoding='utf-8'))
    cfg['hooks']['UserPromptSubmit'] = []
    pu = os.path.join(td, 's_u2.json')
    open(pu, 'w', encoding='utf-8').write(json.dumps(cfg, ensure_ascii=False))
    rc, out = run(['--gate', 'hook-registered', '--root', ROOT, '--settings', pu])
    check('多事件脚本挂一半也拦', rc == 2 and 'next_anchor.py' in out and 'UserPromptSubmit' in out,
          out[-200:])

    # 三态：机器上根本没装 → 「不适用」，既不判通过也不判失败（B-02），退出码 0
    rc, out = run(['--gate', 'hook-registered', '--root', ROOT,
                   '--settings', os.path.join(td, 'not_here.json')])
    check('settings 不存在记不适用 rc=0', rc == 0 and '不适用' in out and '全绿' not in out,
          out[-200:])

    # 判据自证：把 install.sh 的绑定段删掉，就提不出 {脚本:事件}，
    # 此时必须红——否则「删掉合并段」本身就成了一条绕过路径。
    w(os.path.join(td, 'install.sh'),
      'cp "$ROOT/hooks/na.py" "$HOME/.codebuddy/hooks/na.py"\necho no-binding-here\n')
    w(os.path.join(td, 'hooks', 'na.py'), 'x=1\n')
    rc, out = run(['--gate', 'hook-registered', '--root', td, '--settings', SET_OK])
    check('提不出绑定时报红（不可绕过）', rc == 2 and '提取不到' in out, out[-200:])

# ── ⑦ case-count：测试例数不许写死（病12 复发型，2026-11-14 四文件同时命中） ──
# 造违例要用的字面量必须拆成两段存：整串写进源码会被本闸扫到（病1 自指家族，已三犯）。
# 拆开后 `例，失败 %d'` 与 `% (` 不再相邻，正则匹配不上真实源码，只匹配造出来的文件。
_V = "例，失败 %d'" + " % ("

with tempfile.TemporaryDirectory() as td:
    bad = os.path.join(td, 'verify', 'tests', 'test_x.py')
    w(bad, "print('test_x：%d " + _V + "14, len(fails)))\n")
    rc, out = run(['--gate', 'case-count', '--root', td])
    check('例数写死被拦', rc == 2 and 'test_x.py' in out and '病12' in out, out[-200:])

    w(bad, "N = [0]\nprint('test_x：%d " + _V + "N[0], len(fails)))\n")
    rc, out = run(['--gate', 'case-count', '--root', td])
    check('N[0] 自增放行', rc == 0, out[-200:])

    w(bad, "print('test_x：%d " + _V + "len(cases) + 22, len(fails)))\n")
    rc, out = run(['--gate', 'case-count', '--root', td])
    check('偏移估算同样被拦', rc == 2 and 'len(cases' in out, out[-200:])

# impl: B-02 S5   ← 三态不折叠：· 不得被算成 ✓，汇总必须同时报红数与不适用数


# ── ⑧ impl-reconcile：映射声称的强度与实物自报的强度双向对账 ──
# 造的是「映射说有人守 / 实物没人守」和「实物有人守 / 映射说没人」两个方向的断裂。
with tempfile.TemporaryDirectory() as td:
    def mk_rulemap(rules):
        w(os.path.join(td, 'verify', 'rule_map.json'),
          json.dumps({'rules': rules}, ensure_ascii=False))

    # ⑧-① 虚标：machine 却没有任何强度声明（B-02 的原始形态）
    mk_rulemap({'B-99': {'verify_id': 'V-X', 'kind': 'machine', 'check': 'a.py', 'anchor': 'x'}})
    rc, out = run(['--gate', 'impl-reconcile', '--root', td])
    check('machine 无 strength 判虚标', rc == 2 and '虚标' in out, out[-200:])

    # ⑧-② 漏登：实物自报 S1，映射没登记（B-13 的原始形态）
    mk_rulemap({'B-98': {'verify_id': 'V-X', 'kind': 'manual', 'how': '看一眼'}})
    w(os.path.join(td, 'h.py'), '# impl: B-98 S1\nprint(1)\n')
    rc, out = run(['--gate', 'impl-reconcile', '--root', td])
    check('实物有标记而映射未登记判漏登', rc == 2 and '漏登' in out, out[-200:])

    # ⑧-③ 过期登记：映射登记 S1，实物没有标记（改小/退役后忘了改表）
    mk_rulemap({'B-97': {'verify_id': 'V-X', 'kind': 'machine', 'check': 'a.py', 'anchor': 'x',
                         'strength': {'S1': 'h.py#x'}, 'impl': ['h.py']}})
    w(os.path.join(td, 'h.py'), 'print(1)\n')
    rc, out = run(['--gate', 'impl-reconcile', '--root', td])
    check('映射登记而实物无标记判写了没挂', rc == 2 and ('写了没挂' in out or '过期登记' in out),
          out[-200:])

    # ⑧-④ 行内提到标记不算实现（自指防护：首版正则把 docstring 示例当成了落点）
    mk_rulemap({'B-96': {'verify_id': 'V-X', 'kind': 'machine', 'check': 'a.py', 'anchor': 'x',
                         'strength': {'S1': 'h.py#x'}, 'impl': ['h.py']}})
    w(os.path.join(td, 'h.py'), 'NOTE = "see `# impl: B-96 S1` for detail"\n')
    rc, out = run(['--gate', 'impl-reconcile', '--root', td])
    check('行内提到标记不算实现（只认整行注释）',
          rc == 2 and ('写了没挂' in out or '过期登记' in out), out[-200:])

    # ⑧-⑤ 双向一致 → 放行
    mk_rulemap({'B-95': {'verify_id': 'V-X', 'kind': 'machine', 'check': 'a.py', 'anchor': 'x',
                         'strength': {'S1': 'h.py#x'}, 'impl': ['h.py'],
                         'proven_by': {'cmd': 'c', 'expect': 'e', 'got': 'g'}}})
    w(os.path.join(td, 'h.py'), '# impl: B-95 S1\nprint(1)\n')
    rc, out = run(['--gate', 'impl-reconcile', '--root', td])
    check('映射与实物一致放行', rc == 0, out[-200:])
    check('全绿时也报「几无实测」（不假称全verified）', '无实测' in out or '有实测' in out, out[-200:])

    # ⑧-⑥ 无 rule_map → 记不适用，不判通过
    os.remove(os.path.join(td, 'verify', 'rule_map.json'))
    rc, out = run(['--gate', 'impl-reconcile', '--root', td])
    check('无 rule_map 记不适用而非通过', rc == 0 and '不适用' in out, out[-200:])


def test_three_state():
    """B-02 三态诚实：一个检查项说「不适用」时，不许被折叠成「通过」。

    为什么单测它：gate_scan 的返回值支持 ('·', msg)，但「支持」不等于「用对」。
    v0.8.59 的汇总行曾把这个计数写成 `sum(...) if False else 0`，
    永远报「0 不适用」——·  照样被当成绿。
    这里动态注入一个只返回 · 的闸，逼出真实计数。
    """
    spec = importlib.util.spec_from_file_location(
        'gs_for_three_state', os.path.join(ROOT, 'verify', 'gate_scan.py'))
    gs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gs)
    gs.GATES = {'probe': lambda root, settings=None: [('·', '故意不适用')]}
    old_argv, old_out = sys.argv, sys.stdout
    sys.argv = ['gate_scan.py', '--gate', 'probe']
    cap = io.StringIO()
    sys.stdout = cap
    try:
        rc = gs.main()
    finally:
        sys.argv, sys.stdout = old_argv, old_out
    out = cap.getvalue()
    check('返回 · 时汇总报出「1 不适用」', '1 不适用' in out, out[-200:])
    check('返回 · 时不打印「全绿」', '全绿' not in out, out[-200:])
    check('· 不导致非零退出（不适用≠失败）', rc == 0, f'rc={rc}')

    src = open(os.path.join(ROOT, 'verify', 'gate_scan.py'), encoding='utf-8').read()
    check('汇总格式串同时含红数与不适用数', '%d 红 / %d 不适用' in src,
          '汇总行少一个数 = 三态被折叠')
    vsh = open(os.path.join(ROOT, 'verify.sh'), encoding='utf-8').read()
    check('验收入口汇总也报三态', all(k in vsh for k in ('✓ 通过', '✗ 失败', '不适用')),
          'verify.sh 汇总行缺三态之一')


test_three_state()

print('test_gate_scan：%d 例，失败 %d' % (N[0], len(fails)))
sys.exit(1 if fails else 0)
