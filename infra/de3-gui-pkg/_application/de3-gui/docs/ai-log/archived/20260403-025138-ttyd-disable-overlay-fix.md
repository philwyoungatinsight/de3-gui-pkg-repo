# 20260403-025138 — Fix ttyd overlay and 404: use -t disableResizeOverlay, drop --once and --index

## Root causes

1. **CSS approach wrong**: The overlay div in ttyd 1.6.3's bundled xterm.js is created
   dynamically and styled via `.style` (inline), not via a CSS class. `.xterm-overlay`
   CSS targeting was ineffective. ttyd has a dedicated `-t disableResizeOverlay=true`
   client option that disables it via the ttyd protocol.

2. **`--once` caused the 404**: `--once` makes ttyd exit after the WebSocket session
   ends. Any iframe reload or reconnect attempt hits a dead port → 404. Since we track
   `_ttyd_proc` and call `terminate()` on the next `_start_ttyd()` call, `--once` is
   not needed.

3. **`--index` with patched HTML was unnecessary complexity**: The probe-fetch-patch
   pipeline was only needed for the CSS approach; now removed entirely.

## Changes

- `_start_ttyd()`: removed `--once` and `--index`; added `-t disableResizeOverlay=true`
- Removed `_prepare_ttyd_custom_index()`, `_TTYD_PATCHED_INDEX`, and the startup call
- Removed `ttyd_index_patched.html` from `.gitignore` (file no longer generated)
- Deleted `homelab_gui/ttyd_index_patched.html` (was gitignored, but cleaned up)
