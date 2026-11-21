#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify/tests 入口：转发到判据唯一真源 scripts/test_fetch_tristate.py。

判据实体与文档见：能力层/tvbox/skills/probe-hub/scripts/test_fetch_tristate.py
（此处只做 verify glob 发现的薄壳，M2 引用不复制）。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, '能力层', 'tvbox', 'skills', 'probe-hub',
                   'scripts', 'test_fetch_tristate.py')

spec = importlib.util.spec_from_file_location('fetch_tristate_src', SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sys.exit(m.main())
