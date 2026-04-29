# Tree2 View — React Flow Hierarchical Tree Diagram

## Changes

### `homelab_gui/homelab_gui.py`

**New import:** `ImportDict` from `reflex.utils.imports` (needed for CSS import in component).

**`_ReactFlowGraph` component** (NoSSRComponent):
```python
class _ReactFlowGraph(NoSSRComponent):
    library: str = "reactflow@11.11.4"
    tag: str = "ReactFlow"
    is_default: bool = True
    _rename_props: ClassVar[dict] = {"rfStyle": "style", "onNodeClickCb": "onNodeClick"}
    nodes: Var[list]
    edges: Var[list]
    fit_view: Var[bool]
    nodes_draggable: Var[bool]
    nodes_connectable: Var[bool]
    rf_style: Var[dict]
    on_node_click_cb: Var[Any]

    def add_imports(self) -> ImportDict:
        return {"": "reactflow/dist/style.css"}
```
The `add_imports()` override injects a side-effect CSS import (`import 'reactflow/dist/style.css'`)
into the generated bundle so node/edge positions render correctly.

**`_SYNTHETIC_RF_SOURCE`:** 15-node list in `_ALL_NODES_CACHE` format; same hierarchy as the
synthetic Cytoscape data (cat-hmc → proxmox/maas/unifi → pwy-homelab → pve-nodes/machines → leaves).

**`_build_reactflow_elements(source_nodes)`:** Pure-Python tree layout:
1. Builds parent→children index from the `path` and `depth` fields.
2. Bottom-up: recursively computes each subtree's pixel width (`NODE_W=140, H_GAP=24`).
3. Top-down: assigns `(x, y)` positions by centring each subtree over its parent
   (`NODE_H=36, V_GAP=80` between levels).
4. Returns `{"nodes": [...], "edges": [...]}` in React Flow format.
   - Each node carries `id`, `position`, `data`, and inline `style` (provider-tinted background;
     green border for nodes with `has_terragrunt`).
   - Each edge is `type: "smoothstep"` with a dark stroke.

**`_RF_DATA_CACHE` / `_RF_SYNTHETIC_DATA`:** Module-level dicts populated once at import time by
`_init_reactflow_cache()` — positions computed once, computed vars just filter.

**`AppState.reactflow_nodes` / `AppState.reactflow_edges`** (`@rx.var`):
- Use `_RF_DATA_CACHE` if populated, else `_RF_SYNTHETIC_DATA`.
- Filter nodes by `provider_filters`; edges are trimmed to only connect visible nodes.

**`AppState.view_mode`:** Updated to return `"reactflow"` when `viz_framework == "reactflow"`.

**`AppState.set_view_mode()`:** Handles `mode == "reactflow"` → `viz_framework = "reactflow"`.

**`AppState.on_rf_node_click()`:** Same hidden-div trigger pattern as Cytoscape —
reads `window._rfSelectedPath` via `rx.call_script` and forwards to `select_node`.

**`_REACTFLOW_NODE_CLICK_JS`:** `(event, node) => { window._rfSelectedPath = node.id; trigger.click(); }`

**`reactflow_view()`:** Renders `_ReactFlowGraph` with `fitView=True`, dragging/connecting disabled,
dark background.

**`render_left_panel_content()`:** Added `("reactflow", reactflow_view())` case.

**`_panel_view_selector()`:** Added `rx.select.item("Tree2", value="reactflow")`.

**`VIZ_FRAMEWORKS`:** Added `{"key": "reactflow", "label": "Tree2", ...}`.

**`index()`:** Added hidden `rf-node-trigger` div wired to `AppState.on_rf_node_click`.

## How it works

1. App loads → `_RF_DATA_CACHE` pre-built from real infra (or synthetic fallback).
2. User picks "Tree2" from the view selector → `viz_framework = "reactflow"`.
3. `reactflow_view()` renders; React Flow displays a top-down tree.
4. Provider filters from the Filters menu hide matching nodes+edges reactively.
5. Clicking a node → `onNodeClick` JS sets `window._rfSelectedPath`, clicks hidden div,
   Reflex reads the path, calls `select_node()` → right panel shows unit params.
