#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair/engine.py —— 修源引擎首版（S222·batch 2）

真实现（本版可用）：
  · checkup()      —— 体检器：调 livecheck.check_auto + death_cause，
                      产出过 checkup_report.schema.json 的报告（真跑，非声明）
  · route()        —— 按死因查 strategies.json 得修复策略
  · validate()     —— repair_result 写入时 schema 校验（手写轻校验，不引第三方依赖；
                      若环境有 jsonschema 则优先用）

如实声明（M-R136 不造假，本版未接）：
  · apply_patch / llm_call / 整站重写执行器 —— LLM 通道尚未接入（需要模型三件套配置面，
    与壳的 OpenAI 兼容 /chat/completions 对齐），接口位已留：repair() 会按分型返回
    status='not_applicable' + failure_reason='LLM 通道未接入'，绝不伪造 repaired。

用法：
  python3 engine.py checkup <url> [--kind vod|m3u8|auto]     # 体检→打印契约 JSON
  python3 engine.py route <url> [--kind ...]                 # 体检+查策略
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # 使 repair 包可被找到（脚本直跑时）
SCHEMAS = os.path.join(HERE, 'schemas')
STRATEGIES = os.path.join(HERE, 'strategies.json')
LIVECHECK = os.path.join(HERE, '..', 'scripts', 'livecheck.py')


# ── livecheck 桥接（分型单一事实源，M-R38；子进程隔离防其全局态污染） ──
def _livecheck(url, kind='auto'):
    """子进程调 livecheck 单条 --json，返回 (verdict, evidence, kind, death_cause)。"""
    p = subprocess.run(
        [sys.executable, LIVECHECK, url, '--kind', kind, '--json'],
        capture_output=True, timeout=90)
    line = (p.stdout or b'').decode('utf-8', 'replace').strip().splitlines()
    if not line:
        # livecheck 无输出 = 无法判定（M-R57：错误不折叠成 ok）
        return '无法判定', f'livecheck 无输出（stderr: {(p.stderr or b"")[:200]!r}）', kind, '未定·网络'
    d = json.loads(line[-1])
    return d['verdict'], d['evidence'], d.get('kind', kind), d.get('death_cause', '')


