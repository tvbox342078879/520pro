#!/usr/bin/env python3
# impl: B-19 S5   ← 步骤5 闭环完成判据本体（seal 封盘 / plateau 停增三态，非自报）
"""经验闭环 v3 步骤5 · 闭环完成判据（同一 symptom 复发计数停增）。

用户原始定义（docs/handoff_latest.md:9 / :57）：
  「定义『完成』的可测判据——同一症状在收口后复发计数不再增长，接机器读数，非口头宣布。」

为什么需要独立模块（不塞 exp_probe）：
  exp_probe 只看「复用/固化/呈现」存量，回答不了「某症状收口后是否还在复发」——
  这是时间序列问题（收口基线 vs 之后的 events），需要一个显式「收口点」+ 真读账本流水。

三态诚实（B-02，不折叠）：
  plateau   停增：收口后 count 未涨、events 无新增 → 闭环成立
  recurring 仍复发：收口后 count 涨 或 events 有新记录 → 闭环未成立
  unknown   无法判定：无基线 / 账本损坏 / count 倒退（疑似手改洗绿）/ events 丢失

病15 防护（判据识别范围=记账对象范围，禁假绿）：
  ① 对象=用户级真账本（写侧 guard_cmd._live_rec_path 同口径），不读仓内种子（15/16 分叉）；
  ② 不只看 count 标量（可手改洗绿）——count 与 events 双读交叉验证；
  ③ 重复 seal 不重置基线（否则每次复发后重新封盘=假停增洗绿）；
  ④ count 倒退 / events 比基线少 → unknown（数据被手改，不折叠成 plateau）；
  ⑤ selftest 全程 mock 账本隔离，判据对象就是临时文件本身，不靠字符串/注释锚点。

用法：
  python3 verify/exp_closure.py                       # 回读所有封盘症状的停增态
  python3 verify/exp_closure.py --seal 病N [--note X] # 给症状打收口基线（幂等，不重置）
  python3 verify/exp_closure.py --status 病N          # 单症状停增态
  python3 verify/exp_closure.py --selftest            # 正反自证（mock 隔离）
"""
import os
import sys
import json
import tempfile
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 与 exp_probe / guard_cmd._live_rec_path 同口径：用户级优先、仓内种子兜底、不依赖 cwd。
EXP_HOME = os.environ.get('CODEBUDDY_EXP_HOME') or os.path.join(
    os.path.expanduser('~'), '.codebuddy', 'experience')
SEED_REC = os.path.join(ROOT, 'experience_recurrence.json')
CLOSURES_KEY = 'closures'          # 账本内封盘基线段（首次 seal 时建）
TS_FMT = '%Y-%m-%d %H:%M'          # 与 _bump_recurrence 的 events.ts 同格式，字符串可比


def _live_path(seed=SEED_REC):
    """用户级优先解析账本路径（判据可 monkeypatch EXP_HOME 做正反验证）。"""
    live = os.path.join(EXP_HOME, os.path.basename(seed))
    return live if os.path.isfile(live) else seed


def _now():
    return datetime.datetime.now().strftime(TS_FMT)


def _read(path):
    if not os.path.isfile(path):
        return None
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return None


def _write(path, d):
    """原子写回（与 guard_cmd 同款 os.replace，不写坏账本）。"""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def seal(symptom, seed=None, note='', now=None):
    """给症状打收口基线（幂等：已封盘返回 already，绝不重置基线——防洗绿）。

    返回 {'state': 'sealed'|'already'|'unknown', ...}。unknown=账本不可读/symptom 无计数。
    """
    path = seed or _live_path()
    d = _read(path)
    if d is None:
        return {'state': 'unknown', 'why': '账本不可读或缺失'}
    counters = d.get('counters', {})
    if symptom not in counters:
        return {'state': 'unknown', 'why': f'账本无症状 {symptom} 的计数'}
    closures = d.setdefault(CLOSURES_KEY, {})
    if symptom in closures:
        return {'state': 'already', 'baseline': closures[symptom],
                'why': '已封盘，拒绝重置基线（防复发后重新封盘洗绿）'}
    c = counters[symptom]
    base = {
        'sealed_at': now or _now(),
        'count': c.get('count', 0),
        'events_n': len(c.get('events', [])),
        'note': note,
    }
    closures[symptom] = base
    try:
        _write(path, d)
    except Exception as ex:
        return {'state': 'unknown', 'why': f'封盘写回失败: {str(ex)[:60]}'}
    return {'state': 'sealed', 'baseline': base, 'path': path}


