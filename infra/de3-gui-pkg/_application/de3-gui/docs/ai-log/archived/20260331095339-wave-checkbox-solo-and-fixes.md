# Wave Checkbox: Solo Mode, Bug Fix, and Config-Data Quote Default

## Summary

Three related changes to the waves table and one to the file viewer search.

---

## 1. `config_data_quote_path` default → `false`, configurable in `de-gui.yaml`

### What changed
- `_DEFAULT_CONFIG_DATA_QUOTE_PATH` module-level constant reads `file_viewer.config_data_quote_path`
  from `de-gui.yaml` (default `false`).
- State var `config_data_quote_path` now defaults to `_DEFAULT_CONFIG_DATA_QUOTE_PATH` instead
  of hardcoded `True`.
- `_restore_current_config` fallback also uses `_DEFAULT_CONFIG_DATA_QUOTE_PATH`.
- Added `config_data_quote_path: false` under `file_viewer:` in `config/de-gui.yaml`.

### Effect
Node paths auto-populated into the config-data search bar are no longer wrapped in
double-quotes by default. Togglable per-session via the existing UI button.

---

## 2. Wave checkbox double-click: solo mode

### What changed
- New event handler `solo_wave(name: str)`.
- **First double-click**: checks only the clicked wave, unchecks all others.
- **Second double-click** (wave already soloed): inverts — unchecks only that wave,
  checks all others.
- Added `on_double_click=AppState.solo_wave(item["name"])` to the name cell in the
  list-view wave table.
- Added `on_double_click=AppState.solo_wave(item["wave"])` to the name cell in the
  folder-view wave table.
- Guard: `if name not in self.wave_filters: return` prevents folder rows (whose names
  are not wave keys) from accidentally clearing all filters.

### Effect
Double-click a wave row to solo it; double-click again to invert (all others checked,
that one unchecked). Single-click still toggles normally.

---

## 3. Bug fix: config-declared waves couldn't be unchecked

### Root cause
`wave_filters` was initialised only from `_PATH_TO_WAVE_CACHE.values()` — the set of
wave names actually assigned to infra units. Waves declared in the stack config YAML
but with no units yet assigned were absent from the dict, so
`wave_filters.get(name, True)` always returned the default `True`, making them
permanently checked and immune to `hide_all_waves`, `solo_wave`, etc.

### What changed
- New module-level helper `_build_initial_wave_filters()` unions:
  - Wave names from the stack config `waves:` list (declared but possibly unoccupied)
  - Wave names from `_PATH_TO_WAVE_CACHE` (assigned to units)
  - `_none`
- All 6 initialization sites replaced:
  `{"_none": True, **{v: True for v in set(_PATH_TO_WAVE_CACHE.values())}}`
  → `_build_initial_wave_filters()`
  (lines 3826, 4949, 5109, 5218, 5687, 5827)

### Effect
All waves shown in the UI now have explicit keys in `wave_filters`, so hide-all,
solo, and toggle operations work correctly for every wave regardless of whether it
has units assigned.

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `config/de-gui.yaml`
- `docs/ai-log/20260331095339-wave-checkbox-solo-and-fixes.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
