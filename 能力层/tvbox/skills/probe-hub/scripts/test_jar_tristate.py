#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_jar_tristate.py — csp spider jar 下载三态判据（S234b·病15 三态折叠修复）

【为什么需要】
2026-11-22 原仓库 royalhayga/tvbox-master-aggregator 2471 条 sites 实测：
406 条 csp_jar_unknown 中 321 条「jar 下载失败」实为三种状态——
22 个唯一 jar URL 实探：404/410×10、其他 4xx×2、超时×7、200×3。
旧 fetch_jar 丢弃 core.http_get 第三位 reason（st, payload, _ = ...），
把「HTTP 404 确认不存在」（真阴性）与「超时/连接失败」（无法判定）全压成
jar=None，上层 _judge_csp 一律记 csp_jar_unknown → 该剔除的真死源混在待判定池。

判据源（唯一真源）：mount_judge.py#fetch_jar_ex / #_judge_csp
本测试锁死：
  - http_404/410/401/403 → dead → csp_dead
  - timeout/conn/dns/unknown/scheme/5xx/blocked → unknown → csp_jar_unknown（无法判定≠死）
  - 200 但 HTML 兜底/空 body → dead（资源不存在，同 ext 探活口径）
  - 有效 jar + 同名类命中 → csp_ok；无同名类 → csp_dead；解析不出类名 → csp_jar_unknown
  - fetch_jar 对外签名保持 bytes/None（兼容隐藏调用者）
退出码：0 全通 / 1 有用例不符。
"""
import importlib.util
import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'mount_judge_ts', os.path.join(HERE, 'mount_judge.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

results = []


def check(name, cond, detail=''):
    ok = bool(cond)
    results.append((name, ok))
    print(('  ✓ ' if ok else '  ✗ ') + name + (f' ｜ {detail}' if detail and not ok else ''))


_real_hg = m.http_get
_real_jcn = m.jar_class_names


def make_jar():
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('classes.dex', b'dex\n035\x00' + b'\x00' * 100)
    return b.getvalue()


def run_fetch(fake, url='https://x.test/a.jar'):
    m._JAR_CACHE.clear()
    calls = []

    def stub(u, *a, **kw):
        calls.append(u)
        return fake(u)

    m.http_get = stub
    try:
        return m.fetch_jar_ex(url), len(calls)
    finally:
        m.http_get = _real_hg


def judge_verdict(fake, api='csp_XBPQ', classes=None):
    m._JAR_CACHE.clear()

    def stub(u, *a, **kw):
        return fake(u)

    m.http_get = stub
    if classes is not None:
        m.jar_class_names = lambda j: classes
    d = {'api': api, 'name': 't', 'kind': 'csp', 'verdict': '', 'new_api': api,
         'new_ext': None, 'reason': '', 'code': '', 'jar_classes': 0}
    try:
        m._judge_csp(d, {'api': api, 'name': 't'}, api, 't', None, None,
                     'https://x.test/a.jar')
        return d['verdict']
    finally:
        m.http_get = _real_hg
        m.jar_class_names = _real_jcn


def main():
    print('== ① 确认不存在（真阴性）→ dead ==')
    for reason in ('http_404', 'http_410', 'http_401', 'http_403'):
        out, _ = run_fetch(lambda u, r=reason: ('error', None, r))
        check(f'fetch_ex {reason} → dead', out[1] == 'dead', f'out={out}')
    for reason in ('http_404', 'http_410'):
        v = judge_verdict(lambda u, r=reason: ('error', None, r))
        check(f'_judge {reason} → csp_dead', v == 'csp_dead', f'v={v}')

    print('== ② 网络故障（无法判定）→ unknown ==')
    for reason in ('timeout', 'conn', 'dns', 'unknown', 'scheme', 'http_503'):
        out, _ = run_fetch(lambda u, r=reason: ('error', None, r))
        check(f'fetch_ex {reason} → unknown', out[1] == 'unknown', f'out={out}')
    for reason in ('timeout', 'conn', 'http_503'):
        v = judge_verdict(lambda u, r=reason: ('error', None, r))
        check(f'_judge {reason} → csp_jar_unknown', v == 'csp_jar_unknown', f'v={v}')

    print('== ③ SSRF 拦截 → unknown（不硬杀） ==')
    out, _ = run_fetch(lambda u: ('blocked', None, 'ssrf'))
    check('blocked+ssrf → unknown', out[1] == 'unknown', f'out={out}')

    print('== ④ 200 但非 jar（HTML兜底/空）→ dead ==')
    out, _ = run_fetch(lambda u: ('ok', b'<html>404 not found</html>', None))
    check('HTML兜底 → dead', out[1] == 'dead', f'out={out}')
    v = judge_verdict(lambda u: ('ok', b'<html>404 not found</html>', None))
    check('_judge HTML兜底 → csp_dead', v == 'csp_dead', f'v={v}')
    out, _ = run_fetch(lambda u: ('ok', b'', None))
    check('空body → dead', out[1] == 'dead', f'out={out}')

    print('== ⑤ 有效 jar → 类名判定 ==')
    jar = make_jar()
    out, _ = run_fetch(lambda u: ('ok', jar, None))
    check('有效jar → ok', out[0] == jar and out[1] == 'ok', f'out[1]={out[1]}')
    v = judge_verdict(lambda u: ('ok', jar, None), classes=['com.x.spider.XBPQ'])
    check('同名类命中 → csp_ok', v == 'csp_ok', f'v={v}')
    v = judge_verdict(lambda u: ('ok', jar, None), classes=['com.x.spider.Other'])
    check('无同名类 → csp_dead', v == 'csp_dead', f'v={v}')
    v = judge_verdict(lambda u: ('ok', jar, None), classes=[])
    check('解析不出类名 → csp_jar_unknown', v == 'csp_jar_unknown', f'v={v}')

    print('== ⑥ 缓存与向后兼容 ==')
    out1, n1 = run_fetch(lambda u: ('ok', jar, None))
    out2, n2 = run_fetch(lambda u: ('ok', jar, None))
    check('缓存命中次数=1', n1 == 1 and n2 == 1, f'n={n1},{n2}')
    m._JAR_CACHE.clear()
    m.http_get = lambda u, *a, **kw: ('ok', jar, None)
    try:
        check('fetch_jar 仍返回 bytes', m.fetch_jar('https://x.test/a.jar') == jar)
    finally:
        m.http_get = _real_hg

    passed = sum(1 for _, ok in results if ok)
    print(f'\n结果：{passed}/{len(results)} 通过' if passed == len(results)
          else f'\n失败 {len(results) - passed} 项：{[n for n, ok in results if not ok]}')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
