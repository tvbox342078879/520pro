#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网盘取料 pan —— 分享清单 / 下载 / 转存 / 删除

来历：原属探源司 `probe.py harvest pan`（L8464-9653，S170/S197/S218 建设），现独立为本文件，
2026-11-12 迁入 learn-hub。理由：网盘取料与 TVBox 业务零耦合，而 learn-hub 的
`intake` 职责本来就写着「网盘资料」——它才是这份代码的正确归属。

独立运行，**不依赖 tvbox-core**：http_get 已内联（原 core.py::http_get M-R213）。
凭证全部来自本地文件，零明文入库：
    ~/.codebuddy/.quark_cookie   ~/.codebuddy/.uc_cookie
    ~/.codebuddy/.xunlei_cookie  ~/.codebuddy/.xunlei_token
    ~/.codebuddy/.baidu_cookie

三态纪律（与探源司同源，不许折叠）：
    取到了 / 确定取不到（404·已删·明确拒绝）/ 无法判定（超时·412·登录墙·出口被 CDN 拒）
    机房 IP 被 CDN 拒 ≠ 文件不存在 ≠ 代码坏了。清单拿到就说明东西在。

用法：
    python3 pan.py info  --url https://pan.quark.cn/s/<id>
    python3 pan.py pull  --url <链接> --match <子串> --outdir <目录>
    python3 pan.py save  --url <链接> --to 0
    python3 pan.py rm    --match <子串>            # 预演
    python3 pan.py rm    --match <子串> --yes      # 真删
