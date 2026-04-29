# Home Lab GUI — Design Instructions

Authoritative reference for AI sessions working on `homelab_gui`.
Covers every design decision, code convention, and feature instruction given so far.

---

## App Basics

- Python Reflex web app served at `http://localhost:9080` (backend on `8000`).
- Visualises the home lab infrastructure DAG by scanning the `infra/` directory tree.
- Config lives in `infra/de3-gui-pkg/_config/de3-gui-pkg.yaml` (top-level key `de3-gui-pkg:`).
- Runtime UI state persisted to `state/current.yaml` (written by the app; safe to delete).
- The infra DAG is built in memory at startup by scanning `infra/` — no dag.yaml file.
- Stack config (non-secret parameters) auto-located from per-package `infra/<pkg>/_config/<pkg>.yaml`
  files via `git rev-parse --show-toplevel` at startup.

## make / run

- `make` (default) runs `build` then `test`.
- `make run` starts the app in the foreground.
- `make test` probes `http://<vm_ip>:9080` with retries, then opens a browser.
  Browser search order: `google-chrome` → `google-chrome-stable` → `chromium-browser`
  → `chromium` → `xdg-open` → `open`.

---

## Overall Layout

- Fixed navbar (56 px) across the top.
- Below the navbar: two equal-flex panels side by side, full-height.
- **Left panel** — visualization explorer.
- **Right panel** — unit params for the selected node (always).

---

## Visualization Framework System

### Concept

The left panel supports multiple pluggable visualization frameworks.
A framework dropdown in the left panel header switches between them at runtime.

### Registry (`VIZ_FRAMEWORKS` list in `homelab_gui.py`)

Each entry has: `key`, `label`, `description`.
The active framework is stored in `AppState.viz_framework` (default `"reflex"`).

### Currently registered frameworks

| Key           | Label            | Implementation          |
|---------------|------------------|-------------------------|
| `reflex`      | Folder           | Built-in Reflex components (tree view) |
| `cytoscape`   | Nested Networks  | React (react-cytoscapejs NoSSRComponent), Python-computed positions |
| `reactflow`   | Tree             | React Flow NoSSRComponent, Python-computed hierarchical layout |
| `archdiagram` | Arch Diagram     | React Flow group nodes, Python-computed positions from live infra |

### Adding a new framework

1. Add an entry to `VIZ_FRAMEWORKS` with a unique `key`.
2. Implement `<key>_view() -> rx.Component` — for iframe-based viewers,
   call `_iframe_view("/my_viewer.html")`.
3. Add a `("<key>", <key>_view())` case to `render_left_panel_content()`.
4. Create `assets/<key>_viewer.html` for iframe-based frameworks.
5. If the viewer needs data, add a Starlette route via
   `app._api.add_route("/api/...", handler, methods=["GET"])`.
6. Update this file.

### Iframe-based framework pattern

- Viewer HTML files live in `assets/` (Reflex serves them at the root URL).
- Each viewer fetches infra data from a backend API endpoint on load.
- Node clicks send `window.parent.postMessage({type: 'nodeSelected', path: '...'}, '*')`
  to the parent Reflex frame for future two-way state integration.

### API endpoints (Starlette, served on port 8000)

| Endpoint                        | Format                        | Used by               |
|---------------------------------|-------------------------------|-----------------------|
| `GET /api/infra-graph`          | Cytoscape JSON (`elements[]`) | cytoscape viewer      |
| `GET /api/infra-mxgraph`        | Flat cell list (`cells[]`)    | mxGraph viewer        |
| `GET /api/arch-diagram-drawio`  | draw.io mxGraphModel XML      | arch diagram toolbar export |

Data is built from `_ALL_NODES_CACHE` and `_DEPENDENCIES_CACHE`, module-level caches populated once at import.

### Node cache (`_ALL_NODES_CACHE`)

Scanned once at import time by `_init_nodes_cache()`.
`AppState.on_load` reuses this cache instead of re-scanning.
API endpoints read directly from the cache without going through Reflex state.

---

## Left Panel — Arch Diagram Framework

Activated when `viz_framework == "archdiagram"`.

### Config file

`infra/de3-gui-pkg/_config/arch_diagram_config.yaml` (key: `arch_diagram`) controls:

- `direction` — `LR` (swimlanes left→right) or `TB` (top→bottom).
- `component_depth` — depth in the infra path at which nodes become diagram components
  (0 = package root, 1 = first sub-level, etc.).
- `show_connections` — whether to draw TF dependency edges between components.
- `layers[]` — ordered list of swimlane definitions; each has `id`, `label`, `color`,
  `stroke`, `order`, and `path_prefixes`. First matching prefix wins.
  Nodes that match no layer go to an implicit "Other" lane.
