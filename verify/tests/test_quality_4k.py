#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_quality_4k.py — 4K 画质判据（牛马4K实测后新增）

【为什么需要】
2026-11-21 实测牛马4K解析：对真 4K 片源返回的 mpd 流清单读到
  2880x2160（高度达标）与 3840x1920（宽度达标，超宽UHD），分片 HTTP206 真出流。
但旧 resolution_level 有两个洞：
  ① 只有 1080p 档，h>=1000 一律归 1080p → 真 4K 被读成 1080p；
  ② 只认 RESOLUTION=WxH 与裸 WxH，不认 mpd 的 width=/height= 属性 → 读成未知。
本测试锁死修复：宽高任一达标判 4K、mpd 属性可读、bandwidth 不得误命中。

判据源（唯一真源）：能力层/tvbox/skills/probe-hub/scripts/quality.py#resolution_level
退出码：0 全通 / 1 有用例不符。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
QPATH = os.path.join(ROOT, '能力层', 'tvbox', 'skills', 'probe-hub', 'scripts', 'quality.py')

spec = importlib.util.spec_from_file_location('q4k', QPATH)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)

fails = []


def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


def main():
    r = q.resolution_level
    print('== ① HLS m3u8 分辨率档 ==')
    check('m3u8 真4K RESOLUTION=3840x2160 → 4K',
          r('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=20000000,RESOLUTION=3840x2160\n4k.m3u8\n')[0] == '4K')
    check('m3u8 高度4K RESOLUTION=2880x2160 → 4K',
          r('RESOLUTION=2880x2160\n')[0] == '4K')
    check('m3u8 1080p 不回归', r('RESOLUTION=1920x1080\n')[0] == '1080p')
    check('m3u8 720p 不回归', r('RESOLUTION=1280x720\n')[0] == '720p')
    check('m3u8 480p 不回归', r('RESOLUTION=854x480\n')[0] == '480p')
    check('m3u8 无 RESOLUTION → 未知', r('#EXTM3U\n#EXTINF:10,\nseg.ts\n')[0] == '未知')

    print('== ② DASH mpd width=/height= 属性 ==')
    mpd2160 = '<AdaptationSet width="2880" height="2160"><Representation width="2880" height="2160"/></AdaptationSet>'
    check('mpd 高度4K 2880x2160 → 4K', r(mpd2160)[0] == '4K', str(r(mpd2160)))
    mpd1920 = '<Representation width="3840" height="1920" bandwidth="8846678"/>'
    check('mpd 宽度4K 3840x1920 → 4K（不能只看高度）', r(mpd1920)[0] == '4K', str(r(mpd1920)))
    check('mpd 属性顺序颠倒 height 在前 → 4K',
          r('<Representation height="2160" width="3840"/>\n')[0] == '4K')
    check('mpd 普通 320x240 → 360p（不误判4K）',
          r('<Representation width="320" height="240"/>\n')[0] == '360p')
    check('mpd 1080p 不回归',
          r('<Representation width="1920" height="1080"/>\n')[0] == '1080p')

    print('== ③ 病15：bandwidth 不得当宽度 ==')
    check('bandwidth="8846678" 单属性 → 未知（不得误判4K）',
          r('<Representation bandwidth="8846678"/>\n')[0] == '未知', str(r('<Representation bandwidth="8846678"/>\n')))
    check('bandwidth 与真 width 共存 → 取真 width，不取带宽数',
          r('<Representation bandwidth="8846678" width="1920" height="1080"/>\n')[0] == '1080p')

    print('== ④ 真 mpd 样本（实测产物，存在才测）==')
    claim = '/tmp/niuma_4k_claim.mpd'
    if os.path.isfile(claim):
        got = r(open(claim, encoding='utf-8').read())
        check('实测牛马4K mpd 2880x2160 → 4K', got[0] == '4K', str(got))
    else:
        print('  · 实测样本不在，跳过（非失败）')

    print('== ⑤ 4K 档接入评分：不得被当"画质不可测" ==')
    s4k = q.score('4K', 800, 300, '无')
    s1080 = q.score('1080p', 800, 300, '无')
    check('4K 有分数（非 None）', s4k is not None, str(s4k))
    check('4K 评分高于 1080p', s4k is not None and s1080 is not None and s4k > s1080,
          f'4K={s4k} 1080p={s1080}')

    if fails:
        print(f'\n✗ {len(fails)} 用例不符: {fails}')
        return 1
    print('\n✓ 全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
