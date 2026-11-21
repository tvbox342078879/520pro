#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse4k_scan.py —— 4K 解析接口批量探测：不按名字标签，按实测流清单判真伪。

【为什么要有】（2026-11-21/22 实测教训，病15）
  扒作者包 + GitHub/Gitee 400+ 仓的「4K解析」接口：名字带 4K 的十几条里
  只有牛马 1 条真出 4K（流清单 2880x2160 / 3840x1920、分片 HTTP206），
  其余全超时/404/功能不符；而作者包 8 条 parses 里 7 条未标 4K 的被漏测。
  名字里的「4K」是标签不是能力（识别范围≠对象范围）。
  正确做法：扫配置里**所有** http 解析接口，用已知 4K 片源逐条打，
  从回流清单读到 height>=2160 or width>=3840 才算真 4K。

【判据真源】
  分辨率判定复用 quality.py#resolution_level（本文件不复制分辨率逻辑，M2）；
  取流复用 quality._curl（统一取数，C1）。三态纪律（M-R60）：
    真4K     = 流清单实测分辨率达标（真阳性）
    非4K     = 有流清单但分辨率不达标（真阴性）
    无法判定 = 接口超时/404/返回HTML跳转页/流不可达/分辨率不可读
  名字标 4K 但实测非 4K → 判「非4K」，不采信标签。

【用法】
  python3 parse4k_scan.py --config <配置URL或本地JSON>          # 扫全部 http 解析接口
  python3 parse4k_scan.py --config cfg.json --json-out out.json # 存结果
  python3 parse4k_scan.py --selftest                            # 无网络自检
"""
import argparse
import concurrent.futures
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import quality  # noqa: E402  判据真源（resolution_level / _curl）

# 实测真 4K 片源（2026-11-21 牛马4K验证用，mpd 2880x2160 / 3840x1920）
DEFAULT_SAMPLE = 'https://www.bilibili.com/video/BV1kN4y197Ph'
# 流清单地址：mpd/m3u8，允许带查询串；排除 JSON 转义反斜杠与引号
STREAM_RE = re.compile(r'https?://[^\s"\'<>\\]+\.(?:mpd|m3u8)(?:\?[^\s"\'<>\\]*)?', re.I)
MAX_WORKERS = 6  # M-R114 B 档（公网）上限


def load_config(src):
    """配置源（URL 或本地文件）→ dict。去 // 注释行 + BOM。"""
    if re.match(r'^https?://', src or ''):
        req = urllib.request.Request(src, headers={'User-Agent': quality.UA})
        raw = urllib.request.urlopen(req, timeout=25).read().decode('utf-8-sig', 'replace')
    else:
        raw = open(src, encoding='utf-8-sig').read()
    clean = '\n'.join(l for l in raw.splitlines() if not l.lstrip().startswith('//'))
    return json.loads(clean)


def parse_items(cfg):
    """扫 parses → 所有 http 接口 [{name,url,type}]。

    ★ 不按名字过滤、不按 type 过滤——这是本脚本存在的理由：
      名字带不带 4K、type=1 还是 0 都进待测，由实测判真伪，
      避免把「没标 4K 但能出 4K」的通用接口漏掉（问题3的漏检）。
    ★ 非 http（本地/内置 jar）单列 skipped，记「不适用」不算失败。
    """
    items, skipped = [], []
    for p in (cfg.get('parses') or []):
        name = str(p.get('name', ''))
        url = str(p.get('url', '') or '').strip()
        if url.startswith('http'):
            items.append({'name': name, 'url': url, 'type': p.get('type')})
        else:
            skipped.append(name)
    return items, skipped


def extract_stream_url(text):
    """从解析接口响应提取 mpd/m3u8 流地址（兼容 JSON 的 \\/ 转义与 &amp;）。"""
    if not text:
        return ''
    s = text.replace('\\/', '/').replace('&amp;', '&')
    m = STREAM_RE.search(s)
    return m.group(0) if m else ''


def judge_stream(stream_text):
    """流清单文本 → (档位, 是否4K, 分辨率是否可读)。判据完全委托 quality.py。"""
    level, _h = quality.resolution_level(stream_text)
    if level == '未知':
        return level, False, False
    return level, level == '4K', True


def _result(name, api, verdict, evidence, **kw):
    return {
        'name': name, 'api': api, 'verdict': verdict, 'evidence': evidence,
        'quality': kw.get('level', ''), 'stream': kw.get('stream', ''),
    }


def probe_one(item, sample, timeout=12, param='url'):
    """打一条解析接口 → 拉流 → 读分辨率 → 三态结论。"""
    name, api = item['name'], item['url']
    sep = '&' if '?' in api else '?'
    full = f'{api}{sep}{param}={urllib.parse.quote(sample, safe="")}'
    code, body, *_ = quality._curl(full, timeout=timeout)
    if code == 0:
        return _result(name, api, '无法判定', '接口不可达（超时/DNS/TCP）')
    if code in (403, 404, 410, 451):
        return _result(name, api, '无法判定', f'接口 HTTP {code}（失效/拒绝）')

    text = body.decode('utf-8', errors='replace')
    stream = extract_stream_url(text)
    if not stream:
        low = text[:2048].lower()
        kind = ('返回HTML网页（手动解析/跳转型，非直出流）'
                if '<html' in low or '<!doctype' in low else '响应无 mpd/m3u8 流地址')
        return _result(name, api, '无法判定', kind)

    c2, b2, *_ = quality._curl(stream, timeout=timeout)
    if c2 not in (200, 206):
        return _result(name, api, '无法判定', f'流不可达 HTTP {c2}', stream=stream)
    level, is4k, readable = judge_stream(b2.decode('utf-8', errors='replace'))
    if not readable:
        return _result(name, api, '无法判定', '流可读但分辨率不可读（单码率无标记）', stream=stream)
    verdict = '真4K' if is4k else '非4K'
    return _result(name, api, verdict, f'{level}·流清单实测', stream=stream, level=level)