- `provider_styles` — per-provider accent colour overrides for component boxes.

### Component derivation

Components are **auto-derived** from `_ALL_NODES_CACHE` — no manual list in config.
Nodes at `component_depth` are selected; each is assigned to the first layer whose
`path_prefixes` match the start of the node path. Connections come from
`_DEPENDENCIES_CACHE` filtered to component-to-component pairs.

### Toolbar and export

A thin toolbar above the canvas contains a **File** menu with:
- **Export → draw.io / diagrams.net (.drawio)** — downloads the diagram as `.drawio` XML
  via `GET /api/arch-diagram-drawio`. The XML mirrors the React Flow layout and can be
  opened in draw.io desktop or `app.diagrams.net`. Lucidchart can import it directly.

### Clicking nodes

Clicking a component box selects it and updates the right panel (same behaviour as
other React Flow views). Clicking a swimlane group node does nothing.

---

## Left Panel — Reflex Native Framework

### Sub-view selector

Available only when `viz_framework == "reflex"`:
- **Tree** — collapsible infra directory tree.
- **C4 Static** — provider cards with resource lists.
- **Component Diagram** — layered swimlane (On-Premise → Provisioning → Cloud).

### Tree view

- Top-level category nodes are expanded by default.
- Nodes with `terragrunt.hcl` show a package icon.
- Selected node is highlighted in indigo.
- Right-click context menu: Expand / Collapse.

### Tree mode toggle

Visible when `left_view == "tree"`:
- **Separated** (default) — one provider subtree per provider.
- **Merged** — strips the provider segment from every path, deduplicates,
  and shows a single unified tree. Merged nodes show a `providers_str` pill
  listing contributing providers.

### Provider filter (navbar popover)

Checkboxes to show/hide entire provider subtrees.
"All" / "None" buttons for bulk toggle.

---

## Right Panel — Unit Params

Always shows `config_params` from the package YAML config for the selected node.
Clicking any tree node selects it, resets the provider tab, and updates the right panel.

### Provider tab bar

A tab strip appears when the selected node has params from multiple providers:
```
[ All ]  [ proxmox ]  [ maas ]
```
Clicking a tab filters the display to that provider's params.
Clicking the active tab toggles back to All.

### Params structure

For each provider that has matching config, the panel shows:

1. **Provider header** — coloured accent bar (provider-specific hex colour).
2. **Source dividers** — one per ancestor path that contributed params, from
   root → most-specific:
   - `──── inherited from  <path> ────`
   - `──── defined here ────`
3. **Param rows** — key (gray monospace, 160 px) + formatted value.

### Parameter ordering (within each source block)

`_`-prefixed keys first (alphabetical), then all other keys (alphabetical).

### Value formatting

- Scalars: inline monospace.
- Dicts / lists: `yaml.dump` output in a light-grey code block with `white-space: pre`.
- `None` → `(not set)`.

### Inheritance override colouring

When a more-specific ancestor overrides a key from a less-specific one,
the **overriding value** is shown in green, fading lighter with each level:

| Override level | Value colour | Code-block bg  |
|----------------|--------------|----------------|
| 0 (original)   | `#1f2937`    | `#f3f4f6`      |
| 1st override   | `#15803d`    | `#dcfce7`      |
| 2nd override   | `#22c55e`    | `#f0fdf4`      |
| 3rd+ override  | `#86efac`    | `#f7fef9`      |

Overriding values are also displayed in medium weight (500).

### Merged-mode param lookup

In merged mode, `selected_node_path` has no provider segment
(e.g. `proxmox-pkg/_stack/proxmox/pwy-homelab/pve-nodes/pve-1`).
`_get_unit_params_flat(path, is_merged=True)` reconstructs the provider-specific
path by inserting each provider name at depth-1 before matching config_params keys.

---

## Cytoscape.js Viewer (`assets/cytoscape_viewer.html`)

- Dark theme (`#0f172a` background), sidebar on the right.
- Libraries loaded from unpkg CDN: `cytoscape@3.29.2`, `dagre@0.8.5`, `cytoscape-dagre@2.5.0`.
- Fetches `/api/infra-graph` on load.
- Node appearance: size and shape vary by depth and `has_terragrunt`;
  colour from `PROVIDER_ACCENT`.
- Category nodes (depth 0): larger, blue-bordered, bold label.
- Layout switcher (bottom-left): Hierarchy (dagre), Force (cose), Breadth-first, Concentric.
- Controls (top-left): zoom in/out, fit.
- Sidebar: node detail card, filter/search input, provider legend.
- Click sends `postMessage({type: 'nodeSelected', path})` to parent Reflex frame.

