# 20260407-104041 — Waves panel: "▶ Run All" button

## Feature

New **"▶ Run All"** button in the waves panel menu bar. Clicking it opens a
confirmation dialog; confirming runs `./run -a` (apply all waves) in the
terminal and starts the wave status poll.

## Changes

### State var

```python
run_all_waves_dialog_open: bool = False
```

### Handlers

```python
def begin_run_all_waves(self):
    self.run_all_waves_dialog_open = True

def cancel_run_all_waves(self):
    self.run_all_waves_dialog_open = False

def confirm_run_all_waves(self):
    self.run_all_waves_dialog_open = False
    run_script = str(_STACK_DIR / "run")
    self.shell_cwd = str(_STACK_DIR)
    self.shell_initial_cmd = f"{run_script} -a"
    return rx.call_script(self._WAVE_POLL_START_JS)
```

### `waves_controls` (in `_right_panel_header`)

Added after the ↺ refresh button:

```python
rx.separator(orientation="vertical", height="16px"),
rx.button(
    "▶ Run All",
    size="1", variant="ghost", color_scheme="green",
    on_click=AppState.begin_run_all_waves,
    title="Apply all waves: ./run -a",
),
```

### Confirmation dialog

Added before the existing wave-destroy dialog in `bottom_right_panel`.
Shows the command (`./run -a`), Cancel and "Run all waves" (green) buttons.
