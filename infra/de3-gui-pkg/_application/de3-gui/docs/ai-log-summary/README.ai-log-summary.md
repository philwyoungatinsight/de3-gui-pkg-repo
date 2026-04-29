# Goal
- Keep a compacted version of the ai-logs that
  reflects the current state of the code.
- This is a summary of the ai-logs, so that we can
  delete some of the older ai-logs since we don't
  need the full history of changes in the code, git logs have that.

# Action
- Maintain this file, from the "Action" section and above
- Add a section below, and replace it, with a summary of
  the ai-logs, using this file, and the recent ai-logs.
- Do not delete any of the ai-logs.

---

## 2026-04-26 — fw-repos Font Size Slider

Added `Font Size` slider to the fw-repos Mermaid viewer Appearance section (min 10, max 40, step 2, default 18 px).
- `window._setFontSize(px)` exposed on iframe window; re-inits Mermaid `themeVariables.fontSize` and re-renders without iframe reload.
- `_repos` module-level cache + `_initMermaid()` / `_renderDiagram()` helpers refactored out of `load()`.
- `fw_repos_font_size` state var + computed vars + save/load persistence + `set_fw_repos_font_size` event handler wired identically to the existing zoom slider pattern.
- de3-gui-pkg bumped `0.6.0 → 0.7.0`.

---

## 2026-04-22 — Remove filter item tooltips

- Removed `rx.tooltip()` wrappers from `provider_toggle_item`, `_package_toggle_item`, `_region_toggle_item`, `_role_toggle_item`, `_env_toggle_item` — each now returns `rx.hstack(...)` directly
- Button-level `title=` attributes on dropdown trigger buttons left intact

---

## 2026-04-20 — Refactor Panel Auto-Preview

- **Auto-preview on destination set**: clicking a node in the infra tree immediately fires `run_refactor_preview`; typing debounces for 2 s then fires via a hidden JS trigger button
- **Config-controlled**: `refactor_auto_preview: true` and `refactor_auto_preview_delay_ms: 2000` in `de3-gui-pkg.yaml`; `false` disables entirely
- **`_REFACTOR_AUTO_PREVIEW` / `_REFACTOR_AUTO_PREVIEW_DELAY_MS`** module-level constants follow the same pattern as `_WAVE_POLL_INTERVAL_MS`
- **Debounce timer cleared** on panel close and when switching to Delete operation (no destination needed)
- **Hidden trigger button** `id="refactor-auto-preview-trigger"` in `_refactor_panel`; JS `setTimeout` clicks it after the delay

---

## 2026-04-20 — GUI Refactor Menu Update

- **Context menu "Edit" group renamed to "Refactor"**
- **"Rename…" → "Rename"** (no ellipsis); old "Refactor (move / copy)…" and "Remove unit…" items replaced with three direct items: **Move**, **Copy**, **Delete**
- **`begin_refactor(path, operation="move")`** now pre-sets `refactor_operation` on panel open; three new `dispatch_action` routes: `begin_refactor_move`, `begin_refactor_copy`, `begin_refactor_delete`
- **Delete operation** wires into existing `confirm_delete` backend (recursive); preview short-circuits with a message; destination input hidden via `rx.cond`; Execute enabled without destination
- **Float panel title** updated to "Refactor (units and config recursively)"
- **Tooltips** added to all controls in `_refactor_panel`

---

## 2026-04-20 — Fix Wave Panel Empty + git Index Bits Utility

- **Wave panel was empty**: `_find_stack_configs()` required `framework.yaml` to exist as a sentinel before scanning `infra/*/_config/*.yaml`; that file doesn't exist in this repo (config is split across `framework_*.yaml` fragments). Fix: scan whenever the `infra/` directory exists, include `framework.yaml` only if present.
- **`waves_ordering.yaml` not loaded**: path was hardcoded to `config/waves_ordering.yaml` (root-level, never existed); corrected to `infra/default-pkg/_config/waves_ordering.yaml`.
- **New utility**: `infra/default-pkg/_framework/_human-only-scripts/fix-git-index-bits/run` — finds files with `skip-worktree` or `assume-unchanged` index bits, labels missing-on-disk files, and prompts to clear bits + restore from HEAD.
- **Root cause of missing `run` script**: `skip-worktree` bit on a tracked file makes `git status` report clean even when the file is absent from disk; the `de3-gui` `run` script was in this state.

---

# Current State Summary (as of 2026-04-19, rx.radio API fix)

### rx.radio / rx.radio_group API fix (2026-04-19)
`rx.radio` and `rx.radio_group` both resolve to `HighLevelRadioGroup` in Reflex 0.8.27, which
requires a list argument. The pkg-op copy dialog was using the old-style item/root API:
`rx.radio_group(...)` → `rx.radio.root(...)`, `rx.radio("value")` → `rx.radio.item(value="value")`.

## Application Overview
Single-file Reflex 0.8.27 app: `homelab_gui/homelab_gui.py` (~7000+ lines).
Config: `config/de-gui.yaml`. State persistence: `state/current.yaml`.
Layout: four-panel — left explorer, top-right object viewer, bottom-left file viewer,
bottom-right browser/terminal.
Instructions file: `CLAUDE.md` (renamed from `AGENTS.md`).

### Startup status banner (added 2026-04-03)
Fixed bottom bar (`startup_status_banner()`, z_index 9998) driven by `app_status_message` computed var:
- `"Initializing…"` while `is_loading == True`
- `"Refreshing inventory…"` while `inventory_refresh_counter == 0` (background refresh in flight)
- Hidden (`""`) when fully ready

### Post-session automation
A Stop hook (`.claude/settings.local.json` → `.claude/stop-checklist-hook.sh`) fires when
Claude stops. If uncommitted code files exist, it injects an `additionalContext` reminder
to complete the post-session checklist (ai-log → ai-log-summary → git commit).

### Provider template links (fixed 2026-04-02)
`provider_templates` in `PackageInfo` was `list[PackageFileLink]`; clicking pills did nothing because
`lnk.path` (nested `rx.Base` field on an inner foreach item that is a field of an outer foreach item)
does not work as an event arg in Reflex 0.8.27 — even though generated JSX looked correct.
Fix: changed to `list[str]` (absolute paths). New `_pkg_template_pill(path: str)` function receives
the path string directly as the foreach item var, derives filename via `path.split("/")[-1]`, and
passes `path` straight to `open_abs_file_in_viewer`. Only `default-pkg` (6 templates) and `unifi-pkg`
(1 template) have `_providers/<name>/*.tpl` files.

### `{ansible_host}` token in `_browser_url` (as of 2026-04-02)
`_get_browser_url_for_node()` resolves `{ansible_host}` (and other inventory vars) in `_browser_url`
config_param values via Python `.format(**inv_vars)` where `inv_vars` comes from `_load_inventory_hosts()`.
Stack config updated: maas-server-1 `_browser_url = http://{ansible_host}:5240/MAAS/r/machines`,
mesh-central `_browser_url = https://{ansible_host}`.

### SSH recompute after inventory refresh (as of 2026-04-02)
`selected_node_browser_actions` (`@rx.var`) reads `_INVENTORY_HOSTS_CACHE` (module-level global).
Fixed by: `inventory_refresh_counter: int = 0` state var (accessed in the var to register dependency)
+ `signal_inventory_ready` background event (dispatched from `on_load`) that polls
`_INVENTORY_REFRESH_COMPLETE` and bumps the counter when the refresh script finishes.

