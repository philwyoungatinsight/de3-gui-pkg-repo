# 20260403-024040 — ttyd as embedded terminal backend (in-panel, not separate window)

## What changed

### Module-level (terminal backends section)
- `_TTYD_AVAILABLE: bool` and `_TTYD_INSTALL_CMD: str` — set by `_detect_terminal_backends()`
- `_ttyd_proc` — module-level reference to the running ttyd subprocess
- `_find_free_port()` — binds to port 0, returns the OS-assigned port
- `_start_ttyd(cwd, cmd="") -> int` — kills any running ttyd, starts a new one with
  `--once` (exits on session disconnect), returns the port
- `_detect_terminal_backends()` — always adds `"ttyd"` entry (label shows
  "(not installed)" when unavailable); sets `_TTYD_AVAILABLE` and `_TTYD_INSTALL_CMD`

### State vars
- `ttyd_port: int = 0` — port of the running ttyd process

### `terminal_iframe_url` (computed var)
- When `terminal_backend == "ttyd"` and `ttyd_port > 0`, returns `http://localhost:{port}`
- Otherwise falls through to existing xterm.js URL logic

### `open_shell` / `open_ssh_terminal`
- `cwd=""` path (close button): clears `shell_cwd`, `shell_initial_cmd`, `ttyd_port`
- `ttyd` backend: calls `_start_ttyd(cwd, cmd)`, sets `ttyd_port`; also sets `shell_cwd`
  so the panel remains visible (existing `shell_cwd != ""` show-condition still works)

### `install_ttyd` handler
- Forces `ttyd_port = 0` (so `terminal_iframe_url` uses embedded path)
- Sets `shell_cwd` + `shell_initial_cmd` to run `_TTYD_INSTALL_CMD` in the embedded terminal

### Appearance menu — Terminal section
- When `_TTYD_AVAILABLE` is False and `terminal_backend == "ttyd"` (Reflex cond):
  shows a warning row with the install command text and an "Install" button that calls
  `install_ttyd` (runs the install in the embedded terminal panel)
