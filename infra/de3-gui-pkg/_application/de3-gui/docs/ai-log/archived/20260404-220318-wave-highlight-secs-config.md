# 20260404-220318 — wave_recent_highlight_secs configurable in de-gui.yaml

Added `config.wave_recent_highlight_secs` to `config/de-gui.yaml` (default: 30).
Read at startup into `_WAVE_RECENT_HIGHLIGHT_SECS: int` module-level constant.
The threshold check in `refresh_wave_log_statuses` now uses the constant instead
of a hardcoded literal.
