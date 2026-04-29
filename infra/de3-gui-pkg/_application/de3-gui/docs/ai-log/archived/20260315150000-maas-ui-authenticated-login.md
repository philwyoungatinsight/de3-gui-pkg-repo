# MaaS Admin UI: authenticated Playwright login from the GUI button

## What changed

Clicking "MaaS Admin UI" in the GUI context menu now opens the MaaS web
interface fully logged in (no manual login required) when the Playwright
browser panel is active.

## Files modified

- `config/provider-actions.yaml` — added `auth:` block to `maas_ui` and `maas_ui_machine`
- `homelab_gui/homelab_gui.py` — added `_get_provider_level_secrets()` + extended auth resolution in `_get_node_actions` + pass selectors to `playwright_launcher.py` in `dispatch_action`

## Design

### 1. `auth` block in `provider-actions.yaml`

Both `maas_ui` (environment nodes) and `maas_ui_machine` (machine nodes) now carry:

```yaml
param_defaults:
  maas_admin_username: "admin"
auth:
  scheme: form
  username_param: maas_admin_username
  password_param: admin_password
  username_selector: "input[name=username]"
  password_selector: "input[name=password]"
  submit_selector: "button[type=submit]"
  success_url_contains: "/MAAS/r/"
```

`maas_admin_username` is non-sensitive (`admin`) and lives in `param_defaults`.
`admin_password` is resolved from SOPS provider-level secrets (see below).

### 2. `_get_provider_level_secrets(provider_name)` (`homelab_gui.py`)

Reads top-level scalar fields from
`terragrunt_lab_stack_secrets.providers.<provider_name>` — i.e., fields that
are **not** nested under `config_params` and are not themselves dicts/lists.

For MaaS this surfaces `admin_password` without duplicating it from the SOPS file.

### 3. Auth resolution in `_get_node_actions`

When an action has an `auth:` block, credentials are now resolved from three layers (highest priority wins):

1. `merged` (public stack params + param_defaults)
2. `_get_resolved_secret_params(node_path)` — per-path SOPS config_params
3. `_get_provider_level_secrets(action.provider)` — provider-wide SOPS scalars

Form-selector keys (`username_selector`, `password_selector`,
`submit_selector`, `success_url_contains`) from the auth block are embedded
directly into the auth JSON so both the embedded panel and the external
launcher receive them without extra plumbing.

### 4. External launcher (`dispatch_action` → `playwright_launcher.py`)

`PL_SCHEME`, `PL_USERNAME_SELECTOR`, `PL_PASSWORD_SELECTOR`,
`PL_SUBMIT_SELECTOR`, and `PL_SUCCESS_URL` are now passed as environment
variables when auth is present, enabling the external Playwright window to
perform form-based login identically to the embedded panel.

### 5. Embedded panel

`navigate_with_auth` in `playwright_browser.py` already reads these keys
from the auth dict — no change needed there.
