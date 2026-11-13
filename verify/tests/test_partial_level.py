#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_partial_level.py — ◐（环境欠账）与 ·（结构性不适用）必须分得开

【为什么需要】
v0.8.36 之前，三个检查器把「该装没装」和「本来就不该管」都记成 `·` 并同样返回 2。
于是 verify.sh 输出「技能契约 2 项无法判定」时，看的人分不清：
  · tvbox-core 没有 SKILL.md —— 它永远如此，看见了也不用动
  · library 技能没装        —— 该去装一下，否则 22 处外部引用全部没人校验
一个是「不该管」，一个是「欠账」，折叠成一个数就失去了指导下一步的价值。

【本文件锁的是什么】
  ✓ 装根存在、某个技能副本缺失  → ◐（漏装，该修），退出码仍 0
  ✓ 装根整体不存在              → ·（本机不装技能），退出码仍 0
  ✓ library 未安装              → ◐（该装），退出码 2（不阻断）
  ✓ core-8 缺失但 rules 目录在  → ✗（真源丢失，真问题），退出码 2
  ✓ rules 目录整个不存在        → ·（lite 形状），退出码 0
回归的意义：以后谁把 ◐ 改回 ·（或反之），上面任一条立刻红。

退出码：0 全通 / 1 有用例不符
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SK_CHK = os.path.join(ROOT, 'verify', 'skill_contract_check.py')
LIB_CHK = os.path.join(ROOT, 'verify', 'lib_refs_check.py')
TERM_CHK = os.path.join(ROOT, 'verify', 'terminology_check.py')

fails = []


def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


def run(args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True, timeout=180, env=e)
    return p.stdout + p.stderr, p.returncode


def build_repo():
    tmp = tempfile.mkdtemp(prefix='partial-')
    repo = os.path.join(tmp, 'repo')
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))
    return tmp, repo


def main():
    if not all(os.path.isfile(x) for x in (SK_CHK, LIB_CHK, TERM_CHK)):
        print('  ✗ 三个检查器缺件，无法测试')
        return 1

    tmp, repo = build_repo()
    try:
        print('真仓三档计数（基线）')
        out, rc = run([SK_CHK, '--repo', repo])
        check('基线 rc=0', rc == 0, f'rc={rc}')
        check('汇总行含 ◐ 与 · 两列', '◐（环境欠账）' in out and '·（不适用）' in out, out[-300:])
        check('基线 ◐=0（真仓没有漏装）', '0 ◐' in out, [l for l in out.split('\n') if '结果：' in l])

        print('\n① 装根在、技能缺失 → ◐（该装）而非 ·（不该管）')
        inst = os.path.join(tmp, 'install-partial')
        os.makedirs(inst)
        shutil.copytree(os.path.join(repo, '通用层/skills/space-hub'),
                        os.path.join(inst, 'space-hub'),
                        ignore=shutil.ignore_patterns('__pycache__'))
        out, rc = run([SK_CHK, '--repo', repo, '--install', inst])
        check('rc=0（漏装不阻断）', rc == 0, f'rc={rc}')
        check('缺失的技能记 ◐ 且理由含「漏装」',
              '◐ [C5] artifact-store: 安装副本缺失' in out and '漏装' in out,
              [l for l in out.split('\n') if 'C5] artifact-store' in l])
        check('缺失的技能不再记 ·',
              not any('· [C5] artifact-store' in l for l in out.split('\n')), out[:200])

        print('\n② 装根整体不存在 → ·（本机不装技能）')
        out, rc = run([SK_CHK, '--repo', repo, '--install', '/nonexistent-partial-xyz'])
        check('rc=0（不适用不阻断）', rc == 0, f'rc={rc}')
        check('记 · 且理由含「不适用」',
              '· [C5] artifact-store: 安装根不存在' in out and '不适用' in out,
              [l for l in out.split('\n') if 'C5] artifact-store' in l])

        print('\n③ library 未安装 → ◐（该装），退出码 2')
        out, rc = run([LIB_CHK], env={'LIB_REFS_LIB': '/nonexistent-lib-xyz',
                                      'LIB_REFS_ROOT': repo, 'LIB_REFS_NO_PROBE': '1'})
        check('rc=2（无法校验，不阻断也不假绿）', rc == 2, f'rc={rc}')
        check('文案是「环境欠账」不是「无法判定」', '◐ 环境欠账' in out and '无法判定' not in out.split('\n')[0],
              out.split('\n')[0])
        check('报出有多少类引用正等着校验', '类外部引用' in out, out.split('\n')[0])

        print('\n④ core-8 缺失但 rules 目录在 → ✗（真源丢失）')
        lite = os.path.join(tmp, 'lite-with-rules')
        os.makedirs(os.path.join(lite, '通用层', 'rules'))
        os.makedirs(os.path.join(lite, 'verify'))
        shutil.copy(os.path.join(repo, 'verify/rule_map.json'), os.path.join(lite, 'verify'))
        out, rc = run([TERM_CHK, '--repo', lite])
        check('rc=2（真问题要红）', rc == 2, f'rc={rc}')
        check('T1 记 ✗ 且理由含「真源丢失」', '✗ [T1]' in out and '真源丢失' in out,
              [l for l in out.split('\n') if '[T1]' in l])
        check('T4 同样记 ✗', '✗ [T4]' in out, [l for l in out.split('\n') if '[T4]' in l])

        print('\n⑤ rules 目录整个不存在 → ·（lite 形状，不该管）')
        lite2 = os.path.join(tmp, 'lite-no-rules')
        os.makedirs(lite2)
        out, rc = run([TERM_CHK, '--repo', lite2])
        check('rc=0（不适用不阻断）', rc == 0, f'rc={rc}')
        check('T1 记 · 且理由含「不适用」', '· [T1]' in out and '不适用' in out,
              [l for l in out.split('\n') if '[T1]' in l])

        print('\n⑥ 三档互斥（同一个技能不能既 ◐ 又 ·）')
        out, rc = run([SK_CHK, '--repo', repo, '--install', inst])
        for name in ('artifact-store', 'space-hub'):
            levels = [l.split('[')[0].strip() for l in out.split('\n') if f'] {name}:' in l]
            bad = [l for l in levels if l not in ('✓', '✗', '⚠', '◐', '·')]
            check(f'{name} 的 C5 只有一个状态', len([l for l in out.split('\n')
                                                    if 'C5]' in l and f'] {name}:' in l]) == 1, levels)
            check(f'{name} 无未知状态符号', not bad, bad)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print(f'✗ {len(fails)} 项未通过：{fails[:5]}')
        return 1
    print('✓ ◐ 与 · 已分开：欠账该修、不适用不该管，退出码都不阻断')
    return 0


if __name__ == '__main__':
    sys.exit(main())