def checkup(url, kind='auto'):
    """体检：真跑 livecheck → 组装过 schema 的 checkup_report。"""
    verdict, ev, k, dc = _livecheck(url, kind)
    report = {
        'schema_version': '1.0',
        'target': url,
        'kind': k,
        'verdict': verdict,
        'death_cause': dc,
        'repair_route': ROUTES.get(dc, {}).get('hint', ''),
        'evidence': ev,
        'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    ok, why = validate(report, 'checkup_report.schema.json')
    if not ok:
        # 契约校验失败本身要暴露，不能静默（M-R57/M-R136）
        report['repair_route'] = f'【契约校验未过，如实标注】{why}'
    return report


def _load_strategies():
    with open(STRATEGIES, encoding='utf-8') as f:
        return json.load(f)


ROUTES = _load_strategies()['routes']


def route(report):
    """体检报告 → 修复策略条目（查 strategies.json，不硬编码）。"""
    return ROUTES.get(report.get('death_cause', ''), None)


# ── 写入时校验（业内 Tier3 实践：LLM 说过 ≠ 修好，schema 说了算） ──
def validate(obj, schema_name):
    """校验 obj 是否符合 schemas/<schema_name>。优先 jsonschema 库，缺库走手写轻校验。

    轻校验覆盖 required + enum + const（本契约的核心面）；返回 (ok, why)。
    """
    with open(os.path.join(SCHEMAS, schema_name), encoding='utf-8') as f:
        schema = json.load(f)
    try:
        import jsonschema  # noqa
        import jsonschema as _js
        _js.validate(obj, schema)
        return True, ''
    except ImportError:
        pass
    except Exception as e:
        return False, str(e)[:300]
    # —— 手写轻校验（required + const + enum） ——
    for k in schema.get('required', []):
        if k not in obj:
            return False, f'缺必填字段 {k}'
    for k, spec in schema.get('properties', {}).items():
        v = obj.get(k)
        if v is None:
            continue
        if 'const' in spec and v != spec['const']:
            return False, f'{k} 应为 {spec["const"]}，实为 {v!r}'
        if 'enum' in spec and v not in spec['enum']:
            return False, f'{k} 取值 {v!r} 不在 {spec["enum"]}'
    return True, ''


# ── 证据包组装（不给模型猜的机会，AI修源范式） ──
EVIDENCE_LIMIT = 6000


def build_evidence(target, source_path=None, prev_code=None, prev_failure=None,
                   homepage_html=None, candidates=None, recon_report=None):
    """组装证据：真跑结果 + 上轮失败原因 + 上一版代码 + 站点片段 +（可选）侦察报告。

    外部内容全部过 llm.wrap_untrusted（注入防御）。返回 messages 的 user 段文本。
    """
    from repair import llm as _llm  # 兼容包内导入与脚本直跑
    parts = []
    rep = checkup(target)
    parts.append('## 一、真跑体检结果（机器分型）\n' +
                 f"verdict={rep['verdict']}  death_cause={rep['death_cause']}  "
                 f"kind={rep['kind']}\n" +
                 _llm.wrap_untrusted('untrusted_log', rep['evidence']))
    if prev_failure:
        parts.append('## 二、上一轮失败原因（请换个思路，不要重复同样的改法）\n' +
                     _llm.wrap_untrusted('untrusted_log', prev_failure))
    if prev_code:
        parts.append('## 三、上一版代码（供对照，**不要原样返回**）\n' +
                     _llm.wrap_untrusted('untrusted_html', prev_code, limit=20000))
    if homepage_html:
        parts.append(f'## 四、站点现场抓取片段（截断 {EVIDENCE_LIMIT} 字符）\n' +
                     _llm.wrap_untrusted('untrusted_web', homepage_html, limit=EVIDENCE_LIMIT))
    if recon_report:
        # 侦察报告是「机器跑出来的结构结论」，不是外部原文，故不包 untrusted；
        # 但它里面的 URL/标题来自站点，仍按外部内容处理（统一走 wrap）。
        parts.append('## 五、站点侦察（机器实测，不是猜测）\n' +
                     _llm.wrap_untrusted('untrusted_web', recon_report, limit=EVIDENCE_LIMIT))
    if candidates:
        parts.append('## 六、候选域名（来自实测探活，禁止自行编造）\n' +
                     '\n'.join(f'- {c}' for c in candidates))
    return '\n\n'.join(parts), rep


def needs_recon(target):
    """这一单要不要先侦察：只有 rewrite 档需要。→ (bool, 原因)"""
    rep = checkup(target)
    r = route(rep)
    if not r:
        return False, f"分型[{rep['death_cause']}]无需修复"
    return r.get('strategy') == 'rewrite', f"分型[{rep['death_cause']}]→{r.get('strategy')}"


# ── 补丁应用（AI修源硬约束：old 必须原文逐字存在，否则整单 abort） ──
def apply_patch(text, edits):
    """按 edits 顺序做逐字替换。任一 old 匹配不到/不唯一 → 返回 (None, 原因)。

    不使用正则、不做模糊匹配——"近似替换"会静默改错别处，比不动更糟。
    """
    out = text
    for n, e in enumerate(edits, 1):
        old, new = e.get('old', ''), e.get('new', '')
        if not old:
            return None, f'第{n}处 edit 的 old 为空'
        cnt = out.count(old)
        if cnt == 0:
            return None, f'第{n}处 edit 的 old 在原文中不存在（禁止近似替换）'
        if cnt > 1:
            return None, f'第{n}处 edit 的 old 在原文中出现 {cnt} 次（不唯一，拒绝应用）'
        out = out.replace(old, new, 1)
    return out, ''


def write_with_verify(path, new_text):
    """备份 → 写 → 回读比对。不一致即回滚并返回 aborted（AI修源写盘三防）。"""
    import shutil
    bak = path + '.bak.' + datetime.now().strftime('%Y%m%d_%H%M%S')
    shutil.copy2(path, bak)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_text)
    with open(path, encoding='utf-8') as f:
        back = f.read()
    if back != new_text:
        shutil.copy2(bak, path)          # 回滚
        return False, bak, '写回后回读不一致（已回滚原文件）'
    return True, bak, ''


