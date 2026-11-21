#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_fetch_tristate.py — _fetch 三态归类判据（S234·病15 三态折叠修复）

【为什么需要】
2026-11-22 重采试点 10 仓实测：5 仓 scan rc=2「全部候选拉取失败＝网络问题」，
耗时 112–150s 白等；但独立 tree/API 诊断铁证显示 API 全 HTTP 200、仓库无配置文件。
根因：core.http_get 在 err_body=False 下对 HTTP 404/410 返回
  ('error', None, 'http_404')——状态码只在 reason、payload 为 None；
而旧 _fetch 只认 st=='ok' 的 (code,body)，把"文件不存在"(notfound/真阴性)
折叠成"拉取失败"(fail)→ 重试全部镜像（28.8s/候选）→ scan 误报 rc=2。

判据源（唯一真源）：能力层/tvbox/skills/probe-hub/scripts/probe.py#_fetch
本测试锁死：error+http_404/410→notfound 且早退不重试；其余 error 仍 fail。
退出码：0 全通 / 1 有用例不符。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('probe_ts', os.path.join(HERE, 'probe.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

fails = []
def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)

_g = globals() if False else p.__dict__
_real_hg = _g['http_get']


def run_with(fake, url='https://raw.githubusercontent.com/o/r/main/x.json', timeout=6):
    """替 http_get 后跑 _fetch，返回 (state, text, 调用次数)。"""
    calls = []
    def stub(u, *a, **kw):
        calls.append(u)
        return fake(u)
    _g['http_get'] = stub
    try:
        st, txt = p._fetch(url, timeout=timeout)
        return st, txt, len(calls)
    finally:
        _g['http_get'] = _real_hg


def main():
    print('== ① 新分支：error+http_404 → notfound，早退不重试 ==')
    st, _, n = run_with(lambda u: ('error', None, 'http_404'))
    check('error+http_404 → notfound', st == 'notfound', f'st={st}')
    check('404 早退（不重试镜像，调用=1）', n == 1, f'calls={n}')

    st, _, n = run_with(lambda u: ('error', None, 'http_410'))
    check('error+http_410 → notfound', st == 'notfound', f'st={st}')

    print('== ② 旧分支不回归 ==')
    st, _, _ = run_with(lambda u: ('ok', (404, '404: Not Found'), None))
    check('ok+(404,body) → notfound（旧路径保留）', st == 'notfound', f'st={st}')
    st, _, _ = run_with(lambda u: ('ok', (200, '{"sites":[]}'), None))
    check('ok+(200,body) → ok', st == 'ok', f'st={st}')
    st, _, _ = run_with(lambda u: ('ok', (500, 'err'), None))
    check('ok+(500,...) → fail', st == 'fail', f'st={st}')

    print('== ③ 真网络故障仍 fail，不得冒充 notfound ==')
    for reason in ('conn', 'timeout', 'dns', 'http_503'):
        st, _, _ = run_with(lambda u, r=reason: ('error', None, r))
        check(f'error+{reason} → fail', st == 'fail', f'st={st}')

    print(f'\n结果：{16 - len(fails)}/16 通过' if not fails else f'\n失败 {len(fails)} 项：{fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
