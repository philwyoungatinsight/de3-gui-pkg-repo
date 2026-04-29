# 20260404-232230 — Waves panel: dropdown view switcher + Tail wave log button

## Changes

### Object Viewer header: tab buttons → dropdown

The two solid/ghost tab buttons ("Unit Params" / "Waves") were replaced with a
single `rx.dropdown_menu` that shows the current view name + "▾".  Clicking it
reveals the two options; selecting one calls `AppState.set_object_viewer_mode`.
This frees horizontal space in the header bar.

### "⏵ Tail" button in the Waves controls

A new button appears in the Waves controls bar (right of "↺") when
`_WAVE_TAIL_CMD` is non-empty.  Clicking it calls `tail_wave_log`, which sets
`shell_cwd = $HOME` and `shell_initial_cmd = _WAVE_TAIL_CMD`, opening the
command in the terminal panel.

### `tail_wave_log` handler (`AppState`)

```python
def tail_wave_log(self):
    if not _WAVE_TAIL_CMD:
        return
    self.shell_cwd = str(Path.home())
    self.shell_initial_cmd = _WAVE_TAIL_CMD
```

### `_WAVE_TAIL_CMD` module-level constant

Read from `de-gui.yaml` `config.wave_tail_cmd` at import time (same pattern as
`_WAVE_RECENT_HIGHLIGHT_SECS`).  Defaults to `""` (button hidden).

### `config/de-gui.yaml` — new key `wave_tail_cmd`

Default command replicates `_watch_wave_logs`:
```
log_file="$HOME/.run-waves-logs/latest/run.log";
[ -f "$log_file" ] || { echo "No run.log found at $log_file"; exit 1; };
echo "Tailing $log_file (restarts if silent for 2s)…";
while true; do timeout 2s tail -99f "$log_file"; sleep 0.5; done
```
Stored as a YAML `>-` block scalar (no trailing newline).  Empty string
disables the button.