# ── 草稿目录（host 后端：证据包 ↔ 宿主补丁，中间产物落盘可查） ──
DRAFTS = os.path.join(HERE, '.drafts')


def _draft_path(source_path):
    import hashlib
    h = hashlib.md5(os.path.abspath(source_path).encode()).hexdigest()[:8]
    return os.path.join(DRAFTS, f'{os.path.basename(source_path)}.{h}.draft.json')


def drafts(target, *, source_path, homepage_html=None, candidates=None, prev_failure='',
           do_recon=None):
    """host 后端第一步：组装证据包 + 策略提示词，落盘成草稿，等宿主填补丁。

    草稿结构（patch 档）：
      {target, source_path, strategy, death_cause, system_prompt, evidence,
       source_code, reply: null}      ← 宿主只需填 reply
    草稿结构（rewrite 档）额外带 `recon` 与 `reply_code`：
      {..., recon: {...}, reply: null, reply_code: null}
      ← 宿主填 reply_code（整份源码），不是 patch。

    `do_recon`：None=按策略自动（rewrite 才侦察）；False=强制不侦察。
    返回 (草稿路径, 草稿字典)。
    """
    if not source_path or not os.path.exists(source_path):
        raise FileNotFoundError(f'修复需要源码文件，未提供或不存在：{source_path!r}')
    rep = checkup(target)
    r = route(rep)
    if not r or r.get('strategy') == 'none':
        raise ValueError(f"分型[{rep['death_cause']}]不需修复：{rep['repair_route']}")
    code = open(source_path, encoding='utf-8').read()
    is_rw = r.get('strategy') == 'rewrite'

    recon_text, rsum = None, {}
    if is_rw and (do_recon is None or do_recon):
        from repair import recon as _recon
        rr = _recon.recon(target, depth=2)
        blockers = [u for u in rr.get('undetermined', [])
                    if ('未取到' in u or '抓取失败' in u)]
        if rr.get('home_ok') is None or blockers:
            # 侦察不完整 → 不出草稿。让宿主去编一份「没见过真实结构」的源码，
            # 出来的一定是假通过，比原来的坏源更难排查。
            raise ValueError('侦察不完整，不出重写草稿（否则必然是编的）：' +
                             '；'.join(blockers or rr.get('undetermined') or ['未知原因']))
        recon_text = _recon.as_evidence_text(rr)
        d = rr.get('detail_sample') or {}
        rsum = {'home_ok': rr.get('home_ok'), 'hits': rr.get('hits') or {},
                'nav_categories': [c['name'] for c in rr.get('nav_categories') or []][:12],
                'page_url_pattern': rr.get('page_url_pattern') or '',
                'detail_episode_shape': d.get('episode_shape') or '',
                'undetermined': rr.get('undetermined') or []}

    ev_text, _ = build_evidence(target, prev_code=code, prev_failure=prev_failure,
                                homepage_html=homepage_html, candidates=candidates,
                                recon_report=recon_text)
    os.makedirs(DRAFTS, exist_ok=True)
    fp = _draft_path(source_path)
    draft = {
        'target': target, 'source_path': os.path.abspath(source_path),
        'strategy': r['strategy'], 'death_cause': rep['death_cause'],
        'max_rounds': r.get('max_verify_rounds', 3) if is_rw else r.get('max_patch_rounds', 1),
        'system_prompt': _system_prompt(r),
        'evidence': ev_text,
        'source_code': code,
        'recon': rsum,
        'reply': None,
        'reply_code': None,
        '_说明': ('宿主在此填 reply_code（整份源码全文），然后跑 engine.py apply <本文件>'
                  if is_rw else
                  '宿主在此填 reply：{"patch":{"edits":[{"old":"原文逐字片段","new":"替换内容"}]}}，'
                  '然后跑 engine.py apply <本文件>'),
    }
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    return fp, draft


