#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_market_verify.py — market-verify 判据（云取 4+25+47）。

五层（病15 防御：喂真函数看真输出）：
  A 结构层：正门存在 + 有 parse_schema/schema_gate/sha256_hex/verify_entry/rollback_to_previous。
  B schema 门控层：同前缀序号大者 True；小者 False；跨前缀/非法 → None（fail-closed）。
  C 三重校验层：sha256/体积/签名三项全过 verified；逐项改坏 → rejected；撤销 → rejected。
  D 回滚层：失败→上一版；成功→保留；无快照→unknown。
  E 元变异有牙：①注入 keyring/revoked 验表驱动（非背答案）；②改坏签名 → rejected；
    ③字段缺失 → unknown 不放行；④改坏 schema 正则 → 门控真转 None。
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MOD = os.path.join(REPO, '通用层', 'skills', 'market-verify', 'scripts', 'market_verify.py')

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else '  ← ' + str(detail)))


spec = importlib.util.spec_from_file_location('market_verify_mod', MOD)
M = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(M)
    loaded = True
except Exception as ex:
    loaded = False
    check('模块加载', False, repr(ex))

if loaded:
    import hmac
    PUB = 'pub-key-k1'
    BODY = 'skill-package-body-v1'
    DIG = M.sha256_hex(BODY)
    SIG_SRC = 'demo|%s|%d' % (DIG, len(BODY))
    SIG = hmac.new(PUB.encode(), SIG_SRC.encode(), __import__('hashlib').sha256).hexdigest()
    GOOD = {'plugin_id': 'demo', 'sha256': DIG, 'size': len(BODY),
            'signature': SIG, 'key_id': 'k1', 'body': BODY}

    # A 结构层
    check('A 正门 market_verify.py 存在', os.path.isfile(MOD))
    for fn in ('parse_schema', 'schema_gate', 'sha256_hex', 'verify_entry', 'rollback_to_previous'):
        check(f'A 函数 {fn}', callable(getattr(M, fn, None)))

    # B schema 门控层
    check('B 同前缀新版本 → True', M.schema_gate('v1', 'v2') is True)
    check('B 同前缀旧版本 → False', M.schema_gate('v2', 'v1') is False)
    check('B 版本号数值比较(v9→v10)', M.schema_gate('v9', 'v10') is True)
    check('B 跨前缀 → None（无法判定）', M.schema_gate('a1', 'v2') is None)
    check('B 非法版本串 → None', M.schema_gate('v1.x', 'v2') is None)
    try:
        M.parse_schema('bad!')
        check('B 非法版本串 parse 抛异常', False, '没抛')
    except M.InvalidSchema:
        check('B 非法版本串 parse 抛异常', True)

    # C 三重校验层
    r = M.verify_entry(GOOD, {'k1': PUB})
    check('C 三项全过 → verified', r['status'] == 'verified', r)
    check('C 三检查项全 True', all(r.get('checks', {}).values()), r)
    bad_dig = dict(GOOD, sha256='0' * 64)
    check('C 改坏 sha256 → rejected', M.verify_entry(bad_dig, {'k1': PUB})['status'] == 'rejected')
    bad_size = dict(GOOD, size=999)
    check('C 改坏体积 → rejected', M.verify_entry(bad_size, {'k1': PUB})['status'] == 'rejected')
    bad_sig = dict(GOOD, signature='f' * 64)
    check('C 改坏签名 → rejected', M.verify_entry(bad_sig, {'k1': PUB})['status'] == 'rejected')
    check('C 撤销表命中 → rejected',
          M.verify_entry(GOOD, {'k1': PUB}, {'demo'})['status'] == 'rejected')
    check('C 公钥缺失 → unknown（fail-closed）',
          M.verify_entry(GOOD, {})['status'] == 'unknown')

    # D 回滚层
    check('D 失败 → rollback 上一版', M.rollback_to_previous('new', 'old', False)['active'] == 'old')
    check('D 成功 → keep 新版', M.rollback_to_previous('new', 'old', True)['active'] == 'new')
    check('D 无快照 → unknown', M.rollback_to_previous('new', None, False)['status'] == 'unknown')

    # E 元变异有牙
    # ① 注入 keyring——换公钥后原签名不再通过（验真读注入表，非背答案）
    check('E① 换公钥 → 签名失败 rejected',
          M.verify_entry(GOOD, {'k1': 'wrong-pub'})['status'] == 'rejected')
    # ② 注入自定义撤销表——不同 pluginId 不受影响
    check('E② 撤销表注其他 id → 仍 verified',
          M.verify_entry(GOOD, {'k1': PUB}, {'other-plugin'})['status'] == 'verified')
    # ③ 字段缺失 → unknown（不抛崩、不放行）
    check('E③ 缺字段 → unknown（不抛崩）',
          M.verify_entry({'plugin_id': 'demo'}, {'k1': PUB})['status'] == 'unknown')
    # ④ 改坏 schema 正则对象 → 门控真变（验函数真用 SCHEMA_RE，非硬编码结果）
    import re
    orig_re = M.SCHEMA_RE
    try:
        M.SCHEMA_RE = re.compile(r'^(x)(\d*)$')  # 只认 x 前缀
        check('E④ 改坏 schema 正则 → v1/v2 门控转 None', M.schema_gate('v1', 'v2') is None)
    finally:
        M.SCHEMA_RE = orig_re
    check('E④b 还原正则后门控恢复 True', M.schema_gate('v1', 'v2') is True)

print(f'\n=== test_market_verify: {len(PASS)}✓ / {len(FAIL)}✗ ===')
if FAIL:
    for f in FAIL:
        print('  FAIL:', f)
    raise SystemExit(1)
print('ALL PASS')
