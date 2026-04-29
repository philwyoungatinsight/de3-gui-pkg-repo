# Configurable frontend/backend ports

## Summary

Frontend (8080) and backend (8000) ports were hardcoded in `rxconfig.py` and `run`.
Added `frontend_port` / `backend_port` config keys to `de3-gui-pkg.yaml` so they can
be changed without touching code.

## Changes

- **`de3-gui-pkg.yaml`**: added `config.frontend_port: 8080` and `config.backend_port: 8000`
  with explanatory comments
- **`run`**: removed `APP_PORT=8080` hardcode; reads both ports from config via `_read_config`
  after `PKG_CONFIG_FILE` is set; exports `HOMELAB_GUI_FRONTEND_PORT` / `HOMELAB_GUI_BACKEND_PORT`
  for `rxconfig.py`; all internal references to `8000` replaced with `${BACKEND_PORT}`
- **`rxconfig.py`**: reads `HOMELAB_GUI_FRONTEND_PORT` / `HOMELAB_GUI_BACKEND_PORT` env vars
  (set by `run`) with fallback defaults of 8080 / 8000 so it still works when invoked directly
