## v1.0.0 — 2026-11-20
- 云取借鉴立项二期：下载探测技能，取自云取 DEX 借鉴点 28（Range 能力探测识别 text/html 错误页）+ 52（性能诊断 + SSRF 拒内网）。
- 薄壳 `scripts/probe.py` 纯标准库实现：probe() 探测 + is_internal() SSRF 判定 + 三态结果。
- 判据 `verify/tests/test_download_probe.py`：函数级真实输入 + 元变异有牙。
- 触发样本 T8/N6/B3 在册；C9 前置 / C10 词桥 / C11 工具白名单对齐。
