# Startup: infra scan progress + inventory-ready message

## What changed

### `_init_nodes_cache()`
Added `print` before and after the infra scan:
```
[homelab_gui] Scanning infra: /path/to/infra
[homelab_gui] Infra scan done — N nodes
```

### `_print_ready()` — new function, called after `_run_inventory_refresh` is defined
Previously called immediately after `_init_modules_cache()`, which caused
`NameError: name '_run_inventory_refresh' is not defined` because
`_run_inventory_refresh` is defined ~2500 lines later in the file.

**Fix:** moved `_print_ready` definition and call to just after
`_run_inventory_refresh` (after line ~4113).

Behaviour:
1. Prints `[homelab_gui] Infra loaded — N nodes, M modules, T unit templates. Running inventory refresh…`
2. Launches inventory refresh in a background thread (blocking inside the thread)
3. Sets `_INVENTORY_REFRESH_DONE = True` before starting, so `on_load` skips the duplicate refresh
4. Prints `[homelab_gui] Ready — open the app in your browser.` when the refresh completes

**Wait for the `Ready` line before opening the browser.**
If inventory refresh is disabled in config, `_run_inventory_refresh` returns
immediately and "Ready" prints right away.
