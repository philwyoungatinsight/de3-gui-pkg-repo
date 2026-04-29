## 2026-04-26 — Right-click context menu on Framework Repos canvas

**Plan**: `infra/_framework-pkg/_docs/ai-plans/right-click-fw-repo-viz.md`

### What changed

Modified `infra/de3-gui-pkg/_application/de3-gui/assets/fw_repos_mermaid_viewer.html`:

- **Removed left-click navigation**: deleted the Mermaid `link` directive forEach block
  that wrapped class-title text in `<a>` tags and opened git URLs on click.
  This was triggering accidentally during canvas drag.

- **Added right-click context menu**: a dark-themed floating `#ctx-menu` div with two
  items per repo node:
  - **Open Git URL** — converts git@ or .git URLs to a browser URL, opens in new tab.
    Greyed out for local-only repos with no URL.
  - **Open framework_package_repositories.yaml** — constructs the browse URL for
    `infra/<main_package>/_config/_framework_settings/framework_package_repositories.yaml`
    in the repo, handling both GitHub (`/blob/main/`) and GitLab (`/-/blob/main/`) paths.
    Greyed out when `main_package` is absent.

- **`attachContextMenuHandlers(repos)`** called after each `_renderDiagram()`: finds
  class-node title `<text>` elements matching repo safeNames, walks up to the
  `[id^="classid-"]` group (full node box), attaches `contextmenu` listeners.

- Menu dismisses on click-outside or Escape. Menu position is clamped to the viewport.