def scan(cfg, sample=DEFAULT_SAMPLE, timeout=12, workers=MAX_WORKERS, param='url'):
    """批量扫配置 parses → 报告 dict（sample/scanned/skipped/results）。"""
    items, skipped = parse_items(cfg)
    results = []
    n = max(1, min(workers, MAX_WORKERS))
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(probe_one, it, sample, timeout, param): it for it in items}
        for f in concurrent.futures.as_completed(futs):
            it = futs[f]
            try:
                results.append(f.result())
            except Exception as e:  # noqa: BLE001 单条异常不拖垮全批
                results.append(_result(it['name'], it['url'], '无法判定',
                                       f'探测异常 {type(e).__name__}'))
    return {'sample': sample, 'scanned': len(items), 'skipped': skipped, 'results': results}


def _selftest():
    """无网络自检：纯函数 + 判据真源联动。退出码 0 全通 / 1 有失败。"""
    ok, bad = 0, []

    def t(name, cond):
        nonlocal ok
        if cond:
            ok += 1
            print(f'  ✓ {name}')
        else:
            bad.append(name)
            print(f'  ✗ {name}')

    print('== ① 流地址提取 ==')
    t('JSON包裹+转义 \\/ 的 mpd', extract_stream_url('{"url":"https:\\/\\/x.com\\/a.mpd"}') == 'https://x.com/a.mpd')
    t('裸 m3u8 带查询串', extract_stream_url('https://x.com/live.m3u8?token=a') == 'https://x.com/live.m3u8?token=a')
    t('HTML跳转页无流', extract_stream_url('<html>jump</html>') == '')
    t('&amp; 还原', extract_stream_url('https://x.com/a.mpd?a=1&amp;b=2').endswith('a=1&b=2'))

    print('== ② 分辨率判据（委托 quality.py 真源）==')
    t('mpd 2880x2160 → 4K', judge_stream('<MPD><Representation width="2880" height="2160"/></MPD>')[1] is True)
    t('m3u8 3840x2160 → 4K', judge_stream('#EXT-X-STREAM-INF:RESOLUTION=3840x2160')[1] is True)
    t('1920x1080 → 非4K', judge_stream('RESOLUTION=1920x1080')[1] is False)
    t('空文本 → 分辨率不可读', judge_stream('')[2] is False)

    print('== ③ 不按标签过滤（问题3漏检防线）==')
    cfg = {'parses': [
        {'name': '普通解析', 'url': 'http://a.com/jx?url=', 'type': 1},
        {'name': '4K解析', 'url': 'http://b.com/jx?url=', 'type': 1},
        {'name': '本地jar', 'url': './niuma.jar', 'type': 3},
    ]}
    items, skipped = parse_items(cfg)
    t('未标4K的 http 接口也纳入', {x['name'] for x in items} == {'普通解析', '4K解析'})
    t('非http单列 skipped', skipped == ['本地jar'])

    print(f'selftest: {ok}✓ / {len(bad)}✗')
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='4K解析接口批量探测（不按标签，按实测流清单）')
    ap.add_argument('--config', help='配置 URL 或本地 JSON（含 parses 数组）')
    ap.add_argument('--sample', default=DEFAULT_SAMPLE, help='已知 4K 片源 URL')
    ap.add_argument('--param', default='url', help='接口接受片源的参数名（默认 url）')
    ap.add_argument('--timeout', type=int, default=12)
    ap.add_argument('--workers', type=int, default=MAX_WORKERS)
    ap.add_argument('--json-out', default='', help='结果 JSON 路径')
    ap.add_argument('--selftest', action='store_true', help='无网络自检')
    a = ap.parse_args(argv)

    if a.selftest:
        return _selftest()
    if not a.config:
        ap.error('缺 --config（或 --selftest）')

    cfg = load_config(a.config)
    rep = scan(cfg, a.sample, a.timeout, a.workers, a.param)

    from collections import Counter
    cnt = Counter(r['verdict'] for r in rep['results'])
    print(f"扫 {rep['scanned']} 条 http 解析接口；非http跳过 {len(rep['skipped'])} 条")
    print(f"片源：{rep['sample']}")
    for r in rep['results']:
        print(f"  {r['verdict']:4s} | {r['name'][:18]:20s} | {r['evidence'][:60]}")
    print(f"真4K {cnt['真4K']} / 非4K {cnt['非4K']} / 无法判定 {cnt['无法判定']}")
    if a.json_out:
        json.dump(rep, open(a.json_out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'结果 → {a.json_out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