def apply_draft(draft_path, *, target=None, max_rounds=None):
    """host 后端第二/三步：读草稿的 reply → 应用补丁 → 备份写盘回读 → 真跑复验。

    reply 为空 → aborted（宿主还没填，此时代码一行没动）。
    """
    if not os.path.exists(draft_path):
        raise FileNotFoundError(f'草稿不存在：{draft_path}')
    d = json.load(open(draft_path, encoding='utf-8'))
    tgt = target or d['target']
    src = d['source_path']
    base = {'schema_version': '1.0', 'target': tgt, 'strategy': d['strategy'],
            'attempts': 1, 'backup_path': ''}
    if d.get('recon'):
        base['recon'] = d['recon']

    reply_code = d.get('reply_code')
    if d.get('strategy') == 'rewrite':
        # rewrite 草稿走 reply_code（整份源码），不走 edits ——
        # 整站重写和小补是两种产出形态，混在一起会让补丁被当成整份源码写进文件。
        if not reply_code:
            return {**base, 'attempts': 0, 'status': 'not_applicable',
                    'failure_reason': '深写草稿 reply_code 为空：宿主尚未产出整份源码，源码未做任何改动'}
        bad = _rewrite_static_check(reply_code)
        if bad:
            return {**base, 'status': 'aborted',
                    'failure_reason': '静态校验拒绝：' + '；'.join(bad)}
        cur = open(src, encoding='utf-8').read()
        if cur != d.get('source_code'):
            return {**base, 'status': 'aborted',
                    'failure_reason': '源码在出草稿后被改过（与草稿基线不一致），'
                                      '拒绝覆盖（重写会整份替换，这个风险比小补更大）'}
        ok, bak, why = write_with_verify(src, reply_code)
        if not ok:
            return {**base, 'backup_path': bak, 'status': 'aborted', 'failure_reason': why}
        rechk = checkup(tgt)
        res = {**base, 'backup_path': bak,
               'recheck': {'verdict': rechk['verdict'], 'death_cause': rechk['death_cause'],
                           'evidence': rechk['evidence'][:500]}}
        if rechk['verdict'] == '通过':
            return {**res, 'status': 'repaired'}
        return {**res, 'status': 'verify_failed',
                'failure_reason': f'重写后复验未通过（{rechk["verdict"]}/'
                                  f'{rechk["death_cause"]}）：{rechk["evidence"][:300]}'}

    reply = d.get('reply')
    if not reply:
        return {**base, 'attempts': 0, 'status': 'not_applicable',
                'failure_reason': '草稿 reply 为空：宿主尚未产出补丁，源码未做任何改动'}
    edits = ((reply or {}).get('patch') or {}).get('edits') or reply.get('edits') or []
    if not edits:
        return {**base, 'status': 'aborted', 'failure_reason': 'reply 里没有 edits'}

    cur = open(src, encoding='utf-8').read()
    if cur != d.get('source_code'):
        return {**base, 'status': 'aborted',
                'failure_reason': '源码在出草稿后被改过（与草稿基线不一致），拒绝套用旧补丁'}

    new_text, why = apply_patch(cur, edits)
    if new_text is None:
        return {**base, 'status': 'aborted', 'failure_reason': f'补丁不可应用：{why}'}

    # S224 能力层校验：格式合法的补丁也可能偷偷加 subprocess/socket/eval——写盘前拦
    from repair import ai_ast
    aok, akind, amsg, _line = ai_ast.check(new_text, cur)
    if not aok:
        return {**base, 'status': 'aborted',
                'failure_reason': f'AST 校验拒绝（{akind}）：{amsg}——补丁试图新增危险能力'}

    ok, bak, why = write_with_verify(src, new_text)
    if not ok:
        return {**base, 'backup_path': bak, 'status': 'aborted', 'failure_reason': why}

    rechk = checkup(tgt)
    res = {**base, 'backup_path': bak, 'patch': {'edits': edits},
           'recheck': {'verdict': rechk['verdict'], 'death_cause': rechk['death_cause'],
                       'evidence': rechk['evidence'][:500]}}
    if rechk['verdict'] == '通过':
        return {**res, 'status': 'repaired'}
    if rechk['verdict'] == '无法判定':
        return {**res, 'status': 'verify_failed',
                'failure_reason': '复验无法判定（网络/证书类），既不算修复失败也不算成功（M-R60）'}
    rounds = max_rounds or d.get('max_rounds', 1)
    return {**res, 'status': 'verify_failed',
            'failure_reason': f'复验仍失败，新死因[{rechk["death_cause"]}]，'
                              f'小补上限 {rounds} 轮 → 建议升级整站重写'}


