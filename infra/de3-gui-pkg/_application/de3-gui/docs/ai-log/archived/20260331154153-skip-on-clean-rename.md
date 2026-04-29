# Rename skip_on_clean_all → skip_on_clean; fix semantics

## Summary

`skip_on_clean_all` was misnamed and misplaced: `clean-all` is a nuclear operation that
should never skip waves. The flag belongs on `make clean` (regular reverse-order destroy).

---

## Changes

### GUI — `homelab_gui/homelab_gui.py`

- `skip_on_clean_all` → `skip_on_clean` everywhere (YAML key read/written, dict field,
  `toggle_wave_skip_on_clean` handler, `waves_with_visibility` computed var)
- UI labels updated: "Skip on clean-all" → "Skip on clean" (tooltips, column header)

### pwy-home-lab — `scripts/wave-scripts/default/clean-all/run`

- Removed `_read_skip_waves()` function (read `skip_on_clean_all` from YAML)
- `run_nuke()` now hardcodes `skip_patterns = []` — clean-all destroys everything
- Removed skip-count print statements and the "Note: skipped waves are still deployed" footer
- Removed per-wave config example from docstring

### pwy-home-lab — `run`

- `--clean` mode now filters out waves with `skip_on_clean: true` when no `-w` pattern
  is given (explicit `-w` targeting overrides the skip flag)
- Updated usage strings to document the new behaviour

---

## Semantics

| Command | skip_on_clean behaviour |
|---------|------------------------|
| `make clean` (no -w) | waves with `skip_on_clean: true` are skipped |
| `make clean -w <pattern>` | skip_on_clean ignored — user is targeting explicitly |
| `make clean-all` | no skipping — destroys all waves unconditionally |

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331154153-skip-on-clean-rename.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
- `~/git/pwy-home-lab/.../scripts/wave-scripts/default/clean-all/run`
- `~/git/pwy-home-lab/.../run`