### Spinner / banner hang bug (fixed 2026-04-01 / 2026-04-03)
`on_load` has a double-fire guard that early-returns when the test-state marker file is
<5s old. Two bugs fixed in this path:
1. *(2026-04-01)* Omitted `self.is_loading = False` → spinner ran forever on hot-reload.
   Fixed by adding `self.is_loading = False` before the early return.
2. *(2026-04-03)* Omitted `AppState.signal_inventory_ready` from the return value →
   `inventory_refresh_counter` stayed `0` → "Refreshing inventory…" banner never cleared.
   Fixed: early-return now returns `[AppState.install_resizer, AppState.signal_inventory_ready]`.

### Engine repo refactor compatibility (2026-04-09)
The engine (`pwy-home-lab`) was massively refactored. Full plan in `README.refactor.md`.
Key changes made to the GUI:

**`_STACK_DIR` default**: `$HOME/git/pwy-home-lab` — root of the pwy-home-lab repo where `config/framework.yaml` and `infra/` now live. Updated in `run`, `set_env.sh`, `CLAUDE.md`, and `homelab_gui.py`. Startup diagnostic print added to `_load_stack_config()` showing `_STACK_DIR`, whether it exists, and whether `config/framework.yaml` was found.

**Config discovery** (`_find_stack_configs()`): now returns
`config/framework.yaml` + `infra/*/_config/*.yaml` (was `terragrunt_lab_stack*.yaml`).

**Config loading** (`_load_stack_config()`): adapter pattern — reads per-package
configs and synthesises the existing `providers.<provider>.config_params.<path>`
structure. New helper `_resolve_provider_inheritance()` walks ancestor paths to
resolve `_provider` (replicates root.hcl inheritance). Copies `_region`→`region`
and `_env`→`env` for backward-compat. Waves merged from `config/waves_ordering.yaml`
(ordering + `skip_on_clean`) + per-package `waves:` sections (descriptions, playbooks).
`_STACK_CONFIG_KEY` is now `"lab_stack"` (was `"terragrunt_lab_stack_default"`).

**Secrets**: `_find_sops_secrets_files()` (plural) returns all
`infra/<pkg>/_config/<pkg>_secrets.sops.yaml`; `_load_sops_secrets()` merges them
and synthesises legacy `"terragrunt_lab_stack_secrets"` key for backward compat.

**Package/module scanning** (`_scan_packages()`, `_init_modules_cache()`): rewritten
for new per-package layout:
- Modules: `infra/<pkg>/_modules/<module>/` (no provider subdir)
- TG scripts: `infra/<pkg>/_tg_scripts/<role>/`
- Wave scripts: `infra/<pkg>/_wave_scripts/test-ansible-playbooks/<cat>/<wave>/run`
- Module tree depth: 2→1 (package at 0, module at 1; paths are `<pkg>/<module>`)

**Wave write-back**: `toggle_wave_skip_on_clean()` and `_move_wave()` now write to
`config/waves_ordering.yaml` (was the primary stack config YAML).

**`de-gui.yaml`** updated:
- `ansible_inventory_path`: **not set** — auto-resolved from `framework.ansible_inventory.output_file`
  in `config/framework.yaml` (anchored to `$_DYNAMIC_DIR`, same as `generate_ansible_inventory.py`).
  An explicit override can be set in `de3-gui-pkg.yaml` but is not needed in normal operation.
- `ansible_inventory_refresh.script`: `framework/generate-ansible-inventory/run`
- `unit_params.identity_params`: `[_provider, _region, _env]`

### Infra scan fixed for new engine layout (2026-04-09, second session)
The GUI was showing 0 infra nodes and 0 waves despite the config loading being correct.
Root cause: infra scanning functions all assumed old path structure `cat/<provider>/...`
but new engine uses `infra/<pkg>/_stack/<provider>/...`.

**Node paths**: now `<pkg>/_stack/<provider>/env/group/resource` (e.g.
`pwy-home-lab-pkg/_stack/proxmox/pwy-homelab/pve-nodes/ms01-01`). These match
config_params keys exactly, so wave/region/env lookup works.

**`_init_nodes_cache`**: rewritten to iterate `infra/<pkg>/` dirs, check for `_stack/`
subdir, emit a synthetic depth-0 package node, then call `_scan_infra(provider_dir,
depth=1, parts=[pkg, "_stack"])` for each provider dir under `_stack/`.

**`_scan_infra`**: provider extraction changed from `current_parts[1]` → `current_parts[2]`.

**`_infer_type`**: provider extraction changed from `parts[1]` → `parts[2]`. Depth
thresholds unchanged (depth 1 = provider, 2 = env, etc. — still correct since we
start scanning provider dirs at depth=1).

**`_build_merged_nodes`**: merged path now strips both `_stack` and provider:
`merged_parts = [parts[0]] + parts[3:]` (was `parts[2:]`).

**Event handlers** (`navigate_to_source`, `paste_unit`, `confirm_paste`,
`_selected_node_provider`, source display format string): all `parts[1]`
provider references updated to `parts[2]`.

Verification: 246 nodes, 132 unit nodes, 21 waves, 157 nodes with wave assignments.

### Merged-mode path reconstruction fixed (2026-04-09)
Five functions that rebuild full provider-inclusive paths from merged paths were all
missing `_stack`. Old formula: `[parts[0], provider] + parts[1:]`. New formula:
`[parts[0], "_stack", provider] + parts[1:]`.

- **`_merged_full_paths()`** — region/env/wave keep-set lookups in merged view were silently wrong
- **`file_viewer_provider_options`** — provider dropdown built wrong `full_path` values
- **`file_viewer_provider_full_path`** — button label showed wrong path
- **`_read_hcl_file_for_merged()`** — HCL file never loaded in merged mode
- **`_get_hcl_providers_for_merged()`** — scanned `infra/<pkg>/` (all `_`-prefixed, found nothing); now scans `infra/<pkg>/_stack/`

### Comprehensive engine compatibility fixes (2026-04-09)
Full cross-codebase audit found 10 more issues fixed in one pass:

**SOPS secrets** (`_load_sops_secrets`): new engine has no `providers:` wrapper; format is `config_params: {path: {params}}`. Now resolves provider via `_resolve_provider_inheritance` like the public config loader.

**Config write-back** (CRITICAL × 4): `confirm_paste`, `confirm_recursive_paste`, delete-unit, and `save_param_edit` all wrote into `framework.yaml` using a synthetic `lab_stack.providers.*` key that doesn't exist and is never read back. New helpers: `_pkg_config_yaml_for_path`, `_write_pkg_config_param`, `_delete_pkg_config_param` — write to the correct `infra/<pkg>/_config/<pkg>.yaml` under `<pkg>.config_params[path]`.

**`open_source_link` + `_init_modules_cache`**: `framework/_modules/` (contains `null_resource__run-script`, `null_resource__ssh-script`) was never searched or shown in the Modules panel. Both now include `framework/_modules/` as a scan target.

**`_scan_packages`**:
- `providers_str` derived from `_stack/` subdirectory names (was reading non-existent `providers:` key)
- TG scripts: now two levels deep (`group/role` e.g. `proxmox/configure`, `proxmox/install`)
- Wave scripts: now scans all `_wave_scripts/` subdirs (not just `test-ansible-playbooks/`), picks up `common/` scripts

