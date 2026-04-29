# 20260403-025533 — Fix ttyd NxM overlay: patch resizeOverlay=!0 → !1 in fetched JS

## Root cause
`-t disableResizeOverlay=true` does nothing in ttyd 1.6.3. That flag sends a WebSocket
command *after* the terminal is initialised, but the constructor has already set
`this.resizeOverlay=!0` (true). The overlay fires on the first resize event (terminal
fit) before any command is processed.

## Fix
`_prepare_ttyd_custom_index()` (restored): fetches ttyd's self-contained HTML once at
startup, replaces `this.resizeOverlay=!0` → `this.resizeOverlay=!1` (exactly 1
occurrence in the constructor), writes `ttyd_index_patched.html`.
`_start_ttyd()` passes `--index ttyd_index_patched.html` when the file is available;
falls back to ttyd's default index if patching fails (version mismatch safety check).
`--once` remains absent (keeps ttyd alive across iframe reloads).
`ttyd_index_patched.html` is gitignored (generated at startup).
