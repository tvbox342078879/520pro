#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_parse4k_scan.py — 4K解析批量探测（按实测不按标签）判据回归。

【为什么需要】
  2026-11-22 用户三问之一「未标4K的会不会漏检测」成立：作者包 8 条 parses
  只测了标 4K 的 1 条，7 条未标的漏测。固化 parse4k_scan.py 做全量实测，
  本测试锁死两条防线：① 不按名字/type 过滤；② 真伪只读流清单分辨率。

判据源（唯一真源）：能力层/tvbox/skills/probe-hub/scripts/parse4k_scan.py
退出码：0 全通 / 1 有用例不符。
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PPATH = os.path.join(ROOT, '能力层', 'tvbox', 'skills', 'probe-hub',
                     'scripts', 'parse4k_scan.py')

spec = importlib.util.spec_from_file_location('p4k', PPATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

fails = []


def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


def main():
    print('== ① 流地址提取（解析接口响应形态）==')
    check('JSON包裹+\\/转义→mpd',
          m.extract_stream_url('{"url":"https:\\/\\/x.com\\/a.mpd"}') == 'https://x.com/a.mpd')
    check('裸m3u8带查询串',
          m.extract_stream_url('https://x.com/live.m3u8?token=a') == 'https://x.com/live.m3u8?token=a')
    check('HTML跳转页→无流', m.extract_stream_url('<html>jump</html>') == '')
    check('&amp;还原', m.extract_stream_url('https://x.com/a.mpd?a=1&amp;b=2').endswith('a=1&b=2'))
    check('空响应→无流', m.extract_stream_url('') == '')

    print('== ② 分辨率判据（委托 quality.py，宽高任一达标）==')
    check('mpd 2880x2160→4K',
          m.judge_stream('<MPD><Representation width="2880" height="2160"/></MPD>')[1] is True)
    check('mpd 3840x1920→4K（超宽UHD宽达标）',
          m.judge_stream('<MPD><Representation width="3840" height="1920"/></MPD>')[1] is True)
    check('m3u8 3840x2160→4K',
          m.judge_stream('#EXT-X-STREAM-INF:RESOLUTION=3840x2160')[1] is True)
    check('1080p→非4K', m.judge_stream('RESOLUTION=1920x1080')[1] is False)
    check('bandwidth数字不误判4K',
          m.judge_stream('<MPD><Representation bandwidth="8846678" width="1920" height="1080"/></MPD>')[1] is False)
    check('空文本→分辨率不可读', m.judge_stream('')[2] is False)

    print('== ③ 不按标签/type过滤（问题3漏检防线）==')
    cfg = {'parses': [
        {'name': '普通解析', 'url': 'http://a.com/jx?url=', 'type': 1},
        {'name': '4K解析', 'url': 'http://b.com/jx?url=', 'type': 1},
        {'name': '手动网页型', 'url': 'https://c.com/jx/?url=', 'type': 0},
        {'name': '本地jar', 'url': './niuma.jar', 'type': 3},
    ]}
    items, skipped = parse = m.parse_items(cfg)
    check('未标4K的两条http都纳入',
          {x['name'] for x in items} == {'普通解析', '4K解析', '手动网页型'})
    check('type=0的http也纳入（实测为准不预设立场）',
          any(x['name'] == '手动网页型' for x in items))
    check('非http单列skipped', skipped == ['本地jar'])

    print('== ④ 三态与标签证伪 ==')
    r = m._result('名字标4K', 'http://x/jx', '非4K', '1080p·流清单实测', level='1080p')
    check('实测非4K优先于名字标签', r['verdict'] == '非4K' and '4K' in r['name'])
    r2 = m._result('超时接口', 'http://x/jx', '无法判定', '接口不可达（超时/DNS/TCP）')
    check('超时记无法判定（非失败）', r2['verdict'] == '无法判定')
    r3 = m._result('真4K', 'http://x/jx', '真4K', '4K·流清单实测',
                   level='4K', stream='https://x/a.mpd')
    check('真4K携带流地址证据', r3['verdict'] == '真4K' and r3['stream'].endswith('.mpd'))

    print(f'\n结果：{len(fails)} 失败')
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
