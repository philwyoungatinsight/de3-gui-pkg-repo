# URL action: browser-picker dropdown + Open button fix

## Summary

Four related fixes:

1. **"Open" button was broken** for `browser_profile == "none"` — URL was silently
   discarded. Fixed by extracting `_open_url_in_profile()` helper that always falls
   through to `xdg-open` / `webbrowser.open` for the `"none"` / `""` / `"default"` cases.

2. **Browser-picker dropdown on URL action buttons** — all `url`-type action buttons
   now render as a dropdown (label + ▾). Picking a browser profile opens the URL
   immediately in that browser, without needing to pre-select a global profile. Matches
   the UX of the file viewer's "Open in [editor]" selector.

3. **Removed duplicate "MaaS Admin UI" buttons** from `config/provider-actions.yaml`
   (`maas_ui` + `maas_ui_machine` entries). The `_browser_url` key in config_params
   already provides the "Open" button for MaaS nodes — no need for a separate
   provider-actions entry.

4. **Added `_browser_url` for mesh-central** in `terragrunt_lab_stack.yaml`:
   `https://10.0.10.155` (IP from Ansible inventory, MeshCentral HTTPS default port 443).

---

## Changes — `homelab_gui/homelab_gui.py`

### `_open_url_in_profile(url, auth, profile_id)` (new private method)
Extracted from the inline block in `dispatch_action`. All browser cases handled:
- `"playwright"` — launches playwright_launcher.py subprocess with auth env vars
- `"pycharm"` — pycharm + xdg-open fallback
- `"default"` / `"none"` / `""` — xdg-open, webbrowser fallback (**fixes silent drop**)
- named Chrome profile — google-chrome --profile-directory=...

### `dispatch_url_with_profile(value, profile_id)` (new public event handler)
Called by the browser-picker dropdown items. Decodes auth payload from value, then
calls `_open_url_in_profile` with the explicitly chosen `profile_id`.

### `dispatch_action` refactored
URL branch now calls `self._open_url_in_profile(_url, _auth, self.browser_profile)`.

### `_node_action_btn` updated
For `action_type == "url"`: renders a `rx.dropdown_menu.root` with trigger showing
`label ▾`. Items come from `rx.foreach(AppState.chrome_profiles, ...)` — each item
calls `AppState.dispatch_url_with_profile(action["value"], p["id"])`.
For all other action types: unchanged plain button.

---

## Changes — `config/provider-actions.yaml`

Removed `maas_ui` (provider: maas, node_type: environment) and `maas_ui_machine`
(provider: maas, node_type: machine) entries. These were redundant with `_browser_url`
in config_params.

---

## Changes — `terragrunt_lab_stack.yaml` (pwy-home-lab repo)

Added to `cat-hmc/proxmox/pwy-homelab/pve-nodes/pve-1/vms/utils/mesh-central`:
```yaml
_browser_url: https://10.0.10.155
```
IP sourced from Ansible inventory (`ansible_host: 10.0.10.155`).

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `config/provider-actions.yaml`
- `~/git/pwy-home-lab/.../terragrunt_lab_stack.yaml`
- `docs/ai-log/20260331172809-url-action-browser-picker-dropdown.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
