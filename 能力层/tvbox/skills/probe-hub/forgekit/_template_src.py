import json
import re
from urllib.parse import urlparse

PIC_BAD = ('loading', 'placeholder', 'spacer', 'blank.', 'noimage', 'no-image',
           'default_pic', 'defaultpic', '/static/images/', 'data:image')
PIC_PAT = (
    r'data-src="([^"]+)"', r'data-original="([^"]+)"', r'data-background="([^"]+)"',
    r'data-original-src="([^"]+)"', r'poster="([^"]+)"',
    r'background-image:\s*url\([\'"]?([^\'")]+)', r'<img[^>]+src="([^"]+)"',
    r'src="([^"]+)"',
)
STATE_KEYS = ('window.APP_DATA', 'APP_DATA =', '__INITIAL_STATE__', '__NUXT__',
              '__PRELOADED_STATE__', '__APOLLO_STATE__', '__INITIAL_DATA__')
SCORE = (
    (100, frozenset({'player', 'embed', 'm3u8', 'play_url', 'vod_play_url'})),
    (40, frozenset({'video_src', 'file', 'video', 'src'})),
    (25, frozenset({'video_id', 'vid', 'short_id', 'vod_id'})),
    (20, frozenset({'vod_name', 'name', 'title'})),
    (10, frozenset({'image', 'pic', 'cover', 'thumbnail', 'vod_pic'})),
    (5, frozenset({'href', 'url', 'link'})),
)


class Mixin(object):
    def _json_block(self, text, start):
        i = len(text)
        for ch in '{[':
            p = text.find(ch, start)
            if p >= 0:
                i = min(i, p)
        if i >= len(text):
            return None
        op = text[i]
        cl = '}' if op == '{' else ']'
        depth = 0
        q = None
        esc = False
        for j in range(i, len(text)):
            c = text[j]
            if q:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == q:
                    q = None
                continue
            if c in '"\'':
                q = c
            elif c == op:
                depth += 1
            elif c == cl:
                depth -= 1
                if depth == 0:
                    return text[i:j + 1]
        return None

    def _inline_state(self, html):
        for key in STATE_KEYS:
            p = html.find(key)
            if p < 0:
                continue
            raw = self._json_block(html, p + len(key))
            if not raw:
                continue
            try:
                return json.loads(raw)
            except Exception:
                continue
        return None

    def _inline_arrays(self, node, depth=0):
        out = []
        if depth > 5:
            return out
        if isinstance(node, list):
            if node and isinstance(node[0], dict):
                out.append(node)
            for v in node:
                out.extend(self._inline_arrays(v, depth + 1))
        elif isinstance(node, dict):
            for v in node.values():
                out.extend(self._inline_arrays(v, depth + 1))
        return out

    def _inline_score(self, item):
        s = 0
        ks = set(item)
        for val, group in SCORE:
            if ks & group:
                s += val
        return s

    def _inline_walk(self, node, depth=0):
        best = None
        best_k = (0, 0)
        for arr in self._inline_arrays(node, depth):
            if not arr:
                continue
            sc = self._inline_score(arr[0])
            k = (sc, len(arr))
            if k > best_k:
                best, best_k = arr, k
        return best or []

    def _inline_items(self, html):
        st = None
        try:
            st = self._inline_state(html)
        except Exception:
            st = None
        if st is None:
            return []
        return self._inline_walk(st)

    def _pic(self, s):
        if not s:
            return ''
        for pat in PIC_PAT:
            m = re.search(pat, s, re.I)
            if not m:
                continue
            u = (m.group(1) or '').strip()
            low = u.lower()
            if not u or any(b in low for b in PIC_BAD):
                continue
            if u.startswith('data:'):
                continue
            if u.startswith('//'):
                u = 'https:' + u
            elif u.startswith('/'):
                u = (getattr(self, 'host', '') or '') + u
            return u.rstrip('/')
        return ''

    def _play_groups(self, html, tpl):
        out = {}
        if not html or not tpl:
            return out
        for m in re.finditer(tpl, html):
            sid = int(m.group(2) or 0)
            nid = int(m.group(3) or 0)
            u = m.group(1).rstrip()
            if u.startswith('/'):
                u = (getattr(self, 'host', '') or '') + u
            if not u.startswith('http'):
                continue
            out.setdefault(sid, {}).setdefault(nid, u)
        return out

    def _play_build(self, groups, label='线路'):
        def _k(x):
            s = str(x)
            return (0, int(s)) if s.isdigit() else (1, s)
        froms, urls = [], []
        for i, sid in enumerate(sorted(groups, key=_k)):
            eps = groups[sid]
            items = []
            nids = sorted(eps, key=_k)
            single = len(nids) == 1
            for nid in nids:
                name = '正片' if single else '第%02d集' % int(nid)
                items.append('%s$%s' % (name, eps[nid]))
            froms.append('%s%d' % (label, i + 1))
            urls.append('#'.join(items))
        return '$$$'.join(froms), '$$$'.join(urls)

    def _norm_flag(self, name):
        s = re.sub(r'\s+', '', name or '').lower()
        for canon, alias in FLAGS:
            for a in alias:
                if s == a or s.startswith(a):
                    return canon
        return (name or '').strip()

    def _fix_url(self, base, u):
        u = (u or '').strip()
        if not u:
            return ''
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('http'):
            return u
        if u.startswith('/'):
            return (base or '').rstrip('/') + u
        return (base or '').rstrip('/') + '/' + u

    def _aes_decrypt(self, data, key, iv):
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import unpad
            return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(data), 16)
        except ImportError:
            return _aes_cbc_decrypt(data, key, iv)
        except Exception:
            return _aes_cbc_decrypt(data, key, iv)


