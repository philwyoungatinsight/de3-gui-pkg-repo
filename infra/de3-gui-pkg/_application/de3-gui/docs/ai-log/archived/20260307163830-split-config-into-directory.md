# Split config.yaml into config/ directory

## Changes

### Removed: `config.yaml`

The single monolithic config file was replaced by a `config/` directory.

### New: `config/` directory

One YAML file per section, each with a single top-level key matching its filename
(without `.yaml`), per the project convention:

- `config/config.yaml` — top-level key `config`; contains `infra_path` and `vm_ip`
- `config/supported.yaml` — top-level key `supported`; canvas types and provider definitions
- `config/options.yaml` — top-level key `options`; default UI options
- `config/current.yaml` — top-level key `current`; active canvas and provider state
- `config/dag.yaml` — top-level key `dag`; runtime-populated DAG root
- `config/testing.yaml` — top-level key `testing`; UI test settings (see next log entry)

### Modified: `homelab_gui/homelab_gui.py`

- Changed `CONFIG_FILE` constant to `CONFIG_DIR = _CONFIG_DIR / "config"`
- Updated `_load_config()` to glob all `*.yaml` files in `CONFIG_DIR` and merge them:

```python
def _load_config() -> dict:
    merged: dict = {}
    if CONFIG_DIR.is_dir():
        for f in sorted(CONFIG_DIR.glob("*.yaml")):
            try:
                data = yaml.safe_load(f.read_text()) or {}
                merged.update(data)
            except Exception:
                pass
    return merged
```

### Modified: `run` (parent script)

- Changed `CONFIG_FILE` variable to `CONFIG_DIR="$SCRIPT_DIR/config"`
- Updated `_read_config()` to merge all `config/*.yaml` files before key lookup
