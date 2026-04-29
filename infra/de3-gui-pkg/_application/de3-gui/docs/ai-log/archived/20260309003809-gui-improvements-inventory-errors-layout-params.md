# GUI Improvements — Inventory, Error Banner, Layout, Unit Params

**Date:** 2026-03-09
**Session scope:** Multiple related GUI enhancements

---

## 1. Inventory button in controls bar

**Files:** `homelab_gui/homelab_gui.py`, `config/de-gui.yaml`

- Added `ansible_inventory_path` config key to `config/de-gui.yaml` (relative to `_STACK_DIR`).
  Points to: `../../../../k8s-recipes/config/tmp/dynamic/ansible/terragrunt_lab_stack/hosts.yml`
- Added `_read_inventory_file()` helper — reads the configured path, resolves relative to `_STACK_DIR`.
- Added `AppState.show_inventory()` event handler — loads inventory into the file viewer (`hcl_content` / `hcl_file_path`), clears selected node.
- Added "Inventory" button in `left_panel()` controls bar between Appearance and Providers dropdowns.
- Updated file viewer placeholder text to mention the Inventory button.

---

## 2. Backend connection error banner

**Files:** `homelab_gui/homelab_gui.py`

- Imported `has_connection_errors` and `connection_error` from `reflex.components.core.banner` — built-in Reflex frontend JS vars that track WebSocket state without a backend round-trip.
- Added `backend_error_banner()` component: fixed-position red bar (`z-index: 9999`, above navbar) that appears automatically when the WebSocket to the backend drops.
- Displays the actual Reflex-captured error message.
- Disappears automatically when the connection is restored.
- Added as the first element in `index()`.

---

## 3. Prevent horizontal scrollbar / viewport overflow

**Files:** `homelab_gui/homelab_gui.py`

- Root `rx.box` in `index()`: changed `min_height="100vh"` → `height="100vh"` + `max_width="100vw"` + `overflow="hidden"`.
- Added global style to `rx.App`: `html, body { overflow: hidden; height: 100%; max-width: 100vw }` to prevent Reflex's outer wrappers from generating a scrollbar.

---

## 4. "Inherited from" links in unit-params panel

**Files:** `homelab_gui/homelab_gui.py`

- `_get_unit_params_flat()`:
  - Fixed `is_exact` comparison: now uses `lookup_path` (provider-inclusive) instead of `node_path`, fixing merged-mode bug where every row showed "inherited from" instead of "defined here".
  - Added `source_display` field: `"provider:merged_path"` format (e.g. `proxmox:cat-hmc/pwy-homelab`) — consistent in both merged and normal tree modes.
  - All row types get `source_display: ""` to keep the dict schema uniform.
- Added `AppState.navigate_to_source(full_path)` handler:
  - In merged mode: strips the provider segment, calls `click_node` with the merged path.
  - In normal mode: calls `click_node` with the full path directly.
- `_source_header_row()`: renders `source_display` as blue underlined clickable text; click calls `navigate_to_source`.

---

## 5. Unit-params parameter ordering and colour coding

**Files:** `homelab_gui/homelab_gui.py`

### Special key ordering
- Added `_SPECIAL_KEY_ORDER = {"provider": 0, "env": 1, "region": 2}`.
- Added `_param_sort_key(k)`: sorts params as `provider/env/region` → `_underscore` keys (alpha) → regular keys (alpha).
- Replaced previous sort lambda in `_get_unit_params_flat`.

### Special key colours
- `provider` — amber `#d97706`
- `env` — teal `#0d9488`
- `region` — indigo `#4f46e5`

### Underscore key colours (per prefix group)
- Added `hashlib` import.
- Added `_UNDERSCORE_COLOR_PALETTE` (12 colours, distinct from special-key colours).
- Added `_underscore_key_color(key)`: extracts prefix group (`_foo_bar` → `"foo"`), hashes with MD5 for determinism, maps to palette. Keys sharing a prefix group always get the same colour.
- Regular keys: unchanged gray `#6b7280`.
- `key_color` stored per param row; `font_weight="600"` for all non-regular keys.

### "Hide identity" toggle
- Added `hide_special_params: bool = False` state var.
- Added `AppState.toggle_hide_special_params()` handler.
- `selected_node_params_flat` filters out `provider/env/region` rows when `hide_special_params` is True.
- Added "Hide identity" / "Show identity" toggle button in `_right_panel_header()` (unit-params panel header bar).

---

## 6. Terminal two-line prompt

**Files:** `homelab_gui/homelab_gui.py`

- Setting `PS1` via environment variable did not work because `~/.bashrc` loads after env and overwrites it.
- Fixed by writing a temp rcfile (`tempfile.mkstemp`) that:
  1. Sources `~/.bashrc` (preserving user config).
  2. Overrides `PS1` to `\u@\h:\w\n\$ ` — info on line 1, blank input line starting at column 0.
- Bash launched with `--rcfile <temp_path>` so the override is applied last.
- Temp file deleted in the `finally` block when the terminal session closes.

---

## Path hygiene fix + AGENTS.md

**Files:** `config/de-gui.yaml`, `AGENTS.md`, memory

- Corrected hard-coded absolute path in `de-gui.yaml` to a path relative to `_STACK_DIR`.
- Created `AGENTS.md` at repo root documenting the rule: never use absolute paths; always use paths relative to `_STACK_DIR` from `set_env.sh`, with wrong/correct examples.
- Updated persistent memory (`MEMORY.md`) with the same rule.
