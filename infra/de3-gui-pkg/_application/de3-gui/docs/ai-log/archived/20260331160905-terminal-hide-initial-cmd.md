# Appearance option: Hide auto-run commands in terminal

## Summary

Added an Appearance menu toggle — "Hide auto-run commands" — that suppresses the display
of commands automatically sent to the terminal (e.g. `tail -99f <file>` from the Tail
button, SSH commands, etc.).  The command still executes; only its text is hidden.

---

## How it works

Commands are sent to the terminal by writing to the PTY master fd after a short delay.
Without suppression, the PTY's line discipline echoes the characters back, making them
appear in xterm.js as if the user typed them.

With suppression, `termios.ECHO` is cleared on the PTY master before the write, then
restored 50ms later (enough time for the line discipline to process the bytes).
The command executes silently; only its output is visible.

---

## Changes — `homelab_gui/homelab_gui.py`

### State var
```python
terminal_hide_initial_cmd: bool = True  # suppress display of auto-sent commands in terminal
```
Defaults to `True` (hidden).

### Save / restore
`_save_current_config` / `_restore_current_config` — persisted in `state/current.yaml`
under `menu.terminal_hide_initial_cmd`.

### Toggle handlers
`toggle_terminal_hide_initial_cmd(checked)` / `flip_terminal_hide_initial_cmd()`

### `terminal_iframe_url` computed var
Appends `&hide_cmd=1` to the terminal URL when `terminal_hide_initial_cmd` is True and
an `initial_cmd` is present.

### `_terminal_ws_handler`
Parses `hide_cmd` query param.  When set, wraps the `_send_initial` write in a
`termios.ECHO` disable/restore cycle:
```python
attr[3] &= ~termios.ECHO
tcsetattr(master_fd, TCSANOW, attr)
os.write(master_fd, cmd + "\n")
await sleep(0.05)
attr[3] = orig_lflag
tcsetattr(master_fd, TCSANOW, attr)
```

### Appearance menu
New "Terminal" section containing the "Hide auto-run commands" checkbox item.

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331160905-terminal-hide-initial-cmd.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
