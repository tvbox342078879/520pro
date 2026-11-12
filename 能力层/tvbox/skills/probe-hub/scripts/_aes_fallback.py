#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_aes_fallback.py —— 纯 Python AES-128-CBC 解密兜底（S224·吸收 base(5) base/cipher.pyc）

**为什么需要**：生态第一大坑——羊壳没有 Crypto 库，顶层 `from Crypto.Cipher import AES`
导入失败，**整个源文件挂掉**，分类页全空。正确形态是 try/except 降级，而不是要求装库。

**什么时候用（陷阱库 G 组 + 17.3）**：
  · 用于**小数据**兜底（key/iv 解密、短 JSON 载荷）；
  · **>100KB 必须走 pycryptodome**——纯 Python 解 457KB 需 12~18s，超出壳端图片加载窗口，
    表现为「大图不显示、小图正常」的假象；
  · 只做**解密**，不做加密（写源的唯一用途就是解站点载荷）。

正确用法（照抄这段，不要自己写 except 里的兜底）：
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        def aes_cbc_decrypt(data, key, iv):
            return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(data), 16)
    except ImportError:
        from _aes_fallback import aes_cbc_decrypt   # 纯 Python 兜底

判据（来自壳的 _expand_key 常量）：只支持 **AES-128（16 字节 key）**，这是站点载荷的主流。
key 长度不对必须显式抛错——静默 pad/truncate 会导致解密出乱码而不报错（陷阱库 17.3）。
"""
from __future__ import annotations

# ── AES 核心（GF(2^8)，不可约多项式 0x11B） ──
def _xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _gmul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r


def _build_sbox():
    """现场生成 S-box（起点 99，与壳一致）：用 gmul 求逆 + 仿射变换。"""
    p = q = 1
    sbox = [0] * 256
    while True:
        # p 乘 3，q 除 3（在 GF(2^8) 里 3 的逆是 0xF6）
        p = (p ^ (p << 1) ^ (0x1B if p & 0x80 else 0)) & 0xFF
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) \
            ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


_SBOX = _build_sbox()
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i

_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _expand_key(key):
    """AES-128 密钥扩展：16 字节 → 176 字节（11 轮）。"""
    if len(key) != 16:
        raise ValueError(f'AES-128 需要 16 字节 key，当前 {len(key)}')
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]                      # RotWord
            t = [_SBOX[b] for b in t]              # SubWord
            t[0] ^= _RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _add_round_key(s, w, rnd):
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[rnd * 4 + c][r]


def _inv_shift_rows(s):
    for r in range(1, 4):
        s[r] = s[r][-r:] + s[r][:-r]


def _inv_mix_columns(s):
    for c in range(4):
        a = [s[r][c] for r in range(4)]
        s[0][c] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
        s[1][c] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
        s[2][c] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
        s[3][c] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)


def _decrypt_block(block, w):
    s = [[block[c * 4 + r] for c in range(4)] for r in range(4)]
    _add_round_key(s, w, 10)
    for rnd in range(9, 0, -1):
        _inv_shift_rows(s)
        for r in range(4):
            for c in range(4):
                s[r][c] = _INV_SBOX[s[r][c]]
        _add_round_key(s, w, rnd)
        _inv_mix_columns(s)
    _inv_shift_rows(s)
    for r in range(4):
        for c in range(4):
            s[r][c] = _INV_SBOX[s[r][c]]
    _add_round_key(s, w, 0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def aes_cbc_decrypt(data, key, iv):
    """AES-128-CBC 解密（不 unpad）。data 长度必须是 16 的倍数。"""
    if len(data) % 16:
        raise ValueError(f'密文长度必须是 16 的倍数，当前 {len(data)}')
    if len(iv) != 16:
        raise ValueError(f'IV 必须是 16 字节，当前 {len(iv)}')
    w = _expand_key(key)
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        dec = _decrypt_block(blk, w)
        out.extend(bytes(a ^ b for a, b in zip(dec, prev)))
        prev = blk
    return bytes(out)


def unpad(data, block=16):
    """PKCS#7 去填充。填充不合法时抛错——不静默返回原文（陷阱库 17.3 明令）。"""
    if not data:
        raise ValueError('空数据无法去填充')
    n = data[-1]
    if n == 0 or n > block or data[-n:] != bytes([n]) * n:
        raise ValueError(f'PKCS#7 填充非法（末字节 {n}），多半是 key/iv 错')
    return data[:-n]


