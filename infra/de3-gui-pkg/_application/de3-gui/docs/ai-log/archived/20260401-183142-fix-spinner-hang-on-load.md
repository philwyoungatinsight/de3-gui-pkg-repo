# ai-log: Fix spinner hanging forever on page load

**Date:** 2026-04-01  
**Branch:** feat/gui

## Problem

The "Scanning infra…" spinner would hang forever on the initial page load. The
user had to click "refresh app" to make the page finish loading.

## Root cause

`on_load` has a double-fire guard: if the test-state marker file is less than 5s
old and no test-state file exists, it early-returns to avoid overwriting test
state. This path returned `AppState.install_resizer` without setting
`is_loading = False`.

Since `is_loading` defaults to `True`, any page load that hit the early-return
(e.g. app restart in dev mode, or browser reload within 5s of a previous load)
left the spinner running indefinitely.

## Fix

Added `self.is_loading = False` before the early return:

```python
if not _TEST_STATE_FILE.exists() and secs_since_test < 5.0:
    self.is_loading = False   # ← added
    return AppState.install_resizer
```

## Files modified
- `homelab_gui/homelab_gui.py`
