#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凭证安全正门（cred-vault/凭证司）—— 云取 YunGet 借鉴机制 39·22·2 / 41 / 40·30。

三机制（全部纯函数，依赖注入便于判据贴真函数、不靠读源码字符串）：
  1. 加密落盘 seal：AES-GCM tag128 + 信封 wbcred:v1:<b64IV>:<b64CT>，PBKDF2 21万轮派生密钥，0600 落盘。
  2. 域分离 AAD：domain（如 baidu_cookie / github_token）作 updateAAD，跨域解必失败（防密文跨字段重放）。
  3. 密钥自愈 with_retry：密钥条目损坏（AEADBadTag/格式坏）→ 删条目重建重试一次 → 再败抛 PermanentInvalid；
     mark_key_lost / consume_key_lost 一次性全局失效标记（轮换后旧密文全失效，不逐字段试错）。

主密钥不入库、不硬编码：从 --passphrase-env 指定的环境变量运行时注入（零明文凭证 B-05），
或从 0600 key 文件读随机 32B 主密钥。明文只在内存；所有输出 0600。
"""
import argparse
import base64
import hashlib
import json
import os
import stat
import sys

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
except ImportError as _e:  # 缺库不静默：明确无法判定，不假绿
    AESGCM = None
    _IMPORT_ERR = str(_e)
else:
    _IMPORT_ERR = ''

ENV_PREFIX = 'WB_CRED_'
ENVELOPE_PREFIX = 'wbcred:v1:'
KEY_PREFIX = 'wbkey:v1:'
PBKDF2_ROUNDS = 210000          # 云取 AuthCrypto 实证 21 万轮
NONCE_LEN = 12                  # GCM 标准 12B IV
KEY_LEN = 32                    # AES-256
SALT_LEN = 16
LOST_MARK = 'credential_key_lost'


class CredError(Exception):
    """凭证层异常基类。"""


class DomainMismatch(CredError):
    """域不匹配 / 密文被篡改 / 密钥错（AES-GCM 统一表现为 InvalidTag）。"""


class KeyDamaged(CredError):
    """密钥条目损坏（可恢复：删条目重建重试）。"""


class PermanentInvalid(CredError):
    """重建后仍失败（不可恢复：停止，不静默放行）。"""


# ── 机制 1+2：加密落盘 + 域分离 AAD ──────────────────────────────
def derive_key(passphrase: bytes, salt: bytes, rounds: int = PBKDF2_ROUNDS) -> bytes:
    """PBKDF2-HMAC-SHA256 派生 256bit 主密钥（云取 21 万轮实证）。"""
    if AESGCM is None:
        raise CredError('cryptography 不可用：' + _IMPORT_ERR)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=KEY_LEN,
                    salt=salt, iterations=rounds)
    return kdf.derive(passphrase)


def seal(master: bytes, plaintext: bytes, domain: str, nonce: bytes = None) -> str:
    """AES-GCM 封装；domain 作 AAD 实现域分离。返回信封字符串。"""
    if AESGCM is None:
        raise CredError('cryptography 不可用：' + _IMPORT_ERR)
    if not domain or not isinstance(domain, str):
        raise CredError('domain 必须是非空字符串（AAD 域分离不可省略）')
    nonce = nonce or os.urandom(NONCE_LEN)
    if len(nonce) != NONCE_LEN:
        raise CredError(f'nonce 长度 {len(nonce)}≠{NONCE_LEN}')
    ct = AESGCM(master).encrypt(nonce, plaintext, domain.encode('utf-8'))
    return ENVELOPE_PREFIX + base64.b64encode(nonce).decode() + ':' + base64.b64encode(ct).decode()


def open_envelope(master: bytes, envelope: str, domain: str) -> bytes:
    """解封；跨域/篡改/错密钥统一抛 DomainMismatch（不泄露哪一种）。"""
    if AESGCM is None:
        raise CredError('cryptography 不可用：' + _IMPORT_ERR)
    if not envelope.startswith(ENVELOPE_PREFIX):
        raise DomainMismatch('信封前缀不符（非本凭证格式）')
    try:
        b64n, b64c = envelope[len(ENVELOPE_PREFIX):].split(':')
        nonce = base64.b64decode(b64n)
        ct = base64.b64decode(b64c)
    except Exception:
        raise DomainMismatch('信封解码失败')
    try:
        return AESGCM(master).decrypt(nonce, ct, domain.encode('utf-8'))
    except Exception:
        raise DomainMismatch('域不匹配 / 密文被篡改 / 密钥错（AES-GCM InvalidTag）')


def atomic_write_0600(path: str, content: str):
    """临时文件 + 原子 rename + 0600（云取 47 回滚快照原子写借鉴）。"""
    d = os.path.dirname(os.path.abspath(path)) or '.'
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


# ── 机制 3：密钥自愈 + 一次性全局失效标记 ────────────────────────
def load_key_file(path: str) -> bytes:
    """读 0600 主密钥文件；损坏（格式/长度错）抛 KeyDamaged。"""
    try:
        raw = open(path, encoding='utf-8').read().strip()
    except FileNotFoundError:
        raise KeyDamaged('密钥文件不存在')
    if not raw.startswith(KEY_PREFIX):
        raise KeyDamaged('密钥文件格式不符（前缀错）')
    try:
        key = base64.b64decode(raw[len(KEY_PREFIX):])
    except Exception:
        raise KeyDamaged('密钥文件 base64 损坏')
    if len(key) != KEY_LEN:
        raise KeyDamaged(f'密钥长度 {len(key)}≠{KEY_LEN}')
    return key


def init_key_file(path: str, key: bytes = None) -> bytes:
    """生成并 0600 落盘主密钥；返回 key。"""
    key = key or os.urandom(KEY_LEN)
    if len(key) != KEY_LEN:
        raise CredError(f'主密钥长度 {len(key)}≠{KEY_LEN}')
    atomic_write_0600(path, KEY_PREFIX + base64.b64encode(key).decode())
    return key


def with_retry(key_path: str, op, max_retry: int = 1):
    """密钥损坏→删条目重建→重试一次；再败抛 PermanentInvalid（云取 41 实证）。"""
    attempts = 0
    while True:
        try:
            key = load_key_file(key_path)
            return op(key)
        except KeyDamaged:
            if attempts >= max_retry:
                raise PermanentInvalid('密钥重建后仍失败，停止（不静默放行）')
            attempts += 1
            try:
                os.remove(key_path)
            except FileNotFoundError:
                pass
            init_key_file(key_path)   # 重建新密钥；旧密文随之失效（见 mark_key_lost）


def mark_key_lost(state_path: str):
    """一次性全局失效标记，commit 语义（同步写）。"""
    atomic_write_0600(state_path, json.dumps({LOST_MARK: True}, ensure_ascii=False))


def consume_key_lost(state_path: str) -> bool:
    """读并清除一次性标记；读不到/损坏按 False（无失效通知）。"""
    try:
        d = json.load(open(state_path, encoding='utf-8'))
    except Exception:
        return False
    lost = bool(d.get(LOST_MARK))
    if lost:
        try:
            os.remove(state_path)
        except OSError:
            pass
    return lost


# ── selftest：正反全过才落地（S-03）──────────────────────────────
def selftest() -> int:
    import tempfile
    P, F = [], []

    def ck(n, c, d=''):
        (P if c else F).append(n)
        print(f"  {'✓' if c else '✗'} {n}" + (f" — {d}" if d and not c else ''))

    print('── 机制1 加密落盘 ──')
    master = derive_key(b'test-pass', b'0' * SALT_LEN, rounds=1000)
    nonce = b'\x01' * NONCE_LEN
    env = seal(master, b'secret-token-1234', 'baidu_cookie', nonce=nonce)
    ck('信封前缀 wbcred:v1', env.startswith(ENVELOPE_PREFIX), env[:20])
    ck('明文不出现在信封', b'secret-token-1234'.decode() not in env)
    ck('往返解密一致', open_envelope(master, env, 'baidu_cookie') == b'secret-token-1234')

    print('── 机制2 域分离 AAD ──')
    cross_fail = False
    try:
        open_envelope(master, env, 'github_token')
    except DomainMismatch:
        cross_fail = True
    ck('跨域解密被拒（github_token≠baidu_cookie）', cross_fail)
    tampered = env[:-2] + ('AA' if env[-2:] != 'AA' else 'BB')
    tamp_fail = False
    try:
        open_envelope(master, tampered, 'baidu_cookie')
    except DomainMismatch:
        tamp_fail = True
    ck('密文篡改被拒', tamp_fail)

    print('── 机制3 密钥自愈 ──')
    with tempfile.TemporaryDirectory() as d:
        kp = os.path.join(d, 'master.key')
        init_key_file(kp, master)
        ck('密钥文件 0600', stat.S_IMODE(os.stat(kp).st_mode) == 0o600)
        # 正常路径
        got = with_retry(kp, lambda k: open_envelope(k, env, 'baidu_cookie'))
        ck('正常路径解封', got == b'secret-token-1234')
        # 损坏一次 → 重建 → 重试（此时 op 用新密钥解旧密文必失败，证明重建真发生）
        with open(kp, 'w') as f:
            f.write('wbkey:v1:BROKEN!!!')
        newkey_holder = {}

        def op_after_rebuild(k):
            newkey_holder['k'] = k
            return open_envelope(k, env, 'baidu_cookie')

        rebuilt = False
        try:
            with_retry(kp, op_after_rebuild)
        except DomainMismatch:
            rebuilt = True       # 新密钥解旧密文→InvalidTag，说明重建生效
        ck('密钥损坏触发重建（新密钥≠旧密钥）', rebuilt and newkey_holder.get('k') != master)
        # 永久失效：op 恒抛 KeyDamaged → 重建一次仍抛 → PermanentInvalid
        perm = False
        try:
            with_retry(kp, lambda k: (_ for _ in ()).throw(KeyDamaged('always')))
        except PermanentInvalid:
            perm = True
        ck('重建后仍损坏→PermanentInvalid', perm)
        # 一次性失效标记
        sp = os.path.join(d, 'lost.json')
        ck('初始无失效标记', consume_key_lost(sp) is False)
        mark_key_lost(sp)
        ck('mark 后有一次失效标记', consume_key_lost(sp) is True)
        ck('标记一次性消费', consume_key_lost(sp) is False)

    print('── 三态：缺库不假绿 ──')
    ck('cryptography 可用', AESGCM is not None, _IMPORT_ERR)

    print(f'\n{len(P)} passed, {len(F)} failed')
    return 1 if F else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='凭证安全正门：加密落盘/域分离AAD/密钥自愈')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('key-init', help='生成 0600 主密钥')
    p.add_argument('--key', required=True, help='主密钥文件路径（仓库外 0600）')

    p = sub.add_parser('seal', help='加密一段明文/文件为信封')
    p.add_argument('--domain', required=True, help='AAD 域（如 baidu_cookie）')
    p.add_argument('--text', help='明文字符串（与 --file 二选一）')
    p.add_argument('--file', help='明文文件路径')
    p.add_argument('--key', help='主密钥文件（与 --passphrase-env 二选一）')
    p.add_argument('--passphrase-env', help='口令环境变量名（运行时注入，零明文）')
    p.add_argument('--out', help='密文输出文件（默认 stdout）')

    p = sub.add_parser('open', help='解密信封')
    p.add_argument('--domain', required=True)
    p.add_argument('--file', help='密文文件（与 --text 二选一）')
    p.add_argument('--text', help='信封字符串')
    p.add_argument('--key')
    p.add_argument('--passphrase-env')
    p.add_argument('--out', help='明文输出文件（0600，默认 stdout）')

    p = sub.add_parser('key-status', help='密钥状态三态')
    p.add_argument('--key', required=True)

    sub.add_parser('selftest', help='三机制正反自检')

    a = ap.parse_args(argv)
    if a.cmd == 'selftest':
        return selftest()

    if a.cmd == 'key-init':
        try:
            k = init_key_file(a.key)
            print(f'密钥已生成（{len(k)}B，0600）: {a.key}')
            return 0
        except CredError as e:
            print(f'✗ {e}', file=sys.stderr)
            return 2

    if a.cmd == 'key-status':
        try:
            load_key_file(a.key)
            print('OK: 密钥在位且格式正确')
            return 0
        except KeyDamaged as e:
            print(f'DAMAGED: {e}', file=sys.stderr)
            return 2

    # seal / open
    def get_master():
        if a.passphrase_env:
            pw = os.environ.get(a.passphrase_env)
            if not pw:
                raise CredError(f'环境变量 {a.passphrase_env} 未设置（零明文凭证：口令须运行时注入）')
            raw = open(a.file, encoding='utf-8').read() if a.cmd == 'open' and a.file else ''
            # 口令模式：salt 固定派生（信封不含 salt，因口令由调用方安全管理）
            return derive_key(pw.encode(), b'cred-vault-salt')
        if a.key:
            return with_retry(a.key, lambda k: k)
        raise CredError('须指定 --key 或 --passphrase-env')

    try:
        master = get_master()
        if a.cmd == 'seal':
            if a.text is not None:
                data = a.text.encode()
            elif a.file:
                data = open(a.file, 'rb').read()
            else:
                raise CredError('seal 须给 --text 或 --file')
            env = seal(master, data, a.domain)
            if a.out:
                atomic_write_0600(a.out, env)
                print(f'已加密 → {a.out}（0600，{len(env)}B）')
            else:
                print(env)
            return 0
        else:  # open
            env = a.text if a.text is not None else (open(a.file, encoding='utf-8').read() if a.file else '')
            if not env:
                raise CredError('open 须给 --text 或 --file')
            data = open_envelope(master, env.strip(), a.domain)
            if a.out:
                tmp = a.out + '.tmp'
                with open(tmp, 'wb') as f:
                    f.write(data)
                os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
                os.replace(tmp, a.out)
                print(f'已解密 → {a.out}（0600，{len(data)}B）')
            else:
                sys.stdout.buffer.write(data)
            return 0
    except CredError as e:
        print(f'✗ {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