def decrypt_bytes(data, key, iv, do_unpad=True):
    """一步到位：解密 + 去填充。**失败抛异常，绝不返回密文**（陷阱库 17.3 头号红线）。"""
    out = aes_cbc_decrypt(data, key, iv)
    return unpad(out) if do_unpad else out


# ── 自检与命令行入口 ──
_NIST_KEY = '2b7e151628aed2a6abf7158809cf4f3c'
_NIST_IV = '000102030405060708090a0b0c0d0e0f'
_NIST_CT = ('7649abac8119b246cee98e9b12e9197d'
            '5086cb9b507219ee95db113a917678b2'
            '73bed6b8e3c1743b7116e69e22229516')
_NIST_PT = ('6bc1bee22e409f96e93d7e117393172a'
            'ae2d8a571e03ac9c9eb76fac45af8e51'
            '30c81c46a35ce411e5fbc1191a0a52ef')

# 交叉校验专用向量：明文带**合法 PKCS#7 填充**（NIST 那条末字节 0xef 不是合法填充，
# 模板版内联去填充会抛错，只能比「抛没抛」，比不出解得对不对——那会假绿）。
# 这条两边都能解密并去填充，结果可直接与明文比对。
_XC_KEY = '00112233445566778899aabbccddeeff'
_XC_IV = '0f0e0d0c0b0a09080706050403020100'
_XC_CT = 'aed0cdfdcce121411801acbec29531953bce205da04764e9a65b704d7632d816'
_XC_PT = b'tvbox aes crosscheck ok'


def _selftest():
    """NIST AES-128-CBC 已知向量——本实现唯一可信的验证方式。"""
    import binascii
    pt = aes_cbc_decrypt(binascii.unhexlify(_NIST_CT),
                         binascii.unhexlify(_NIST_KEY),
                         binascii.unhexlify(_NIST_IV))
    ok = pt == binascii.unhexlify(_NIST_PT)
    print('NIST 向量:', '✅ 通过' if ok else '❌ 失败')
    print('输出:', pt.hex())
    return 0 if ok else 1


def _crosscheck():
    """与 forgekit/_template_src.py 的 AES 片段对账。

    两份实现是同一算法的两种形态（本模块供 import，模板片段供 forge hook 内联进
    单文件源——产物必须自包含，不能 import 外部模块）。形态必须不同，算法核不能漂。
    所以这里只对账两件不依赖接口签名的事：SBOX 逐字节相同、同一密文解出的明文相同。
    找不到 forgekit（单独拷走本文件时）按三态报「无法判定」，不报通过。
    """
    import binascii, importlib.util, os
    here = os.path.dirname(os.path.abspath(__file__))
    tpl = os.path.join(os.path.dirname(here), 'forgekit', '_template_src.py')
    if not os.path.isfile(tpl):
        print(f'无法判定：未找到 {tpl}（本模块可能被单独拷走），不是通过')
        return 2
    spec = importlib.util.spec_from_file_location('_forgekit_template_src', tpl)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, '_aes_cbc_decrypt') or not hasattr(mod, '_build_sbox'):
        print('无法判定：模板里找不到 _aes_cbc_decrypt / _build_sbox，接口已变，需人工核对')
        return 2

    bad = 0
    ok_sbox = _build_sbox() == mod._build_sbox()
    print('SBOX 一致:', '✅' if ok_sbox else '❌ 两份实现已漂移')
    bad += 0 if ok_sbox else 1

    # 比明文，不比「抛没抛错」：用带合法 PKCS#7 填充的固定向量，两边都能解到明文。
    # 早先版本拿 NIST 向量比、只查错误类型，SBOX 改坏时照样报 ✅——那是假绿。
    key = binascii.unhexlify(_XC_KEY)
    iv = binascii.unhexlify(_XC_IV)
    ct = binascii.unhexlify(_XC_CT)
    try:
        mine = decrypt_bytes(ct, key, iv)
    except ValueError as e:
        print(f'❌ 本模块解不开交叉校验向量：{e}')
        return 1
    if mine != _XC_PT:
        print('❌ 本模块解出的明文与预期不符（本模块自身已坏）')
        return 1
    try:
        theirs = mod._aes_cbc_decrypt(ct, key, iv)
        same = theirs == _XC_PT
        print('同密文解密一致:', '✅' if same else '❌ 模板片段解出的明文不同')
    except ValueError as e:
        same = False
        print(f'❌ 模板片段解不开（{e}）——两份实现已漂移')
    bad += 0 if same else 1
    return 0 if bad == 0 else 1