# ── 修复编排（api 后端全自动 / host 后端走 drafts+apply） ──
def repair(target, *, source_path=None, homepage_html=None, candidates=None,
           max_rounds=None):
    """一条修复链：分型 → 策略 → 出补丁 → 应用 → 真跑复验 → 不过则带新死因重来。

    api 后端：全自动（需 Key）。
    host 后端：不自动产出补丁——返回 not_applicable 并提示改用 drafts/apply
               （宿主模型不在代码里，代码不能替它编补丁）。
    返回过 repair_result.schema.json 的字典。
    """
    base = {'schema_version': '1.0', 'target': target, 'attempts': 0, 'backup_path': ''}
    rep = checkup(target)
    r = route(rep)
    if not r or r.get('strategy') == 'none':
        return {**base, 'strategy': 'none', 'status': 'not_applicable',
                'failure_reason': f"分型[{rep['death_cause']}]不需修复：{rep['repair_route']}"}

    from repair import llm as _llm
    be = _llm.backend()
    if be == 'host':
        return {**base, 'strategy': r['strategy'], 'status': 'not_applicable',
                'failure_reason': f"分型[{rep['death_cause']}]→策略[{r['strategy']}]已路由；"
                                  '当前后端=host（无 Key），须走两段式：'
                                  '`engine.py drafts <url> --src <源.py>` 出证据包，'
                                  '宿主填 reply 后 `engine.py apply <草稿>`'}

    try:
        _llm.load_config()
    except Exception as e:
        return {**base, 'strategy': r['strategy'], 'status': 'not_applicable',
                'failure_reason': f'分型[{rep["death_cause"]}]→策略[{r["strategy"]}]已路由，'
                                  f'但 api 后端未配置：{e}'}

    if not source_path or not os.path.exists(source_path):
        return {**base, 'strategy': r['strategy'], 'status': 'aborted',
                'failure_reason': f'修复需要源码文件，未提供或不存在：{source_path!r}'}

    if r['strategy'] == 'rewrite':
        # batch 4：整站重写档。先侦察，侦察不完整就 aborted（不生成编的源）。
        return rewrite(target, source_path=source_path, homepage_html=homepage_html,
                       candidates=candidates,
                       max_rounds=r.get('max_verify_rounds', 3))

    rounds = max_rounds or r.get('max_patch_rounds', 1)
    prev_code = open(source_path, encoding='utf-8').read()
    prev_failure = ''
    for rd in range(1, rounds + 1):
        ev_text, rep = build_evidence(target, prev_code=prev_code,
                                      prev_failure=prev_failure,
                                      homepage_html=homepage_html,
                                      candidates=candidates)
        msgs = [{'role': 'system', 'content': _system_prompt(r)},
                {'role': 'user', 'content': ev_text}]
        try:
            obj, raw = _llm.chat(msgs, expect_json=True)
        except Exception as e:
            return {**base, 'strategy': r['strategy'], 'status': 'aborted',
                    'attempts': rd - 1, 'failure_reason': f'LLM 调用失败：{e}'}

        edits = ((obj or {}).get('patch') or {}).get('edits') or obj.get('edits') or []
        new_text, why = apply_patch(prev_code, edits)
        if new_text is None:
            prev_failure = why
            if rd == rounds:
                return {**base, 'strategy': r['strategy'], 'status': 'aborted',
                        'attempts': rd, 'failure_reason': f'补丁不可应用：{why}'}
            continue

        # S224 能力层校验（同 apply_draft）：新增危险能力直接拒，且不重试——换一轮也是同样问题
        from repair import ai_ast
        aok, akind, amsg, _line = ai_ast.check(new_text, prev_code)
        if not aok:
            return {**base, 'strategy': r['strategy'], 'status': 'aborted',
                    'attempts': rd,
                    'failure_reason': f'AST 校验拒绝（{akind}）：{amsg}——补丁试图新增危险能力'}

        ok, bak, why = write_with_verify(source_path, new_text)
        if not ok:
            return {**base, 'strategy': r['strategy'], 'status': 'aborted',
                    'attempts': rd, 'backup_path': bak, 'failure_reason': why}

        rechk = checkup(target)
        result = {**base, 'strategy': r['strategy'], 'attempts': rd,
                  'backup_path': bak,
                  'patch': {'edits': edits},
                  'recheck': {'verdict': rechk['verdict'],
                              'death_cause': rechk['death_cause'],
                              'evidence': rechk['evidence'][:500]}}
        if rechk['verdict'] == '通过':
            return {**result, 'status': 'repaired'}
        prev_code, prev_failure = new_text, rechk['evidence']
        if rechk['verdict'] == '无法判定':
            return {**result, 'status': 'verify_failed',
                    'failure_reason': '复验无法判定（网络/证书类），不算修复失败也不算成功（M-R60）'}
        if rd == rounds:
            return {**result, 'status': 'verify_failed',
                    'failure_reason': f'复验仍失败，新死因[{rechk["death_cause"]}]，'
                                      f'小补 {rd} 轮已用完 → 建议升级整站重写'}
    return {**base, 'strategy': r['strategy'], 'status': 'aborted',
            'failure_reason': '轮次耗尽未产出可用补丁'}


