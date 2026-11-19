#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stop_guard.py — 回合末拽回（Stop 事件 · B-13 完成态凭落点）

为什么要有它（520 的高频毛病）:
  「完成 / 已修复 / 全部通过」是本项目最常被滥用的一句话。规则文件里写了
  B-13「说完成必须同时给落点」，但那是**软约束**——模型想省就省，用户只能事后发现。
  Stop 是唯一能在「这条消息即将成为最终答复」这个时刻介入的地方。

协议（实测确认，2026-11-14 · 两次对照实验）:
  Stop payload 含 `last_assistant_message`（本轮最后一条回复全文）+ `transcript_path`
  + `stop_hook_active`。两种「拦住不让停」的写法，实测结果不同：

    ① exit 2 + stderr 有内容  → **未观察到当场续写**。回合照常结束，用户得自己再发
       一条消息才被拉回来。降级为「事后可见」，不是拽回。
    ② stdout 输出 JSON {"decision":"block","reason":"..."} + exit 0 → **确实拽回**。
       平台把 reason 作为 `Stop hook feedback`（CLI 侧呈现为用户消息）注入回模型，
       模型当场看到并必须继续这一轮。探针日志佐证：脚本仅被调用 1 次
       （stop_hook_active=false，计数 1），说明是平台注入而非钩子二次执行。

  结论：本脚本走 ② 。**这不是硬阻断，是拽回**——话说出口了才被拽回来重说，
  用户仍会看到那次失败的收尾，只是紧接着就能看到补充。

  注意 stop_hook_active 的重入语义：走 ② 时平台注入反馈、模型续写、再次 Stop 时
  该字段是否置真未观测到（探针只跑了 1 次）。因此本机计数 MAX_RETRY 是**主**防线，
  不能只依赖 stop_hook_active。

判据（保守优先，误报会让人关掉钩子 = 全域失防）:
  同时满足三条才拽回：
    ① 最后一条消息里出现「任务完成」类断言词
    ② 该断言词不在否定语境里（「未完成 / 没通过 / 无法验证」不算）
    ③ 全文找不到任何一个落点证据（rc= / 退出码 / commit sha / 文件:行号 / 0 ✗ / ✓ N）
  任一证据存在即放行——宁可放过，不可误伤。

防死循环:
  `stop_hook_active` 为真时一律放行（平台已因上一次拽回重入）。
  另加本机计数：同一 session 连续拽回上限 MAX_RETRY 次，超过即放行并留痕，
  避免判据写坏导致会话卡死。
