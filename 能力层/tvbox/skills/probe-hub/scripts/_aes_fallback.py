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


if __name__ == '__main__':
    # 自检：用 NIST AES-128-CBC 已知向量验证（本实现唯一可信的验证方式）
    import binascii
    key = binascii.unhexlify('2b7e151628aed2a6abf7158809cf4f3c')
    iv = binascii.unhexlify('000102030405060708090a0b0c0d0e0f')
    ct = binascii.unhexlify(
        '7649abac8119b246cee98e9b12e9197d'
        '5086cb9b507219ee95db113a917678b2'
        '73bed6b8e3c1743b7116e69e22229516')
    pt = aes_cbc_decrypt(ct, key, iv)
    want = binascii.unhexlify(
        '6bc1bee22e409f96e93d7e117393172a'
        'ae2d8a571e03ac9c9eb76fac45af8e51'
        '30c81c46a35ce411e5fbc1191a0a52ef')
    print('NIST 向量:', '✅ 通过' if pt == want else '❌ 失败')
    print('输出:', pt.hex())
    raise SystemExit(0 if pt == want else 1)