def plateau(symptom, seed=None, now=None):
    """核心停增判据：真读用户级账本，返回三态（不口头宣布）。

    对象范围 = count 标量 + events 时间序列（双读交叉），不是单一字段。
    """
    path = seed or _live_path()
    d = _read(path)
    if d is None:
        return {'state': 'unknown', 'why': '账本不可读或缺失', 'symptom': symptom}
    counters = d.get('counters', {})
    closures = d.get(CLOSURES_KEY, {})
    c = counters.get(symptom)
    base = closures.get(symptom)
    if c is None:
        return {'state': 'unknown', 'why': f'无症状 {symptom} 的计数', 'symptom': symptom}
    if base is None:
        return {'state': 'unknown', 'why': f'症状 {symptom} 未封盘（无收口基线）', 'symptom': symptom}

    try:
        now_count = int(c.get('count', 0))
        base_count = int(base.get('count', 0))
        events = c.get('events', []) or []
        base_n = int(base.get('events_n', 0))
        sealed_at = str(base.get('sealed_at', ''))
    except (TypeError, ValueError):
        return {'state': 'unknown', 'why': '基线/计数字段损坏', 'symptom': symptom}

    if not sealed_at:
        return {'state': 'unknown', 'why': '封盘基线缺 sealed_at', 'symptom': symptom}

    # 病15 防护④：数据倒退（手改 count 变小 / events 被删）→ 无法判定，不折叠为 plateau。
    if now_count < base_count or len(events) < base_n:
        return {'state': 'unknown', 'symptom': symptom,
                'why': f'数据倒退疑似手改（count {base_count}→{now_count}, events {base_n}→{len(events)}）',
                'count': now_count, 'base_count': base_count}

    # 收口后新增 = 基线时间之后的 events（严格 >，同分钟去重不算新增）。
    new_events = [e for e in events if str(e.get('ts', '')) > sealed_at]
    grew = now_count > base_count

    if grew or new_events:
        return {'state': 'recurring', 'symptom': symptom,
                'why': f'收口后仍复发（count +{now_count - base_count}, 新 events {len(new_events)} 条）',
                'count': now_count, 'base_count': base_count,
                'new_events': len(new_events), 'sealed_at': sealed_at}

    # count 未涨、events 无新增，且 events 数量与基线一致（未被删后重排）→ 停增。
    if now_count == base_count and len(events) == base_n and not new_events:
        return {'state': 'plateau', 'symptom': symptom,
                'why': f'停增（收口 {sealed_at} 后 count={now_count} 未涨、events 无新增）',
                'count': now_count, 'base_count': base_count, 'sealed_at': sealed_at}

    return {'state': 'unknown', 'symptom': symptom,
            'why': 'count/events 中间态不一致（不折叠为停增）',
            'count': now_count, 'base_count': base_count, 'events_n': len(events), 'base_n': base_n}


def _status_all(seed=None):
    """回读所有封盘症状（供 verify.sh 接电，三态不折叠）。"""
    path = seed or _live_path()
    d = _read(path)
    if d is None:
        return {'state': 'unknown', 'items': ['账本不可读'], 'summary': 'unknown'}
    closures = d.get(CLOSURES_KEY, {})
    if not closures:
        return {'state': 'ready', 'items': ['判据在位；0 症状封盘（尚未启用）'], 'summary': 'no-seal'}
    items, states = [], []
    for symptom in sorted(closures):
        r = plateau(symptom, seed=path)
        states.append(r['state'])
        items.append(f"{symptom}: {r['state']} — {r['why']}")
    worst = 'recurring' if 'recurring' in states else ('unknown' if 'unknown' in states else 'plateau')
    return {'state': worst, 'items': items, 'summary': ','.join(states)}


