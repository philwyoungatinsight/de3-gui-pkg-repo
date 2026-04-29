# AMT Web UI: authenticated Playwright login from the GUI button

## What changed

Clicking "AMT Web UI" in the GUI context menu now opens the AMT management
interface fully logged in (no credential prompt) when the Playwright browser
panel is active.

## Files modified

- `config/provider-actions.yaml` — added `auth:` block to the `amt_ui` action
- `homelab_gui/homelab_gui.py` — SOPS loading + auth resolution in `_get_node_actions` + `dispatch_action`
- `homelab_gui/playwright_browser.py` — `navigate_with_auth` + pending-auth handshake

## Design

### 1. `auth` block in `provider-actions.yaml`

```yaml
- id: amt_ui
  ...
  auth:
    scheme: digest
    username_param: power_user
    password_param: power_pass
```

`username_param` and `password_param` name the keys to look up in the merged
public + secret config params.

### 2. SOPS integration (`homelab_gui.py`)

Three new functions, all lazy/cached:

- `_find_sops_secrets_file()` — locates `terragrunt_lab_stack_secrets.sops.yaml`
  by running `git rev-parse --show-toplevel` from `_STACK_DIR`, then
  `rglob`-ing under `deploy/config/`.
- `_load_sops_secrets()` — runs `sops --decrypt`, parses YAML, caches in
  `_SOPS_SECRETS_CACHE`.  Never written to state, logs, or browser.
- `_get_resolved_secret_params(node_path)` — same prefix-match inheritance as
  `_get_resolved_params` but reads `terragrunt_lab_stack_secrets`.

### 3. Action resolution (`_get_node_actions`)

When an action has an `auth:` block:
1. Secret params are loaded (lazy) and overlaid on the merged public params
2. `username_param` / `password_param` are resolved to actual values
3. If either is empty the action is **skipped** (button not shown)
4. `value` is replaced with JSON: `{"url": "…", "auth": {"scheme": "digest", "username": "…", "password": "…"}}`

Credentials never appear as plain strings in state or the browser DOM.

### 4. `dispatch_action`

When `action_type == "url"`:
- Tries `json.loads(value)` to detect the auth payload
- If found and `browser_profile == "playwright"`: calls `set_pending_auth(url, auth)` then `open_playwright_url(url)`
- Non-Playwright paths (iframe, xdg-open, Chrome profiles) use `_url` (decoded URL only)

### 5. Playwright auth (`playwright_browser.py`)

**`_PW_PENDING_AUTH: dict[str, dict]`** — server-side store keyed by URL.
Credentials never leave the Python process.

**`set_pending_auth(url, auth)`** — synchronous, called from `dispatch_action`.

**`navigate_with_auth(url, auth)`** — async:
1. Closes existing page and auth context (if any)
2. Creates new `BrowserContext` with `http_credentials` + `ignore_https_errors=True`
3. Navigates to URL
4. Auto-clicks `input[type=submit]` (AMT's "Log On…" button) if present
5. Waits for `domcontentloaded` after click

**WS receiver** — on `navigate` message, pops `_PW_PENDING_AUTH[url]` and calls
`navigate_with_auth` if found, otherwise plain `navigate`.
