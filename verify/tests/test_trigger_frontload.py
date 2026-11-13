#!/usr/bin/env python3
"""test_trigger_frontload.py — C9/C10 触发判据的变异回归（拆掉实现必须翻红）

C9/C10 是 v0.8.31 新增的两条：判「用户说人话时技能会不会被想起来」。
判据全绿不代表判据有效——本测试用**构造样本**逐一验证：

  F1 正例：当用户句式在前 40 字 + 前 80 字命中 3 个触发词      → C9 必须绿
  F2 反例：触发词埋在 400 字处（今天实测的真实形态）           → C9 必须红（红因须指向「当用户」）
  F3 反例：有当用户句式，但前 80 字只命中 1 个触发词            → C9 必须红（红因须指向「命中数」）
  F4 边界：前 40 字刚好没有、第 41 字才有                      → C9 必须红（窗口是硬界）

  B1 正例：样本 prompt 的二字词出现在描述里                    → C10 必须绿
  B2 反例：样本 prompt 与描述毫无词桥                          → C10 必须红（须报出该条编号）
  B3 反例：唯一重合是泛用词（「用户」「问题」）                → C10 必须红（泛用词不算桥，防假绿）
  B4 正例：英文/数字词桥（token / 10%）                        → C10 必须绿

破坏实现的方式：把窗口常量改大、把 GENERIC_BG 清空、把英文兜底删掉——
任一被改都必须让对应 case 翻红，否则判据形同虚设。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'verify'))

import skill_contract_check as sc  # noqa: E402

fails = []


def check(name, cond, detail=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' ｜ {detail}' if detail and not cond else ''))
    if not cond:
        fails.append(name)


# ── C9 触发前置 ────────────────────────────────────────────
print('C9 触发前置')

good = ('当用户说「本地瘦身」「手机变卡」「清理产物」时使用本技能。'
        '治理本地产物与记忆负担的总闸。能力：①LRU 归档；②记忆减负。不要用于：云端文档整理。'
        '触发词：本地瘦身 / 手机变卡 / 清理产物 / 产物归档。')
ok, msg = sc.check_frontload(good)
check('F1 正例（句式在前 + 命中 3 个）通过', ok, msg)

buried = ('治理本地产物与记忆负担的总闸，协调 LRU 归档、记忆与会话减负、上下文纪律，'
          '优先复用官方原生能力。' + '铺垫说明。' * 40 +
          '触发词：本地瘦身 / 手机变卡 / 清理产物。')
ok, msg = sc.check_frontload(buried)
check('F2 反例（触发词埋 400 字后）翻红', not ok and '当用户' in msg, msg)

few = ('当用户有本地清理需求时使用本技能。治理本地产物与记忆负担的总闸。'
       '能力：①LRU 归档。不要用于：云端整理。触发词：本地瘦身 / 手机变卡 / 清理产物。')
ok, msg = sc.check_frontload(few)
check('F3 反例（前 80 字仅 1 个触发词）翻红', not ok and '命中' in msg, msg)

edge = ('说明说明说明说明说明说明说明说明说明说明说明说明说明说明说明说明说明说明说明说明'
        '当用户说「本地瘦身」「手机变卡」「清理产物」时用。')
ok, msg = sc.check_frontload(edge)
check('F4 边界（第 41 字才有句式）翻红', not ok, msg)

# ── C10 样本词桥 ───────────────────────────────────────────
print('C10 样本词桥')

desc = ('当用户说「把文件夹搬到别处」「清理资料库」时使用本技能。能力：①搬迁；②清理。'
        '不要用于：源码编辑。触发词：搬节点 / 清理 / 建库 / 回执归档。')
samples_ok = ('### T01\n- Prompt：`把整个文件夹搬到别处去`\n'
              '### T02\n- Prompt：`帮我清理一下资料库里的空库`\n')
ok, unc = sc.check_bridge(desc, samples_ok)
check('B1 正例（样本有词桥）通过', ok, str(unc))

samples_bad = ('### T01\n- Prompt：`把整个文件夹搬到别处去`\n'
               '### T02\n- Prompt：`帮我写一首关于秋天的诗`\n')
ok, unc = sc.check_bridge(desc, samples_bad)
check('B2 反例（无词桥）翻红且报出 T02',
      (not ok) and any(i == 'T02' for i, _ in unc), str(unc))

samples_generic = ('### T01\n- Prompt：`用户的问题怎么处理`\n')
ok, unc = sc.check_bridge(desc, samples_generic)
check('B3 反例（只重合泛用词）翻红', not ok, str(unc))

desc_en = ('当用户说「token 不用每次输」时使用本技能。能力：①凭据。不要用于：业务加工。'
           '触发词：token / 换机 / 新设备。')
samples_en = ('### T01\n- Prompt：`token 怎么配，我不想每次输`\n'
              '### T02\n- Prompt：`先给 10% 的用户放量`\n')
desc_en2 = desc_en + '支持按 10% 用户放量。'
ok, unc = sc.check_bridge(desc_en2, samples_en)
check('B4 正例（英文/数字词桥）通过', ok, str(unc))

print()
if fails:
    print(f'✗ C9/C10 变异回归失败 {len(fails)} 项：{fails}')
    sys.exit(1)
print('✓ C9/C10 变异回归通过（8 用例：4 前置 + 4 词桥）')
