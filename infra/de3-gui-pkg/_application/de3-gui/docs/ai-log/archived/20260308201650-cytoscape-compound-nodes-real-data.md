# Cytoscape Compound Nodes — Real Data + Click to Expand/Collapse

## Changes

### `homelab_gui/homelab_gui.py`

**Compound node format** (`_build_cytoscape_elements`):
- Rewrote to use the `parent` data field instead of edges.
  Cytoscape.js renders nodes with a `parent` field as visually nested
  compound nodes (parent box visually contains its children).
- Returns empty list when infra dir is unavailable; caller falls back to
  synthetic demo data.

**Synthetic fallback** (`_SYNTHETIC_COMPOUND_ELEMENTS`):
- Replaced the flat edge-based `_SYNTHETIC_ELEMENTS` with a realistic
  compound hierarchy mirroring the real infra structure:
  `cat-hmc → proxmox/maas/unifi → pwy-homelab → pve-nodes/machines → pve-1/pve-2/...`

**Stylesheet** (`_CYTOSCAPE_STYLESHEET`):
- `:parent` selector styles compound (container) nodes — semi-transparent
  background, bold label at top, rounded border, padding so children fit.
- `:childless` selector for leaf resource nodes (smaller, solid colour).
- `node[depth = 0]` for the outermost category box.
- `node[?has_terragrunt]:childless` adds a green border to resources that
  have a `terragrunt.hcl`.
- Per-provider accent colours via CSS class selectors
  (`node.proxmox:parent`, `node.proxmox:childless`, etc.).

**Click-to-collapse/expand** (`_CYTOSCAPE_INIT_JS`):
- Pure Cytoscape.js, no plugin required.
- `cy` callback prop: `(cy) => { cy.on('tap', 'node', ...) }`
- Clicking a compound node hides/shows all its descendants using
  `node.descendants().hide()` / `.show()` and toggles the `.cy-collapsed`
  class (which makes the border dashed).

**`_CytoscapeGraph` component**:
- Added `cy_cb: Var[Any]` prop (Python) → renamed to `cy` in JSX via
  `_rename_props: {"cyCb": "cy"}`.
- `Var(_js_expr=_CYTOSCAPE_INIT_JS)` passes the raw JS function
  expression as a React prop without JSON serialization.

**`AppState`**:
- Added `cytoscape_elements: list[dict]` field; default is the synthetic
  compound data so something renders before `on_load` fires.
- `on_load` populates it from `_build_cytoscape_elements()`, falling back
  to synthetic if the infra directory is unavailable.

**`cytoscape_view()`**:
- Passes `AppState.cytoscape_elements` (reactive) so the graph updates
  when state changes.
- Layout: `cose` with `nestingFactor: 5` — handles compound nodes well
  without external layout extensions.

## How it works

1. App starts → `cytoscape_elements` defaults to synthetic compound data.
2. `on_load` fires → scans infra dir → populates `cytoscape_elements` with
   real compound elements (or keeps synthetic if no infra).
3. Cytoscape renders compound nodes: categories → providers → locations →
   resources, all visually nested.
4. Click a compound node → all descendants hide (node collapses to min-size).
5. Click again → descendants show (node expands).
