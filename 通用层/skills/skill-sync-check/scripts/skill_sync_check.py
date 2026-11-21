#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_sync_check.py — 技能版本清单对比（云取借鉴第4条·查更新，skill-sync-check 正门）。

第4条原始诉求（transcript L2565）："MarketClient 从仓库拉插件列表、PluginUpdateChecker 查更新；
520 技能全靠手工登记进 git，没有'从远端拉/查更新'；学了能像应用商店一样更新，对上
'达标晋升能不能同步'。" 本技能实现其中**查更新**一环：把本地契约登记的版本与远端
（调用方喂入的）版本清单逐技能对比，产出待更新/超前/无法判定/缺失四态报告。

三态诚实（B-02）：
  - behind   本地落后远端（该更新）
  - ahead    本地超前远端（远端旧/本地未推）
  - same     版本一致
  - unknown  版本串格式非法/字段缺失——无法判定，不硬判（fail-closed）
  - missing  某技能只在一侧出现——远端新增或本地多余，无法判定谁新

边界：本工具**只读、不触网**——远端版本清单由调用方喂文件（可从 git/raw 取后传入）；
"从仓库自动拉列表 + sourceMirror 镜像源 + 达标晋升联动"是下一步，不在本技能内（触网判据难做真阳性）。

设计：纯函数 + 数据驱动；判据喂真 contracts 看真输出，不读源码字符串（病15 对象范围）。
"""
import argparse
import json
import re
import sys

# 点分数字版本：1.1.0 / 1.28.9 / 2.8.0；段落数可变（1.0 vs 1.0.0 视为等价补零）
_SEG_RE = re.compile(r'^\d+$')


class InvalidVersion(Exception):
    """版本串格式非法——显式抛，不静默折叠成 0。"""


def parse_version(version):
    """点分数字版本 → 归一化 tuple（右侧补 0 对齐）。格式非法抛 InvalidVersion。

    只接受纯数字段（1.28.9）；带 v 前缀/字母/空段（market 的 v1 那套）一律拒——
    那是另一种版本号对象，不混用（M3 受控词表，避免病15 真源分裂）。
    """
    if not isinstance(version, str) or not version:
        raise InvalidVersion('版本串必须是非空字符串：%r' % (version,))
    segs = version.split('.')
    if not segs or any(not _SEG_RE.match(s) for s in segs):
        raise InvalidVersion('版本串格式非法（须纯数字点分）：%r' % (version,))
    nums = tuple(int(s) for s in segs)
    # 右侧补 0：1.0 与 1.0.0 等价
    width = len(nums)
    return nums


def compare_versions(local, remote):
    """两版本串比较 → 'behind' / 'ahead' / 'same' / 'unknown'（无法判定 fail-closed）。

    behind=本地小（远端新）、ahead=本地大、same=相等；任一格式非法 → unknown。
    逐段比较，段数不同按缺段补 0（1.0 == 1.0.0；1.2 > 1.1.9）。
    """
    try:
        a, b = parse_version(local), parse_version(remote)
    except InvalidVersion:
        return 'unknown'
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    if a < b:
        return 'behind'
    if a > b:
        return 'ahead'
    return 'same'


def _versions_from(contracts):
    """契约 dict → {技能名: version}。取 skills 段的 version 字段；非 dict 返回 None。"""
    if not isinstance(contracts, dict):
        return None
    skills = contracts.get('skills')
    if not isinstance(skills, dict):
        return None
    return {k: v.get('version') for k, v in skills.items()
            if isinstance(v, dict) and 'version' in v}


def build_update_report(local_contracts, remote_contracts):
    """本地 vs 远端契约 dict → 三态清单报告。

    返回 {summary: {...}, items: [{skill, local, remote, status}, ...]}。
    - 远端缺该技能 → missing（远端新增/本地独有，无法判定谁新）
    - 本地缺该技能 → missing
    - 版本串非法/字段缺 → unknown
    """
    lv, rv = _versions_from(local_contracts), _versions_from(remote_contracts)
    if lv is None or rv is None:
        return {'summary': {'error': '契约格式非法（缺 skills 段）', 'total': 0}, 'items': []}
    all_skills = sorted(set(lv) | set(rv))
    items = []
    for name in all_skills:
        lver, rver = lv.get(name), rv.get(name)
        if lver is None or rver is None:
            status = 'missing'
        else:
            status = compare_versions(lver, rver)
        items.append({'skill': name, 'local': lver, 'remote': rver, 'status': status})
    summary = {'total': len(items)}
    for s in ('behind', 'ahead', 'same', 'unknown', 'missing'):
        summary[s] = sum(1 for it in items if it['status'] == s)
    return {'summary': summary, 'items': items}


def _self_check():
    ok = (compare_versions('1.0.0', '1.1.0') == 'behind'
          and compare_versions('1.1.0', '1.0.0') == 'ahead'
          and compare_versions('1.0', '1.0.0') == 'same'
          and compare_versions('1.2', '1.1.9') == 'ahead'
          and compare_versions('v1', 'v2') == 'unknown'
          and compare_versions('1.0.0', 123) == 'unknown')
    rep = build_update_report(
        {'skills': {'a': {'version': '1.0.0'}, 'b': {'version': '2.0.0'}}},
        {'skills': {'a': {'version': '1.1.0'}, 'c': {'version': '1.0.0'}}})
    ok = ok and rep['summary']['behind'] == 1 and rep['summary']['missing'] == 2
    return ok


def main():
    ap = argparse.ArgumentParser(description='技能版本清单对比（查更新，只读不触网）')
    ap.add_argument('--local', help='本地 skill_contracts.json 路径')
    ap.add_argument('--remote', help='远端 skill_contracts.json 路径（调用方取好后传入）')
    ap.add_argument('--json-out', help='结果写入 JSON 文件')
    ap.add_argument('--selftest', action='store_true', help='自省自检')
    a = ap.parse_args()
    if a.selftest:
        ok = _self_check()
        print('SELFTEST %s' % ('OK' if ok else 'FAIL'))
        return 0 if ok else 2
    if not a.local or not a.remote:
        print(json.dumps({'summary': {'error': '须给 --local 和 --remote；--selftest 自检'}}, ensure_ascii=False))
        return 2
    try:
        with open(a.local, encoding='utf-8') as f:
            local = json.load(f)
        with open(a.remote, encoding='utf-8') as f:
            remote = json.load(f)
    except Exception as ex:
        print(json.dumps({'summary': {'error': '读取失败：%s' % ex}}, ensure_ascii=False))
        return 2
    out = build_update_report(local, remote)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if a.json_out:
        with open(a.json_out, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == '__main__':
    sys.exit(main())
