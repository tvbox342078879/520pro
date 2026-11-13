#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机指令「硬轨正文」→ 云端资料库副本 的同步器（v0.8.26）

## 为什么要有它

`手机指令.md` 的粘贴区是手机端注入用**真源**；云端那份 doc 是它的**镜像**，用来在
手机 App 里直接打开复制（本地路径手机打不开，GitHub raw 链接手机上也不稳）。

镜像靠人手更新必然过期：过期后手机上粘进去的是旧规则，而且**没有任何信号**告诉你它旧了。
本轮就是靠人手建了一次，下一次改粘贴区（比如再加 B 条）没人记得同步。

## 这个活交给谁（三层，缺一层都会有洞）

| 层 | 谁 | 作用 |
|---|---|---|
| 动作 | 本脚本 `sync_phone_directive.py` | 幂等同步：sha 一致就短路不调 API；写后**导出回读**比对 |
| 触发 | `hooks/pre-commit` 第②步 | 只在 `手机指令.md` 进本次提交时才跑自动同步 |
| 判据 | `verify.sh` 调本脚本 `--check` | **离线**判过期：状态登记的 sha ≠ 当前粘贴区 sha 即红 |

为什么要判据而不只靠触发：pre-commit 能被 `--no-verify` 绕过、也能在没装库的环境里跑；
判据是"过期这件事本身可见"，不依赖触发是否成功。

## 子命令

    python3 sync_phone_directive.py            # 同步（幂等；无变化直接 NOOP）
    python3 sync_phone_directive.py --check    # 离线判过期（verify.sh 用），过期 rc=1
    python3 sync_phone_directive.py --dry-run  # 只算不写

退出码（三态，别混）：
    0  已同步 / 无需同步       1  已过期（仅 --check）
    2  无法执行（环境/API 失败，**不是**"已过期"）   3  回读不一致（写进去了但内容对不上）

## 关键取舍

- **按标记行定位而不是行号**：行号会随任何一次编辑漂移，标记不会。
- **回读不做逐字比对**：写入后服务端会重排结构（段落/列表变成块），逐字比必然假红。
  改为「锚点 + 条数」的语义校验，能真正发现"没落地/落错/缺条"。
- **回读走 `get-doc-review` 而不是导出下载**：导出链路要先拿预签名地址再下载，
  在沙箱里会被 `export_node.py` 的 COS 域名/IP 校验挡掉（实测 `下载地址无效`）。
  `get-doc-review` 直接返回文档内容的块结构，一步到位、无外部下载面。
- **幂等靠状态文件**：`docs/手机指令云端副本.json` 记 nodeId + sha256；sha 相同就不发请求。
  这也是"回执≠回读"的落点——只有回读通过才写状态，失败不写，下次还会重试。
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

START_MARK = '## 【粘贴区 · 从下一行开始复制】'
END_MARK = '**【粘贴区 结束】**'
STATE_REL = 'docs/手机指令云端副本.json'
SRC_REL = '手机指令.md'
DEFAULT_TITLE = '手机指令粘贴区（复制即用）'


# ---------------------------------------------------------------- 粘贴区提取

