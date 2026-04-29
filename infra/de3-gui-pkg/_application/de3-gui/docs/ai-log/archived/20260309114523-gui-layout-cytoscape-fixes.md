# GUI Layout and Cytoscape Fixes

## Changes

### Reflex `.__len__()` compile error fix
- `bottom_right_panel()` header separator was using `selected_node_browser_actions.__len__() > 0`
- Replaced with a dedicated `has_node_browser_actions` boolean `@rx.var`

### `rx.foreach` action button fix
- `_node_action_btn()` was called from `rx.foreach`, so `action` arg is a Reflex Var, not a plain dict
- Replaced Python string ops and `.get()` with `rx.match` for icon prefix and `color_scheme`

### Nested Networks grid layout
- Nodes with >3 children now arranged in a near-square grid (4→2×2, 9→3×3, etc.)
- `cols = ceil(sqrt(n))`, `rows = ceil(n/cols)`, children placed row-by-row
- Added `subtree_h()` helper for vertical spacing per row in `_compute_cytoscape_positions()`

### Cytoscape category/region filters fix
- Filters were not applied in the Cytoscape (Nested Networks) view
- Added filter logic to `cytoscape_elements` computed var to check `category_filters` and `region_filters`

### Zoom sensitivity slider
- Added `cy_wheel_sensitivity` state var (default 0.3) with save/restore from config
- Slider added to Appearance dropdown menu (range 0.05–1.0, step 0.05)
- `cy_wheel_sensitivity_list` and `cy_wheel_sensitivity_label` computed vars for Reflex compat
- `wheelSensitivity` prop wired into `cytoscape_view()`

### File viewer vertical scrollbar fix
- Panel lacked reliable scrollbar for large files
- Root cause: `flex="1"` on child of a block container doesn't constrain height
- Fix: changed outer `bottom_left_panel()` box from `flex="1"` to `height="100%"`
- Content area: `flex="1"`, `min_height="0"`, `overflow_y="auto"`, `overflow_x="auto"`

### Full-width horizontal resizer
- H-resizer between top/bottom panel rows was not spanning both columns
- Restructured layout: `vstack(top-hstack, h_panel_resizer(), bottom-hstack)`
- Updated `_RESIZER_JS` to also update `left-column-bottom`; `_HRESIZER_JS` uses `main-panels`

### Embedded browser panel fill fix
- iframe was tiny, not filling the bottom-right panel
- Same root cause as file viewer: `flex="1"` → `height="100%"` on `bottom_right_panel()` outer box

### Skip generic Chrome profiles
- Dropdown was showing "Your Chrome", "Person 1", "Default", "Guest Profile" entries
- Added `_generic` set filter: skip profiles whose name starts with any generic label
