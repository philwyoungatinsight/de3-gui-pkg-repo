# AMT Web UI: secure login plan + Playwright integration test

## Background

The "AMT Web UI" button for MaaS machine nodes is defined in
`config/provider-actions.yaml` (not hard-coded in Python):
```yaml
- id: amt_ui
  label: "AMT Web UI"
  action_type: url
  url_template: "https://{power_address}:{amt_port}"
  params: [power_address, amt_port]
  param_defaults: { amt_port: "16993" }
  provider: maas
  node_type: machine
```
Public params (`power_address`, `amt_port`) come from `terragrunt_lab_stack.yaml`.
Credentials (`power_user`, `power_pass`) are in the SOPS-encrypted
`terragrunt_lab_stack_secrets.sops.yaml` under
`terragrunt_lab_stack_secrets.providers.maas.config_params.<path>`.

## General plan for secure web-console login

### 1. SOPS integration
- `_load_sops_secrets()`: subprocess `sops --decrypt <file>` → `yaml.safe_load()`
- `_get_resolved_secret_params(node_path, provider)`: same prefix-match
  inheritance as `_get_resolved_params`, but reads from `terragrunt_lab_stack_secrets`
- Module-level `_SOPS_SECRETS_CACHE`: populated lazily, never written to Reflex
  state, `current.yaml`, logs, or browser

### 2. `auth` block in `provider-actions.yaml`
```yaml
auth:
  scheme: digest        # digest | basic | form
  username_param: power_user   # resolved from public OR secret params
  password_param: power_pass
```
For form-based logins (Proxmox, MaaS UI):
```yaml
auth:
  scheme: form
  username_selector: "#username"
  password_selector: "#password"
  submit_selector: "button[type=submit]"
  username_param: proxmox_username
  password_param: proxmox_password
  success_url_contains: "/ui/"
```

### 3. Action resolution
When an action has `auth:`, resolve credential param names from merged
public + secret params. Skip the action if required credentials are missing.

### 4. Playwright login
`playwright_browser.py` gets `navigate_with_auth(url, auth)`:
- `digest`/`basic` → `browser.new_context(http_credentials={…}, ignore_https_errors=True)`
- `form` → `page.goto`, `page.fill`, `page.click(submit)`, wait for success URL

`dispatch_action` passes resolved `auth` dict to `open_playwright_url(url, auth=…)`.
Credentials travel as Python objects only — never embedded in URLs or sent to browser JS.

## New test: `tests/test_amt_web_ui.py`

Three tests for ms01-03 (`power_address: 10.0.11.12`, port 16993):

1. **`test_amt_endpoint_reachable`** — raw HTTPS request; expects HTTP 401
   (Digest challenge). Skips if machine is off/unreachable.

2. **`test_amt_web_ui_login`** — Playwright with
   `http_credentials={username, password}` + `ignore_https_errors=True`;
   asserts page contains "intel" / "management" / "amt".

3. **`test_amt_web_ui_no_error_banner`** — Same login; asserts page does NOT
   contain "401", "unauthorized", "access denied", etc.

All three skip gracefully if:
- SOPS key unavailable (`sops --decrypt` fails)
- `power_address`/`power_user`/`power_pass` missing from config
- Machine unreachable (network timeout)
- `playwright` package not installed

Credentials are resolved via `_resolve_config_params()` using the same
prefix-match inheritance as the production code, with
`terragrunt_lab_stack_secrets` as the root key for the SOPS file.

Run: `pytest tests/test_amt_web_ui.py -v`