"""
import argparse
import json
import os
import re
import sys

STATE = os.path.join(os.path.expanduser('~'), '.codebuddy', 'hooks', '.stop_guard_state')
MAX_RETRY = 2

# 断言词：只收「宣称一件事已经办完」的说法，不收「完成了 X 功能」这类过程描述
ASSERT_PATS = [
    r'已完成', r'已修复', r'已落地', r'已通过', r'全部通过', r'验证通过',
    r'已上线', r'已部署', r'已提交并推送', r'修复完成', r'改完了', r'做完了',
    r'已闭环', r'搞定了',
]

# 否定语境：断言词前 4 字内出现这些，视为「没做完」的正常表述，不拽回
NEG_RE = re.compile(r'(?:未|没|没有|无法|不能|不算|尚未|并不|不会|还没|未完全)'
                    r'[\u4e00-\u9fa5]{0,4}$')

# 落点证据：任一条命中即认为给了凭据（宽松，宁放过不误伤）
EVIDENCE_PATS = [
    r'\brc\s*=\s*\d+',                      # rc=0
    r'退出码\s*[:：]?\s*\d*',                # 退出码 0
    r'(?:commit|提交|sha)\s*[:：=]?\s*`?[0-9a-f]{7,40}',   # commit 6ed5df1
    r'(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}',     # 裸 sha（必含 a-f，避免把纯数字当 sha）
    r'[\w./-]+\.(?:py|md|sh|json|js|ts|tsx|yml|yaml|html|css|toml):\s*\d+',  # 文件:行号
    r'0\s*✗',                                # 0 ✗
    r'✓\s*\d+',                              # ✓ 66
    r'\d+\s*例.{0,6}(?:通过|0\s*失败)',        # 39 例 0 失败
    r'第\s*\d+\s*行',                         # 第 120 行
]


def _read_state():
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except Exception:
        return {}


def _write_state(d):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(d, open(STATE, 'w', encoding='utf-8'))
    except Exception:
        pass


def has_assert(text):
    """有没有「宣称完成」，且不在否定语境。"""
    for p in ASSERT_PATS:
        for m in re.finditer(p, text):
            if NEG_RE.search(text[max(0, m.start() - 6):m.start()]):
                continue
            return True
    return False


def has_evidence(text):
    for p in EVIDENCE_PATS:
        if re.search(p, text):
            return True
    return False


# impl: B-13 S2   ← 断言词命中且零落点证据 → JSON decision:block 拽回
# impl: B-03 S5   ← L3 环境定位留痕缺失且未消解 → Stop 拽回
# impl: B-07 S5   ← L3 开机读 handoff 留痕缺失且未消解 → Stop 拽回
def judge(text):
    """返回 (是否拽回, 原因)。"""
    if not text or not text.strip():
        return False, '空消息'
    if not has_assert(text):
        return False, '无完成断言'
    if has_evidence(text):
        return False, '有落点证据'
    return True, '宣称完成但全文无任何落点证据'


def load_rule_trace():
    """加载 verify/rule_trace.py（不依赖 sys.path，钩子独立运行）。"""
    import importlib.util
    vp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'verify', 'rule_trace.py')
    try:
        spec = importlib.util.spec_from_file_location('_rule_trace', vp)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:
        return None                      # fail-open：判据坏了不卡死会话


# impl: B-18 S2   ← 交付正文缺「N 条有出处 / M 条无出处」计数对 → Stop 拽回
def judge_delivery(text):
    """L4 溯源拽回：交付段缺计数对 → (True, 'B-18')；真阳/unknown 放行。

    判据坏（delivery_trace 加载失败）fail-open。
    """
    import importlib.util
    vp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'verify', 'delivery_trace.py')
    try:
        spec = importlib.util.spec_from_file_location('_delivery_trace', vp)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return (True, 'B-18') if m.unresolved(text) else (False, '')
    except Exception:
        return False, ''                     # fail-open


def judge_trace(state_path=None):
    """L3 留痕拽回：B-03/B-07 真阴性且未消解 → (True, 规则列表)。

    真阳性/unknown 不拦（B-02 不折叠）；已 confirm 的不误伤（病15 识别范围≠对象范围）。
    判据坏（rule_trace 加载失败）fail-open。
    """
    rt = load_rule_trace()
    if rt is None:
        return False, []
    st = rt.load_state(state_path)
    bad = [r for r in ('B-07', 'B-03') if rt.unresolved(st, r)]
    return bool(bad), bad


# 单行：注入回模型后不占多行、不被当成排版块（踩过「多行字段被闸截断」的坑）
MSG = ('⛔ B-13 完成态凭落点：上一条回复宣称「完成 / 通过」，但全文找不到任何落点证据。'
       '落点证据指：改动的文件与行号、跑过的命令与退出码（rc=0）、commit sha，或判据输出原文。'
       '请二选一：①补上上述证据后重发结论；②把结论改写成「未验证 / 无法判定」。'
       '这条拦的是「我看了一下，应该没问题」——它不算完成。')

# L3 留痕拽回文案（单行——踩过「多行字段被注入截断」的坑）
MSG_TRACE = ('⛔ 行为留痕缺失：本轮 B-03（动手前核环境）/ B-07（换模型读交接）的执行留痕'
             '判为真阴性（回退猜仓/开机没读到交接）且未补证据。'
             '请二选一：①真补做后运行 python3 verify/rule_trace.py confirm <规则> --proof "证据" 消解，'
             '再重发；②若本轮确实无法判定，把结论改写成「本会话未对齐 / 无法判定」。'
             '这条拦的是「规则写了但没发生」——软约束必须有牙。')

# L4 溯源拽回文案（单行）
MSG_DELIVERY = ('⛔ B-18 产出可溯源：上一条有交付段（交付物/交付报告/交付：），'
                '但没给出「N 条有出处 / M 条无出处」两个计数。'
                '请补上这两个数（无出处项单列「⚠️ 无出处」，不要删掉或混进正文）后重发；'
                '若本条并非交付正文，把交付段标记去掉或改写成过程描述。'
                '这条拦的是「交付了却不报溯源账」——计数模板是确定性形态，机器可判。')


def main():
    ap = argparse.ArgumentParser(description='回合末拽回（Stop · B-13）')
    ap.add_argument('--check', metavar='TEXT', help='只判定一段文本，打印结论（调试/测试用）')
    ap.add_argument('--list', action='store_true', help='列出判据')
    ap.add_argument('--probe', action='store_true', help='查看拽回观测（hit/via：判定走过哪条分支）')
    a = ap.parse_args()

    if a.probe:
        st = _read_state()
        if not st:
            print('（无拽回记录：判据从未命中，或钩子未被调用——病13 三态要分清）')
            return 0
        out = {'event': 'Stop', 'hit': False, 'via': 'pass', 'sessions': {},
               'trace': {}}
        for sid, v in st.items():
            n = int(v.get('n', 0))
            out['sessions'][sid] = {
                'retries': n,
                'gave_up': bool(v.get('gave_up')),
                'last_why': v.get('last_why', ''),
            }
            if n > 0:
                out['hit'] = True
                out['via'] = 'deny'
        # L3：留痕侧观测（读真实 next_anchor state）
        rt = load_rule_trace()
        if rt:
            rstate = rt.load_state()
            out['trace'] = {'rules': {r: {'verdict': rt.verdict(rstate, r),
                                          'unresolved': rt.unresolved(rstate, r)}
                                      for r in ('B-07', 'B-03')}}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if a.list:
        print('断言词：', ' / '.join(ASSERT_PATS))
        print('否定豁免：', NEG_RE.pattern)
        print('落点证据（任一即放行）：')
        for p in EVIDENCE_PATS:
            print('  ', p)
        return 0

    if a.check is not None:
        d, why = judge(a.check)
        print(json.dumps({'deny': d, 'why': why}, ensure_ascii=False))
        return 2 if d else 0

    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    # 平台已因上次拽回重入 → 必须放行，否则死循环
    if data.get('stop_hook_active'):
        return 0

    sid = str(data.get('session_id') or '')
    st = _read_state()
    n = int((st.get(sid) or {}).get('n', 0))
    if n >= MAX_RETRY:
        st.setdefault(sid, {})['n'] = n
        st[sid]['gave_up'] = True
        _write_state(st)
        return 0

    text = str(data.get('last_assistant_message') or '')
    deny, why = judge(text)
    deny_t, bad_rules = judge_trace() if not deny else (False, [])
    deny_d, _ = judge_delivery(text) if (not deny and not deny_t) else (False, '')
    if not deny and not deny_t and not deny_d:
        return 0

    if deny:
        reason, why_log = MSG, why
    elif deny_t:
        reason, why_log = MSG_TRACE + '（规则：%s）' % ','.join(bad_rules), \
                         '留痕缺失:' + ','.join(bad_rules)
    else:
        reason, why_log = MSG_DELIVERY, '交付缺溯源计数:B-18'
    st.setdefault(sid, {})['n'] = n + 1
    st[sid]['last_why'] = why_log
    _write_state(st)
    # JSON decision:block（实测能拽回；exit 2 + stderr 不能，见文件头「协议」）
    print(json.dumps({'decision': 'block', 'reason': reason}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)          # fail-open：判据坏了不该卡死会话