def rewrite(target, *, source_path, homepage_html=None, candidates=None,
            max_rounds=3, do_recon=True, recon_report=None):
    """整站重写档。→ repair_result dict（status ∈ repaired / verify_failed / aborted）。

    ★ 与小补的关键差异：**重写不基于旧代码改**，而是「侦察 → 整份生成 → 真跑复验」。
      所以它不接受 edits，只接受一份**完整的新源码文本**（reply.code）。

    ★ 为什么必须先侦察：小补只要知道「哪一行错」，重写要知道「这站怎么出数据」。
      不给侦察结果就让 LLM 重写，它必然套 maccms 模板 —— r147 记的就是这个坑
      （host 写成站点主域的 .html，播放器一条都拉不到）。

    ★ 侦察结果不完整怎么办（本次落地的核心判断）：
      只要 recon 里有 `undetermined` 且涉及「真实内容未取到」，
      就**不生成**，直接 aborted 并说清楚缺什么。理由：
      在没拿到真实列表/详情结构的情况下生成的源，一定是编的，
      跑起来是「假通过 + 零播放地址」，比原来的坏源更难排查。
    """
    import re as _re
    from repair import recon as _recon
    base = {'schema_version': '1.0', 'target': target, 'strategy': 'rewrite',
            'attempts': 0, 'backup_path': ''}
    if not source_path or not os.path.exists(source_path):
        return {**base, 'status': 'aborted',
                'failure_reason': f'整站重写需要原源文件做备份与对照，未提供：{source_path!r}'}

    # ── ① 侦察 ──
    if recon_report is None:
        rr = _recon.recon(target, depth=2) if do_recon else None
        if rr is None:
            return {**base, 'status': 'aborted',
                    'failure_reason': 'do_recon=False 且未提供 recon_report——'
                                      '重写必须有侦察结果，不接受凭空生成'}
        if rr.get('home_ok') is None:
            return {**base, 'status': 'aborted',
                    'failure_reason': '侦察失败，站点真实内容未取到：'
                                      + '；'.join(rr.get('undetermined') or ['无原因记录'])}
        # 「内容没取到」类无法判定 → 拒绝生成
        blockers = [u for u in rr.get('undetermined', [])
                    if ('未取到' in u or '抓取失败' in u)]
        if blockers:
            return {**base, 'status': 'aborted',
                    'failure_reason': '侦察不完整，拒绝生成（否则必然是编的）：'
                                      + '；'.join(blockers)}
        recon_text = _recon.as_evidence_text(rr)
    else:
        rr = None
        recon_text = recon_report
    # 侦察摘要进结果（便于人工复核「这次重写是基于什么生成的」）
    rsum = {}
    if rr:
        d = rr.get('detail_sample') or {}
        rsum = {'home_ok': rr.get('home_ok'), 'hits': rr.get('hits') or {},
                'nav_categories': [c['name'] for c in rr.get('nav_categories') or []][:12],
                'page_url_pattern': rr.get('page_url_pattern') or '',
                'detail_episode_shape': d.get('episode_shape') or '',
                'undetermined': rr.get('undetermined') or []}
    base = {**base, 'recon': rsum}

    old_code = open(source_path, encoding='utf-8').read()
    prev_failure = ''
    last_reason = ''
    for rd in range(1, max_rounds + 1):
        ev_text, _ = build_evidence(target, prev_code=old_code, prev_failure=prev_failure,
                                    homepage_html=homepage_html, candidates=candidates,
                                    recon_report=recon_text)
        ev_text += ('\n\n## 输出要求\n'
                    '返回 JSON：{"code":"<完整可运行的源文件全文>","candidates":[{"url":"...","why":"..."}]}\n'
                    'code 必须是**整份文件**，不是 diff；不得留 TODO/占位符/省略号。')
        r = route(checkup(target)) or {'strategy': 'rewrite',
                                       'prompt': 'prompts/rewrite.md',
                                       'max_patch_rounds': 1, 'max_verify_rounds': max_rounds}
        msgs = [{'role': 'system', 'content': _system_prompt(r)},
                {'role': 'user', 'content': ev_text}]
        from repair import llm as _llm
        try:
            obj, raw = _llm.chat(msgs, expect_json=True)
        except Exception as e:                                # noqa: BLE001
            return {**base, 'attempts': rd - 1,
                    'status': 'aborted', 'failure_reason': f'LLM 调用失败：{e}'}

        code = (obj or {}).get('code') or ''
        if not code.strip():
            last_reason = '模型未返回 code 字段（或为空）'
            prev_failure = last_reason
            continue
        # ── 静态三查（写盘前的机器闸门）──
        bad = _rewrite_static_check(code)
        if bad:
            last_reason = '静态校验拒绝：' + '；'.join(bad)
            prev_failure = last_reason
            continue

        ok, bak, why = write_with_verify(source_path, code)
        if not ok:
            return {**base, 'attempts': rd, 'backup_path': bak,
                    'status': 'aborted', 'failure_reason': why}

        # ── 真跑复验 ──
        ver, ev, _k, dc = _livecheck(target)
        if ver == '通过':
            return {**base, 'attempts': rd, 'backup_path': bak, 'status': 'repaired',
                    'recheck': {'verdict': ver, 'evidence': ev[:1500]}}
        last_reason = f'第{rd}轮重写后复验未通过（{ver}/{dc}）：{ev[:400]}'
        prev_failure = last_reason
        old_code = code

    return {**base, 'attempts': max_rounds, 'status': 'verify_failed',
            'failure_reason': last_reason + '——建议人工介入，不再自动重试'}


