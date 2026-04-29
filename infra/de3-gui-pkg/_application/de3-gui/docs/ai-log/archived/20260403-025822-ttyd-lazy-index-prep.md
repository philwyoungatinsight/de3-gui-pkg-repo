# 20260403-025822 — Fix startup loop: make ttyd index prep lazy

## Problem
`_prepare_ttyd_custom_index()` was called at module import time. It starts a probe ttyd
subprocess and sleeps up to 2s waiting for it. Reflex imports the module repeatedly
during startup and hot-reload, so this blocked the startup loop indefinitely.

## Fix
Removed the eager `_TTYD_PATCHED_INDEX = _prepare_ttyd_custom_index()` call from
module level. `_start_ttyd()` now prepares the patched index lazily on its first
invocation (`_TTYD_PATCHED_INDEX is None` guard). The 2-second probe only runs when
the user first opens a ttyd terminal, not on every app start.
