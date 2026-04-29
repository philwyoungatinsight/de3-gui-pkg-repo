# Nested Networks: dependency arrows + color-by-wave

## Summary

Added two new Appearance menu options under a "Nested Networks" section:

1. **Show dependency arrows** — renders Cytoscape edge elements between nodes based on
   `dependency { config_path = "..." }` blocks parsed from `terragrunt.hcl` files.
2. **Color nodes by wave** — overrides provider-based node colors with a 12-color wave
   palette, assigned by wave declaration order in the stack config.

---

## Changes — `homelab_gui/homelab_gui.py`

### New constants
```python
_WAVE_PALETTE: list[str] = [...]          # 12-color fixed palette
_DEPENDENCY_PATH_RE = re.compile(...)     # matches dependency config_path lines
```

### `_DEPENDENCIES_CACHE` + `_init_dependencies_cache()`
Parses each HCL leaf node's `terragrunt.hcl` for `config_path` references, resolves
them to infra-relative paths, and stores the result as `{source: [target, ...]}`.
Populated at startup (after `_init_path_param_maps()`) and on manual rescan.

### `_build_cytoscape_edges()`
Returns Cytoscape edge element dicts from `_DEPENDENCIES_CACHE`.

### `_CYTOSCAPE_STYLESHEET` additions
- `node.wave-colored` — sets `background-color: data(wave_color)` (overrides provider rules)
- `node.wave-colored:parent` — same for compound/parent nodes
- `edge` — bezier arrows, muted slate color, 0.55 opacity

### Updated `_build_cytoscape_elements()`
Embeds `wave` and `wave_color` into each node's data dict using `_WAVE_PALETTE` indexed
by wave declaration order.

### Updated `cytoscape_elements` computed var
- When `cy_color_by_wave`: appends `wave-colored` CSS class to each element
- When `cy_show_dependencies`: extends result with edges filtered to visible node set

### New state vars
```python
cy_show_dependencies: bool = False
cy_color_by_wave:     bool = False
```

### Toggle/flip handlers (4 new handlers)
`toggle_cy_show_dependencies` / `flip_cy_show_dependencies`
`toggle_cy_color_by_wave` / `flip_cy_color_by_wave`

### Save/restore
Both vars persisted under `menu.cy_show_dependencies` / `menu.cy_color_by_wave` in
`state/current.yaml`.

### Appearance menu
New "Nested Networks" section with "Show dependency arrows" and "Color nodes by wave"
checkbox items.

---

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260331162825-nested-networks-dependencies-wave-color.md` (this file)
- `docs/ai-log-summary/README.ai-log-summary.md`