**Cytoscape region filter**: `parts[2]` was the provider name, not the region. Now uses `_PATH_TO_REGION_CACHE.get(data["id"], "")`.

### Missing `_stack` in 6 merged-mode path sites (2026-04-09)
Four additional functions used `[parts[0], provider] + parts[1:]` instead of
`[parts[0], "_stack", provider] + parts[1:]` for merged→full path reconstruction:
`_get_unit_params_flat` (Unit Params panel showed nothing in merged mode),
`_get_browser_url_for_node` (browser URL not resolved in merged mode),
`select_node` config_data mode full_path and provider fallback (wrong index `_segs[1]` → `_segs[2]`),
`open_param_edit_dialog` and `confirm_edit_param` (inherited param detection/write-key wrong).

### `make test` fixed for interactive observation mode (2026-04-09)
`make test` now passes reliably with `observation_mode: interactive`.

Three fixes in `tests/browser_test.py`:

1. **`wait_for_ready` — chunked polling with page reloads**: replaced single 120s
   `wait_for_function` with a loop of `READY_CHUNK_MS = 12_000` ms windows. On timeout,
   the page is reloaded and the next attempt starts. Handles the cold-Vite-cache OOM
   crash: attempt 1 times out → reload → Vite has restarted → attempt 2 succeeds.

2. **`wait_for_ready` — combined ready condition**: now requires both `-pkg` in
   `innerText` AND no `Connection Error` in `innerText`. After the reload+restart,
   Vite HMR fires and briefly disconnects the Reflex WebSocket; the combined condition
   waits until the HMR cycle settles before declaring the page ready.

3. **`check_no_element` — `innerText`-based poll**: replaced
   `get_by_text().filter(visible=True).count()` with `wait_for_function` on
   `document.body.innerText`. `innerText` respects CSS hiding; the Reflex
   `ConnectionPulser` div has `title="Connection Error: ..."` always in the DOM
   (matched incorrectly by the old locator approach). Poll-based wait handles
   any transient state that clears quickly.

Config: `observation_mode: interactive`, `observation_timeout_secs: 10`,
`post_continue_pause_secs: 1`.

### `_stack` ancestor path bug fixed (2026-04-09)
**Critical**: the infra tree showed only depth-0 package names and nothing below them.

Root cause: node paths include `_stack` as an intermediate segment (e.g.
`pwy-home-lab-pkg/_stack/proxmox`). The `visible_nodes` computed var checks whether
each ancestor prefix is in `expanded_paths`. It checked `"pwy-home-lab-pkg/_stack"` —
which is never a real node and thus never in `expanded_paths` — causing all depth-1+
nodes to fail the visibility check.

Fix: in the ancestor-path loop inside `visible_nodes`, skip the `expanded_paths`
lookup when `part == "_stack"`. The `_stack` segment is a virtual filesystem
organisational level with no corresponding tree node. `merged_visible_nodes` is
unaffected (merged paths strip `_stack` at build time).

---

## Layout & Panels

### Per-unit build status indicator (2026-04-09, updated 2026-04-10)
New appearance option "Show build status" (under the "Folder view" section). When enabled, a 7px
coloured dot appears before each leaf unit's name in the tree:

- **Green** — `default.tfstate` exists in GCS (`gs://<bucket>/<node-path>/default.tfstate`)
- **Red** — unit appeared in `~/.run-waves-logs/latest/run.log` "Unit queue" but has no GCS state
- **Grey** — no evidence (never attempted or fully cleaned up)
- **Accent (blue)** — shown on all dots while a refresh is in progress (`is_refreshing_build_statuses == True`)

Data collected by `refresh_unit_build_statuses` (`@rx.event(background=True)` async):
1. Sets `is_refreshing_build_statuses = True` (triggers in-panel indicator)
2. Reads bucket name from `infra/pwy-home-lab-pkg/_config/gcp_seed.yaml`
3. Runs `gsutil ls -r gs://<bucket>/` per package prefix; maps `*/default.tfstate` → `"ok"`
4. Parses run.log for `"- Unit <path>"` lines; marks attempted-but-no-state → `"fail"`
5. Sets `unit_build_statuses` and clears `is_refreshing_build_statuses`

State vars: `unit_build_statuses: dict[str, str]`, `is_refreshing_build_statuses: bool`.
`unit_build_statuses` injected into each node via `visible_nodes` computed var.

**Loading indicator:** while `is_refreshing_build_statuses`:
- "⟳ Refresh status" button in appearance menu → "⟳ Updating…" (yellow, disabled)
- All visible build-status dots → accent colour, tooltip "Updating status…"

Refresh fires automatically when the toggle is turned on, when a wave run completes, and
manually via the "⟳ Refresh status" button.  Setting persisted to `state/current.yaml`.

### Explorer (left panel)
- Tree view of `infra/` directory; "Separated" (category/provider/region/env) or "Merged" modes
  - **Expand behaviour**: clicking a folder opens the entire subtree to leaf units in one click
    (adds path + all descendant paths to `expanded_paths`); collapsing still closes the whole subtree
- View selector dropdown: Folder / Tree / Nested Networks (Nested Networks last)
- **Explorer root dropdown**: Infra / Modules / **Packages** / Ansible Inventory
- Filters: **Package**, Category, Provider, Region, Env, Wave, Role (ansible inventory)
  - **All filter checkboxes** (Category, Provider, Region, Env, Role): click toggles;
    double-double-click solos (show only that value); second double-double-click inverts.
    Dict-based filters use `solo_category/region/env/provider`; Role uses `solo_role`
    (list-based: empty = no filter). All items have tooltip explaining the interaction.
  - **Roles source**: stack config `additional_tags` (via `_PATH_TO_ROLES_CACHE`, built
    in `_init_path_param_maps()`) is the primary source — covers all nodes whether
    Ansible-provisioned or not. Ansible inventory used as supplement only.
    All 5 role lookup sites now use full node path as key (was: hostname/label).
  - **Package filter** (added 2026-04-04, bug fixed 2026-04-10): `package_filters: dict`;
    `packages_with_visibility` computed var; `toggle_package`/`solo_package`/`toggle_all_packages`
    handlers. Applied as a keep-set in `visible_nodes` AND `merged_visible_nodes`.
    **Key**: filter uses `node["path"].split("/")[0]` (infra directory package) NOT `node["package"]`
    (module source package — set by `_populate_module_tree_paths`, reflects the module's origin not
    the unit's location). Using `node["package"]` caused cross-package module consumers (e.g.
    `pwy-home-lab-pkg` units using `maas-pkg` modules) to be misclassified.
    All 6 filter sites (2 closures + 3 `package_filters` inits + `packages_with_visibility`) now
    use `path.split("/")[0]`.
    `packages_with_visibility` collects names from both `all_nodes` AND `_PACKAGES_CACHE` — ensures
    packages not yet referenced by any infra node still appear.
    Small monospace package pill shown **left of the type badge** in each tree row.
    "Packages ▾" filter button placed left of "Categories ▾" in the filter bar.
  - **Filter button active indicator**: each filter dropdown button turns orange when
    any item is hidden/filtered. Computed vars: `category_filter_active`,
    `package_filter_active`, `provider_filter_active`, `region_filter_active`,
    `env_filter_active`, `role_filter_active`. Roles button also shows count: "Roles (N) ▾".
  - Filter bar layout: `Packages | Categories | Providers | [Regions] | Envs | Roles | Search…` — `_divider` vertical bars between every control.