"""
import argparse
import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlparse, urlsplit
import urllib.error
import urllib.request

# ══════════════════ http_get（内联自 core.py::http_get，M-R213 单一事实源）══════════════════
def http_get(url, timeout=15, ua=None, max_bytes=None, as_text=True,
             headers=None, method='GET', data=None, ssl_verify=True,
             return_status=False, err_body=False):
    """统一 HTTP 取数入口（M-R38 单一事实源 / M-R213 共享核心）。

    带 SSRF 防护（拦截私有/环回/链路本地/保留/组播地址，含 169.254.169.254 元数据）、
    超时、三态返回。纯新增函数，零影响现有调用（core 原无 http 能力）。
    返回 (status, payload, reason)：
      ok      -> ('ok', bytes/str 或 (status, payload), None)
      blocked -> ('blocked', None, 'ssrf')   # 命中内网/元数据
      error   -> ('error', None, 'dns'|'scheme'|'timeout'|'conn'|'http_<code>'|'unknown')
    新增参数（向后兼容，不传=与原行为一致）：
      headers       追加/覆盖请求头（如 Referer），与默认 UA 合并
      method/data   支持非 GET 请求
      ssl_verify    False 时跳过证书校验（spider_verify 等内网自签场景）
      return_status True 时 payload 改为 (http_status, payload) 元组
      err_body      True 时 HTTP 错误（非 2xx）payload 改为 (code, 错误正文)，
                    供调用方保留服务端排障信息（默认不读错误体，行为不变）
    """
    import ipaddress
    import socket
    import ssl as _ssl
    import urllib.request
    import urllib.error
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return ('error', None, 'scheme')
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        try:
            infos = socket.getaddrinfo(host, port)
        except Exception:
            return ('error', None, 'dns')
        for info in infos:
            ip = info[4][0]
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if (addr.is_private or addr.is_loopback or addr.is_link_local
                    or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
                return ('blocked', None, 'ssrf')
        hdrs = {'User-Agent': ua or 'Mozilla/5.0 (TVBox-core)'}
        if headers:
            hdrs.update(headers)
        ctx = None
        if parsed.scheme == 'https' and not ssl_verify:
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            status = getattr(resp, 'status', 200)
            data = resp.read() if max_bytes is None else resp.read(max_bytes)
        if as_text:
            try:
                data = data.decode('utf-8', 'replace')
            except Exception:
                pass
        payload = (status, data) if return_status else data
        return ('ok', payload, None)
    except urllib.error.HTTPError as e:
        if err_body:
            try:
                _b = e.read()
                if as_text:
                    _b = _b.decode('utf-8', 'replace')
            except Exception:
                _b = None
            return ('error', (e.code, _b), 'http_%d' % e.code)
        return ('error', None, 'http_%d' % e.code)
    except urllib.error.URLError as e:
        if isinstance(getattr(e, 'reason', None), socket.timeout):
            return ('error', None, 'timeout')
        return ('error', None, 'conn')
    except Exception:
        return ('error', None, 'unknown')


PAN_API = 'https://drive-pc.quark.cn'
# S197 扩 UC 网盘（drive.uc.cn）：与夸克同 API 体系（阿里系），接口路径一致，
# 差异只在域名 / pr 参数 / Referer。UC 的 pr 值实测验证，不对再按三态调整。
PAN_PLATFORMS = {
    'quark': {'api': 'https://drive-pc.quark.cn', 'referer': 'https://pan.quark.cn/', 'pr': 'ucpro'},
    'uc':    {'api': 'https://pc-api.uc.cn',     'referer': 'https://drive.uc.cn/', 'pr': 'UCBrowser'},
    'xunlei':{'api': 'https://api-pan.xunlei.com', 'referer': 'https://pan.xunlei.com/', 'pr': ''},
}
#   ⚠️ UC 下载 403 坏法清单（S197 实测，真实分享 4bb62a7a8e794）：
#     · API 全通：token/detail/直链签发都成功（pc-api.uc.cn 不拒机房 IP）；
#     · 下载 CDN（dl-uf-sz.pds.uc.cn）→ 18/18 全 403；
#     · 对照实验 5 组头全 403（无Referer/UC Referer/api来源页/默认UA/Range）→ 拦截与请求头无关；
#     · 结论：与夸克 412 同构——**下载 CDN 按出口 IP 段拒绝机房网络**，归「无法判定·出口被拒」，
#       不是文件坏、不是 token 错。处置同夸克：换出口网络或用户手动下载，不许记「源失效」。
PAN_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def _pan_req(path, data=None, timeout=30, platform='quark', cookie=None):
    """调分享 API（夸克/UC）。返回 (ok, json|err)。**不吞异常**——网络问题要显式分类。

    cookie：网盘登录 cookie。实测含 __pus/__puus/__kps 组即有效，**不必含 ck 字段**。
    save 类接口 require login 必须传；info/pull 留空即 guest。
    """
    import urllib.request
    import urllib.error
    pf = PAN_PLATFORMS.get(platform) or PAN_PLATFORMS['quark']
    path = path.replace('pr=ucpro', f'pr={pf["pr"]}')
    url = f'{pf["api"]}{path}'
    hdr = {'User-Agent': PAN_UA, 'Referer': pf['referer']}
    if cookie:
        hdr['Cookie'] = cookie
    body = None
    if data is not None:
        hdr['Content-Type'] = 'application/json'
        body = json.dumps(data).encode()
    # C1b：底层取数统一走 core.http_get（err_body 保留服务端错误正文，排障必需）
    try:
        _st, _pl, _rs = http_get(url, timeout=timeout, headers=hdr,
                                 method='POST' if data is not None else 'GET',
                                 data=body, err_body=True)
        if _st == 'ok':
            return True, json.loads(_pl)
        if isinstance(_pl, tuple):
            _code, _b = _pl
            return False, f'HTTP {_code} {(_b or "")[:300]}'.strip()
        return False, f'HTTP错误 {_rs}' if _rs and _rs.startswith('http_') else f'网络错误 {_rs}'
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def pan_parse_share(text):
    """从分享文本里抠出 pwd_id。用户常见贴法是**整段分享文案**，不是干净 URL。

    实测样本：
      「…打开「夸克APP」即可获取。祄七另枫诶并闭页冉为喔汢 /~d9803bYsb2~:/
       链接：https://pan.quark.cn/s/9d5b78140523 …」
    注意 `/~xxx~/` 是**口令**不是 pwd_id，真正的 id 在 /s/ 后面。
    """
    import re as _re
    if not text:
        return ''
    m = _re.search(r'pan\.quark\.cn/s/([0-9a-zA-Z]+)', text)
    if m:
        return m.group(1)
    # S197：UC 网盘分享（drive.uc.cn/s/<id>）
    m = _re.search(r'drive\.uc\.cn/s/([0-9a-zA-Z]+)', text)
    return m.group(1) if m else ''


def pan_parse_share_ex(text):
    """四平台版：返回 (id, platform)。platform ∈ {'quark','uc','xunlei','baidu'}；认不出返回 ('', '')。"""
    import re as _re
    if not text:
        return '', ''
    m = _re.search(r'pan\.quark\.cn/s/([0-9a-zA-Z_]+)', text)
    if m:
        return m.group(1), 'quark'
    m = _re.search(r'drive\.uc\.cn/s/([0-9a-zA-Z_]+)', text)
    if m:
        return m.group(1), 'uc'
    m = _re.search(r'pan\.xunlei\.com/s/([0-9a-zA-Z_-]+)', text)
    if m:
        return m.group(1), 'xunlei'
    m = _re.search(r'pan\.baidu\.com/s/([0-9a-zA-Z_-]+)', text)
    if m:
        return m.group(1), 'baidu'
    return '', ''


def cmd_pan_info(a):
    """摸清分享里有什么：文件树 + 大小 + 格式。**不下载**。

    这一步在 IPv4-only 环境下也能完全成功——它走的是 API，不是 CDN。
    """
    pwd_id, plat = pan_parse_share_ex(a.url)
    if not pwd_id:
        print('❌ 认不出分享 id：需要夸克 https://pan.quark.cn/s/<id> 或 UC https://drive.uc.cn/s/<id> 或 迅雷 https://pan.xunlei.com/s/<id> 或 百度 https://pan.baidu.com/s/<id>（或含它们的整段分享文案）')
        sys.exit(2)
    if plat == 'xunlei':
        return cmd_pan_info_xunlei(a, pwd_id)
    if plat == 'baidu':
        return cmd_pan_info_baidu(a, pwd_id)

    ok, r = _pan_req(f'/1/clouddrive/share/sharepage/token?pr=ucpro&fr=pc&uc_param_str=',
                     {'pwd_id': pwd_id, 'passcode': a.passcode or ''}, platform=plat)
    if not ok:
        print(f'❌ 取 stoken 失败：{r}')
        sys.exit(1)
    if r.get('status') != 200:
        # 三态：有明确业务码就照实报，不折叠成"网络失败"
        print(f"❌ 分享不可用：code={r.get('code')} {r.get('message')}")
        sys.exit(1)
    st = r['data']['stoken']
    meta = r['data']

    # BFS 遍历：分享通常有外层文件夹包着，不能只看第一层
    queue = [('0', '')]
    rows, seen = [], 0
    while queue and seen < (a.limit or 500):
        pdir, prefix = queue.pop(0)
        q = (f'/1/clouddrive/share/sharepage/detail?pr=ucpro&fr=pc'
             f'&pwd_id={pwd_id}&stoken={quote(st, safe="")}&pdir_fid={pdir}'
             f'&force=0&_page=1&_size=200&_fetch_total=1')
        ok, d = _pan_req(q, platform=plat)
        if not ok:
            print(f'  ⚠️ 目录 {prefix or "/"} 读取失败：{d}（无法判定，不当作空目录）')
            continue
        for f in ((d.get('data') or {}).get('list') or []):
            seen += 1
            name = f.get('file_name') or ''
            full = f'{prefix}{name}'
            if f.get('dir'):
                rows.append({'path': full + '/', 'kind': 'dir', 'size': 0})
                queue.append((f['fid'], full + '/'))
            else:
                rows.append({'path': full, 'kind': 'file',
                             'size': int(f.get('size') or 0),
                             'fmt': f.get('format_type') or '',
                             'fid': f.get('fid'),
                             'token': f.get('share_fid_token') or ''})

    print(f"📦 {'UC' if plat == 'uc' else '夸克'}分享 {pwd_id}")
    print(f"   标题：{meta.get('title')}｜作者：{(meta.get('author') or {}).get('nick_name')}"
          f"｜类型：{meta.get('share_type')}")
    print(f"   本期：{'需提取码' if meta.get('expired_type') == 2 else '无需提取码'}"
          f"｜条目 {len(rows)}\n")
    if a.json:
        print(json.dumps({'pwd_id': pwd_id, 'stoken': st, 'items': rows},
                         ensure_ascii=False, indent=1))
        return

    files = [r for r in rows if r['kind'] == 'file']
    if files:
        print(f"   {'大小':>10}  格式                 路径")
        for r in sorted(files, key=lambda x: -x['size']):
            print(f"   {_fmt_size(r['size']):>10}  {(r.get('fmt') or '-'):<20} {r['path']}")

        # ★这是个**有用的旁证**，不是装饰：正常 apk 不可能几十 KB，
        #   而 format_type=application/zip 说明它是个包。两者一起看就能判断"是不是被改名了"。
        susp = [r for r in files
                if r['path'].lower().endswith('.apk') and r['size'] < 100 * 1024]
        if susp:
            print(f"\n   ⚠️ {len(susp)} 个 .apk 小于 100KB —— 正常 apk 不会这么小，"
                  f"多半是改了后缀的 zip/文本。取回后先 `file` 一下再当安装包看待。")
        zips = [r for r in files
                if 'zip' in (r.get('fmt') or '') and r['path'].lower().endswith('.apk')]
        if zips:
            print(f"   ℹ️ {len(zips)} 个 .apk 的 format_type 是 application/zip（容器是 zip，后缀是 apk）")
    print(f"\n   下一步：pan.py pull --url <同一链接> --outdir <目录>"
          f"\n   （下载受 CDN 出口策略限制：本类机房 IP 段会被 412 拒绝，与 IPv6 无关）")


def _fmt_size(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.0f}{u}' if u == 'B' else f'{n:.1f}{u}'
        n /= 1024
    return f'{n:.1f}TB'


def cmd_pan_pull(a):
    """取料：拿直链 → 下载。**412 的成因是出口网络被 CDN 拒（非 IPv6、非文件坏）**，必须说清楚。"""
    import urllib.request
    import urllib.error
    pwd_id, plat = pan_parse_share_ex(a.url)
    if not pwd_id:
        print('❌ 认不出分享 id')
        sys.exit(2)

    ok, r = _pan_req(f'/1/clouddrive/share/sharepage/token?pr=ucpro&fr=pc&uc_param_str=',
                     {'pwd_id': pwd_id, 'passcode': a.passcode or ''}, platform=plat)
    if not ok or r.get('status') != 200:
        print(f'❌ 分享不可用：{r if not ok else r.get("message")}')
        sys.exit(1)
    st = r['data']['stoken']

    # 收齐所有文件（含子目录）
    queue, files = [('0', '')], []
    while queue:
        pdir, prefix = queue.pop(0)
        q = (f'/1/clouddrive/share/sharepage/detail?pr=ucpro&fr=pc'
             f'&pwd_id={pwd_id}&stoken={quote(st, safe="")}&pdir_fid={pdir}'
             f'&force=0&_page=1&_size=200&_fetch_total=1')
        ok, d = _pan_req(q, platform=plat)
        if not ok:
            print(f'  ⚠️ 目录读取失败：{d}'); continue
        for f in ((d.get('data') or {}).get('list') or []):
            if f.get('dir'):
                queue.append((f['fid'], f"{prefix}{f.get('file_name')}/"))
            else:
                files.append({'name': f"{prefix}{f.get('file_name')}",
                              'fid': f['fid'], 'size': int(f.get('size') or 0),
                              'token': f.get('share_fid_token') or '',
                              'pdir': f.get('pdir_fid') or pdir})
    if a.match:
        files = [f for f in files if a.match in f['name']]
    if not files:
        print('❌ 没有匹配的文件'); sys.exit(1)

    outdir = a.outdir or '.'
    os.makedirs(outdir, exist_ok=True)

    ok_n, fail_n, cdn_reject = 0, 0, 0
    for f in files:
        # 按 pdir 分组取直链（接口一次能要多条同目录的）
        ok, d = _pan_req('/1/clouddrive/file/download?pr=ucpro&fr=pc&uc_param_str=',
                         {'fids': [f['fid']], 'pwd_id': pwd_id, 'stoken': st,
                          'fids_token': [f['token']], 'pdir_fid': f['pdir']}, platform=plat)
        if not ok or not (d.get('data') or []):
            print(f'  ❌ {f["name"]}：取直链失败（{d}）'); fail_n += 1; continue
        url = d['data'][0].get('download_url') or ''
        if not url:
            print(f'  ❌ {f["name"]}：接口未返回 download_url'); fail_n += 1; continue

        dst = os.path.join(outdir, os.path.basename(f['name']))
        try:
            rq = urllib.request.Request(url, headers={'User-Agent': PAN_UA,
                                                     'Referer': (PAN_PLATFORMS.get(plat) or PAN_PLATFORMS['quark'])['referer']})
            with urllib.request.urlopen(rq, timeout=a.timeout) as resp, open(dst, 'wb') as fh:
                shutil.copyfileobj(resp, fh)
            got = os.path.getsize(dst)
            if got != f['size']:
                print(f'  ⚠️ {f["name"]}：大小不符 {got}≠{f["size"]}（可能被截断）')
            print(f'  ✅ {f["name"]}  {_fmt_size(got)}')
            ok_n += 1
        except urllib.error.HTTPError as e:
            if e.code == 412:
                cdn_reject += 1
                print(f'  🚫 {f["name"]}：412 Precondition Failed —— **CDN 拒绝本出口，非文件问题**')
            else:
                print(f'  ❌ {f["name"]}：HTTP {e.code}')
            fail_n += 1
            try:
                os.remove(dst)
            except Exception:
                pass
        except Exception as e:
            print(f'  ❌ {f["name"]}：{type(e).__name__}: {e}'); fail_n += 1

    print(f'\n   取料小结：成功 {ok_n}｜失败 {fail_n}｜保存到 {os.path.abspath(outdir)}')
    if cdn_reject:
        # ★这是**无法判定**，不是"下载失败"。412 的成因是出口网络被拒，重试无用。
        print(f"""
   🚫 其中 {cdn_reject} 个被 CDN 以 412 拒绝。**不是文件坏了，也不是签名过期**：
      · **正确 token 与故意改坏的 token 都是 412**（响应体一模一样）→ 拦截在校验签名**之前**；
      · 同一出口访问 `pan.quark.cn` 200、`image.quark.cn` 200 → 不是断网、不是全站封禁；
      · 响应头 `Server: Tengine` + `Via: ens-cache2.<节点>`，262 字节固定 HTML。
      → 成因是**请求来自机房/云 IP 段，被 CDN 边缘节点策略性拒绝**（与 IPv4/IPv6 无关）。
   处置（按代价从低到高）：
      ① 换一个**家宽/移动网络**出口跑同一条命令（机房 IP 换机房 IP 没用）；
      ② 用夸克 App/网页版手动下载后放进指定目录；
      ③ 让分享者换网盘（直链可公网访问的）。
      **清单已拿到（`pan info`），别把"取不到"当成"里面没东西"。**""")
        sys.exit(0 if ok_n else 1)
    sys.exit(0 if ok_n else 1)


def _load_pan_cookie(plat='quark'):
    """读网盘登录态（按平台分文件/环境变量，同 S209 单一事实源风格）。
    夸克 → .quark_cookie / QUARK_COOKIE；UC → .uc_cookie / UC_COOKIE；
    迅雷 → .xunlei_cookie / XUNLEI_COOKIE；百度 → .baidu_cookie / BAIDU_COOKIE。
    缺则返回 ''，由调用方按需报错（转存必须登录）。"""
    import os
    if plat == 'uc':
        fpath, env = os.path.expanduser('~/.codebuddy/.uc_cookie'), 'UC_COOKIE'
    elif plat == 'xunlei':
        fpath, env = os.path.expanduser('~/.codebuddy/.xunlei_cookie'), 'XUNLEI_COOKIE'
    elif plat == 'baidu':
        fpath, env = os.path.expanduser('~/.codebuddy/.baidu_cookie'), 'BAIDU_COOKIE'
    else:
        fpath, env = os.path.expanduser('~/.codebuddy/.quark_cookie'), 'QUARK_COOKIE'
    try:
        if os.path.exists(fpath):
            return open(fpath, encoding='utf-8').read().strip()
    except Exception:
        pass
    return (os.environ.get(env) or '').strip()


# ── 迅雷网盘（S218 续·2026-10-24 本轮回补）──────────────────────────────
# 迅雷分享转存接口与夸克/UC **不同构**：独立验证码（X-Captcha-Token）+ 独立鉴权
# （Authorization: x_token）+ 独立列文件（/share + /share/detail）+ 独立转存
# （POST /share/restore，无需 users/me）。x_token 在网页 localStorage，不在 Cookie 头。
# captcha_sign 为动态签名（12 轮 md5 加盐），来自 Gopeed 开源迅雷扩展（适配 1.92.89），2026-10-24 实测有效。
XUNLEI_CLIENT_ID = 'Xqp0kJBXWhwaTpB6'
XUNLEI_CLIENT_VERSION = '1.92.89'
XUNLEI_CAPTCHA_SALTS = [
    'q1FLg', 'OECaw0higFYs7qCdOWvMEe', '1UQvF/CWht+RATnmBnyakvJFHL1jaAb8MRYvdVHQLZ',
    'OV+xWBsbnAehPNmDEUnjcVT', 'bbuvyCYHdJwBOtJ8Cdeg', '9ROgxnyRfQInpATpkchBTZW',
    'vXA2EpRk8', 'oEd', 'QCBQwX/', 'P5NlYzyVtGjJUI/dIzi+SOL+mf0Wl17',
    '7GRbxu7OmpasI841c66J', 'PEVQN9w+A4wRbGoX', 'CJ3yz0fu1kqhPDOyL438W', 'tD75Q',
]

def _xunlei_captcha_sign(ts, device_id):
    """迅雷验证码签名：CLIENT_ID+版本+域名+device_id+时间戳 经 12 轮 md5 加盐。"""
    cur = XUNLEI_CLIENT_ID + XUNLEI_CLIENT_VERSION + 'pan.xunlei.com' + device_id + ts
    for s in XUNLEI_CAPTCHA_SALTS:
        cur = hashlib.md5((cur + s).encode()).hexdigest()
    return '1.' + cur

def _xunlei_device_id(cookie):
    """迅雷 device_id：取 cookie 里 wdi10. 后的 32 位 hex（与 captcha 签名一致）。"""
    import re as _re
    m = _re.search(r'deviceid=wdi10\.([a-f0-9]+)', cookie or '')
    return (m.group(1)[:32] if m else '0' * 32)

def _xunlei_pwd_from_url(url):
    """从迅雷分享链接 query 取访问密码（pwd=）；取不到返回空串。"""
    import urllib.parse as _up
    try:
        return (_up.parse_qs(_up.urlparse(url or '').query).get('pwd') or [''])[0]
    except Exception:
        return ''

def _xunlei_captcha_token(device_id):
    """POST xluser-ssl.xunlei.com/v1/shield/captcha/init 拿验证码令牌。"""
    import time as _t
    ts = str(int(_t.time() * 1000))
    sign = _xunlei_captcha_sign(ts, device_id)
    body = {'client_id': XUNLEI_CLIENT_ID, 'action': 'get:/drive/v1/share',
            'device_id': device_id,
            'meta': {'username': '', 'phone_number': '', 'email': '',
                     'package_name': 'pan.xunlei.com', 'client_version': XUNLEI_CLIENT_VERSION,
                     'captcha_sign': sign, 'timestamp': ts, 'user_id': '0'}}
    hdr = {'User-Agent': PAN_UA, 'Content-Type': 'application/json',
           'X-Client-Id': XUNLEI_CLIENT_ID, 'X-Client-Version': XUNLEI_CLIENT_VERSION,
           'X-Device-Id': device_id, 'Referer': 'https://pan.xunlei.com/'}
    # C1b：底层取数统一走 core.http_get（err_body 保留服务端错误正文）
    try:
        _st, _pl, _rs = http_get('https://xluser-ssl.xunlei.com/v1/shield/captcha/init',
                                 timeout=30, headers=hdr, method='POST',
                                 data=json.dumps(body).encode(), err_body=True)
        if _st == 'ok':
            d = json.loads(_pl)
        elif isinstance(_pl, tuple):
            return False, 'captcha/init HTTP %d %s' % (_pl[0], (_pl[1] or '')[:120])
        else:
            return False, 'captcha/init %s' % _rs
        if not d.get('captcha_token'):
            return False, 'captcha/init 未返回 captcha_token：%s' % str(d)[:120]
        return True, d['captcha_token']
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, e)

def _xunlei_headers(captcha_token, cookie=None, token=None, device_id=''):
    """迅雷请求头：验证码令牌 + Cookie + Authorization(登录态) + 设备标识。"""
    hdr = {'User-Agent': PAN_UA, 'X-Client-Id': XUNLEI_CLIENT_ID,
           'X-Client-Version': XUNLEI_CLIENT_VERSION, 'X-Device-Id': device_id,
           'X-Captcha-Token': captcha_token, 'Referer': 'https://pan.xunlei.com/'}
    if cookie:
        hdr['Cookie'] = cookie
    if token:
        hdr['Authorization'] = token
    return hdr

def _xunlei_get(url, hdr):
    """迅雷 GET，返回解析后的 json。（C1b：走 core.http_get）"""
    _st, _pl, _rs = http_get(url, timeout=30, headers=hdr)
    if _st != 'ok':
        raise RuntimeError('迅雷 GET 失败: %s' % _rs)
    return json.loads(_pl)

def _xunlei_post(url, hdr, body):
    """迅雷 POST（JSON），返回解析后的 json。（C1b：走 core.http_get）"""
    h = dict(hdr)
    h['Content-Type'] = 'application/json'
    _st, _pl, _rs = http_get(url, timeout=30, headers=h, method='POST',
                             data=json.dumps(body).encode())
    if _st != 'ok':
        raise RuntimeError('迅雷 POST 失败: %s' % _rs)
    return json.loads(_pl)

def _xunlei_token(cookie):
    """迅雷登录态 x_token（JWT）。优先从 cookie 文本解析 x_token=；取不到则回退到
    独立文件 .xunlei_token 或环境变量 XUNLEI_TOKEN
    （迅雷 x_token 在网页 localStorage，不在请求 Cookie 头，故单独存放）。"""
    import os, re as _re
    if cookie:
        m = _re.search(r'(?:^|;\s*)x_token=([^;]+)', cookie)
        if m:
            return m.group(1).strip()
        m = _re.search(r'(?:^|;\s*)(?:authorization|token)=([^;]+)', cookie, _re.I)
        if m:
            return m.group(1).strip()
    p = os.path.expanduser('~/.codebuddy/.xunlei_token')
    if os.path.exists(p):
        return open(p, encoding='utf-8').read().strip()
    return (os.environ.get('XUNLEI_TOKEN') or '').strip()


def _xunlei_share_files(share_id, passcode, cookie=None, token=None, device_id=''):
    """递归列出迅雷分享内全部文件。返回 (ok, rows, pass_code_token, root_ids)。
    根层 /share?share_id=&pass_code=；folder 递归 /share/detail?parent_id=&pass_code_token=。
    文件在响应顶层 files（非 data.files）；folder kind=drive#folder。参数必须 urlencode。
    root_ids 为分享顶层条目 id（转存 file_ids 用）。"""
    import urllib.parse as _up
    ok, ct = _xunlei_captcha_token(device_id)
    if not ok:
        return False, ct, '', []
    hdr = _xunlei_headers(ct, cookie=cookie, token=token, device_id=device_id)
    q = _up.urlencode({'share_id': share_id, 'pass_code': passcode or '',
                       'limit': '100', 'space': '', 'thumbnail_size': 'SIZE_MEDIUM', 'scene': 'NORMAL'})
    try:
        d = _xunlei_get('https://api-pan.xunlei.com/drive/v1/share?' + q, hdr)
    except Exception as e:
        return False, '根层列文件失败：%s' % e, '', []
    pct = (d.get('pass_code_token') or '').strip()
    root = d.get('files') or []
    out, root_ids = [], []
    for f in root:
        out.append(f)
        root_ids.append(f.get('id'))
        if f.get('kind') == 'drive#folder':
            _xunlei_walk(share_id, f['id'], pct, hdr, out)
    return True, out, pct, root_ids

def _xunlei_walk(share_id, folder_id, pct, hdr, out, _depth=0):
    """递归展开 folder（/share/detail?parent_id=&pass_code_token=，必须 urlencode）。"""
    import urllib.parse as _up
    if _depth > 20:
        return
    q = _up.urlencode({'share_id': share_id, 'parent_id': folder_id, 'pass_code_token': pct,
                       'limit': '100', 'space': '', 'thumbnail_size': 'SIZE_MEDIUM', 'scene': 'NORMAL'})
    try:
        d = _xunlei_get('https://api-pan.xunlei.com/drive/v1/share/detail?' + q, hdr)
    except Exception:
        return
    for f in (d.get('files') or []):
        out.append(f)
        if f.get('kind') == 'drive#folder':
            _xunlei_walk(share_id, f['id'], pct, hdr, out, _depth + 1)


def _xunlei_restore_status(d):
    """转存任务状态：优先读取 restore_status/phase_type/task_status/status/phase。"""
    for k in ('restore_status', 'phase_type', 'task_status', 'status', 'phase'):
        v = d.get(k)
        if v:
            return str(v).upper()
    return ''

def _xunlei_restore_task_id(d):
    """转存任务 id：优先读取 restore_task_id/task_id/id。"""
    for k in ('restore_task_id', 'task_id', 'id'):
        v = d.get(k)
        if v:
            return str(v)
    return ''

def _xunlei_restore_done(d, file_ids):
    """转存是否已同步完成。"""
    return _xunlei_restore_status(d) in ('RESTORE_COMPLETE', 'PHASE_TYPE_COMPLETE', 'COMPLETE')

def _xunlei_restore_error(d):
    """转存是否已失败。"""
    return _xunlei_restore_status(d) in ('RESTORE_ERROR', 'PHASE_TYPE_ERROR', 'ERROR', 'FAILED')

def _xunlei_wait_restore(task_id, file_ids, hdr, timeout=60):
    """轮询转存任务（GET /drive/v1/tasks/{id}），最多 timeout 秒。返回 (done, msg)。
    参考 Gopeed 开源迅雷扩展 waitRestoreTask（MAX_RESTORE_POLL=120，1s 间隔）。"""
    url = 'https://api-pan.xunlei.com/drive/v1/tasks/' + quote(task_id, safe='')
    for _ in range(timeout):
        try:
            d = _xunlei_get(url, hdr)
        except Exception as e:
            return False, '轮询异常：%s' % e
        st = _xunlei_restore_status(d)
        if st in ('RESTORE_COMPLETE', 'PHASE_TYPE_COMPLETE', 'COMPLETE'):
            return True, '任务完成'
        if st in ('RESTORE_ERROR', 'PHASE_TYPE_ERROR', 'ERROR', 'FAILED'):
            return False, '任务失败：%s' % (d.get('message') or st)
        time.sleep(1)
    return False, '超时未结束'


def cmd_pan_info_xunlei(a, pwd_id):
    """迅雷分享清单（不下载，走 API，IPv4 可成功）。"""
    ck = _load_pan_cookie('xunlei')
    token = _xunlei_token(ck) if ck else ''
    did = _xunlei_device_id(ck) if ck else ''
    passcode = a.passcode or _xunlei_pwd_from_url(a.url)
    ok, rows, _pct, _root = _xunlei_share_files(pwd_id, passcode, cookie=ck, token=token, device_id=did)
    if not ok:
        print(f'❌ 读取迅雷分享失败：{rows}')
        sys.exit(1)
    files = [r for r in rows if r.get('kind') != 'drive#folder']
    print(f"📦 迅雷分享 {pwd_id}｜条目 {len(rows)}（文件 {len(files)}）\n")
    if a.json:
        print(json.dumps({'share_id': pwd_id, 'items': rows}, ensure_ascii=False, indent=1))
        return
    if files:
        print(f"   {'大小':>10}  路径")
        for r in sorted(files, key=lambda x: -int(x.get('size') or 0)):
            print(f"   {_fmt_size(int(r.get('size') or 0)):>10}  {r.get('name')}")
    print(f"\n   下一步：pan.py save --url https://pan.xunlei.com/s/{pwd_id}")


def cmd_pan_save_xunlei(a, pwd_id):
    """★迅雷网盘分享转存（S218 续）。

    链路：列分享文件（/share + /share/detail，验证码令牌即可，无需登录态）
    → 转存（POST /drive/v1/share/restore，需 Authorization: x_token 登录态）。
    转存 body（下划线风格）：parent_id(空=我的云盘根)、share_id、pass_code_token、
    ancestor_ids=[]、file_ids=[顶层条目id]、specify_parent_id=true。
    异步任务则轮询 GET /drive/v1/tasks/{id}。
    参考 Gopeed 开源迅雷扩展（1.92.89），2026-10-24 实测列文件有效。"""
    import os
    ck = _load_pan_cookie('xunlei')
    if not ck:
        print("""❌ 缺少迅雷网盘 Cookie，无法读取分享/转存。
   迅雷凭证分两部分（实测确认）：
     · Cookie 部分（sessionid/deviceid）→ 写入 `~/.codebuddy/.xunlei_cookie`
       （登录 pan.xunlei.com 后复制任意请求的 Cookie 头整串；你已给过）
     · **x_token（JWT，Authorization 用）不在 Cookie 头，在网页 localStorage**
       → 写入 `~/.codebuddy/.xunlei_token`（单行，权限 600）
         或环境变量 `export XUNLEI_TOKEN='eyJ...'`
   获取 x_token：F12 → 应用/Application → 本地存储/Local Storage → 选 pan.xunlei.com
     → 找键 `x_token`（值是一长串 eyJ...）→ 复制完整值
   注：仅复制 Cookie 头（sessionid）不够——转存报 401 帐号认证失败；必须有 x_token。""")
        sys.exit(1)
    did = _xunlei_device_id(ck)

    # 1) 列文件（验证码令牌即可，不需要 x_token）
    passcode = a.passcode or _xunlei_pwd_from_url(a.url)
    ok, rows, pct, root_ids = _xunlei_share_files(pwd_id, passcode, cookie=ck, device_id=did)
    if not ok:
        print(f'❌ 读取迅雷分享失败：{rows}')
        sys.exit(1)
    files = [r for r in rows if r.get('kind') != 'drive#folder']
    if a.match:
        files = [f for f in files if a.match in f.get('name', '')]
    if not files:
        print('❌ 没有可转存的文件'); sys.exit(1)

    # 2) 校验登录态（转存必须有 x_token）
    token = _xunlei_token(ck)
    if not token:
        print(f'✅ 分享可读（共 {len(files)} 个文件），但**缺少 x_token 登录态，无法转存**。\n'
              f'   请按上方提示把 x_token 写入 ~/.codebuddy/.xunlei_token 或环境变量 XUNLEI_TOKEN 后重试。')
        sys.exit(1)

    # 3) 计算要转存的顶层 file_ids（默认整分享；--match 时取其所在根条目）
    root_set = set(root_ids)
    if a.match:
        by_id = {r.get('id'): r for r in rows}
        sel = set()
        for f in files:
            fid = f.get('id')
            if fid in root_set:
                sel.add(fid); continue
            cur = by_id.get(f.get('parent_id'))
            while cur and cur.get('id') not in root_set:
                cur = by_id.get(cur.get('parent_id'))
            if cur:
                sel.add(cur.get('id'))
        file_ids = list(sel)
    else:
        file_ids = list(root_ids)
    if not file_ids:
        print('❌ 没有可转存的顶层条目'); sys.exit(1)

    # 4) 转存：POST /drive/v1/share/restore（需 x_token 登录态）
    ok2, ct = _xunlei_captcha_token(did)
    if not ok2:
        print(f'❌ 获取验证码令牌失败：{ct}'); sys.exit(1)
    hdr = _xunlei_headers(ct, cookie=ck, token=token, device_id=did)
    to_parent = '' if (a.to in ('', '0', None)) else a.to  # 迅雷根目录是空串，非 '0'
    body = {
        'parent_id': to_parent,
        'share_id': pwd_id,
        'pass_code_token': pct,
        'ancestor_ids': [],
        'file_ids': file_ids,
        'specify_parent_id': True,
    }
    try:
        d = _xunlei_post('https://api-pan.xunlei.com/drive/v1/share/restore', hdr, body)
    except urllib.error.HTTPError as e:
        print(f'❌ 转存请求被拒 HTTP {e.code}：{e.read()[:240].decode("utf-8", "replace")}')
        sys.exit(1)
    except Exception as e:
        print(f'❌ 转存请求失败：{type(e).__name__} {e}'); sys.exit(1)

    # 5) 处理响应：同步完成 / 异步任务轮询 / 失败
    if _xunlei_restore_done(d, file_ids):
        print(f'  ✅ 转存完成：{len(file_ids)} 个顶层条目（含 {len(files)} 个文件）'
              f'→ 网盘（parent_id={to_parent or "我的云盘根"}）')
        sys.exit(0)
    task_id = _xunlei_restore_task_id(d)
    if task_id:
        done, msg = _xunlei_wait_restore(task_id, file_ids, hdr)
        if done:
            print(f'  ✅ 转存任务完成：{msg}｜{len(file_ids)} 个顶层条目'
                  f'→ 网盘（parent_id={to_parent or "我的云盘根"}）')
            sys.exit(0)
        print(f'  ❌ 转存任务未完成：{msg}'); sys.exit(1)
    if _xunlei_restore_error(d):
        print(f'  ❌ 转存被拒：{d.get("message") or d}'); sys.exit(1)
    print(f'  ⚠️ 转存已提交（无明确完成状态）：task={task_id}'
          f'｜file_ids={len(file_ids)} 个顶层条目。请稍后到网盘确认。')
    sys.exit(0)


def cmd_pan_save(a):
    """★直送二期（S170 延续）：把分享里的文件**转存到用户自己的夸克网盘**。

    链路：token → detail 取清单 → sharepage/save（**fid 参数必须是数组**，
    逗号串会 500 inner error，2026-10-24 实测）→ task 轮询确认（2=完成 3=失败）。
    save 接口 `require login [guest]`——**必须有你的夸克登录态**，否则被拒。
    与 pull 不同，save **走 API 域（drive-pc.quark.cn），不经过 CDN 下载域**，
    所以本机房出口可达（同 token/detail），唯一卡点是登录态。
    """
    import os
    from collections import defaultdict
    pwd_id, plat = pan_parse_share_ex(a.url)
    if not pwd_id:
        print('❌ 认不出分享 id：需要夸克 https://pan.quark.cn/s/<id> 或 UC https://drive.uc.cn/s/<id> 或 迅雷 https://pan.xunlei.com/s/<id> 或 百度 https://pan.baidu.com/s/<id>')
        sys.exit(2)
    if plat == 'xunlei':
        return cmd_pan_save_xunlei(a, pwd_id)
    if plat == 'baidu':
        return cmd_pan_save_baidu(a, pwd_id)

    ok, r = _pan_req(f'/1/clouddrive/share/sharepage/token?pr=ucpro&fr=pc&uc_param_str=',
                     {'pwd_id': pwd_id, 'passcode': a.passcode or ''}, platform=plat)
    if not ok or r.get('status') != 200:
        print(f'❌ 分享不可用：{r if not ok else r.get("message")}')
        sys.exit(1)
    st = r['data']['stoken']

    # 收齐文件（含子目录），记录 fid + share_fid_token + pdir
    queue, files = [('0', '')], []
    while queue:
        pdir, prefix = queue.pop(0)
        q = (f'/1/clouddrive/share/sharepage/detail?pr=ucpro&fr=pc'
             f'&pwd_id={pwd_id}&stoken={quote(st, safe="")}&pdir_fid={pdir}'
             f'&force=0&_page=1&_size=200&_fetch_total=1')
        ok, d = _pan_req(q, platform=plat)
        if not ok:
            print(f'  ⚠️ 目录读取失败：{d}'); continue
        for f in ((d.get('data') or {}).get('list') or []):
            if f.get('dir'):
                queue.append((f['fid'], f"{prefix}{f.get('file_name')}/"))
            else:
                files.append({'name': f"{prefix}{f.get('file_name')}",
                              'fid': f['fid'],
                              'token': f.get('share_fid_token') or '',
                              'pdir': f.get('pdir_fid') or pdir})

    if a.fid:
        files = [f for f in files if f['fid'] == a.fid]
    if a.match:
        files = [f for f in files if a.match in f['name']]
    if not files:
        print('❌ 没有可转存的文件'); sys.exit(1)

    # ★硬前置：登录态（save 必须，按平台选凭证文件）
    ck = _load_pan_cookie(plat)
    if not ck:
        if plat == 'uc':
            print("""❌ 缺少 UC 网盘登录态，无法转存。
   转存接口 sharepage/save 要求登录。请提供你的 UC 网盘登录 cookie：
     · 方式①：写入文件 `~/.codebuddy/.uc_cookie`（单行，cookie 原文，权限 600）
     · 方式②：环境变量 `export UC_COOKIE='...'`
   获取方法：登录 drive.uc.cn 后复制任意请求的 Cookie 头**整串**即可——
   实测含 __pus/__puus 组就有效，不需要专门找 ck 字段。""")
        else:
            print("""❌ 缺少夸克登录态，无法转存。
   转存接口 sharepage/save 要求登录。请提供你的夸克网盘登录 cookie：
     · 方式①：写入文件 `~/.codebuddy/.quark_cookie`（单行，cookie 原文，权限 600）
     · 方式②：环境变量 `export QUARK_COOKIE='...'`
   获取方法：登录 pan.quark.cn 后复制任意请求的 Cookie 头**整串**即可——
   实测含 __pus/__puus/__kps 组就有效，**不需要专门找 ck 字段**。""")
        sys.exit(1)

    to = a.to or '0'
    by_pdir = defaultdict(list)
    for f in files:
        by_pdir[f['pdir']].append(f)

    ok_n, fail_n = 0, 0
    for pdir, grp in by_pdir.items():
        ok, d = _pan_req('/1/clouddrive/share/sharepage/save?pr=ucpro&fr=pc&uc_param_str=',
                         {'pwd_id': pwd_id, 'stoken': st,
                          'fid_list': [x['fid'] for x in grp],          # ★必须是数组，逗号串会 500
                          'fid_token_list': [x['token'] for x in grp],  # ★同上
                          'to_pdir_fid': to, 'pdir_fid': pdir, 'scene': 'link'},
                         platform=plat, cookie=ck)
        if not ok:
            print(f'  ❌ 目录 {pdir} 转存请求失败：{d}'); fail_n += len(grp); continue
        code = d.get('status') or d.get('code')
        if code != 200:
            print(f'  ❌ 目录 {pdir} 转存被拒：code={code} {d.get("message")}'); fail_n += len(grp); continue
        # 轮询任务状态：2=完成 3=失败（实测约 2 秒一轮内完成）
        task_id = (d.get('data') or {}).get('task_id') or ''
        done = False
        if task_id:
            import time as _t
            for _i in range(15):
                _t.sleep(2)
                ok2, t2 = _pan_req(f'/1/clouddrive/task?pr=ucpro&fr=pc&task_id={quote(task_id, safe="")}&retry_index={_i}',
                                   platform=plat, cookie=ck)
                td = (t2.get('data') or {}) if ok2 and isinstance(t2, dict) else {}
                if td.get('status') == 2:
                    done = True; break
                if td.get('status') == 3:
                    break
        else:
            done = True  # 无 task_id 时以 200 受理为准
        if done:
            ok_n += len(grp)
            print(f'  ✅ 转存 {len(grp)} 个文件到网盘（to_pdir_fid={to}，任务已完成）')
        else:
            print(f'  ⚠️ 目录 {pdir} 转存任务未确认完成（task_id={task_id}）'); fail_n += len(grp)

    if plat == 'uc':
        src = '文件 .uc_cookie' if os.path.exists(os.path.expanduser('~/.codebuddy/.uc_cookie')) else '环境变量 UC_COOKIE'
    else:
        src = '文件 .quark_cookie' if os.path.exists(os.path.expanduser('~/.codebuddy/.quark_cookie')) else '环境变量 QUARK_COOKIE'
    print(f'\n   转存小结：成功 {ok_n}｜失败 {fail_n}｜分享 {pwd_id}｜登录态来源：{src}')
    if ok_n:
        sid = _pan_snapshot_save(plat, pwd_id, to, [f['name'] for f in files])
        if sid:
            print(f'   快照已存 id={sid}｜撤销用：pan.py rm --undo {sid} --platform {plat}')
    sys.exit(0 if ok_n and not fail_n else 1)


def _parse_since(s):
    """--since 时间解析：'30'→最近30分钟；13位数字→毫秒时间戳；否则试 ISO。

    为什么要它：按文件名关键词猜"哪些是刚转存的"很脆弱（漏掉不含关键词的、
    误伤同名的）。接口每个文件都返回 created_at，按时间筛才稳。
    """
    import time as _t
    import datetime as _dt
    s = (s or '').strip()
    if not s:
        return 0
    if s.isdigit():
        n = int(s)
        if n < 100000:          # 小于十万视为"分钟数"
            return int((_t.time() - n * 60) * 1000)
        return n                # 13 位＝毫秒时间戳
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return int(_dt.datetime.strptime(s, fmt).timestamp() * 1000)
        except ValueError:
            continue
    print(f'❌ 认不出时间：{s}（用分钟数如 30，或 2026-10-25 00:00）')
    sys.exit(2)


def _fmt_ts(ms):
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(ms)


def _pan_snapshot_save(plat, pwd_id, to, names):
    """转存快照：记下本次转存了哪些文件（供 --undo 精确撤销）。

    为什么必须有：转存接口只回 task_id，**不回"落盘后的新 fid"**，
    所以事后只能按文件名反推。把当时转存的文件名清单存下来，
    撤销时才能精确匹配，而不是拿关键词瞎猜（本轮 42 个误转就是这么猜的）。
    """
    import time as _t
    import hashlib as _h
    fp = os.path.expanduser('~/.codebuddy/.pan_snapshots.json')
    try:
        d = json.load(open(fp, encoding='utf-8')) if os.path.exists(fp) else {'snapshots': []}
    except Exception:
        d = {'snapshots': []}
    sid = _h.sha1(('%s|%s|%s' % (plat, pwd_id, _t.time())).encode('utf-8')).hexdigest()[:10]
    d.setdefault('snapshots', []).append({
        'id': sid, 'time': int(_t.time() * 1000), 'platform': plat,
        'pwd_id': pwd_id, 'to': to, 'names': list(names)})
    d['snapshots'] = d['snapshots'][-20:]      # 只留最近 20 次，防无限膨胀
    try:
        json.dump(d, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        os.chmod(fp, 0o600)
        return sid
    except Exception:
        return ''


def _pan_snapshot_load(sid):
    """读快照：sid='last' 取最近一次，否则按 id 精确取。"""
    fp = os.path.expanduser('~/.codebuddy/.pan_snapshots.json')
    try:
        d = json.load(open(fp, encoding='utf-8'))
    except Exception:
        return None
    snaps = d.get('snapshots') or []
    if not snaps:
        return None
    if sid == 'last':
        return snaps[-1]
    for s in snaps:
        if s.get('id') == sid:
            return s
    return None


def _write_backup_manifest(sel, plat):
    """破坏性操作门禁第 2 步：删前把待删清单落盘备份（可据此核对/恢复）。"""
    import time as _t
    fp = os.path.expanduser('~/.codebuddy/pan_rm_backup_%s.json') % _t.strftime('%m%d_%H%M%S')
    try:
        json.dump({'time': int(_t.time() * 1000), 'platform': plat,
                   'items': [{'fid': x['fid'], 'name': x['name'],
                              'dir': x.get('dir'), 'size': x.get('size', 0)} for x in sel]},
                  open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'   💾 删前备份清单已落盘：{fp}')
        return fp
    except Exception as e:
        print(f'   ⚠️ 备份清单写入失败：{e}')
        return ''


def cmd_pan_rm(a):
    """★删除你自己网盘里的文件/目录。默认**预演**（只列将删的），--yes 才真删。

    删除走 `/1/clouddrive/file/delete`（夸克/UC 同构），body 传 filelist（fid 数组）。
    删目录会递归清掉里面所有内容。写操作，需登录态（与 save 同套 cookie）。
    筛选：--fid 精确（逗号分隔，优先）｜--match 多关键词（逗号分隔，任一命中即选）｜都不给则删整个 --pdir 范围。
    """
    import urllib.parse as _up
    plat = a.platform
    ck = _load_pan_cookie(plat)
    if not ck:
        print('❌ 缺少 %s 网盘登录态，无法删除。请提供 cookie 写入 ~/.codebuddy/.%s_cookie（权限600）'
              % ('夸克' if plat == 'quark' else 'UC', plat))
        sys.exit(1)

    # 1) 列出目标范围内全部条目（支持递归进子目录）
    items = []
    queue = [a.pdir or '0']
    while queue:
        pdir = queue.pop(0)
        q = (f'/1/clouddrive/file?pr=ucpro&fr=pc&pdir_fid={_up.quote(pdir, safe="")}'
             f'&_page=1&_size=200&_fetch_total=1&_fetch_sub_count=1')
        ok, d = _pan_req(q, platform=plat, cookie=ck)
        if not ok:
            print(f'  ⚠️ 目录 {pdir} 读取失败：{d}'); continue
        for f in ((d.get('data') or {}).get('list') or []):
            items.append({'fid': f.get('fid'), 'name': f.get('file_name') or '',
                          'dir': bool(f.get('dir')), 'size': int(f.get('size') or 0),
                          'ct': int(f.get('created_at') or 0)})   # ★创建时间，供 --since 用
            if a.recursive and f.get('dir'):
                queue.append(f['fid'])

    # 2) 筛选（--undo 优先：按转存快照精确撤销，不用文件名猜）
    if getattr(a, 'undo', ''):
        snap = _pan_snapshot_load(a.undo)
        if not snap:
            print(f'❌ 找不到快照：{a.undo}（用 last 取最近一次）'); sys.exit(1)
        want = set(snap.get('names') or [])
        sel = [x for x in items if x['name'] in want]      # 精确名匹配，不是子串
        print(f'   ↩️  按快照 {snap.get("id")} 撤销（快照 {len(want)} 个文件名，精确匹配到 {len(sel)} 项）')
    elif a.fid:
        want = set(x for x in a.fid.split(',') if x.strip())
        sel = [x for x in items if x['fid'] in want]
    elif a.match:
        keys = [k.strip() for k in a.match.split(',') if k.strip()]
        sel = [x for x in items if any(k in x['name'] for k in keys)]
    else:
        sel = items  # 没指定则整个 --pdir 范围

    # 2.5) --since：只保留该时间点之后新增的（按转存/创建时间筛，不靠文件名猜）
    if getattr(a, 'since', ''):
        th = _parse_since(a.since)
        before = len(sel)
        sel = [x for x in sel if x['ct'] >= th]
        print(f'   ⏱️  按创建时间筛（{_fmt_ts(th)} 之后）：{before} → {len(sel)} 项')

    if not sel:
        print('❌ 没有匹配到要删的文件'); sys.exit(1)

    # 3) 预演 / 执行
    print(f"🗑️  将删除 {len(sel)} 项（{'【执行】' if a.yes else '【预演】加 --yes 才真删'}）：")
    for x in sel:
        print(f"   [{'目录' if x['dir'] else '文件'}] {x['name']}  (fid={x['fid']})")

    if not a.yes:
        print('\n   预演完毕，未删除任何东西。确认无误后加 --yes 执行。')
        sys.exit(0)

    # 破坏性门禁第 2 步：执行前必须落备份清单（清单→备份→确认→执行，缺一即中止）
    _bk = _write_backup_manifest(sel, plat)
    if not _bk:
        print('❌ 备份清单未生成，按破坏性操作门禁中止删除')
        sys.exit(1)

    fids = [x['fid'] for x in sel]
    ok_n = 0
    for i in range(0, len(fids), 50):
        chunk = fids[i:i + 50]
        ok, d = _pan_req('/1/clouddrive/file/delete?pr=ucpro&fr=pc&uc_param_str=',
                         {'actoin_type': 2, 'exclude_fids': [], 'filelist': chunk},
                         platform=plat, cookie=ck)
        if not ok:
            print(f'  ❌ 删除请求失败：{d}'); continue
        code = d.get('status') or d.get('code')
        if code not in (200, 0, 'ok', None):
            print(f'  ❌ 删除被拒：code={code} {d.get("message")}'); continue
        ok_n += len(chunk)
        print(f'  ✅ 已删除 {len(chunk)} 项')
    print(f'\n   删除小结：成功 {ok_n}｜失败 {len(fids) - ok_n}')
    sys.exit(0 if ok_n == len(fids) else 1)


# ── 百度网盘（S218 续·2026-10-24 本轮回补）──────────────────────────────
# 百度与夸克/UC/迅雷**不同构**：独立 cookie（BDUSS/STOKEN/PANPSC）+
# 独立分享解析（surl→shareid+uk）+ 独立列文件（share/list）+
# 独立转存（share/transfer，fsidlist 明文 JSON 数组，配 shareid+share_uk+bdstoken，
#   无需 RSA 加密——disk-share 前端 JS 无 RSA 公钥，契约来自 BaiduPCS-Go 逆向佐证）。
BAIDU_REF = 'https://pan.baidu.com/'
BAIDU_APP_ID = '250528'

def _baidu_req(url, ck, data=None, timeout=20):
    """百度 GET/POST（form）。data 有则 POST(form-urlencoded)，无则 GET。返回解析 json。"""
    hdr = {'User-Agent': PAN_UA, 'Cookie': ck, 'Referer': BAIDU_REF}
    if data is not None:
        import urllib.parse as _up
        _st, _pl, _rs = http_get(url, timeout=timeout,
                                 headers={**hdr, 'Content-Type': 'application/x-www-form-urlencoded'},
                                 method='POST', data=_up.urlencode(data).encode('utf-8'))
    else:
        _st, _pl, _rs = http_get(url, timeout=timeout, headers=hdr)
    if _st != 'ok':
        raise RuntimeError('百度请求失败: %s' % _rs)
    return json.loads(_pl)

def _baidu_fetch_raw(url, ck, timeout=20):
    """抓原始 HTML/JS（用于从分享页 JS 提取 RSA 公钥）。（C1b：走 core.http_get）"""
    _st, _pl, _rs = http_get(url, timeout=timeout,
                             headers={'User-Agent': PAN_UA, 'Cookie': ck, 'Referer': BAIDU_REF})
    if _st != 'ok':
        raise RuntimeError('百度页面抓取失败: %s' % _rs)
    return _pl

def _baidu_parse_surl(text):
    """从分享文本抠出 surl + 提取码。返回 (surl, pwd)。"""
    import re as _re
    m = _re.search(r'pan\.baidu\.com/s/([0-9a-zA-Z_-]+)', text or '')
    if not m:
        return '', ''
    surl = m.group(1)
    pm = _re.search(r'[?&]pwd=([0-9a-zA-Z]+)', text or '')
    return surl, (pm.group(1) if pm else '')

def _baidu_shareinfo(surl, pwd, ck):
    """从分享页内联 locals 提取 shareid + share_uk（分享者 uk）+ bdstoken。返回 (ok, shareid, share_uk, bdstoken, err)。

    实测确证：百度 `api/shareinfo` 接口已废弃（404），而页面 locals 内联了 shareid/share_uk/bdstoken；
    `uk`（当前登录用户）≠ `share_uk`（分享者），分享列表/转存必须用 share_uk。故直接抓页提取。"""
    import re as _re
    try:
        html = _baidu_fetch_raw('https://pan.baidu.com/s/' + surl + ('?pwd=' + pwd if pwd else ''), ck)
    except Exception as e:
        return False, '', '', '', '抓分享页失败：%s' % e
    sid = _re.search(r'share_uk["\']?\s*[:=]\s*["\']?(\d+)', html)
    uk = _re.search(r'shareid["\']?\s*[:=]\s*["\']?(\d+)', html)
    bt = _re.search(r'bdstoken["\']?\s*[:=]\s*["\']?([0-9a-f]+)', html)
    if not sid or not uk:
        return False, '', '', '', '分享页未含 shareid/share_uk（链接无效、需登录查看，或 cookie 失效）'
    return True, uk.group(1), sid.group(1), (bt.group(1) if bt else ''), ''

def _baidu_verify(surl, pwd, ck, shareid, share_uk):
    """验证提取码，返回 (ok, stoken, err)。百度要求先 verify 拿 stoken，再带 stoken 列文件/转存。"""
    import urllib.parse as _up
    data = {'shareid': shareid, 'uk': share_uk, 'pwd': pwd,
            'clienttype': '0', 'channel': 'chunlei', 'web': '1', 'app_id': BAIDU_APP_ID}
    try:
        d = _baidu_req('https://pan.baidu.com/share/verify', ck, data)
    except Exception as e:
        return False, '', 'share/verify 失败：%s' % e
    if d.get('errno') != 0:
        return False, '', 'share/verify 错误：errno=%s %s（提取码错误，或 cookie 登录态失效需重登重发）' % (d.get('errno'), d.get('errmsg'))
    return True, (d.get('stoken') or ''), ''

def _baidu_bduss_alive(ck):
    """轻量探活：BDUSS 登录态是否有效（仅依赖 BDUSS，不依赖分享专用 STOKEN）。返回 bool。"""
    try:
        d = _baidu_req('https://pan.baidu.com/api/quota?check_free=1&checkexpire=1&web=1', ck)
        return d.get('errno') == 0
    except Exception:
        return False

def _baidu_verify_hint(ck, err_v):
    """verify 失败时的精准指引：区分「服务端风控(出口IP)」与「登录态整体失效」。"""
    if 'errno=-12' in err_v:
        if _baidu_bduss_alive(ck):
            return ('❌ 验证提取码失败（errno=-12，err_msg 为空）：账号 BDUSS 登录态有效、'
                    'quota 正常，但分享验证被百度服务端静默拒绝。\n'
                    '   实测「所有参数/UA/请求方式组合都 -12 且空 err_msg、连无效 shareid 也 -12」，'
                    '而 quota/list 接口正常——这种表现通常是当前运行出口'
                    '（数据中心 / 云服务器 IP）被百度对分享操作风控。\n'
                    '   → 请在你的本机（家庭宽带、已登录该账号的浏览器网络）运行同样命令，'
                    '用此 cookie 重试；或让请求走非机房出口 IP。cookie 本身无需重发。')
        return ('❌ 验证提取码失败（errno=-12）：登录态整体失效。\n'
                '   → 重新登录 pan.baidu.com，F12 复制整串 Cookie 覆盖写入 '
                '~/.codebuddy/.baidu_cookie（权限 600），再重跑。')
    return '❌ 验证提取码失败：%s' % err_v


def _baidu_resolve_stoken(surl, pwd, ck, shareid, share_uk, force_verify=False):
    """决定列文件/转存所需的 stoken。百度契约：无密码分享直接 list（errno=0）；
    有密码分享 list 返回 -9，需先 verify 拿 stoken。返回 (stoken, err)，err='' 即成功。

    force_verify：转存(save)场景必须为 True——公开分享虽能直接 list，但 transfer
    仍需要 verify 拿到的 stoken。列文件(info)场景用默认 False（公开分享跳过 verify 即可）。

    实测价值：沙箱环境 share/verify 被百度静默风控（errno=-12 空 err_msg），但 share/list
    对公开分享完全可用——故「先无密码试 list」既能让公开分享端到端跑通列文件，
    又能把转存所需的 verify/transfer 风控精准隔离出来。"""
    import urllib.parse as _up
    short = surl[1:] if surl.startswith('1') else surl
    q = {'web': '5', 'app_id': BAIDU_APP_ID, 'desc': '1', 'showempty': '0',
         'page': '1', 'num': '100', 'order': 'time',
         'shorturl': short, 'root': '1', 'view_mode': '1'}
    try:
        d = _baidu_req('https://pan.baidu.com/share/list?' + _up.urlencode(q), ck)
    except Exception as e:
        return '', 'share/list 失败：%s' % e
    errno = d.get('errno')
    if errno == 0:
        if not force_verify:
            return '', ''  # 列文件(info)：公开无密码，无需 stoken
        # 转存(save)：公开分享也需 verify 拿 stoken 供 transfer
        ok_v, stoken, err_v = _baidu_verify(surl, pwd, ck, shareid, share_uk)
        if not ok_v:
            return '', err_v
        return stoken, ''
    if errno == -9:
        if not pwd:
            return '', '此分享需要提取码，请加 ?pwd= 或在命令后加 --passcode <提取码>'
        ok_v, stoken, err_v = _baidu_verify(surl, pwd, ck, shareid, share_uk)
        if not ok_v:
            return '', err_v  # 命令函数会用 hint 美化 -12
        return stoken, ''
    return '', 'share/list 错误：errno=%s %s' % (errno, d.get('errmsg'))


def _baidu_collect(surl, pwd, ck, shareid, share_uk, out, stoken='', dir_fsid='', prefix='', _depth=0):
    """递归列文件，写入 out（含子目录）。返回 err 或 ''。
    实测契约（来自 disk-share 前端 JS getShareList）：GET /share/list?
      web=5&app_id=250528&desc=1&showempty=0&page=N&num=100&order=time
      &shorturl=<surl去开头1>&root=1&view_mode=1[&pwd=..][&stoken=..][&dir=<fs_id>]
    shorturl 必须把 URL 里 surl 开头的 '1' 去掉（JS: _surl.split('').slice(1).join('')）。"""
    import urllib.parse as _up
    if _depth > 20:
        return ''
    short = surl[1:] if surl.startswith('1') else surl
    page = 1
    while True:
        q = {'web': '5', 'app_id': BAIDU_APP_ID, 'desc': '1', 'showempty': '0',
             'page': str(page), 'num': '100', 'order': 'time',
             'shorturl': short, 'root': '1', 'view_mode': '1'}
        if pwd:
            q['pwd'] = pwd
        if stoken:
            q['stoken'] = stoken
        if dir_fsid:
            q['dir'] = dir_fsid
        try:
            d = _baidu_req('https://pan.baidu.com/share/list?' + _up.urlencode(q), ck)
        except Exception as e:
            return 'share/list 失败：%s' % e
        if d.get('errno') != 0:
            return 'share/list 错误：errno=%s %s' % (d.get('errno'), d.get('errmsg'))
        lst = d.get('list') or []
        if not lst:
            break
        for f in lst:
            isdir = (f.get('isdir') == 1)
            name = f.get('server_filename') or f.get('filename') or ''
            full = prefix + name
            out.append({'fs_id': f.get('fs_id'), 'name': full, 'isdir': isdir,
                        'size': int(f.get('size') or 0), 'md5': f.get('md5')})
            if isdir:
                e2 = _baidu_collect(surl, pwd, ck, shareid, share_uk, out, stoken,
                                    dir_fsid=str(f.get('fs_id')), prefix=full + '/', _depth=_depth + 1)
                if e2:
                    return e2
        if not d.get('more') or len(lst) < 100:
            break
        page += 1
    return ''

# 注：百度网盘网页端分享转存（/share/transfer）实测用 fsidlist 明文 JSON 数组（非 RSA filelist），
# disk-share 前端 JS（common-chunks-all）中亦无 RSA 公钥，故无需 RSA 加密与公钥提取。
# 转存见 _baidu_transfer（fsidlist 方式，契约来自 BaiduPCS-Go 逆向 + 网页端佐证）。

def _baidu_transfer(surl, pwd, ck, shareid, share_uk, bdstoken, items, to_path='/'):
    """转存。items=[(fs_id, server_filename), ...]。返回 (ok, err)。
    实测契约（BaiduPCS-Go 逆向 + 网页端 disk-share JS 佐证）：POST /share/transfer，
    fsidlist 为明文 JSON 数组字符串，配 shareid + share_uk + bdstoken，无需 RSA 加密 filelist。"""
    fsidlist = json.dumps([str(f) for f, _ in items], ensure_ascii=False)
    data = {'shareid': shareid, 'uk': share_uk, 'fsidlist': fsidlist,
            'path': to_path, 'bdstoken': bdstoken,
            'clienttype': '0', 'channel': 'chunlei', 'web': '1', 'app_id': BAIDU_APP_ID}
    try:
        d = _baidu_req('https://pan.baidu.com/share/transfer', ck, data)
    except Exception as ex:
        return False, 'share/transfer 失败：%s' % ex
    if d.get('errno') != 0:
        return False, 'share/transfer 错误：errno=%s %s' % (d.get('errno'), d.get('errmsg'))
    return True, ''

def cmd_pan_info_baidu(a, surl):
    """百度分享清单（列文件，不下载）。"""
    ck = _load_pan_cookie('baidu')
    if not ck:
        print('❌ 缺少百度网盘登录态（~/.codebuddy/.baidu_cookie）。F12 复制 pan.baidu.com 的 Cookie 整串写入该文件（权限600）。')
        sys.exit(1)
    pwd = a.passcode or _baidu_parse_surl(a.url)[1]
    ok, shareid, share_uk, bdstoken, err = _baidu_shareinfo(surl, pwd, ck)
    if not ok:
        print('❌ 读取百度分享失败：%s' % err); sys.exit(1)
    stoken, e = _baidu_resolve_stoken(surl, pwd, ck, shareid, share_uk)
    if e:
        if 'errno=-12' in e:
            print(_baidu_verify_hint(ck, e)); sys.exit(1)
        print('❌ ' + e); sys.exit(1)
    out = []
    e2 = _baidu_collect(surl, pwd, ck, shareid, share_uk, out, stoken=stoken)
    if e2:
        print('❌ 列文件失败：%s' % e2); sys.exit(1)
    files = [r for r in out if not r['isdir']]
    print(f"📦 百度分享 {surl}｜条目 {len(out)}（文件 {len(files)}）\n")
    if files:
        print(f"   {'大小':>10}  路径")
        for r in sorted(files, key=lambda x: -x['size']):
            print(f"   {_fmt_size(r['size']):>10}  {r['name']}")
    print(f"\n   下一步：pan.py save --url https://pan.baidu.com/s/{surl}")

def cmd_pan_save_baidu(a, surl):
    """★百度网盘分享转存（S218 续）。"""
    ck = _load_pan_cookie('baidu')
    if not ck:
        print('❌ 缺少百度网盘登录态（~/.codebuddy/.baidu_cookie）。F12 复制 pan.baidu.com 的 Cookie 整串写入该文件（权限600）。')
        sys.exit(1)
    pwd = a.passcode or _baidu_parse_surl(a.url)[1]
    ok, shareid, share_uk, bdstoken, err = _baidu_shareinfo(surl, pwd, ck)
    if not ok:
        print('❌ 读取百度分享失败：%s' % err); sys.exit(1)
    stoken, e = _baidu_resolve_stoken(surl, pwd, ck, shareid, share_uk, force_verify=True)
    if e:
        if 'errno=-12' in e:
            print(_baidu_verify_hint(ck, e)); sys.exit(1)
        print('❌ ' + e); sys.exit(1)
    out = []
    e2 = _baidu_collect(surl, pwd, ck, shareid, share_uk, out, stoken=stoken)
    if e2:
        print('❌ 列文件失败：%s' % e2); sys.exit(1)
    files = [r for r in out if not r['isdir']]
    if a.match:
        files = [f for f in files if a.match in f['name']]
    if not files:
        print('❌ 没有可转存的文件'); sys.exit(1)
    items = [(f['fs_id'], f['name']) for f in files]
    ok2, err2 = _baidu_transfer(surl, pwd, ck, shareid, share_uk, bdstoken, items, to_path=(a.to or '/'))
    if not ok2:
        print(f'❌ 转存失败：{err2}'); sys.exit(1)
    print(f'✅ 转存完成：{len(items)} 个文件 → 网盘（{a.to or "我的网盘根"}）')
    sys.exit(0)

# ══════════════════ 自检（原探源司 self-check ㉓/㉓b，迁移时判据未改）══════════════════
def cmd_self_check(_a=None):
    """网盘模块自检。两项判据来自探源司，迁移时一字未改。

    为什么这两项值钱：
      ① 用户贴的是**整段分享文案**（含口令 `/~xxx~/`），口令长得很像 id；
         认错了就会拿口令去查分享，报"分享不存在"，而真因是解析错了。
      ② 412 的成因是机房 IP 段被 CDN 边缘拒，**不是 IPv6、不是文件坏**。
         归因错了，后面所有处置都是错的——这类错不会报错、不会变红，只会把人指向无效动作。
    """
    rs = []

    txt = ('我用夸克网盘给你分享了「夸克上传文件」，点击链接或复制整段内容，'
           '打开「夸克APP」即可获取。祄七另枫诶并闭页冉为喔汢 /~d9803bYsb2~:/\n'
           '链接：https://pan.quark.cn/s/9d5b78140523 查看链接中文件')
    hit = (pan_parse_share(txt) == '9d5b78140523')
    clean = (pan_parse_share('https://pan.quark.cn/s/abc123') == 'abc123'
             and pan_parse_share('随便一段没有链接的话') == '')
    base = (pan_parse_share('/~d9803bYsb2~/') == '')
    rs.append(('网盘取料·整段文案认出id且口令不误认', hit, clean, base))

    hit_why = clean_why = base_why = False
    try:
        tree = ast.parse(open(__file__, encoding='utf-8').read())
        fn = next((n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == 'cmd_pan_pull'), None)
        lits = [n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)] if fn else []
        text = '\n'.join(lits)
        hit_why = ('机房' in text and '412' in text)
        bad = [k for k in ('在有 IPv6 的机器上', '换 IPv6 机器') if k in text]
        clean_why = not bad
        base_why = ('坏' in text)
    except Exception as e:
        print(f'  ⚠️ 归因探针异常：{type(e).__name__}: {e}')
    rs.append(('网盘412归因·机房IP段而非IPv6', hit_why, clean_why, base_why))

    ok = 0
    for name, h, c, b in rs:
        good = h and c and b
        ok += 1 if good else 0
        print(f"  {'✅' if good else '❌'} {name}：捕获={'是' if h else '否'}"
              f" 清理后清零={'是' if c else '否'} 假阳性基线={'净' if b else '脏'}")
    print(f"\n网盘模块自检 {ok}/{len(rs)} 通过")
    return 0 if ok == len(rs) else 1


# ══════════════════ CLI ══════════════════
def build_parser():
    ap = argparse.ArgumentParser(prog='pan.py', description='网盘分享取料：清单/下载/转存/删除')
    sp = ap.add_subparsers(dest='cmd', required=True)

    p1 = sp.add_parser('info', help='列分享清单（只走 API，IPv4 环境也能成功）')
    p1.add_argument('--url', required=True, help='分享链接或整段分享文案')
    p1.add_argument('--passcode', default='', help='提取码（无则留空）')
    p1.add_argument('--limit', type=int, default=500, help='最多遍历条目数')
    p1.add_argument('--json', action='store_true')

    p2 = sp.add_parser('pull', help='下载文件（机房 IP 段可能被 CDN 拒绝，会如实报）')
    p2.add_argument('--url', required=True)
    p2.add_argument('--passcode', default='')
    p2.add_argument('--outdir', default='.')
    p2.add_argument('--match', default='', help='只下文件名含该子串的')
    p2.add_argument('--timeout', type=int, default=120)

    p3 = sp.add_parser('save', help='转存分享到你的网盘（需登录态 cookie）')
    p3.add_argument('--url', required=True)
    p3.add_argument('--passcode', default='')
    p3.add_argument('--fid', default='', help='只转存该 fid（默认全部）')
    p3.add_argument('--match', default='', help='只转存文件名含该子串的')
    p3.add_argument('--to', default='0', help='目标目录 fid，0=根目录')
    p3.add_argument('--json', action='store_true')

    p4 = sp.add_parser('rm', help='删除你自己网盘里的文件/目录（先预演，--yes 才真删）')
    p4.add_argument('--pdir', default='0', help='从哪个目录开始列，0=根目录')
    p4.add_argument('--recursive', action='store_true', help='递归进入子目录')
    p4.add_argument('--match', default='', help='只删文件名含该子串的')
    p4.add_argument('--fid', default='', help='直接指定 fid（逗号分隔），优先于 --match')
    p4.add_argument('--platform', default='quark', choices=['quark', 'uc'])
    p4.add_argument('--yes', action='store_true', help='确认执行删除（缺省仅预演列出）')
    p4.add_argument('--since', default='', help='只删创建时间晚于该点（N分钟/毫秒戳/日期）')
    p4.add_argument('--undo', default='', help='按转存快照精确撤销：last 或快照 id')

    sp.add_parser('self-check', help='网盘模块自检（识别 id / 412 归因）')
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    return {'info': cmd_pan_info, 'pull': cmd_pan_pull, 'save': cmd_pan_save,
            'rm': cmd_pan_rm, 'self-check': cmd_self_check}[a.cmd](a)


if __name__ == '__main__':
    main()