def normalize(text):
    """粘贴区文本规范化：统一换行、去行尾空白、剥掉 HTML 注释行、去首尾空行。

    HTML 注释（`<!-- hard-rail: ... -->`）是给机检读的登记，不属于要粘进 App 的正文，
    必须剥掉——否则手机上一复制就把注释带进去。
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    out, in_comment = [], False
    for ln in text.split('\n'):
        s = ln.strip()
        if in_comment:
            if '-->' in s:
                in_comment = False
            continue
        if s.startswith('<!--'):
            if '-->' not in s:
                in_comment = True
            continue
        out.append(ln.rstrip())
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return '\n'.join(out) + '\n'


def extract_paste(md_text):
    """从 手机指令.md 全文里取出粘贴区正文（已规范化）。找不到标记就抛错。"""
    i = md_text.find(START_MARK)
    if i < 0:
        raise ValueError('找不到粘贴区起始标记：%s' % START_MARK)
    body = md_text[i + len(START_MARK):]
    j = body.find(END_MARK)
    if j < 0:
        raise ValueError('找不到粘贴区结束标记：%s' % END_MARK)
    return normalize(body[:j])


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def clause_count(text):
    return len(re.findall(r'(?m)^\s*[0-9]+\.\s', text))


# ---------------------------------------------------------------- 状态文件

def load_state(repo):
    p = os.path.join(repo, STATE_REL)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(repo, state):
    p = os.path.join(repo, STATE_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write('\n')


# ---------------------------------------------------------------- 回读校验

def _fold(s):
    """剥掉列表编号、块标签、markdown 记号与全部空白，只留字面内容。

    列表编号必须剥：源里是 `2. **三态诚实**：...`，回读里编号由 `<NumberedList>` 块表达、
    正文不再带 `2. `。不剥就会把"末句是一列表项"误判成内容缺失（T4 正例抓到的假红）。
    """
    s = re.sub(r'(?m)^\s*[0-9]+\.\s+', '', s)
    s = re.sub(r'<[^>]{1,200}>', '', s)
    s = re.sub(r'[\\*_`#>|]', '', s)
    return re.sub(r'\s+', '', s)


def pin_titles(source):
    """每条的小标题（`1. **全程简体中文**：...` 里的加粗段）。"""
    return re.findall(r'(?m)^\s*[0-9]+\.\s+\*\*(.+?)\*\*', source)


def _count_clauses(text):
    """条数。回读内容是块结构时数列表块，纯文本时数 `1. ` 行。"""
    if '<NumberedList' in text:
        return text.count('<NumberedList')
    return len(re.findall(r'(?m)^\s*[0-9]+\.\s', text))


def check_readback(exported_md, source_text):
    """回读校验：内容真落地了吗。

    不做逐字比对（服务端会重排块结构，必然假红），改为三条语义判据：
      A 首句、末句都在回读内容里（换了内容立刻死）
      B 条数一致（少一条立刻死）
      C 每条小标题都在回读内容里（错条、串条立刻死）
    返回 (ok, 说明列表)。
    """
    ex, src = _fold(exported_md), _fold(source_text)
    problems = []
    src_lines = [ln for ln in source_text.split('\n') if ln.strip()]
    if not src_lines:
        return False, ['源粘贴区为空']
    for label, line in (('首句', src_lines[0]), ('末句', src_lines[-1])):
        if _fold(line) not in ex:
            problems.append('%s 未出现在回读内容里' % label)
    n_src = clause_count(source_text)
    n_ex = _count_clauses(exported_md)
    if n_src != n_ex:
        problems.append('条数不一致：源 %d 条，回读 %d 条' % (n_src, n_ex))
    missing = [t for t in pin_titles(source_text) if _fold(t) not in ex]
    if missing:
        problems.append('回读里缺这些小标题：%s' % '、'.join(missing[:5]))
    return (not problems), problems


# ---------------------------------------------------------------- 资料库调用

def _skill_dir():
    """库 skill 的位置。先看环境变量，再退到默认安装路径——都能没有就报错。"""
    cands = []
    env = os.environ.get('CODEBUDDY_SKILL_DIR') or ''
    if env:
        cands.append(env)
        cands.append(os.path.join(env, 'library'))
    cands.append(os.path.expanduser('~/.codebuddy/skills/library'))
    for c in cands:
        if os.path.exists(os.path.join(c, 'space_api.py')):
            return c
    raise RuntimeError('找不到资料库 skill（space_api.py）；本机未安装则无法同步')


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def _api(skill, args):
    rc, out = _run([sys.executable, os.path.join(skill, 'space_api.py')] + args)
    line = ''
    for ln in out.splitlines():
        if ln.strip().startswith('{'):
            line = ln.strip()
            break
    if rc != 0 or not line:
        raise RuntimeError('API 调用失败（rc=%s）：%s' % (rc, (out.strip().splitlines() or [''])[0][:200]))
    data = json.loads(line)
    if 'error' in data and data.get('error'):
        raise RuntimeError('API 返回错误:%s' % str(data.get('error'))[:200])
    return data


def push_doc(skill, space_id, node_block_id, title, markdown):
    args = ['space.importer.create-doc', '--space-id', space_id, '--title', title,
            '--markdown', markdown]
    if node_block_id:
        args += ['--node-block-id', node_block_id]
    data = _api(skill, args)
    d = data.get('data') or {}
    nid = d.get('nodeBlockId')
    if not nid:
        raise RuntimeError('API 未返回 nodeBlockId，无法确认落地')
    return nid


def read_doc(skill, space_id, node_id):
    """回读文档内容（块结构）。比导出下载短一条链路，也不碰 COS 下载面。"""
    data = _api(skill, ['space.workspace.get-doc-review', '--space-id', space_id,
                        '--page-id', node_id, '--output-mode', 'markdown',
                        '--page-type', 'doc'])
    c = (data.get('data') or {}).get('content')
    if not c:
        raise RuntimeError('回读内容为空（接口未返回 content）')
    return c


def node_version(skill, node_id):
    try:
        data = _api(skill, ['space.workspace.node-info', '--node-id', node_id])
        return (data.get('data') or {}).get('node', {}).get('version')
    except Exception:
        return None


# ---------------------------------------------------------------- 主流程

def read_source(repo):
    p = os.path.join(repo, SRC_REL)
    with open(p, encoding='utf-8') as f:
        return f.read()


def do_check(repo):
    """离线判过期：只读本地文件，不联网。"""
    try:
        src = extract_paste(read_source(repo))
    except Exception as e:
        print('ERROR  粘贴区不可读：%s' % e)
        return 2
    st = load_state(repo)
    cur = digest(src)
    if not st.get('node_id'):
        print('STALE  尚未建立云端副本（状态文件缺 node_id）')
        return 1
    if st.get('sha256') != cur:
        print('STALE  云端副本已过期：登记 %s → 当前 %s（改过粘贴区没同步）'
              % ((st.get('sha256') or '?')[:8], cur[:8]))
        return 1
    print('FRESH  云端副本与真源一致（%s，%d 条，%d 字节）'
          % (cur[:8], clause_count(src), len(src.encode('utf-8'))))
    return 0


def do_sync(repo, dry_run=False):
    try:
        src = extract_paste(read_source(repo))
    except Exception as e:
        print('ERROR  粘贴区不可读：%s' % e)
        return 2

    st = load_state(repo)
    cur = digest(src)
    nbytes = len(src.encode('utf-8'))
    nclause = clause_count(src)
    title = st.get('title') or DEFAULT_TITLE

    if st.get('node_id') and st.get('sha256') == cur:
        print('NOOP   无需同步（sha %s 一致，%d 条 / %d 字节）' % (cur[:8], nclause, nbytes))
        return 0

    if dry_run:
        print('DRYRUN 将同步：%s → %s（%d 条 / %d 字节；node=%s）'
              % ((st.get('sha256') or '无')[:8], cur[:8], nclause, nbytes,
                 st.get('node_id') or '新建'))
        return 0

    try:
        skill = _skill_dir()
    except Exception as e:
        print('ERROR  %s' % e)
        return 2

    space_id = st.get('space_id') or os.environ.get('WB_SPACE_ID') or ''
    node_id = st.get('node_id') or ''

    try:
        if not space_id:
            # 只查一次：个人空间 id 拿不到就没法建
            sp = _api(skill, ['space.workspace.list-user-spaces', '--limit', '20'])
            for s in (sp.get('data') or {}).get('spaces', []) or []:
                if s.get('category') == 'personal':
                    space_id = s.get('spaceId')
                    break
            if not space_id:
                raise RuntimeError('取不到个人空间 spaceId')
        node_id = push_doc(skill, space_id, node_id, title, src)
    except Exception as e:
        print('ERROR  写入失败：%s' % e)
        return 2

    # —— 回读（只看回执就宣布成功，正是本项目踩过的坑）
    try:
        exported = read_doc(skill, space_id, node_id)
    except Exception as e:
        print('ERROR  %s' % e)
        return 2

    ok, probs = check_readback(exported, src)
    if not ok:
        print('READBACK_FAIL  已提交但导出内容对不上，状态不落盘（下次会重试）：')
        for p in probs:
            print('       - %s' % p)
        return 3

    ver = node_version(skill, node_id)
    state = {
        'node_id': node_id,
        'url': 'https://www.workbuddy.cn/space/d/%s' % node_id,
        'space_id': space_id,
        'title': title,
        'source': '%s 粘贴区（两标记行之间，已剥 HTML 注释）' % SRC_REL,
        'sha256': cur,
        'bytes': nbytes,
        'clauses': nclause,
        'readback_bytes': len(exported.encode('utf-8')),
        'node_version': ver,
        'synced_at': __import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds'),
    }
    save_state(repo, state)
    print('SYNCED 已同步 %s（v%s，%d 条 / %d 字节，回读通过）'
          % (node_id, ver, nclause, nbytes))
    return 0


def main():
    ap = argparse.ArgumentParser(description='手机指令粘贴区 → 云端资料库副本同步器')
    ap.add_argument('--repo', default=os.getcwd(), help='仓库根（默认当前目录）')
    ap.add_argument('--check', action='store_true', help='离线判过期（verify.sh 用）')
    ap.add_argument('--dry-run', action='store_true', help='只算不写')
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    if a.check:
        return do_check(repo)
    return do_sync(repo, a.dry_run)


if __name__ == '__main__':
    sys.exit(main())