- Appearance menu: theme, folder view options, file viewer columns, wave panel behaviour
- **Help menu**: Docs (GUI) → GUI `README.md`; Docs (Engine) → `lab_stack/README.md`; Topics → `lab_stack/docs/README.md`; Scripts → `lab_stack/scripts/README.md`; About; License. Handlers: `open_docs`, `open_docs_engine`, `open_docs_topics`, `open_docs_scripts`, `open_help_about`, `open_help_license`.
- Module pill per node showing `module_source_short` (bare name) or `module_tree_path` (full resolved path);
  click opens the module file directly via `navigate_to_module` (no hover card); full path shown as native `title=` tooltip; toggled by "Show full module name" in Appearance menu
- **Re-clicking a selected node** toggles `file_viewer_mode` between `unit_file` and
  `config_data`. Implemented via `toggling_mode` flag at top of `click_node`.
- **config_data click always finds the right file**: `_find_config_file_for_node(provider, node_path)`
  scans all stack config YAMLs for the longest-prefix `config_params` key match, then loads that
  file. Handles nodes defined in package-specific YAML files (not just the base file).
  Reconstructs the provider-inclusive path for merged-mode nodes before lookup.
- `module_source` (from `_extract_module_path`) is always just the bare name due to greedy regex on
  double-interpolated HCL sources; `module_tree_path` (from `_populate_module_tree_paths`) is the resolved full path
- `_populate_module_tree_paths()` must be called after every `_init_nodes_cache()` call (both at module
  level, in `on_load`, and in `update_inventory_and_dag`) — otherwise all `module_tree_path` fields are `""`
- Node icons: physical-host SVG (`_host_icon()`) when `node["is_host"]`; else 📦 (has HCL) / 📁 (folder) / blank
  - `is_host` determined by `modules_to_include` from stack YAML's `ansible_inventory` section
  - `_is_host` in `config_params` overrides module-based detection (leaf-only)
- Node right-click → context menu; groups:
  - **Build**: Apply unit, Apply (recursive)
  - **Edit**: Rename…, **Refactor (move / copy)…**, Remove unit…, Remove unit (recursive)…
  - **Status**: Show inputs, Show outputs, Refresh build status (recursive) *(when show_unit_build_status)*
  - **Debug**: Remove state lock file…, Remove state lock files (recursive)…
  - **Destroy**: Destroy unit, Destroy (recursive), Taint unit…, Taint (recursive)…
  - **Shell**: Open local shell, SSH to host (when applicable)
  - **Provider UI** / **Unit** / **Misc**: from `provider-actions.yaml`
  - *(Clipboard group removed — replaced by Refactor panel)*

### Tree collapse broken during search (fixed 2026-04-13)
`visible_nodes` / `merged_visible_nodes` had a special `if filtering:` path that completely
ignored `expanded_paths` when search/role filters were active. Clicking a folder had no
visual effect (children stayed visible; ▼ indicator stayed on). Fix: removed the special
filtering branch — both filtered and normal modes now use the same `expanded_paths` check.
Added ancestor auto-expansion in `set_explorer_search` and `on_load` so search results remain
visible regardless of `depth_limit` or prior collapsed state.

### Rename node (2026-04-13)
Right-click any tree node → **Edit → Rename…** opens a dialog to rename the directory.
On confirm: (1) rewrites all matching `config_params` keys in every
`infra/*/_config/*.yaml` (both flat and legacy-providers formats), (2) decrypts /
renames keys / re-encrypts every `*_secrets.sops.yaml` (temp file in same dir so
`.sops.yaml` creation rules apply), (3) `mv`s the directory on disk, (4) invalidates
SOPS cache, (5) reloads node tree and corrects `selected_node_path`.
Validation: non-empty, no `/`, not `.` or `..`. SOPS failures are non-fatal warnings.

### Build status — subtree refresh via right-click (2026-04-13)
Right-clicking any node when "Show build status" is enabled shows **Refresh build status
(recursive)** in the Build group. `refresh_subtree_status(path)` (sync entry, sets
spinner) dispatches `do_refresh_subtree_status(path)` (background task). Scoped to
`infra/<path>` subtree: Tier 1 `find` (no `-newer` marker, always reads current state)
+ Tier 2 `gsutil ls -l -r gs://<bucket>/<path>/` (reuses `gcs_state_mtimes` for
incremental download; GCS result overrides Tier 1). Results merged into
`unit_build_statuses` without touching entries outside the subtree.

### Build status Tier 3 — apply exit code capture (2026-04-13)
`apply_unit` now wraps its shell command to write the exit code to
`/tmp/homelab_gui_apply_<path-with-+-separators>.exit`. The `local_state_watcher`
loop scans for these files each iteration, recovers the unit path by reversing `+`→`/`,
and sets status to `"fail"` if exit code ≠ 0 (overriding Tier 1's tfstate-based "ok"
for partial failures). Exit code 0 confirms Tier 1 finding (logged only). Files are
deleted after reading (one-shot). `apply_recursive` is not wrapped — individual units
within the recursive run are covered by Tier 1 as each writes its tfstate.

### Build status Tier 2 — GCS mtime cache + resource count (2026-04-13)
`do_refresh_unit_build_statuses` now uses `gsutil ls -l -r` (adds mtime to listing).
Mtime strings saved in `gcs_state_mtimes: dict[str,str]`. On subsequent bulk refreshes,
only files whose mtime changed since the last scan are downloaded (`gsutil cat`) and
parsed as JSON. `resources` array length determines status: non-empty → `"ok"`,
empty → `"destroyed"`. On a stable lab with no recent applies: zero downloads after
the first scan. Result is merged with existing `unit_build_statuses` (Tier 1 local
entries survive for units not yet visible in GCS).

### Build status Tier 1 — local cache watcher (2026-04-13, bug-fixed)
`local_state_watcher` (`@rx.event(background=True)`) — process-level singleton loop.
Uses `find infra -path "*/.terragrunt-cache/*/terraform.tfstate" -newer <marker>` as a
**change detector only** — local file content is NOT read. With a GCS backend, the local
`terraform.tfstate` always has `resources:[]` (backend pointer, not actual state); reading
it caused all units to show purple "destroyed". On detecting a mtime change, does a targeted
`gsutil cat gs://<bucket>/<unit>/default.tfstate` for the real resource count → `"ok"` /
`"destroyed"`. Sets `"unknown"` (amber) if GCS unreachable. Marker at
`/tmp/homelab_gui_state_check.marker` makes scans incremental. `apply_unit` /
`apply_recursive` set `_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL = now + 60 s` for 2 s polls.

### Build status — fresh GCS scan on load (2026-04-13)
`on_load` now clears `unit_build_statuses` and `gcs_state_mtimes` on load when
`show_unit_build_status` is True, then dispatches `do_refresh_unit_build_statuses`
so the dots always start from a fresh GCS scan. This prevents stale "destroyed"
entries (from old hot-reload code) from persisting across restarts. Spinner flag
(`is_refreshing_build_statuses = True`) is set immediately before the scripts list
so the UI shows "Updating…" from the very first render.

