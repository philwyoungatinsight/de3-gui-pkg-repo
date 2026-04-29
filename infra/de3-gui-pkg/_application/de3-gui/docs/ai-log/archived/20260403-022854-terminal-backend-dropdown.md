# 20260403-022854 — Terminal backend dropdown (embedded vs native)

## Motivation
The embedded xterm.js terminal is sluggish. Users want to be able to choose a
native terminal emulator (gnome-terminal, xterm, etc.) as an alternative.

## Changes

### Module-level (`homelab_gui.py`, near `_CHROME_PROFILES_CACHE`)
- `_KNOWN_NATIVE_TERMINALS` — static list of supported native terminal emulators
- `_detect_terminal_backends()` — probes PATH via `shutil.which`; always prepends
  `{"id": "embedded", "label": "Embedded (xterm.js)"}` then appends any found natives
- `_TERMINAL_BACKENDS` — module-level cache of available backends
- `_launch_native_terminal(terminal_id, cwd, cmd="")` — launches the chosen terminal
  emulator via `subprocess.Popen(..., start_new_session=True)`. When `cmd` is non-empty
  the inner bash invocation is `bash --login -c "<cmd>; exec bash"` so the shell stays
  open after the command finishes.
  Supports: gnome-terminal, xterm, konsole, alacritty, tilix, kitty.

### State var
- `terminal_backend: str = "embedded"` added after `terminal_hide_initial_cmd`

### `open_shell` / `open_ssh_terminal`
Both methods now check `self.terminal_backend`: if not `"embedded"`, call
`_launch_native_terminal(...)` and return early (no iframe shown). Otherwise
behave as before.

### `set_terminal_backend(backend: str)` handler
Sets `self.terminal_backend` and saves config.

### Save / load (`_save_current_config` / `on_load`)
`terminal_backend` persisted in `state/current.yaml` under `menu`. On load,
validated against the set of available backend IDs; falls back to `"embedded"`.

### Appearance menu — Terminal section
Added a "Backend" row with an `rx.select` dropdown below "Hide auto-run commands".
Only backends detected on the current machine are shown.
