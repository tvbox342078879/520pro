#!/usr/bin/env python3
"""classify_routing_check.py — 归类路由判据（离线）：交付物只能归产物归档。

为什么要有（S-02 机制解决，不打补丁）：
  2026-11-17 出现"产物归档空、交付物全进主题夹"的归类偏差。根因是
  classify_rules.json 里「完工交付报告」同时命中第5条（→产物归档/文档）和
  第9条子项目演进（→520进化论/03）。靠"取首条命中"才侥幸落对，一旦规则
  顺序变化或被显式 --target 覆盖就归错。base_blueprint:31 又有"人读交付归
  02/03/05"的冲突措辞。改文件只能修当前，判据才能防复发。

判据：
  ① 交付信号词（报告/交付/完工/终审/验收）的归口规则 target == 📦 产物归档/文档
  ② 主题夹（🧬 520进化论/*）的任一规则 match 不得含交付信号词
  ③ 交付信号词归口唯一：不得有第二条规则抢同一批词指向别处
  ④ base_blueprint 不得残留"人读交付归 02/03/05"旧措辞

出口码：0=OK / 1=FAIL（红）/ 2=OPT（文件缺失，无法判定，不冒充绿也不冒充红）。
仅查仓库真源文件，不联网、不改文件。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RULES_REL = os.path.join('通用层', 'skills', 'space-hub', 'scripts', 'classify_rules.json')
BLUE_REL = os.path.join('通用层', 'skills', 'space-hub', 'scripts', 'base_blueprint.json')

DELIVER_WORDS = {'报告', '交付', '完工', '终审', '验收'}
DELIVER_TARGET = '📦 产物归档/文档'
TOPIC_PREFIX = '🧬 520进化论/'


def _load_rules(rules_path, blue_path):
    with open(rules_path, encoding='utf-8') as f:
        rules = json.load(f).get('rules', [])
    with open(blue_path, encoding='utf-8') as f:
        blue_text = f.read()
    return rules, blue_text


def check(rules, blue_text):
    """返回 (ok: bool, 问题列表)。纯函数，供变异回归复用。"""
    errs = []
    # ① 含交付信号词的规则，归口必须是产物归档/文档
    for r in rules:
        match = set(r.get('match', []))
        if match & DELIVER_WORDS:
            tgt = str(r.get('target', ''))
            if tgt != DELIVER_TARGET:
                errs.append(f"交付词规则[{r.get('category')}]归口={tgt}，应为 {DELIVER_TARGET}")
    # ②③ 主题夹规则不得含交付信号词；交付词归口唯一
    for r in rules:
        tgt = str(r.get('target', ''))
        match = set(r.get('match', []))
        if tgt.startswith(TOPIC_PREFIX) and (match & DELIVER_WORDS):
            errs.append(f"主题夹规则[{r.get('category')}]含交付词 {sorted(match & DELIVER_WORDS)}")
    hit_cats = [r.get('category') for r in rules if set(r.get('match', [])) & DELIVER_WORDS]
    if len(hit_cats) > 1:
        errs.append(f"交付词命中多条规则（非唯一归口）: {hit_cats}")
    # ④ base_blueprint 旧措辞
    if '人读交付归' in blue_text:
        errs.append("base_blueprint.json 残留「人读交付归 02/03/05」旧措辞（与 B-09 冲突）")
    return (len(errs) == 0), errs


def main():
    rp = os.path.join(ROOT, RULES_REL)
    bp = os.path.join(ROOT, BLUE_REL)
    if not (os.path.isfile(rp) and os.path.isfile(bp)):
        print('OPT 归类真源缺失，无法判定')
        return 2
    rules, blue = _load_rules(rp, bp)
    ok, errs = check(rules, blue)
    if ok:
        print(f'OK 归类路由正确：交付词唯一归 {DELIVER_TARGET}，主题夹无交付词，蓝图无旧措辞')
        return 0
    print('FAIL 归类路由错误：')
    for e in errs:
        print('  -', e)
    return 1


if __name__ == '__main__':
    sys.exit(main())