### Filter persistence (2026-04-13)
Wave, region, env, package, and role filters are now saved/restored across sessions.
- `_save_current_config()` now includes `wave_filters`, `region_filters`, `env_filters`,
  `package_filters`, and `selected_roles` in its snapshot dict.
- All 24 filter toggle/solo/show/hide handlers now call `self._save_current_config()`.
- `on_load` restores saved filter state after initialising filters from cache using a
  "known keys only, new entries default to True" merge — so newly-added waves/regions/etc.
  appear visible by default while previously hidden entries stay hidden. Role filter is
  validated against `available_roles` on restore.

### manage-unit CLI (2026-04-14, new framework tool)
`framework/manage-unit/run <move|copy> <src> <dst> [--dry-run] [--json-report] [--skip-state] [--skip-secrets]`

Moves or copies a Terragrunt unit tree while keeping 4 things in sync:
1. Filesystem directory (`shutil.copytree` + `.terragrunt-cache` stripping)
2. `config_params` keys in the owning package YAML (`ruamel.yaml`, `ignore_aliases`, `width=4096`)
3. SOPS secrets (`sops --decrypt` / `sops --encrypt --output`, never uses `>`)
4. GCS Terraform state blobs (`gsutil cp` + `gsutil rm`, verifies dst before deleting src)

Also scans all `.hcl` files for `dependencies { paths = [...] }` references into the moved tree and reports external inbound refs (requiring manual update) as warnings.

Output: human-readable log + optional JSON report after `---JSON---` sentinel.
Cross-package moves supported. `--skip-state` for units that have never been applied.

Modules: `manage_unit/{main,unit_tree,dependency_scanner,config_yaml,sops_secrets,gcs_state,report}.py`

### Object Viewer (top-right panel)
- **View selector dropdown** ("Unit Params ▾" / "Waves ▾" / **"Refactor ▾"**) replaces the two tab buttons; calls `set_object_viewer_mode`
- **Unit Params**: flat list of config params from stack YAML, with inline editing via dialog
- **Waves**: table or folder view; columns: #, Wave, Actions, Pre, Run, Test,
  Start Time*, End Time*, Duration*, Age* (* = toggleable in Appearance menu), Order
  - **Pre** / **Run** / **Test** status icons (✓/✗/–) each link to their respective log file:
    - Pre: `wave-<name>-precheck.log`
    - Run: `wave-<name>-(apply|destroy).log`
    - Test: `wave-<name>-test-playbook.log`
  - All three resolved independently (newest dir containing that log type)
  - **Wave checkbox**: tooltip explains click/double-click/double-double-click interactions;
    click toggles visibility; double-click solos; second double-click inverts
  - **Wave name text**: click opens the stack config in the file viewer, searching for
    that wave's definition (`open_wave_definition` handler)
  - Bug fix: config-declared waves with no units assigned are now included in `wave_filters` via
    `_build_initial_wave_filters()` (unions stack config wave list + `_PATH_TO_WAVE_CACHE`)
  - Apply (▶), Destroy (🗑), Skip-on-clean (⊘) action buttons per wave
    - `skip_on_clean: true` in stack YAML → wave skipped by `make clean` (regular reverse destroy)
    - `make clean-all` (nuclear) always destroys all waves — no skipping
    - `-w <pattern>` on `make clean` overrides skip_on_clean for explicit targeting
  - Re-order ↑/↓ buttons in Order column; swap entries in stack YAML directly
  - Duration/Age format: `{h:>2}h-{m:02d}m-{s:02d}s` (no days; hours accumulate past 24;
    leading zero components replaced with `\u00a0` for HTML alignment; age includes seconds)
  - **Optional columns** (Appearance → Waves Columns): Start Time, End Time, Duration, Age, **Log Update** (time since last write to `run.log`, same format as Age/Duration; default off)
  - **Status icons**: Pre/Run/Test cells show **–** (none), **⟳** (running, amber, in-progress), **✓** (ok, green), **✗** (fail, red). `_wave_status()` returns `"running"` when a log file has no done/fail marker and `run.log` was modified within 300 s (`_RUNNING_THRESHOLD_SECS`); older → `"fail"`. `run_log_mtime` is passed to all three status calls per directory.
  - Row highlight: most recently updated wave (within `_WAVE_RECENT_HIGHLIGHT_SECS` seconds, default 30, configurable via `config.wave_recent_highlight_secs` in `de-gui.yaml`) shown with `--accent-3` background;
    controlled by "Highlight recent wave" toggle (Appearance menu, default on)
  - **"▶ Run All" button**: opens confirmation dialog then runs `./run -a` (apply all waves) in the terminal; starts wave status poll. State var: `run_all_waves_dialog_open`; handlers: `begin_run_all_waves`, `cancel_run_all_waves`, `confirm_run_all_waves`.
  - **"⏵ Tail" button**: runs `_WAVE_TAIL_CMD` (from `config.wave_tail_cmd` in de-gui.yaml) in the terminal; replicates `_watch_wave_logs` (infinite `timeout 2s tail -99f latest/run.log` loop); hidden when `wave_tail_cmd` is empty
  - Live polling via JS `setInterval` + hidden trigger div while Waves tab is active; interval configurable via `config.wave_poll_interval_ms` in `de-gui.yaml` (default 10 000 ms; module-level `_WAVE_POLL_INTERVAL_MS` constant)
  - `refresh_wave_log_statuses` + poll also started in `on_load` when waves tab is restored
  - All column headers have `title=` tooltip descriptions
  - Wave log dir: `config.wave_logs_dir` in `de-gui.yaml` (default: `~/.run-waves-logs`)
  - **Unit-state.yaml** (added 2026-04-14): `~/.run-waves-logs/unit-state.yaml` persists per-unit statuses across restarts.
    Written by `local_state_watcher` (on every detected apply), `do_validate_unit_build_statuses` (after GCS scan), and
    `do_refresh_subtree_status` (after subtree scan). Read by `on_load` (instant startup). "⟳ Refresh" reads the YAML
    (fast); new "Validate (GCS)" button runs the full GCS scan. Per-unit logs written to `~/.run-waves-logs/unit-logs/<path>/`
    by `apply_unit` (timestamped + `latest.log` symlink, using `PIPESTATUS[0]` for correct exit code through tee).
  - **Auto-refresh** (added 2026-04-14): Appearance → "Auto-refresh" checkbox under "Show build status". `local_state_watcher`
    reads `unit-state.yaml` on every poll when enabled. Interval: `0` = on-change (mtime), N s = periodic (10/15/30/60/120/300).
    State: `unit_status_auto_refresh`, `unit_status_auto_refresh_secs` (both persisted). Globals: `_UNIT_STATE_YAML_MTIME`,
    `_UNIT_STATE_LAST_AUTO_REFRESH`.
  - **Waves folder view — collapsible folders** (added 2026-04-14): folder nodes show a `▶`/`▼` chevron; clicking
    toggles collapse via `toggle_wave_folder(folder_path)`. State: `wave_folder_collapsed: list[str]` (empty = all
    expanded; not persisted — resets each session to avoid hiding waves on name changes). `waves_folder_rows` filters
    out rows whose ancestors are in the collapsed set; adds `folder_path`, `has_children`, `is_expanded` fields to
    every row dict. Collapsing a parent also discards any already-collapsed descendant entries.
  - **Expand/Collapse all button** (added 2026-04-14): `⊟ Collapse` / `⊞ Expand` toolbar button (visible only in
    folder view). `toggle_wave_folder_all()`: expand clears the list; collapse computes all top-level folder prefixes
    from `wave_filters` and sets them. Computed var `wave_folders_collapsed: bool` drives the label/icon.
  - **Folder-level apply / destroy** (added 2026-04-14): `▶` and `🗑` buttons on every folder row.
    `begin_wave_folder_run(folder_path, mode)`: apply goes direct to terminal; destroy opens a confirmation dialog.
    `_open_wave_folder_terminal(folder_path, mode)` builds `-w '<folder>.*'` command (leverages `fnmatch.fnmatch`
    filter already in the `./run` script — no run-script changes needed). State vars:
    `wave_folder_run_dialog_open`, `wave_folder_run_pending_path`, `wave_folder_run_pending_mode`.
    Also fixed missing `log_update_age` in `wave_attrs` dict (was always showing `–` in folder view Log Update column).