def _decrypt_cli(args):
    """命令行解密：救急用（站点载荷解不开时不必现写脚本）。"""
    import binascii, os
    try:
        key = binascii.unhexlify(args.key)
        iv = binascii.unhexlify(args.iv)
    except (binascii.Error, TypeError) as e:
        print(f'✗ key/iv 必须是十六进制串：{e}')
        return 2
    if len(key) != 16:
        print(f'✗ key 必须是 16 字节（AES-128），当前 {len(key)} 字节——静默 pad/截断会解出乱码不报错')
        return 2

    if args.hex:
        try:
            data = binascii.unhexlify(''.join(args.source.split()))
        except binascii.Error as e:
            print(f'✗ 输入不是合法十六进制：{e}')
            return 2
    else:
        if not os.path.isfile(args.source):
            print(f'✗ 找不到文件：{args.source}')
            return 2
        with open(args.source, 'rb') as f:
            data = f.read()

    if len(data) > 100 * 1024:
        print(f'⚠ 密文 {len(data)/1024:.0f}KB > 100KB：纯 Python 解密会慢到十几秒，'
              f'壳端会表现为「大图不显示、小图正常」，生产请走 pycryptodome')

    try:
        out = decrypt_bytes(data, key, iv, do_unpad=not args.no_unpad)
    except ValueError as e:
        print(f'✗ 解密失败：{e}')
        return 1

    if args.out:
        with open(args.out, 'wb') as f:
            f.write(out)
        print(f'✓ 已写出 {args.out}（{len(out)} 字节）')
        return 0
    if args.raw:
        print(out.hex())
        return 0
    try:
        print(out.decode('utf-8'))
    except UnicodeDecodeError:
        print('（非 UTF-8，按 hex 输出）')
        print(out.hex())
    return 0


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(
        description='纯 Python AES-128-CBC 解密兜底（羊壳无 Crypto 时的降级路径）')
    ap.add_argument('--selftest', action='store_true', help='NIST 向量自检（默认动作）')
    ap.add_argument('--crosscheck', action='store_true',
                    help='与 forgekit/_template_src.py 的 AES 片段对账（防两份实现漂移）')
    ap.add_argument('--decrypt', dest='source', metavar='FILE|HEX',
                    help='要解密的文件路径；配合 --hex 时直接给十六进制串')
    ap.add_argument('--hex', action='store_true', help='输入按十六进制串解析')
    ap.add_argument('--key', metavar='HEX32', help='16 字节 key 的十六进制（AES-128）')
    ap.add_argument('--iv', metavar='HEX32', help='16 字节 IV 的十六进制')
    ap.add_argument('--out', metavar='FILE', help='结果写入文件（默认打印）')
    ap.add_argument('--raw', action='store_true', help='打印 hex 而非尝试 UTF-8')
    ap.add_argument('--no-unpad', action='store_true', help='不去 PKCS#7 填充')
    a = ap.parse_args()

    if a.crosscheck:
        raise SystemExit(_crosscheck())
    if a.source:
        if not a.key or not a.iv:
            ap.error('--decrypt 需要同时给 --key 和 --iv')
        raise SystemExit(_decrypt_cli(a))
    raise SystemExit(_selftest())
