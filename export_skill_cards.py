#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_skill_cards.py — 导出技能卡片，供手机端手动导入账号库

用法:
  python3 export_skill_cards.py                 # 全部技能，Markdown 输出到 stdout
  python3 export_skill_cards.py --only space-hub,learn-hub
  python3 export_skill_cards.py --json          # 机器读（name/version/description/triggers）
  python3 export_skill_cards.py > 卡片.md        # 自己决定往哪落（本脚本默认不落盘，B-09）

为什么要有它（而不是写一份静态文档）:
  description 是路由真源，几乎每次改技能都会动。手抄进文档 → 下次就过期 →
  手机上贴的还是老版本，症状是「明明技能更新了，手机却叫不动」。
  故本脚本从 SKILL.md 现读现出，卡片永不落后于仓库。

纪律:
  · 只读 —— 不改任何 SKILL.md；
  · 缺 name/version/description 的技能**整条不输出并报错**，不输出半张卡片
    （半张卡片贴到手机上等于一个坏技能，比没有更难查）；
  · 不猜 App 的导入格式：输出标准 frontmatter 文本块，格式不符时以 --json 二次适配。
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
BASES = [('通用层', '通用层/skills'), ('能力层', '能力层/tvbox/skills')]


def parse_skill(path):
    """返回 {name, version, description, triggers} 或抛 ValueError（原因写清）。"""
    t = open(path, encoding='utf-8').read()
    if not t.startswith('---'):
        raise ValueError('缺 frontmatter')
    end = t.find('\n---', 3)
    if end < 0:
        raise ValueError('frontmatter 未闭合')
    fm = t[3:end]
    out = {}
    for key in ('name', 'version'):
        m = re.search(r'^' + key + r':\s*(.+)$', fm, re.M)
        if not m:
            raise ValueError(f'缺 {key}')
        out[key] = m.group(1).strip().strip('"\'')
    # ★ 必须截到下一个顶格键（allowed-tools 等），否则会把 allowed-tools 整行吞进 description，
    #   粘到手机上就成了一张坏卡片（2026-11-12 首次跑就踩到）。
    m = re.search(r'^description:\s*(.*?)(?=^[^\s]|\Z)', fm, re.M | re.S)
    if not m:
        raise ValueError('缺 description')
    g = m.group(1)
    q = re.match(r'\s*"(.*?)"\s*$', g, re.S)
    out['description'] = q.group(1) if q else g.strip()
    # 触发词（两种官方写法都认，与惊门 chk_triggers 同口径）
    tw = []
    mm = re.search(r'触发词[:：](.*?)(?:。|正门[:：]|能力[:：]|★|【|$)', out['description'], re.S)
    if mm:
        tw = [x.strip().strip('；;，,。 ') for x in re.split(r'[/／、]', mm.group(1)) if x.strip()]
    if not tw:
        tw = re.findall(r'「([^」]+)」', out['description'])[:20]
    out['triggers'] = tw
    return out


def collect(only=None):
    cards, bad = [], []
    for layer, base in BASES:
        d = os.path.join(REPO, base)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            sk = os.path.join(d, name, 'SKILL.md')
            if not os.path.isfile(sk):
                continue
            if only and name not in only:
                continue
            try:
                c = parse_skill(sk)
            except ValueError as e:
                bad.append((name, str(e)))
                continue
            c['layer'] = layer
            c['dir'] = os.path.relpath(sk, REPO)
            cards.append(c)
    return cards, bad


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--repo', default='')
    a = ap.parse_args(argv)
    global REPO
    if a.repo:
        REPO = os.path.abspath(a.repo)
    only = {x.strip() for x in a.only.split(',') if x.strip()} or None
    cards, bad = collect(only)

    if a.json:
        print(json.dumps({'cards': cards, 'broken': bad}, ensure_ascii=False, indent=1))
        return 2 if bad else 0

    for name, why in bad:
        print(f'✗ {name}: {why}（该技能整条未输出——半张卡片比没有更难查）', file=sys.stderr)
    if not cards:
        print('✗ 没有可导出的技能', file=sys.stderr)
        return 2

    print('# 技能卡片（供手机端导入账号库）\n')
    print(f'> 由 `export_skill_cards.py` 从仓库现读生成，共 {len(cards)} 个技能。'
          f'改完技能重跑一次即可，不要手改本文。\n')
    print('> 每个技能给两块：**一句话定位**（人看）与 **YAML 卡片**（粘贴用）。\n')
    cur = None
    for c in cards:
        if c['layer'] != cur:
            cur = c['layer']
            print(f'\n## {cur}\n')
        head = c['description'].split('。')[0][:60]
        print(f'### {c["name"]} · v{c["version"]}\n')
        print(f'- 定位：{head}。')
        print(f'- 触发词 {len(c["triggers"])} 个：{"、".join(c["triggers"][:12])}'
              + ('…' if len(c['triggers']) > 12 else '') + '\n')
        print('```yaml')
        print(f'name: {c["name"]}')
        print(f'version: "{c["version"]}"')
        # 单行输出、不折行：中文按 76 字硬折会把词切成两半（"清"+"理产物"），
        # 折叠标量虽合法但语义已被切开，粘贴到手机上更难读。
        print('description: "' + c['description'].replace('"', '\\"') + '"')
        print('```\n')
    print('---\n')
    print('## 导入后怎么验证（别只看"装上了"）\n')
    print('1. 开**新会话**（技能只在会话构建时注入，旧会话看不到）；')
    print('2. 说一句该技能的触发词，看它是否被叫起；')
    print('3. 再故意说一句**不该归它**的话（如对 space-hub 说"改一下源码"），看它是否老实让路。')
    print('   第 3 步才是关键——只测"能触发"证明不了"不乱触发"。')
    return 2 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