- **Refactor** (added 2026-04-14): calls `framework/manage-unit/run` via background task
  - Opened by right-click → Edit → **Refactor (move / copy)…** — pre-fills Source from selected node
  - Operation toggle (Move / Copy), Destination text input, Preview (dry-run) and Execute buttons
  - Preview runs `--dry-run --json-report --skip-state` and displays unit count, external dep warnings, state/config counts
  - Execute runs the full operation and reloads the infra tree on completion
  - Replaced old clipboard copy/paste mechanism (removed: `copy_unit`, `copy_recursive`, `begin_paste`, `confirm_paste`, all clipboard state vars and dialogs)

### File Viewer (bottom-left panel)
- Menu bar: `FILE VIEWER | Type: [label] | Editor: [selector] | Copy | Download | Tail | [Chrome profile]`
- Three modes: **Unit File** (HCL), **Config Data** (YAML), **Wave Log** (ANSI)
- **Empty state**: `file_viewer_status_msg: str` state var drives a single `rx.text` in the
  content area when `hcl_content` is empty. Default: `"Select a node to view its file"`.
  Set to `"No unit file found for: {path}"` / `"No config data found for: {path}"` by
  `click_node` branches. Cleared (`""`) by all file-loading paths (`navigate_to_source`,
  `open_wave_definition`, `show_inventory`, `click_modules_node`, `navigate_to_module`,
  `open_abs_file_in_viewer`). Replaces the old nested `rx.cond` hardcoded messages.
