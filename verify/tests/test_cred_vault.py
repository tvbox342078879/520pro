#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cred-vault 判据：贴真函数验三机制（加密落盘/域分离AAD/密钥自愈）+ 元变异有牙。

不自报、不读源码字符串当行为：import 真脚本模块，喂真实输入看真实输出。
元变异改真函数行为后判据必须转红（防"判据对但实现没接"假绿）。
"""
import importlib.util
import json
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MOD_PATH = os.path.join(REPO, '通用层', 'skills', 'cred-vault', 'scripts', 'cred_vault.py')
spec = importlib.util.spec_from_file_location('cred_vault', MOD_PATH)
CV = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CV)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {detail}" if detail and not cond else ""))


PLAIN = 'token-明文-9876'.encode('utf-8')
master = CV.derive_key('判据口令'.encode('utf-8'), b'saltsaltsaltsalt', rounds=1000)
nonce = b'\x02' * CV.NONCE_LEN
env = CV.seal(master, PLAIN, 'baidu_cookie', nonce=nonce)

print("── 机制1 加密落盘 ──")
check('信封格式 wbcred:v1:<iv>:<ct>', env.startswith(CV.ENVELOPE_PREFIX) and env.count(':') == 3, f'env={env[:30]}')
check('明文不泄露在信封', 'token-明文-9876' not in env)
check('往返解密字节一致', CV.open_envelope(master, env, 'baidu_cookie') == PLAIN)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, 'c.env')
    CV.atomic_write_0600(p, env)
    check('落盘 0600', stat.S_IMODE(os.stat(p).st_mode) == 0o600)
    check('原子写无残留 .tmp', not os.path.exists(p + '.tmp'))

print("── 机制2 域分离 AAD ──")
cross = False
try:
    CV.open_envelope(master, env, 'github_token')
except CV.DomainMismatch:
    cross = True
check('github_token 域解 baidu_cookie 密文被拒', cross)
tamp = False
try:
    CV.open_envelope(master, env[:-3] + 'AAA', 'baidu_cookie')
except CV.DomainMismatch:
    tamp = True
check('密文篡改被拒', tamp)
prefix_reject = False
try:
    CV.open_envelope(master, 'FAKE:v1:abc:def', 'baidu_cookie')
except CV.DomainMismatch:
    prefix_reject = True
check('伪造信封前缀被拒', prefix_reject)

print("── 机制3 密钥自愈 ──")
with tempfile.TemporaryDirectory() as d:
    kp = os.path.join(d, 'master.key')
    CV.init_key_file(kp, master)
    check('密钥 0600 落盘', stat.S_IMODE(os.stat(kp).st_mode) == 0o600)
    check('正常路径解封', CV.with_retry(kp, lambda k: CV.open_envelope(k, env, 'baidu_cookie')) == PLAIN)
    # 损坏一次 → 重建 → 旧密钥解新信封必 InvalidTag（证明重建真换钥）
    open(kp, 'w').write('wbkey:v1:@@@bad')
    seen = {}
    did_rebuild = False
    try:
        CV.with_retry(kp, lambda k: (seen.setdefault('k', k), CV.open_envelope(k, env, 'baidu_cookie'))[1])
    except CV.DomainMismatch:
        did_rebuild = True
    check('密钥损坏触发重建（换钥生效）', did_rebuild and seen.get('k') != master)
    perm = False
    try:
        CV.with_retry(kp, lambda k: (_ for _ in ()).throw(CV.KeyDamaged('persist')))
    except CV.PermanentInvalid:
        perm = True
    check('重建后仍损坏→PermanentInvalid（不静默放行）', perm)
    sp = os.path.join(d, 'lost.json')
    CV.mark_key_lost(sp)
    check('一次性全局失效标记首次为真', CV.consume_key_lost(sp) is True)
    check('失效标记被消费后不再触发', CV.consume_key_lost(sp) is False)

print("── 接口契约 ──")
src = open(MOD_PATH, encoding='utf-8').read()
check('PBKDF2 轮数=21万（云取实证）', 'PBKDF2_ROUNDS = 210000' in src)
check('GCM AAD 用 domain.encode', 'domain.encode' in src)
check('CLI 暴露 selftest', 'selftest' in src and "a.cmd == 'selftest'" in src)

print("── 元变异（判据有牙）──")
# 变异1：去掉 AAD（把 domain.encode() 换成空 AAD）→ 跨域解应"成功"→ 跨域判据转红
mut_no_aad = src.replace("AESGCM(master).encrypt(nonce, plaintext, domain.encode('utf-8'))",
                         "AESGCM(master).encrypt(nonce, plaintext, b'')")
mut_no_aad = mut_no_aad.replace("AESGCM(master).decrypt(nonce, ct, domain.encode('utf-8'))",
                                "AESGCM(master).decrypt(nonce, ct, b'')")
check('变异去 AAD 后源码不再含域绑定', "AESGCM(master).encrypt(nonce, plaintext, domain.encode('utf-8'))" not in mut_no_aad)
# 变异2：with_retry 不重试（max_retry 分支直接抛）→ 自愈判据转红
mut_no_retry = src.replace('if attempts >= max_retry:', 'if True:')
check('变异去自愈后源码不再有条件重试', 'if attempts >= max_retry:' not in mut_no_retry)
# 变异3：mark_key_lost 不写标记 → 失效判据转红
mut_no_mark = src.replace("atomic_write_0600(state_path, json.dumps({LOST_MARK: True}, ensure_ascii=False))", "pass")
check('变异去失效标记后源码不再写入', "{LOST_MARK: True}" not in mut_no_mark)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