# ── selftest：mock 账本隔离，真跑对象，正反覆盖病15 防护 ──────────────────
def _selftest():
    ok = fail = 0

    def chk(name, cond, detail=''):
        nonlocal ok, fail
        if cond:
            ok += 1
            print('  ✓ ' + name)
        else:
            fail += 1
            print(f'  ✗ {name}  {detail}')

    td = tempfile.mkdtemp()
    try:
        # 造一个 mock 账本：症状病X 有 3 条历史 events、count=3（收口前）
        fp = os.path.join(td, 'experience_recurrence.json')
        base = {'counters': {'病X': {'count': 3, 'status': 'active',
                'events': [{'ts': '2026-11-10 10:00', 'coord': '旧1'},
                           {'ts': '2026-11-11 10:00', 'coord': '旧2'},
                           {'ts': '2026-11-12 10:00', 'coord': '旧3'}]}}}

        # ① 无基线 → unknown（不报停增）
        json.dump(base, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        chk('无封盘基线 → unknown（不默认停增）', plateau('病X', seed=fp)['state'] == 'unknown')

        # ② seal 真写基线到 mock 账本
        r = seal('病X', seed=fp, note='回归已固化', now='2026-11-13 00:00')
        d = json.load(open(fp, encoding='utf-8'))
        chk('seal 写基线（sealed_at/count/events_n 落账本）',
            r['state'] == 'sealed' and d['closures']['病X']['sealed_at'] == '2026-11-13 00:00'
            and d['closures']['病X']['count'] == 3 and d['closures']['病X']['events_n'] == 3)

        # ③ 收口后无新事件 → plateau（正向）
        chk('收口后无复发 → plateau', plateau('病X', seed=fp)['state'] == 'plateau')

        # ④ 收口后加 event + count+1 → recurring（真读流水）
        d['counters']['病X']['count'] = 4
        d['counters']['病X']['events'].append({'ts': '2026-11-14 10:00', 'coord': '新复发'})
        json.dump(d, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        chk('收口后新复发 → recurring', plateau('病X', seed=fp)['state'] == 'recurring')

        # ⑤ 病15 核心：只手改 count（无 event 支撑）也算 recurring（不只看单字段）
        d = json.load(open(fp, encoding='utf-8'))
        d['counters']['病X']['count'] = 5
        d['counters']['病X']['events'] = d['counters']['病X']['events'][:4]  # 撤掉新event，只留count
        json.dump(d, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        chk('手改count涨无event → 仍 recurring（双读交叉）', plateau('病X', seed=fp)['state'] == 'recurring')

        # ⑥ count 倒退（手改洗绿）→ unknown，不折叠 plateau
        d = json.load(open(fp, encoding='utf-8'))
        d['counters']['病X']['count'] = 1
        json.dump(d, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        chk('count 倒退疑似手改 → unknown', plateau('病X', seed=fp)['state'] == 'unknown')

        # ⑦ events 被删（比基线少）→ unknown
        d = json.load(open(fp, encoding='utf-8'))
        d['counters']['病X']['count'] = 3
        d['counters']['病X']['events'] = d['counters']['病X']['events'][:2]
        json.dump(d, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        chk('events 比基线少 → unknown', plateau('病X', seed=fp)['state'] == 'unknown')

        # ⑧ 重复 seal 不重置基线（防复发后重新封盘洗绿）
        json.dump(base, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        seal('病X', seed=fp, now='2026-11-13 00:00')
        d['counters']['病X']['count'] = 9
        json.dump(d, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        r2 = seal('病X', seed=fp, now='2026-11-20 00:00')  # 试图重新封盘洗绿
        d_after = json.load(open(fp, encoding='utf-8'))
        chk('重复 seal 拒绝重置基线（already）',
            r2['state'] == 'already' and d_after['closures']['病X']['sealed_at'] == '2026-11-13 00:00')

        # ⑨ 账本损坏 → unknown（不崩溃、不折叠）
        open(fp, 'w', encoding='utf-8').write('{ broken json')
        chk('账本损坏 → unknown（不崩溃）', plateau('病X', seed=fp)['state'] == 'unknown')

        # ⑩ 对象范围：真读用户级账本路径（不是仓内种子）——_live_path 用户级优先。
        # 病15 防护：判据对象=EXP_HOME 指向的真文件；须 monkeypatch 模块 EXP_HOME（_live_path
        # 读的是它，非 os.getenv 实时值），否则又变成「只测路径字符串」的假绿。
        global EXP_HOME
        _saved_exp = EXP_HOME
        EXP_HOME = td
        try:
            chk('_live_path 用户级优先（真函数，EXP_HOME 指向 td）',
                _live_path(os.path.join(ROOT, 'experience_recurrence.json')) == fp)
        finally:
            EXP_HOME = _saved_exp
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)

    print(f'exp_closure selftest：{ok} ✓ / {fail} ✗')
    return 0 if fail == 0 else 1


def main():
    args = sys.argv[1:]
    if '--selftest' in args:
        return _selftest()
    if '--seal' in args:
        i = args.index('--seal')
        symptom = args[i + 1] if i + 1 < len(args) else None
        if not symptom:
            print('用法: --seal <症状> [--note 说明]')
            return 2
        note = ''
        if '--note' in args:
            j = args.index('--note')
            note = args[j + 1] if j + 1 < len(args) else ''
        r = seal(symptom, note=note)
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r['state'] in ('sealed', 'already') else 2
    symptom = None
    if '--status' in args:
        i = args.index('--status')
        symptom = args[i + 1] if i + 1 < len(args) else None
    if symptom:
        print(json.dumps(plateau(symptom), ensure_ascii=False, indent=1))
    else:
        r = _status_all()
        print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
