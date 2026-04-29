# File Viewer Mode: Unit File vs Config Data

## Feature
Added a "Unit File / Config Data" dropdown to the File Viewer menu bar. Allows
switching between viewing the node's `terragrunt.hcl` (default) and the full
`terragrunt_lab_stack.yaml` stack config file.

## Config
Added `stack_config_path` support to `config/de-gui.yaml` (optional; auto-detected
via git root if absent):
```yaml
# stack_config_path: "../../../../k8s-recipes/config/files/platform-config/terragrunt/terragrunt_lab_stack/terragrunt_lab_stack.yaml"
```

Auto-detection via `_find_stack_config()`: walks git root looking for
`terragrunt_lab_stack.yaml`.

## State var
```python
file_viewer_mode: str = "unit_file"  # "unit_file" | "config_data"
```
Persisted in `state/current.yaml` (see persistence fix log).

## Behaviour

### Unit File mode (default)
Clicking any node loads its `infra/<path>/terragrunt.hcl` as before.

### Config Data mode
- File viewer shows `terragrunt_lab_stack.yaml` (loaded once when mode is switched).
- Clicking a node scrolls the file viewer to the best-matching section for that node.
- Scroll uses `_find_config_scroll_line(content, node_path)`: tries the full node
  path as a search term, then progressively shorter prefixes, returns the 0-based
  line index of the best match.
- JS scroll emitted via `rx.call_script(_file_viewer_scroll_js(line_idx))` which
  scrolls the `#file-viewer-pre` element's scrollable ancestor.

## Event handlers modified

### `click_node` (tree view)
- Loads HCL only when `file_viewer_mode == "unit_file"`.
- Emits scroll JS (returned as `rx.call_script`) only when `file_viewer_mode == "config_data"`.
- Expand/collapse always runs regardless of mode.

### `select_node` (cytoscape/reactflow)
- Same guard: loads HCL or emits scroll based on mode.

### `set_file_viewer_mode(mode)`
- Switches mode and saves it.
- On switch to "config_data": loads stack config file into `hcl_content`/`hcl_file_path`,
  scrolls to current selected node if any.
- On switch to "unit_file": reloads the selected node's HCL (or clears if none).

## UI: `_file_viewer_mode_selector()`
`rx.dropdown_menu` placed in `bottom_left_panel()` menu bar between "File Viewer"
label and spacer. Button label changes reactively between "Unit File ▾" and
"Config Data ▾". The `<pre>` element has `id="file-viewer-pre"` for JS targeting.