def _rewrite_static_check(code):
    """整份源码的静态闸门 → 拒绝原因列表（空 = 通过）。

    只查「一定会出问题」的三类，不做风格审查：
      ① 六接口缺一 → 壳直接不认这个源
      ② 语法错 → 加载即失败
      ③ 补丁式残留（`...`/`TODO`/`<省略>`）→ 一定跑不起来
    """
    import ast as _ast
    bad = []
    try:
        tree = _ast.parse(code)
    except SyntaxError as e:
        return [f'语法错误：{e}']
    names = {n.name for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef)}
    need = ('homeContent', 'categoryContent', 'detailContent',
            'searchContent', 'playerContent')
    miss = [m for m in need if m not in names]
    if miss:
        bad.append(f'缺接口方法 {miss}')
    if any(k in code for k in ('...省略', '<省略>', 'TODO:', 'FIXME')):
        bad.append('含占位符（省略号/TODO），不是完整源码')
    # getName 空返回必须**按函数体查**，不能全文搜 `return ""`。
    # 第一版就是全文搜，结果正常源里 `_get()` 失败返回 ""、`_fix()` 空值返回 ""
    # 全被判成「getName 返回空串」—— 假阳性把一个好源拒了。
    for n in _ast.walk(tree):
        if isinstance(n, _ast.FunctionDef) and n.name == 'getName':
            vals = [b.value.value for b in n.body
                    if isinstance(b, _ast.Return) and isinstance(b.value, _ast.Constant)
                    and isinstance(b.value.value, str)]
            if vals and not any(v.strip() for v in vals):
                bad.append('getName 返回空串（用户列表里认不出是哪个站）')
            elif not vals:
                # return 了变量或没有字面量 return —— 判不了，如实说，不算拒绝
                pass
    return bad


