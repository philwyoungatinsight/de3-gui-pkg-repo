# Fix: file viewer blank on startup + YAML breadcrumb not showing

## Bugs fixed

### Bug 1: file viewer blank on startup in config_data mode

`select_node` for `config_data` mode assumed `hcl_content` was already loaded (set by
`set_file_viewer_mode`). On app start it is always empty, so the viewer was blank.

**Fix — `select_node`**: added guard at the top of the `config_data` branch:
```python
if not self.hcl_content:
    content, fpath = _read_stack_config_file()
    self.hcl_content = content
    self.hcl_file_path = fpath if fpath else "(stack config not found...)"
```

**Fix — `on_load`**: added fallback after `select_node` call to cover the case where no
node was saved but mode is `config_data` (config file should still be shown):
```python
if self.file_viewer_mode == "config_data" and not self.hcl_content:
    content, fpath = _read_stack_config_file()
    self.hcl_content = content
    self.hcl_file_path = fpath if fpath else "(stack config not found...)"
```

### Bug 2: YAML breadcrumb bar showing nothing

Two root causes:

1. **`#yaml-breadcrumb` not in DOM when JS ran** — the element was inside `rx.cond(hcl_content != "", ...)` so it was absent when `_yaml_breadcrumb_install_js()` executed (content may still be empty at that point).

   **Fix**: Replaced the `rx.cond`-wrapped span with an always-present `rx.box(id="yaml-breadcrumb")` whose `display` is toggled via `rx.cond`. Element is always in the DOM.

2. **JS ran before React committed new DOM** — the `rx.call_script` at the end of `on_load`'s script list executes before React finishes re-rendering with the new state. `#file-viewer-pre` may not exist yet.

   **Fix**: Moved `_yaml_breadcrumb_install_js()` into `install_resizer`, which is dispatched as a separate WebSocket event after the initial render — guaranteed post-hydration. Removed redundant install from `on_load` script list.
