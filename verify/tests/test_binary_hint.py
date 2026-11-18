#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据：next_anchor.binary_hint 二进制自动出场软提示。
正反向 + 病15（识别范围=对象范围）：中文目标名无扩展名须靠动词命中；普通文字不误伤。
判据对象=真函数（按路径加载 next_anchor.py 直喂样本），不查源码字符串存在（病15）。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(ROOT, 'hooks', 'next_anchor.py')

spec = importlib.util.spec_from_file_location('next_anchor', ENGINE)
na = importlib.util.module_from_spec(spec)
spec.loader.exec_module(na)

fails = []


def ck(label, cond, detail=''):
    ok = bool(cond)
    print(('  ✓ ' if ok else '  ✗ ') + label + ('' if ok else '  ← ' + str(detail)))
    if not ok:
        fails.append(label)


print('── 正向（真命中）──')
ck('纯 .apk 路径命中', bool(na.binary_hint('详细看一下 weixin/云取_2.7.12.apk.1.1')),
   na.binary_hint('详细看一下 weixin/云取_2.7.12.apk.1.1'))
ck('.dex 命中', bool(na.binary_hint('扒 classes.dex 的类源码')))
ck('.so 命中', bool(na.binary_hint('解包 lib/arm64/libaria2c.so')))
ck('.jar 命中', bool(na.binary_hint('反编译 ysbox.jar')))
ck('中文名+逆向动词命中（病15 核心：无扩展名）',
   bool(na.binary_hint('熔铸司出场，把云取这个应用的类源码扒出来')),
   na.binary_hint('熔铸司出场，把云取这个应用的类源码扒出来'))
ck('动词+二进制名词命中', bool(na.binary_hint('加载 jadx 看字节码')))

print('── 反向（不误伤）──')
ck('普通中文对话不误伤', na.binary_hint('继续') == '', na.binary_hint('继续'))
ck('普通描述不误伤', na.binary_hint('帮我看看这份报告的结论') == '')
ck('单独「出场」无二进制对象不误伤', na.binary_hint('出场顺序你定') == '',
   na.binary_hint('出场顺序你定'))
ck('仅名词无动词不误伤', na.binary_hint('这里有个 apk 文件') == '',
   na.binary_hint('这里有个 apk 文件'))
ck('空串不误伤', na.binary_hint('') == '')
ck('None 不误伤', na.binary_hint(None) == '')

print('── 三态与提示内容 ──')
ck('命中返回含「熔铸司 foundry」', '熔铸司 foundry' in na.binary_hint('看这个 apk 的类源码'))
ck('软提示不含拦截措辞', na.binary_hint('看这个 apk 的类源码') != ''
   and 'deny' not in na.binary_hint('看这个 apk 的类源码').lower())

print('── 端到端（UserPromptSubmit 真跑 hook，防「函数对/没接线」假绿）──')
import json as _j, subprocess as _sp


def hook_ctx(prompt):
    payload = _j.dumps({'hook_event_name': 'UserPromptSubmit', 'prompt': prompt,
                        'cwd': os.path.dirname(ROOT)}, ensure_ascii=False)
    try:
        p = _sp.run([sys.executable, ENGINE], input=payload, text=True,
                    capture_output=True, timeout=30)
        out = _j.loads(p.stdout)
        return out.get('hookSpecificOutput', {}).get('additionalContext', ''), p.returncode
    except Exception as e:
        return '__ERR__' + str(e), -1


_hit, _rc_hit = hook_ctx('详细看一下云取这个应用的类源码')
ck('真 payload 注入提示进 additionalContext', '熔铸司 foundry' in _hit, _hit[:80])
ck('命中路径不拦截（rc=0）', _rc_hit == 0, _rc_hit)
_miss, _rc_miss = hook_ctx('继续')
ck('无关 prompt 不注入出场提示', '熔铸司 foundry' not in _miss, _miss[:80])
ck('无关路径同样不拦截（rc=0）', _rc_miss == 0, _rc_miss)

print('\n结果：%s' % ('全部通过' if not fails else str(len(fails)) + ' 项失败：' + ','.join(fails)))
sys.exit(0 if not fails else 2)
