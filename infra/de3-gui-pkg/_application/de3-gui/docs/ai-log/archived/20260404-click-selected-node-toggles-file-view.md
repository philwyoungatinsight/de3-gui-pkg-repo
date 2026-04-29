# 20260404 — Re-clicking a selected node toggles unit_file ↔ config_data

## What changed

### `click_node(path)`

Added `toggling_mode = bool(path and path == self.selected_node_path)` at the top.

When `toggling_mode` is True:
- `file_viewer_mode` is toggled: `"unit_file"` → `"config_data"` or vice versa.
- The rest of the handler runs normally with the new mode.

When toggling to `config_data`, the existing branch would search in whatever is
currently in `hcl_content` (the unit file).  Added a reload guard:

```python
if toggling_mode or not self.hcl_content:
    content, fpath = _read_stack_config_file()
    self.hcl_content = content
    self.hcl_file_path = fpath if fpath else "..."
```

When toggling back to `unit_file`, the existing unit-file load branch handles it
(it always re-reads the HCL file on any click).