def _build_sbox():
    p = q = 1
    sbox = [0] * 256
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
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
_INV = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV[_v] = _i
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _gmul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return r


def _expand_key(key):
    if len(key) not in (16, 24, 32):
        raise ValueError('AES key 必须 16/24/32 字节，当前 %d' % len(key))
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _decrypt_block(block, w, nr):
    # ★ 状态矩阵必须按「列优先」铺：state[r][c] = block[4c+r]。
    #   写 block[i::4] 得到的其实是行优先 → 每 4 字节被分到错误的格子里，
    #   密钥扩展本身是对的（w[43]=b6630ca6 校验通过），但解密结果全错。
    s = [[block[c * 4 + r] for c in range(4)] for r in range(4)]
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[(nr * 4 + c)][r]
    for rnd in range(nr - 1, -1, -1):
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]
        for r in range(4):
            for c in range(4):
                s[r][c] = _INV[s[r][c]]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]
        if rnd:
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
                s[1][c] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
                s[2][c] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
                s[3][c] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _aes_cbc_decrypt(data, key, iv):
    if len(data) % 16:
        raise ValueError('密文长度 %d 不是 16 的倍数' % len(data))
    w, nr = _expand_key(key)
    prev = list(iv)
    out = bytearray()
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        dec = _decrypt_block(blk, w, nr)
        out.extend(bytes(dec[j] ^ prev[j] for j in range(16)))
        prev = list(blk)
    pad = out[-1]
    if not 1 <= pad <= 16 or out[-pad:] != bytes([pad]) * pad:
        raise ValueError('PKCS7 填充非法，key/iv 可能不对')
    return bytes(out[:-pad])


FLAGS = (
    ('youku', ('youku', '优酷')),
    ('qq', ('qq', '腾讯')),
    ('iqiyi', ('iqiyi', 'qiyi', '奇艺', '爱奇艺')),
    ('m1905', ('m1905',)),
    ('xigua', ('xigua',)),
    ('letv', ('letv', 'leshi', '乐视')),
    ('sohu', ('sohu', '搜狐')),
    ('tudou', ('tudou',)),
    ('pptv', ('pptv',)),
    ('mgtv', ('mgtv', '芒果', 'imgo')),
    ('bilibili', ('bilibili', '哔哩')),
)