## mxGraph Viewer (`assets/mxgraph_viewer.html`)

- Light theme, sidebar on the right.
- mxGraph library loaded from `unpkg.com/mxgraph@4.2.2`.
- Fetches `/api/infra-mxgraph` on load.
- Uses `mxHierarchicalLayout` (top-to-bottom).
- Node style varies by depth, provider colour, and `has_terragrunt`.
- Controls: zoom in/out, fit, reset layout.
- Click sends `postMessage({type: 'nodeSelected', path})` to parent Reflex frame.

---

## Visual Design Principles

- Light theme for Reflex Native; dark theme for Cytoscape.js; light for mxGraph.
- Provider accent colours used consistently everywhere:

  | Provider | Hex       |
  |----------|-----------|
  | gcp      | `#4285F4` |
  | aws      | `#FF9900` |
  | azure    | `#0078D4` |
  | proxmox  | `#E07000` |
  | maas     | `#7C3AED` |
  | unifi    | `#4338CA` |
  | null     | `#6B7280` |

- Panel headers: 36 px, grey background, uppercase label in small caps.
- Tree rows: subtle indigo highlight on selection (`#e0e7ff`), blue hover.
- Monospace font for all keys and YAML values.
- Code blocks: light grey background, rounded border, `pre` white-space.

---

## Build Status System

### Overview

Per-unit build status dots (7 px circles) are shown in the tree when **Show build
status** is enabled. Status is derived from three independent tiers that run
concurrently and merge their results into `unit_build_statuses: dict[str, str]`.

### Status values

| Value | Colour | Source |
|---|---|---|
| `"ok"` | Green | resources > 0 in tfstate (Tier 1 or 2) |
| `"destroyed"` | Purple | resources == [] in tfstate (Tier 1 or 2) |
| `"fail"` | Red | Tier 3 non-zero exit, or in run.log queue with no GCS state |
| `"none"` | Grey | No state file found anywhere |

### Tier 1 — local `.terragrunt-cache` watcher

**Handler:** `local_state_watcher` (`@rx.event(background=True)`)
**Type:** Process-level singleton (guarded by `_LOCAL_STATE_WATCHER_RUNNING`)
**Started:** `on_load` dispatches it; re-dispatch on each page load is safe

Poll loop (runs forever while the process is alive):
1. `find <infra_dir> -path "*/.terragrunt-cache/*/terraform.tfstate" [-newer <marker>]`
2. Strip `.terragrunt-cache/...` suffix to recover unit path relative to `infra/`
3. **Do NOT read local file content.** With a GCS backend the local `terraform.tfstate`
   is always `resources:[]` (backend pointer, not actual state). Reading it would set
   every unit to "destroyed" regardless of real state.
4. For each detected change: `gsutil cat gs://<bucket>/<unit_path>/default.tfstate` →
   parse JSON → `resources` length → `"ok"` or `"destroyed"`. Sets `"unknown"` if GCS
   unreachable (apply may still be in progress).
5. Merge into `unit_build_statuses` (does not replace entries from other tiers)
6. Touch `/tmp/homelab_gui_state_check.marker` after each scan

Poll intervals:
- Normal: 8 s
- Accelerated: 2 s for 60 s after `apply_unit` or `apply_recursive` is called

Acceleration is controlled by two module-level globals set in the apply handlers:
- `_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL: float` — `time.time()` deadline
- `_LOCAL_STATE_WATCHER_FOCUS_PATHS: list[str]` — targeted unit paths (informational)

**Path mapping:** unit path form is `<pkg>/_stack/<provider>/env/.../leaf`. The
`.terragrunt-cache` segment is at depth immediately below the unit dir:
```
infra/<pkg>/_stack/<provider>/.../leaf/.terragrunt-cache/<hash>/<hash>/terraform.tfstate
```
`Path.relative_to(infra_dir)` strips the `infra/` prefix; everything before `.terragrunt-cache`
is the unit path.

### Tier 2 — GCS state bucket scan

**Handler:** `do_refresh_unit_build_statuses` (`@rx.event(background=True)`)
**Entry point:** `refresh_unit_build_statuses` (sync; sets spinner flag, dispatches task)
**Triggers:** toggle on, "⟳ Refresh status" button, wave run completion

Algorithm:
1. `gsutil ls -l -r gs://<bucket>/<pkg>/_stack/` per package prefix (adds mtime to listing)
2. Compare each file's mtime against `gcs_state_mtimes: dict[str, str]` (state var)
3. **Changed or new file:** `gsutil cat <uri>` → parse JSON → check `resources`
4. **Unchanged file:** carry forward previous status (zero GCS downloads)
5. Parse `run.log` "Unit queue" lines; units in queue with no GCS state → `"fail"`
6. Merge with existing `unit_build_statuses` (Tier 1 local entries survive for units not yet in GCS)

