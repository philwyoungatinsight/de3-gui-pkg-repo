# Add testing.yaml config and Chrome profile discovery

## Changes

### New: `config/testing.yaml`

```yaml
testing:
  ui_testing:
    headless: true
    user: ""
    incognito: false
```

- `headless`: when `true`, uses `--headless=new` Chrome flag; when `false`, opens a visible browser
- `user`: email of the Google account whose Chrome profile to use (empty = system default)
- `incognito`: when `true`, opens Chrome in incognito mode

### New: `tests/roles/gui-test/files/find_chrome_profile.py`

Python script that resolves a Chrome profile directory name from a user's email address.

**Primary strategy** — reads `Local State` JSON (O(1), single file):
```
~/.config/google-chrome/Local State
  → profile.info_cache[dir].user_name
```

**Fallback strategy** — scans individual `*/Preferences` files:
```
~/.config/google-chrome/*/Preferences
  → account_info[].email
```

Supports Linux (`~/.config/google-chrome`) and macOS
(`~/Library/Application Support/Google/Chrome`). Exits 0 and prints the
profile directory name (e.g. `Profile 1`); exits 1 if not found.

### Modified: `tests/roles/gui-test/tasks/screenshot.yml`

Added four screenshot branches to support all browser modes:
1. **headless** — `--headless=new --screenshot` PNG capture
2. **non-headless + named profile** — `launch_persistent_context` with real user-data dir
3. **non-headless + incognito** — `--incognito` flag
4. **non-headless plain** — no profile, no incognito

Non-headless branches use `async: 10, poll: 0` to avoid blocking the playbook
while Chrome loads.

### Modified: `tests/roles/gui-test/tasks/main.yml`

- Loads `testing.yaml` via `include_vars` at the top of the role
- Sets `_ui_headless`, `_ui_user`, `_ui_incognito` facts for downstream tasks
- Added `ansible.builtin.pause` before `clear_state` in non-headless mode so the
  browser has time to load and `on_load` can consume `.test_state.yml` before it
  is deleted. User presses Enter to proceed; in CI (piped stdin) the pause
  auto-skips with a warning.

### Modified: `tests/roles/gui-test/defaults/main.yml`

Added:
- `gui_config_dir: "{{ playbook_dir }}/../../config"`
- `_ui_headless: true`, `_ui_user: ""`, `_ui_incognito: false`
- `browser_checks: []`

## Debugging notes

- **Non-headless race condition**: `async: 1, poll: 0` returned immediately and
  `clear_state` ran before `on_load` could read `.test_state.yml`. Fixed by
  increasing to `async: 10` and adding the pause prompt.
