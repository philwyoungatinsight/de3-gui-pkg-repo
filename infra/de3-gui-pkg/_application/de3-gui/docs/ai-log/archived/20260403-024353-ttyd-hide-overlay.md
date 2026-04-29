# 20260403-024353 — Hide ttyd size overlay ("109x28" splash)

## Problem
ttyd's built-in xterm.js shows a resize overlay (e.g. "109x28") on first connect.

## Fix
- `homelab_gui/ttyd_index.html` — custom index served via `ttyd --index`.
  Identical structure to ttyd's built-in index (loads `app.css`, `#terminal-container` div,
  loads `app.js`), plus one inline style rule:
  `.xterm-overlay { display: none !important; }`
- `_start_ttyd()` passes `--index <path>/ttyd_index.html` to the ttyd subprocess.
  ttyd still serves its own `app.js` and `app.css`; only the HTML is replaced.
