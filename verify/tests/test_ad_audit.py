#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_ad_audit.py — 百度 docx 正文广告排查一键命令（ad-audit）机器判据。

四层判据（病15 防御：判据识别范围 ≠ 对象范围）：
  A 命令层：build_parser 有 ad-audit 子命令 + main dispatch 有 handler。
  B 源码层：AST 锚定 cmd_pan_ad_audit 函数体确实复用 randsk/BDCLND 验证态
            + docview→dlink→PDF→OCR 链（标识符词级，非子串——防 WIPED_FIELDS 假绿）。
  C 纯函数层：ad_hits(text) 关键词判定——离线喂广告/干净样本，不依赖 cookie/网络。
  D 经验固化层：广告排查方法固化为经验条目，fixed_path 指可执行 pan.py，
            exp_probe.match 命中能带出该落点（踩坑→能力→直达闭环实证）。
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO, '通用层', 'skills', 'learn-hub', 'scripts')
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(REPO, 'verify'))
import pan as P  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


SRC = open(os.path.join(SCRIPTS, 'pan.py'), encoding='utf-8').read()

# ── A 命令层：可离线，直接看 parser 解析结果 ──────────────────────────────
try:
    ns = {}
    tree = ast.parse(SRC)
    cmds = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == 'add_parser' and node.args \
                and isinstance(node.args[0], ast.Constant):
            cmds.append(node.args[0].value)
    check('build_parser 注册 ad-audit 子命令', 'ad-audit' in cmds, cmds)
    check('main dispatch 映射 ad-audit → handler',
          "'ad-audit'" in SRC and 'cmd_pan_ad_audit' in SRC)
except Exception as ex:
    check('命令层解析', False, repr(ex))

# ── B 源码层：AST 锚定 handler 函数体确实复用验证态 + 预览/OCR 链 ─────────
def handler_names(src):
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == 'cmd_pan_ad_audit':
            for n in ast.walk(node):
                if isinstance(n, ast.Name):
                    names.add(n.id)
                elif isinstance(n, ast.Attribute):
                    names.add(n.attr)
                elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                    names.add(n.value)
    return names


try:
    hn = handler_names(SRC)
    check('handler 复用带密码验证态 _baidu_randsk', '_baidu_randsk' in hn, hn)
    check('handler 复用 BDCLND 鉴权 cookie', 'BDCLND' in hn or '_baidu_authed_cookie' in hn)
    check('handler 走 picdocpreview→dlink 预览链', 'picdocpreview' in hn and 'dlink' in hn)
    # 病15 防护：PDF→OCR 已抽到 ad_scan_pdf()（handler 只调用它），判据须贴实现
    # 所在函数而非调用点——锚 ad_scan_pdf 函数体含 tesseract，handler 含其调用。
    def _body_names(fname):
        names = set()
        for node in ast.walk(ast.parse(SRC)):
            if isinstance(node, ast.FunctionDef) and node.name == fname:
                for n in ast.walk(node):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
                    elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                        names.add(n.value)
        return names
    scan_names = _body_names('ad_scan_pdf')
    check('PDF→OCR 链 ad_scan_pdf 含 tesseract + 被 handler 调用',
          'tesseract' in scan_names and 'ad_scan_pdf' in hn,
          (scan_names & {'tesseract', 'fitz'}, 'ad_scan_pdf' in hn))
except Exception as ex:
    check('源码层 AST 锚定', False, repr(ex))

# ── C 纯函数层：ad_hits 关键词判定（离线，喂样本）────────────────────────
try:
    check('pan 暴露 ad_hits(text) 关键词判定纯函数', hasattr(P, 'ad_hits'))
    if hasattr(P, 'ad_hits'):
        ad = P.ad_hits('请加微信 xmly22333，扫二维码，添加我为朋友')
        clean = P.ad_hits('本期讲量子计算与宇宙膨胀，敬请期待下期。')
        check('广告文本命中关键词', bool(ad), ad)
        check('干净文本不误命中（真阴性）', not clean, clean)
    # C2 端到端扫描链：本地造 PDF 喂 ad_scan_pdf，真跑 PDF→OCR→命中（离线，不依赖网络）
    check('pan 暴露 ad_scan_pdf(pdf_bytes) 扫描链纯函数', hasattr(P, 'ad_scan_pdf'))
    if hasattr(P, 'ad_scan_pdf'):
        import fitz
        def _pdf_with(txt):
            d = fitz.open(); pg = d.new_page(); pg.insert_text((72, 100), txt, fontsize=16)
            b = d.tobytes(); d.close(); return b
        r_ad = P.ad_scan_pdf(_pdf_with('Weixin xmly22333 QR code'), pages_each=1,
                             workdir='/tmp', _tag='pos')
        r_ok = P.ad_scan_pdf(_pdf_with('Quantum physics and universe'), pages_each=1,
                             workdir='/tmp', _tag='neg')
        check('含广告 PDF 真跑 OCR 命中（端到端真阳性）',
              bool(r_ad.get('hits')) and r_ad['flag'] == '★AD', r_ad)
        check('干净 PDF 真跑 OCR 不误命中（端到端真阴性）',
              not r_ok.get('hits') and r_ok['flag'] == '  ok', r_ok)
except Exception as ex:
    check('纯函数层 ad_hits/ad_scan_pdf', False, repr(ex))

# ── D 经验闸层：ad-audit 动手前走 exp_probe.gate，命中带出可执行落点 ──────
try:
    import json
    import exp_probe as EP
    # D1 源码层：handler 函数体内确实调用 exp_probe.gate（AST 词级锚定，防病15）
    def calls_gate(src):
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == 'cmd_pan_ad_audit':
                for n in ast.walk(node):
                    # exp_probe.gate(...) 或 _ep.gate(...)：Call.func 是 Attribute(attr='gate')
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                            and n.func.attr == 'gate':
                        return True
        return False
    check('ad-audit handler 动手前调用经验闸 gate', calls_gate(SRC))
    # D2 行为层：用库里真实存在的症状验证 gate 能带出可执行落点（不伪造经验条目）
    rec = json.load(open(os.path.join(REPO, 'experience_recurrence.json'), encoding='utf-8'))
    es = rec.get('exp_entries') or []
    with_fp = [e for e in es if e.get('fixed_path', '').endswith(('.py', '.sh'))]
    check('经验库存在带可执行落点的条目（踩坑已固化）', bool(with_fp), len(with_fp))
    if with_fp:
        real_sym = with_fp[0].get('symptom', '')[:40]
        g = EP.gate(real_sym, rec=rec, commit=False)
        check('gate 命中真实症状并带出 .py/.sh 落点',
              bool(g) and g.get('fixed_path', '').endswith(('.py', '.sh')))
except Exception as ex:
    check('经验闸层', False, repr(ex))

print('\n%d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