def _system_prompt(strategy_entry):
    """拼系统提示：_common 注入防御 + 该策略提示词正文。"""
    parts = []
    for fn in ('_common.md', os.path.basename(str(strategy_entry.get('prompt') or ''))):
        if not fn:
            continue
        fp = os.path.join(HERE, 'prompts', fn)
        if os.path.exists(fp):
            parts.append(open(fp, encoding='utf-8').read())
    if strategy_entry.get('strategy') == 'rewrite':
        parts.append('## 输出格式（必须是纯 JSON，不要任何解释文字）\n'
                     '{"code": "<完整源文件全文>", '
                     '"candidates": [{"url": "...", "why": "..."}]}')
    else:
        parts.append('## 输出格式（必须是纯 JSON，不要任何解释文字）\n'
                     '{"patch": {"edits": [{"old": "原文逐字片段", "new": "替换内容"}]}}')
    return '\n\n'.join(parts)


def main():
    ap = __import__('argparse').ArgumentParser(
        description='修源引擎：checkup 体检 / route 查策略 / drafts 出证据包 / apply 应用补丁 / repair 自动')
    ap.add_argument('action', choices=['checkup', 'route', 'drafts', 'apply', 'repair',
                                       'recon', 'rewrite'])
    ap.add_argument('target', help='源 URL（drafts/repair/checkup/route）或草稿路径（apply）')
    ap.add_argument('--kind', default='auto')
    ap.add_argument('--src', help='drafts 用：被修的源 .py 路径')
    ap.add_argument('--html', help='drafts 用：站点首页片段文件')
    ap.add_argument('--candidates', nargs='*', help='drafts 用：候选域名')
    ap.add_argument('--prev-failure', default='', help='drafts 用：上一轮失败原因')
    ap.add_argument('--depth', type=int, default=2, help='recon 用：1 只抓首页 / 2 加分类页+详情页')
    ap.add_argument('--json', action='store_true', help='recon 用：输出 JSON')
    a = ap.parse_args()

    if a.action == 'recon':
        from repair import recon as _recon
        rr = _recon.recon(a.target, depth=a.depth)
        if a.json:
            print(json.dumps(rr, ensure_ascii=False, indent=2))
        else:
            print(_recon.as_evidence_text(rr))
        return 0 if rr.get('home_ok') else 1
    if a.action == 'rewrite':
        if not a.src:
            print('rewrite 需要 --src 指定原源文件（用于备份与对照）', file=sys.stderr)
            return 2
        html = open(a.html, encoding='utf-8').read() if a.html else None
        rr = rewrite(a.target, source_path=a.src, homepage_html=html,
                     candidates=a.candidates)
        ok, why = validate(rr, 'repair_result.schema.json')
        print(json.dumps(rr, ensure_ascii=False, indent=2))
        if not ok:
            print(f'⚠ 结果未过契约：{why}', file=sys.stderr)
            return 3
        return 0 if rr['status'] == 'repaired' else 1

    if a.action == 'drafts':
        html = open(a.html, encoding='utf-8').read() if a.html else None
        fp, d = drafts(a.target, source_path=a.src, homepage_html=html,
                       candidates=a.candidates, prev_failure=a.prev_failure)
        print(json.dumps({'draft_path': fp, 'strategy': d['strategy'],
                          'death_cause': d['death_cause'],
                          'evidence_chars': len(d['evidence']),
                          'source_lines': len(d['source_code'].splitlines()),
                          'next': f'把补丁写进 {fp} 的 reply 字段，再跑 engine.py apply {fp}'},
                         ensure_ascii=False, indent=2))
        return 0
    if a.action == 'apply':
        r = apply_draft(a.target)
        ok, why = validate(r, 'repair_result.schema.json')
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if not ok:
            print(f'⚠ 结果未过契约：{why}', file=sys.stderr)
            return 3
        return 0 if r['status'] == 'repaired' else 1
    if a.action == 'repair':
        print(json.dumps(repair(a.target), ensure_ascii=False, indent=2))
        return 0
    rep = checkup(a.target, a.kind)
    if a.action == 'route':
        print(json.dumps({'report': rep, 'strategy': route(rep)}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
