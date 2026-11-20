#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""market_verify.py — 技能市场包完整性校验链（云取借鉴 4+25+47，market-verify 正门）。

四道校验（证据等级：DEX 类名实证 + 转录归纳，方法体未 dump——见 SKILL.md §6）：
  4 索引三重校验：sha256 摘要 + 体积 + Ed25519 签名，按 keyId 找 <keyId>.pub 公钥验签；
    撤销表命中即拒。三项任一失败 → rejected，不静默放行。
  25 schema 版本门控：版本串正则 ^([a-zA-Z]*)(\\d*)$ → (字母前缀, 数字序号)；
    门控比较（同前缀才可比，序号大者新）；格式非法/跨前缀 → unknown，不硬判。
  47 安装失败回滚：本技能只产出回滚决策（rollback_to_previous）；真实的原子写落盘
    由 cred_vault.py:100 已落地的"回滚快照原子写"承担——本技能引用不复制（M2）。

设计：纯函数 + 规则表驱动（keyring/revoked 可注入）；判据喂真样本看输出，不读源码字符串。
三态：verified（全过）/ rejected（明确失败）/ unknown（无法判定，fail-closed 不放行）。
"""
import argparse
import hashlib
import json
import re
import sys

# ── 25 schema 版本正则（转录归纳 DEX ^([a-zA-Z]*)(\d*)$）──
SCHEMA_RE = re.compile(r'^([a-zA-Z]*)(\d*)$')


class InvalidSchema(Exception):
    """版本串格式非法——显式报错，不静默折叠。"""


def parse_schema(version):
    """版本串 → (前缀, 序号)；格式非法抛 InvalidSchema（不硬猜）。"""
    if not isinstance(version, str):
        raise InvalidSchema('版本串必须是字符串：%r' % (version,))
    m = SCHEMA_RE.match(version)
    if not m or (not m.group(1) and not m.group(2)):
        raise InvalidSchema('版本串格式非法：%r' % (version,))
    return (m.group(1), int(m.group(2)) if m.group(2) else 0)


def schema_gate(installed, required):
    """版本门控：required 是否比 installed 新（同前缀才可比）。
    返回 True/False/None（None=无法判定，跨前缀或格式非法，fail-closed）。"""
    try:
        p1, n1 = parse_schema(installed)
        p2, n2 = parse_schema(required)
    except InvalidSchema:
        return None
    if p1 != p2:
        return None
    return n2 > n1


def sha256_hex(data):
    """正文 → sha256 十六进制摘要（bytes 或 str）。"""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def verify_entry(entry, keyring=None, revoked=None):
    """索引条目三重校验（4）：sha256 / 体积 / 签名（按 keyId 找公钥）。
    返回三态 dict：verified / rejected / unknown。
    - keyring: {keyId: 公钥串}；revoked: set(pluginId)——都可注入（判据验表驱动）。
    - 签名用 HMAC-SHA256 作确定性验签代理（标准库无 Ed25519，见 SKILL.md §6 证据等级）。
    - 缺字段 / 公钥缺失 / 格式非法 → unknown（fail-closed，不放行）。
    """
    keyring = {} if keyring is None else keyring
    revoked = set() if revoked is None else revoked
    required = ('plugin_id', 'sha256', 'size', 'signature', 'key_id')
    if not isinstance(entry, dict) or any(k not in entry for k in required):
        return {'status': 'unknown', 'reason': '条目字段缺失', 'plugin_id':
                (entry or {}).get('plugin_id') if isinstance(entry, dict) else None}
    pid = entry['plugin_id']
    if pid in revoked:
        return {'status': 'rejected', 'reason': '公钥/插件已撤销', 'plugin_id': pid}
    pub = keyring.get(entry['key_id'])
    if not pub:
        return {'status': 'unknown', 'reason': '公钥 <keyId>.pub 缺失', 'plugin_id': pid}
    checks = {}
    # ① sha256 摘要
    body = entry.get('body', '')
    checks['sha256'] = (sha256_hex(body) == entry['sha256']) if 'body' in entry else (entry.get('digest_ok') is True)
    # ② 体积
    checks['size'] = (len(body.encode('utf-8') if isinstance(body, str) else body) == entry['size']) if 'body' in entry else (entry.get('size_ok') is True)
    # ③ 签名（HMAC-SHA256 验签代理）
    try:
        import hmac
        sig_src = ('%s|%s|%s' % (pid, entry['sha256'], entry['size'])).encode('utf-8')
        checks['signature'] = hmac.compare_digest(
            hmac.new(str(pub).encode('utf-8'), sig_src, hashlib.sha256).hexdigest(),
            str(entry['signature']))
    except Exception:
        checks['signature'] = False
    failed = [k for k, ok in checks.items() if not ok]
    if failed:
        return {'status': 'rejected', 'reason': '三重校验失败：' + '/'.join(failed),
                'plugin_id': pid, 'checks': checks}
    return {'status': 'verified', 'plugin_id': pid, 'checks': checks}


def rollback_to_previous(current, previous, ok):
    """47 安装失败回滚决策：失败→回上一版；成功→保留新版。
    真实原子写落盘归 cred_vault.py（引用不复制，本函数只产决策）。"""
    if ok:
        return {'status': 'verified', 'action': 'keep', 'active': current}
    if previous is None:
        return {'status': 'unknown', 'action': 'none', 'reason': '无上一版快照可回滚'}
    return {'status': 'rejected', 'action': 'rollback', 'active': previous,
            'reason': '安装失败，回滚上一版（落盘走 cred_vault 原子写）'}


def _self_check():
    pub = 'pub-for-test'
    import hmac
    body = 'hello-market'
    dig = sha256_hex(body)
    sig_src = 'demo|%s|%d' % (dig, len(body))
    sig = hmac.new(pub.encode(), sig_src.encode(), hashlib.sha256).hexdigest()
    e = {'plugin_id': 'demo', 'sha256': dig, 'size': len(body), 'signature': sig,
         'key_id': 'k1', 'body': body}
    ok = (schema_gate('v1', 'v2') is True
          and schema_gate('v2', 'v1') is False
          and schema_gate('a1', 'v2') is None
          and verify_entry(e, {'k1': pub})['status'] == 'verified'
          and verify_entry(e, {'k1': pub}, {'demo'})['status'] == 'rejected'
          and rollback_to_previous('new', 'old', False)['action'] == 'rollback')
    return ok


def main():
    ap = argparse.ArgumentParser(description='技能市场包三重校验（market-verify 正门）')
    ap.add_argument('cmd', nargs='?', help='verify/gate/rollback 或 JSON 文件路径')
    ap.add_argument('--key-id', help='公钥 id')
    ap.add_argument('--pub', help='公钥串（演示用，真实取 <keyId>.pub）')
    ap.add_argument('--revoke', help='撤销的 pluginId（逗号分隔）')
    ap.add_argument('--installed', help='当前版本（gate）')
    ap.add_argument('--required', help='目标版本（gate）')
    ap.add_argument('--selftest', action='store_true', help='自省自检')
    ap.add_argument('--json-out', help='结果写入 JSON 文件')
    a = ap.parse_args()
    if a.selftest:
        ok = _self_check()
        print('SELFTEST %s' % ('OK' if ok else 'FAIL'))
        return 0 if ok else 2
    if a.installed is not None and a.required is not None:
        out = {'installed': a.installed, 'required': a.required,
               'upgrade': schema_gate(a.installed, a.required)}
    elif a.cmd and a.cmd.endswith('.json'):
        with open(a.cmd, encoding='utf-8') as f:
            payload = json.load(f)
        entry = payload.get('entry', payload)
        keyring = {a.key_id: a.pub} if a.key_id and a.pub else payload.get('keyring', {})
        revoked = set(a.revoke.split(',')) if a.revoke else set(payload.get('revoked', []))
        out = verify_entry(entry, keyring, revoked)
    else:
        out = {'status': 'unknown', 'reason': '给 JSON 文件路径或 --installed/--required；--selftest 自检'}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if a.json_out:
        with open(a.json_out, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == '__main__':
    sys.exit(main())
