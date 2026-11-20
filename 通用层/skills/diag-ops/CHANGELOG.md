# diag-ops CHANGELOG

## v1.0.0（2026-11-21）
- 新建：诊断运维三件套（云取借鉴 53+3+48）。
- `scripts/diag_ops.py`：`reconcile_tasks`（53 启动对账，queued0/running1→paused2，幂等不改入参）；`capture_crash`/`export_diag`（3 崩溃现场，crash_<毫秒>.txt + 最近3份各截16384字 + logcat末3万行，窗口可注入）；`redact`（48 日志脱敏，token/密码/手机号正则表→<redacted>，规则可注入）。三态 ok/skipped/unknown，fail-closed。
- 证据等级：53 SQL 方法体实证，3/48 DEX 类名+转录归纳、方法体未 dump，标注不冒称完整还原。
- 判据：`verify/tests/test_diag_ops.py`（A-E 五层，元变异有牙：注入脱敏规则/改坏正则/改中断态常量/注入导出窗口）。
