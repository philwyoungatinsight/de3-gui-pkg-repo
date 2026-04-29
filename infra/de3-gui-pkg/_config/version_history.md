# de3-gui-pkg version history

## 0.8.0  (2026-04-28, git: 992ef04)
- appearance menu: replace "Floating panels mode" checkbox with `Mode:` dropdown (4-panels / Floating Panels / Tabbed Panels)
- new Tabbed Panels layout: infra-tree sidebar + draggable resizer + tab column (Object Viewer, File Viewer, Terminal)
- `floating_panels_mode: bool` → `panel_mode: str` with backward-compatible migration from saved state
- main layout switch: nested `rx.cond` → `rx.match` over `panel_mode`

## 0.7.0  (2026-04-26, git: d5a4e8f)
- fw-repos viewer: add Font Size slider — scales Mermaid classDiagram text (10–40 px) independently of zoom, with real-time re-render via `_setFontSize` on the iframe window

## 0.6.0  (2026-04-25, git: fcb6480)
- fw-repos viewer: add Verbose mode — labeled attributes (git-url:, config-package:),
  named separator (─── Packages ───), ◆/◇ symbols for embedded/external packages,
  notes() + bullet-point note methods in the class methods compartment
- fw-repos viewer: add Show backend option — displays framework_backend type·bucket
  as an attribute (labeled in verbose mode)
- GUI appearance submenu: add Verbose and Show backend checkboxes for fw-repos section

## 0.5.1  (2026-04-25, git: 0bcd51b)
- fw-repos viewer: show `config_package` as second attribute in each class node;
  class link now opens `framework_repo_manager.yaml` in the config package instead
  of the repo root URL

## 0.5.0  (2026-04-24, git: a885591)
- feat: replace fw-repos Cytoscape view with Mermaid classDiagram iframe — repos as UML classes, embedded packages as + members, external as - members, created_by as inheritance arrows; removes ~370 lines of Cytoscape state/handlers/menus

## 0.4.0  (2026-04-23, git: 907d191)
- feat: add Framework Repos Cytoscape view — repos as compound nodes, packages as children, lineage edges, per-repo collapse, multi-layout support (cose/breadthfirst/dagre/preset), layout persistence

## 0.3.1  (2026-04-22, git: 829ead3)
- homelab_gui: replace hardcoded default-pkg tool paths with _FRAMEWORK_PKG_DIR/_PKG_MGR/_UNIT_MGR env vars

## 0.3.0  (2026-04-22, git: 2885d20)
- feat: nested deployment diagram — zone/provider/env/resource hierarchy, depth-range controls, drawpyo cloud icons, extensible export registry

## 0.2.0  (2026-04-22, git: 95d2a8e)
- feat: add Arch Diagram visualization framework — swimlane layout auto-derived from live infra data, draw.io XML export

## 0.1.0  (initial)
- Initial de3-gui-pkg implementation