- **Tail** button: runs `tail -99f <file>` in the terminal for the currently viewed file
- ANSI log rendering via `_ansi_to_html()` — SGR sequences, 256-color, search marks baked in
- **Markdown rendering**: `.md` files rendered via `rx.markdown()` with themed code blocks.
  - **Relative link interception**: `_markdown_link_interceptor_js()` installed via `install_resizer`; intercepts `<a>` clicks inside `#file-viewer-markdown`; relative paths resolved via `new URL(href, 'file://' + dir).pathname` (base dir from hidden `#hcl-file-path-src` `rx.box`) → triggers hidden `#markdown-link-input` → `open_markdown_link` handler opens the file if it exists; `http/https` links open in new tab; `#anchor` links scroll normally. Note: use `rx.box`, not `rx.span` (doesn't exist in 0.8.27).
  Toggle via Appearance menu → "File Viewer" → "Render markdown files" (default on).
  State var: `file_viewer_render_markdown`. Computed var: `hcl_is_markdown`.
- **Line numbers**: toggleable via Appearance menu → "File Viewer" → "Show line numbers" (default off).
  State var: `file_viewer_show_line_numbers`. Each line dict in `hcl_parsed_lines` includes `line_num: str(i+1)`.
  `_render_hcl_line` prepends a styled `rx.el.span` (dim, right-aligned, `width:4ch`, non-selectable,
  right-border rule) when enabled; an empty span otherwise. Persisted in `state/current.yaml`.
- **Path bar**: shows full `hcl_file_path` below the menu bar; long paths wrap (`word-break: break-all`) across multiple lines; clipboard icon button on the right copies the path (`copy_file_path_to_clipboard` handler)
- Search bar (always visible): query, **"Not found" badge** (red, shown when query has text but 0 matches), prev/next, case toggle, smooth scroll toggle
  - Search query is **cleared** when a unit file is loaded (`select_node`/`click_node` unit_file branch); only the YAML breadcrumb is cleared via `_CLEAR_CRUMB_JS`
  - `file_search_not_found` computed var: True when query non-empty AND `hcl_content` non-empty AND `file_search_match_count == 0`
  - **Config-data search "Not found" fix (2026-04-07)**: `_config_data_node_search_js` cached mark rebuilding behind `if(pre.dataset.searchQ !== ql)`. After React re-renders with new `hcl_content`, all `<mark>` elements are destroyed but `pre.dataset.searchQ` persists on the `pre` element itself. If the next node's query string is identical, the rebuild was skipped → 0 marks → "Not found". Fix: removed the cache guard; marks are always rebuilt unconditionally (function only called once per node navigation, so no performance impact). Deferred-search via `post_mode_switch_search` also remains in place to ensure React commits new content before JS runs.
- **Config-data quote toggle**: wrapping node paths in quotes is now `false` by default;
  configurable via `file_viewer.config_data_quote_path` in `de-gui.yaml`; overridable per-session
- YAML breadcrumb bar showing YAML key path at cursor/selection (e.g. `terragrunt_lab_stack.providers.proxmox.config_params`)
  - Only visible in `config_data` mode; hidden otherwise
  - Cleared (`_CLEAR_CRUMB_JS`) on every file load (prepended to search JS at all file-loading call sites: `_search_reapply_script`, `select_node`, `post_mode_switch_search`, `click_node`, `navigate_to_source`)
- Download and clipboard copy buttons
- "Open in editor" dropdown (configurable editors in `de-gui.yaml`)
  - **Embedded editor opens at viewed line**: `enter_file_edit_mode` reads top-visible line from `#file-viewer-pre` scroll position (`_read_pre_top_line_js`) via callback before activating Monaco; `open_editor_at_line` callback sets `file_editor_active` then calls `_monaco_reveal_line_js` (polls until Monaco mounted, then `getTopForLineNumber` + `setScrollPosition` to pin line to top). `_read_pre_top_line_js` uses `getBoundingClientRect()` (not `offsetTop`/`scrollTop`) so viewport-coordinate comparison is correct regardless of intermediate positioned wrappers.

### Terminal / Browser (bottom-right panel)
- xterm.js terminal over PTY WebSocket (`/ws/terminal?cwd=...`)
- `open_shell` and `open_ssh_terminal` close any existing terminal before opening a new one (embedded/ttyd only): clear `shell_cwd`/`shell_initial_cmd`/`ttyd_port` and `yield` to flush blank state to browser first
- Browser iframe for node-click auto-URLs and Playwright viewer
- **Hide auto-run commands** (Appearance menu, default on): suppresses display of
  auto-sent commands (tail, SSH, etc.) via `termios.ECHO` disable/restore around the
  PTY write; command still executes, only its text is hidden
- **Terminal backend dropdown** (Appearance menu → Terminal → Backend, added 2026-04-03):
  `terminal_backend` state var; options: `"embedded"` (xterm.js), `"ttyd"` (in-panel, faster),
  native terminals that open in a separate window.
  - **ttyd**: `_start_ttyd(cwd, cmd)` spawns `ttyd --port N [--index patched.html]` on a free port; `ttyd_port` state var;
    no `--once` (stays alive across iframe reloads; killed by next `_start_ttyd()` or `open_shell("")`);
    `_prepare_ttyd_custom_index()` patches `this.resizeOverlay=!0` → `!1` in ttyd's self-contained JS
    to suppress the "NxM" overlay (called lazily on first `_start_ttyd()` — NOT at import time, which caused startup loop);
    `terminal_iframe_url` returns `http://localhost:{port}` when ttyd is active. Always shown in
    dropdown; if not installed, Appearance menu shows warning + "Install" button that runs
    `_TTYD_INSTALL_CMD` (`sudo apt install -y ttyd` / `brew install ttyd`) in the embedded terminal.
  - **Native terminals** (separate window): Linux: gnome-terminal, xterm, konsole, tilix;
    macOS: iTerm2 (osascript), Terminal.app (osascript); cross-platform: alacritty, kitty, WezTerm.
    `_launch_native_terminal(id, cwd, cmd)` — inner bash runs `cmd; exec bash` to keep shell open.
  - Platform-aware: Linux terminals hidden on macOS and vice versa (`sys.platform == "darwin"`).
  Detected at startup via `_TERMINAL_BACKENDS`; persisted in `state/current.yaml`.
- **URL action buttons are browser-picker dropdowns** — each shows `label ▾`; picking
  a profile opens the URL immediately without pre-selecting a global profile
  (`dispatch_url_with_profile` handler; `_open_url_in_profile` helper)
- `browser_profile == "none"/"" / "default"` all fall through to `xdg-open` (bug fix)
- `maas_ui` / `maas_ui_machine` entries removed from `provider-actions.yaml`; covered
  by `_browser_url` in config_params
- mesh-central: `_browser_url: https://{ansible_host}` in stack YAML (was hardcoded IP `10.0.10.155`)
- maas-server-1: `_browser_url: http://{ansible_host}:5240/MAAS/r/machines` (was hardcoded `10.0.10.11`)
- `_browser_url` supports `{ansible_host}` and other inventory-var tokens via Python `.format()`
  resolved in `_get_browser_url_for_node()`
- **Global browser profile selector removed** — all URL dispatch paths now use inline
  browser-picker; context menu URL items use a `rx.context_menu.sub` sub-menu
- Removed dead code: `_browser_profile_selector`, `_profile_menu_item`,
  `browser_profile_label`, `has_node_browser_actions`, `selected_node_url_actions`,
  `set_browser_profile`

---

## Packages View

- Explorer root = `"packages"` shows collapsible list of all packages in `_modules/<provider>/<package>/`
- `_scan_packages()` builds `_PACKAGES_CACHE` at startup; state var `packages_data`
- `PackageInfo.source_repo: str` — empty for built-in packages; holds ext repo name for cloned packages

### Expand/collapse
- `packages_expanded_names: list[str]` state var; default all collapsed.
- `toggle_package_expanded(name)` handler adds/removes names from the list.
- `expand_all_packages()` / `collapse_all_packages()` handlers set/clear the full list.
- `packages_all_expanded: bool` computed var (`True` when all packages are in the expanded list).
- **"⊞ Expand all" / "⊟ Collapse all" button** in the packages panel header (ghost style, between spacer and "+ Repo"); toggles based on `packages_all_expanded`.
- **Collapsed row**: chevron (▶), 📦, name, providers (dim), source-repo badge (cyan if ext).
- **Expanded card**: full detail — header row collapses on click; shows same six sections as before.

### External package repos
- `_EXT_PACKAGES_DIR = _STACK_DIR / "_ext_packages"` — clone target parent.
- `_load_ext_package_repos()` / `_save_ext_package_repos()` — persist `[{name, url}]` under
  `current.ext_package_repos` in `state/current.yaml`.
- `clone_pkg_repo()` background task: `git clone --depth=1 <url> _ext_packages/<name>/`, then rescans.
- `remove_pkg_repo(name)`: `shutil.rmtree` the clone, update state, rescan.
- Ext repo packages use the cloned repo's own `scripts/` and `_providers/` dirs for scripts/templates.
- UI: header "PACKAGES" + "+ Repo" button; "Ext repos: chip…" row with ✕ per repo.
- `_add_pkg_repo_dialog()` — dialog with Name + URL inputs, Clone button, cloning/error status.

### Package data
- `PackageFileLink(rx.Base)` — generic `label`/`path` typed pair; used for `tg_scripts_sub_dirs` and `wave_test_playbooks` in `PackageInfo`
- `PackageInfo.provider_templates` — `list[str]` (absolute paths); NOT `list[PackageFileLink]`
  (changed to avoid nested rx.Base field access as event arg in doubly-nested foreach)
- Each expanded card shows six sections (conditionally rendered):
  1. **Header**: name | source-repo badge | config YAML (ghost) | secrets YAML (orange ghost, if exists)
  2. **Providers**: comma-joined provider names
  3. **Provider Templates**: pills linking to `_providers/<pkg>/*.tpl` files (via `_pkg_template_pill`)
  4. **Modules**: table of provider/name/.tf links with optional tg-scripts README button
  5. **TG Scripts**: `pkg_env.sh` + `README.md` files; then provider sub-dir READMEs as pills
  6. **Wave Scripts**: `pkg_env.sh` + `README.md` files; then test playbook `run` scripts
     (label = `category/wave`, path = abs path to `run` script)
- `_pkg_template_pill(path: str)` — renders provider template pill; label = `path.split("/")[-1]`
- `_pkg_file_link_pill(lnk)` — renders clickable button or non-clickable styled text (for PackageFileLink items)
- All links call `open_abs_file_in_viewer(abs_path)`
- Known packages (as of 2026-04-02): `default` (config-only), `buckets-pkg` (aws/azure/gcp), `default-pkg` (null+more, has provider templates), `maas-pkg`, `proxmox-pkg`, `unifi-pkg` (has provider templates)
- Provider templates exist only for `default-pkg` and `unifi-pkg` (checked via `_providers/<name>/*.tpl`)
- Section labels have tooltips: **Providers** ("Terraform providers used by the modules"), **TG Scripts** ("Scripts called by the Terragrunt units"), **Wave Scripts** ("Scripts available to be called by the wave(s)")

---

## Stack Config Loading

- `_find_stack_config()`: rglobs `terragrunt_lab_stack*.yaml` (excl. secrets) under
  `deploy/config/files/platform-config/terragrunt/terragrunt_lab_stack/`
- Sort key ensures `terragrunt_lab_stack.yaml` (base, no package suffix) is always first;
  package files now live in subdirectories (`maas-pkg/`, `proxmox-pkg/`, etc.) — alphabetically
  they sort before the base file, so an explicit sort key is required.
- `_STACK_CONFIG_KEY`: detected at load time from actual YAML top-level key — never hardcoded
- Config file watcher (`config_file_watcher`, `@rx.event(background=True)`) polls mtime every 2s;
  on YAML change also refreshes `hcl_content`/`hcl_file_path` when file viewer is in `config_data` mode
- `select_node` in `config_data` mode always reloads via `_read_stack_config_file()` (no `if not self.hcl_content` guard).
  `_read_stack_config_file()` uses `_stack_config_file_cache` (mtime-based): caches the resolved path (avoids
  `git rev-parse` subprocess on every click) and the file content (skips disk read when mtime unchanged).
  Re-reads on mtime change; clears path cache if file disappears.

### "Inherited from" links (fixed 2026-04-04)
`navigate_to_source(full_path)` now:
1. Selects the ancestor node in the tree (provider-stripped in merged mode, as before).
2. Calls `_find_source_config_file(provider, full_path)` — iterates all stack config files
   to find the one whose `providers[provider].config_params` contains `full_path`.
3. Loads that file in `config_data` mode and searches with the **full provider-inclusive path**
   (e.g. `cat-hmc/proxmox/pwy-homelab`), so the right YAML entry is always found.
Previously: called `click_node(stripped_path)` → searched with the merged path in the base file only.

### Performance caches (as of 2026-04-04)
- **`_load_config()`**: mtime-cached; only re-parses `de-gui.yaml` when the file changes.
  Globals: `_config_cache`, `_config_mtime`.
- **`_read_hcl_file()`**: two-level mtime cache.
  `_hcl_path_cache` (node_path → abs_path, declared at line of `_ALL_NODES_CACHE`) avoids
  `_find_unit_hcl()` dir scans on repeated clicks. `_hcl_content_cache` (abs_path → {mtime, content})
  avoids re-reading unchanged files. Both cleared in `_init_nodes_cache()`. Path entry evicted on
  `FileNotFoundError` so deleted files are re-probed.
- **`_save_current_config()`**: debounced 800 ms via `_schedule_config_write()` + `threading.Timer`.
  Write runs in background via `_do_write_menu()`. `_state_write_lock` (threading.Lock) shared with
  `_save_ext_package_repos()`. Rapid clicks produce at most one disk write per 800 ms.
- **`click_node()`**: `yield` after `selected_node_path` + `expanded_paths` update flushes tree
  highlight to client before file I/O begins.

---

## Context Menu Actions

- Groups: build → destroy → clipboard → shell → provider/unit/misc
- SSH detection: `_get_ssh_command(path)` — exact then prefix match on inventory hostname;
  requires `ansible_host` to be set. No SSH button if VM not yet deployed/inventoried.
- SSH command always includes `-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR` to suppress known-hosts prompts and warnings.
- **Open Kube Shell** (added 2026-04-03): injected in Shell group (context menu) and as a **"Kube"**
  button in the browser-panel header when the node's last path segment is `"kubeconfig"`.
  Cluster name = second-to-last segment. Command (via `_build_kube_shell_cmd`):
  `source <abs-path>/set_env.sh && export KUBECONFIG=$_DYNAMIC_DIR/kubeconfig/{cluster_name}_kubeconfig.yaml && kubectl get nodes`
  Uses absolute path `_APP_DIR.parent / "set_env.sh"` (NOT `git rev-parse` — that breaks when cwd is not a git repo).
  `cwd` = node's infra dir (`shell_dir`, or `_infra_path / path` fallback). Uses `action_type: "ssh"` → `open_ssh_terminal`.
- `_DYNAMIC_DIR` added to `set_env.sh` (2026-04-03): derived as `$_STACK_DIR/../../../../k8s-recipes/config/tmp/dynamic`
  → `$HOME/git/pwy-home-lab/deploy/k8s-recipes/config/tmp/dynamic`. Prints WARNING if path doesn't exist.
- **SSH recompute after inventory refresh**: `selected_node_browser_actions` (a `@rx.var`) reads
  inventory from a module-level cache Reflex doesn't track. Fixed by adding `inventory_refresh_counter`
  state var (accessed in the var to register dependency) + `signal_inventory_ready` background event
  (dispatched from `on_load`) that polls `_INVENTORY_REFRESH_COMPLETE` and bumps the counter when
  the refresh script finishes.

---

## Copy / Paste / Delete

- Single: `copy_unit` / `confirm_paste` — copies HCL + config block
- Recursive: `copy_recursive` / `confirm_recursive_paste`
- Delete: `begin_delete_file` / `confirm_delete_file`
- **`_deep_plain(obj)`**: helper that recursively strips Reflex proxy wrappers before
  writing config blocks to YAML; must be used at all yaml.dump sites that receive
  state-var dicts (shallow `dict()` copy leaves nested lists/dicts as proxies, which
  PyYAML serialises as `!!python/object/apply:reflex.istate.proxy._unwrap_for_pickle`)

---

## Wave Operations

- `begin_wave_run(name, mode)`: apply → terminal immediately; destroy → confirmation dialog
- Command: `_STACK_DIR/run -a -w {name} --skip-test` (apply) / `run --clean -w {name}` (destroy)
- Log scanning: three independent passes per wave (main apply/destroy, precheck, test-playbook)
- `refresh_wave_log_statuses()` called on tab switch AND on page load when waves tab is restored

---

## Reflex Constraints (see also CLAUDE.md)

- Background tasks: `@rx.event(background=True)` — `rx.background` does NOT exist in 0.8.27
- Background task names must be public (no leading `_`)
- `rx.call_script` callbacks receive a single scalar; return two values via two separate calls
- `node["field"]` inside `rx.foreach` is an `ObjectItemOperation` — use `rx.text("(", node["x"], ")")`
- Underscore-prefixed methods are not Reflex events — never use as `callback=` args

---

## Key State Variables

| Var | Type | Purpose |
|-----|------|---------|
| `selected_node_path` | str | Currently selected infra node path |
| `object_viewer_mode` | str | `"params"` or `"waves"` |
| `hcl_content` / `hcl_file_path` | str | File viewer content / path |
| `file_viewer_mode` | str | `"unit_file"`, `"config_data"`, `"wave_log"` |
| `wave_show_start_time/end_time/duration/age` | bool | Timing column visibility |
| `wave_highlight_recent` | bool | Highlight most-recently-updated wave row |
| `recent_wave_name` | str | Wave name updated within last 10s (or `""`) |
| `waves_view_mode` | str | `"list"` or `"folder"` |
| `clipboard_unit_path` | str | Copied unit path |
| `delete_dialog_open` / `destroy_dialog_open` / `taint_dialog_open` | bool | Confirmation dialogs |
| `param_edit_dialog_open` | bool | Inline param edit dialog |
| `show_wave_numbers` / `show_full_module_name` | bool | Appearance toggles |
| `cy_show_dependencies` | bool | Nested Networks: show dependency arrows |
| `cy_color_by_wave` | bool | Nested Networks: color nodes by wave |

---

## Nested Networks View

- Cytoscape.js compound node graph; parent-child hierarchy via `parent` data field
- View selector dropdown option "Nested Networks" (last in list)
- Appearance menu "Nested Networks" section:
  - **Show dependency arrows**: parses `dependency { config_path = "..." }` from each
    HCL leaf, resolves to infra-relative paths, stores in `_DEPENDENCIES_CACHE`; rendered
    as bezier Cytoscape edges filtered to visible node set
  - **Color nodes by wave**: maps waves to `_WAVE_PALETTE` (12-color) by declaration order;
    embeds `wave_color` in node data; appends `wave-colored` CSS class (overrides provider
    colors via higher-specificity stylesheet rules placed after provider rules)
- `_build_cytoscape_edges()` — returns edge dicts from `_DEPENDENCIES_CACHE`
- `_init_dependencies_cache()` — called at startup + manual rescan
