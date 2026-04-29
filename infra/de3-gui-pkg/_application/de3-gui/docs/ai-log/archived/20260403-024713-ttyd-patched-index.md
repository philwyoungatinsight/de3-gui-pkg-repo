# 20260403-024713 — Fix ttyd white screen: generate patched index at startup

## Problem
The previous fix used a custom `ttyd_index.html` that referenced `app.css` and `app.js`
as separate assets. In ttyd 1.6.3 (Ubuntu apt package), everything is inlined into a
single self-contained HTML (~446KB) — those external files don't exist, causing a blank
white page.

## Fix

### `_prepare_ttyd_custom_index()` (new function)
Spins up a temporary `ttyd --once bash` on a free port, fetches its self-contained
index HTML via `urllib.request`, injects `.xterm-overlay{display:none!important}`
before `</head>`, writes the result to `homelab_gui/ttyd_index_patched.html`, and
returns the path. Called once at module load when `_TTYD_AVAILABLE` is True.

### `_start_ttyd()` — uses patched index when available
Passes `--index <path>` only when `_TTYD_PATCHED_INDEX` is set; falls back to ttyd's
default index otherwise.

### Removed `homelab_gui/ttyd_index.html`
The static placeholder file was wrong; the generated `ttyd_index_patched.html` replaces it.

### `.gitignore` — `homelab_gui/ttyd_index_patched.html`
Generated at runtime; not committed.
