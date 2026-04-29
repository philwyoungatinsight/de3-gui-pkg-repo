# de3-gui-pkg

Optional GUI package for visualising and operating the home-lab infrastructure DAG.

## Structure

```
de3-gui-pkg/
├── _config/de3-gui-pkg.yaml        — all user-editable settings (top-level key: de3-gui-pkg:)
├── _setup/run                      — install Python/Node.js dependencies
└── _application/de3-gui/           — Python/Reflex web application
    ├── homelab_gui/homelab_gui.py  — main app; reads config from _config/de3-gui-pkg.yaml
    ├── state/                      — runtime state written by the running app
    ├── run                         — start / stop / test entry point
    └── tests/run                   — smoke test (app must be running)
```

## How it Works

The app scans `$_STACK_DIR/infra/*/` at startup, reads every `_config/<pkg>.yaml` for
`config_params` and `waves`, and builds a DAG of all Terraform units. The tree view,
C4 diagrams, and wave panel all derive from this in-memory graph.

Config (providers, editors, UI defaults, context-menu actions) is read from
`_config/de3-gui-pkg.yaml` at runtime — no restart needed for most settings.

## Steps

1. **Setup** (once): `infra/de3-gui-pkg/_setup/run`
2. **Run**: `cd infra/de3-gui-pkg/_application/de3-gui && ./run --run`
3. **Test** (app must be running): `cd tests && ./run --test`
4. **Stop**: `./run --stop`

Set `_STACK_DIR` in the environment to point the GUI at a different repo root.

## What setup installs

`infra/de3-gui-pkg/_setup/run` installs:

- **python3** — if missing, delegates to `default-pkg/_setup/run` (brew / apt / dnf)
- **Node.js 18+** — via Homebrew on macOS; via [nvm](https://github.com/nvm-sh/nvm) on Linux
  (consistent with how the `run` script loads node at runtime via `_load_nvm`)
- **Python packages** from `requirements.txt` — pip install with `--break-system-packages`
  fallback for PEP 668 environments (Homebrew Python, modern Debian/Ubuntu)

`make setup` (at the repo root) runs all package setup scripts and can be used instead
of calling this script directly.
