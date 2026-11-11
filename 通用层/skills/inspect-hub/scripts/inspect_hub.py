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
    items, sts = [], []
    for d in cfg.get('declarations', []):
        script = os.path.join(target, d['script'])
        if not os.path.isfile(script):
            items.append({'t': '【黄】脚本缺失无法清点: ' + d['skill'], 'e': d['script'], 'c': '核对登记路径'})
            sts.append('yellow')
            continue
        txt = open(script, encoding='utf-8', errors='ignore').read()
        n = len(re.findall(d['regex'], txt))
        if n == d['declared']:
            items.append({'t': '【绿】' + d['skill'] + ' 声明与实况一致', 'e': 'SKILL 声明 ' + str(d['declared']) + ' = 代码实count ' + str(n), 'c': '无需处置'})
            sts.append('green')
        else:
            items.append({'t': '【红】' + d['skill'] + ' 文档吹牛：声明 ' + str(d['declared']) + ' ≠ 实况 ' + str(n), 'e': d['script'], 'c': '改 SKILL.md 或补实现，二者必须对齐'})
            sts.append('red')
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


def chk_ledger(target, cfg, ctx):
    lp = os.path.join(target, cfg.get('ledger', 'docs/遗留登记.md'))
    if not os.path.isfile(lp):
        return {'status': 'yellow', 'items': [{'t': '【黄】遗留登记文件缺失', 'e': lp + ' 不存在（遗留无处登记就会烂尾）', 'c': '创建并登记当前待办'}]}
    items, sts = [], []
    n = 0
    for ln, line in enumerate(open(lp, encoding='utf-8', errors='ignore'), 1):
        s = line.strip()
        if s.startswith('- 【待】'):
            n += 1
            items.append({'t': '【黄】遗留待办 #' + str(n), 'e': s[4:], 'c': '闭环后从登记册删除该行'})
            sts.append('yellow')
        elif s.startswith('- 【阻】'):
            n += 1
            items.append({'t': '【红】阻塞项', 'e': s[4:], 'c': '优先处置，阻塞项压总评分'})
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


def main():
    ap = argparse.ArgumentParser(description='inspect-hub 520 巡检司')
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run', help='跑全量巡检并产出面板')
    r.add_argument('--target', default=os.environ.get('INSPECT_TARGET') or '.')
    r.add_argument('--out', default=None)
    sub.add_parser('self-check', help='引擎/登记册/模板健康预检')
    a = ap.parse_args()
    if a.cmd == 'self-check':
        sys.exit(cmd_selfcheck())
    sys.exit(cmd_run(a.target, getattr(a, 'out', None)))


if __name__ == '__main__':
    main()