`gcs_state_mtimes` persists between refreshes in state. On a stable lab with no recent
applies, only the `gsutil ls -l -r` call is made (zero downloads).

### Tier 3 — apply exit code

**Triggered by:** `apply_unit` context-menu action only (not `apply_recursive`)

`apply_unit` appends to the shell command:
```bash
; echo $? > /tmp/homelab_gui_apply_<safe_path>.exit
```
where `safe_path = unit_path.replace("/", "+")` (reversible; `+` never appears in unit paths).

Each Tier 1 watcher loop also calls `glob.glob("/tmp/homelab_gui_apply_*.exit")`:
- Reads file, parses exit code int
- Recovers unit path: `stem[len("homelab_gui_apply_"):].replace("+", "/")`
- Exit code ≠ 0 → `"fail"` (overrides Tier 1 `"ok"` for partial failures)
- Exit code == 0 → log only (Tier 1 tfstate reading already set the correct status)
- File is deleted unconditionally after reading (one-shot)

`apply_recursive` is NOT wrapped — individual unit statuses within the recursive run are
picked up by Tier 1 as each unit writes its local tfstate.

### Refresh triggers summary

| Trigger | Tier | Notes |
|---|---|---|
| Toggle "Show build status" on | 2 | Full GCS scan |
| "⟳ Refresh status" button | 2 | Full GCS scan, incremental if mtimes cached |
| Wave run completes | 2 | `had_running_wave` transition detection in `refresh_wave_log_statuses` |
| Right-click → "Refresh build status (recursive)" | 1 + 2 | Scoped to clicked node's subtree; reuses `gcs_state_mtimes` |
| `apply_unit` called | 1 + 3 | Accelerates Tier 1 to 2 s; Tier 3 exit file read on next loop |
| `apply_recursive` called | 1 | Accelerates Tier 1 to 2 s; individual units updated as each completes |
| Background Tier 1 loop | 1 | Every 8 s; markers make it incremental |

### Module-level globals

```python
_LOCAL_STATE_WATCHER_RUNNING: bool          # process singleton guard
_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL: float  # time.time() fast-poll deadline
_LOCAL_STATE_WATCHER_FOCUS_PATHS: list[str]   # paths targeted by last apply (informational)
```

### State vars

```python
unit_build_statuses:          dict[str, str]  # the merged status map shown in the tree
gcs_state_mtimes:             dict[str, str]  # GCS mtime cache for incremental Tier 2 scans
show_unit_build_status:       bool            # feature toggle
is_refreshing_build_statuses: bool            # True while Tier 2 is running (spinner)
build_status_error:           str             # error message from last Tier 2 scan
local_state_watcher_active:   bool            # True while Tier 1 loop is alive
```

### Adding a new status value

1. Add the value string to the `do_refresh_unit_build_statuses` docstring.
2. Add a new arm to both `rx.match` blocks in the tree node renderer (around line
   10740 — background colour and tooltip title).
3. Choose a Radix colour token (`--<colour>-9`) not already used.

---

## Code Conventions

### Module-level globals (never state vars)
- `_STACK_CONFIG` — loaded once from the package YAML config at import.
- `_ALL_NODES_CACHE` — infra nodes scanned once at import via `_init_nodes_cache()`.
- Both avoid serialising large dicts to the Reflex frontend.

### Pre-computed booleans in state dicts
All server-side booleans used in `rx.cond` (e.g. `is_bold`, `is_override`,
`is_override`, `show_badge`) are pre-computed in Python before being stored
in state lists. Reflex `ObjectItemOperation` variables do not support Python
comparison operators (`<`, `>`, `!=`) at render time.

### Typed pydantic models
Required for any nested `rx.foreach` so Reflex can infer element types.
Use `pydantic.BaseModel`, not the deprecated `rx.Base`.

### Flat list pattern
`list[dict]` with a string `row_type` discriminator field is used instead of
nested lists to avoid `ForeachVarError` on `Any`-typed vars.
`rx.match(item["row_type"], ...)` dispatches to the correct renderer.

### Adding a new Starlette API route
```python
from starlette.requests import Request
from starlette.responses import JSONResponse as _JSONResponse

async def _api_my_endpoint(request: Request) -> _JSONResponse:
    return _JSONResponse({...})

app._api.add_route("/api/my-endpoint", _api_my_endpoint, methods=["GET"])
```
Note: `app.api` does not exist in Reflex 0.8.27; use `app._api` (Starlette instance).
