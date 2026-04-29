# 2026-04-26 — fw-repos Font Size Scale Slider

## What changed

Added a **Font Size** slider to the fw-repos Mermaid viewer Appearance panel, letting
the user scale classDiagram text (10–40 px) independently of the SVG zoom level.

### `assets/fw_repos_mermaid_viewer.html`

- Added `_fontSizePx` module-level variable, initialised from `?fontSize` URL param (default 18 — Mermaid dark theme default).
- Added `_repos` module-level cache so repos data survives re-renders without re-fetching.
- Extracted `_initMermaid()`: calls `mermaid.initialize()` with `themeVariables: { fontSize: _fontSizePx + 'px' }`.
- Extracted `_renderDiagram()`: re-renders from cached `_repos`, calls `_initZoom()`.
- Refactored `load()` to use helpers and cache data.
- Exposed `window._setFontSize(sizePx)` — updates `_fontSizePx`, re-inits Mermaid, re-renders without an iframe reload.

### `homelab_gui/homelab_gui.py` (7 touch points)

1. State var: `fw_repos_font_size: int = 18`
2. `fw_repos_iframe_src`: `&fontSize={self.fw_repos_font_size}` for initial load
3. Computed vars: `fw_repos_font_size_list` and `fw_repos_font_size_label`
4. `_save_current_config()`: persist `fw_repos_font_size`
5. Load state: `self.fw_repos_font_size = int(saved_menu.get("fw_repos_font_size", 18))`
6. Event handler: `set_fw_repos_font_size()` — validates 10–40, saves config, calls `window._setFontSize` on the live iframe via `rx.call_script`
7. UI: Font Size `rx.slider` (min 10, max 40, step 2) added after the Zoom slider in the fw-repos Appearance section

### `_config/de3-gui-pkg.yaml`

Bumped `_provides_capability` from `0.6.0` to `0.7.0`.

### `_config/version_history.md`

Appended `## 0.7.0` entry.
