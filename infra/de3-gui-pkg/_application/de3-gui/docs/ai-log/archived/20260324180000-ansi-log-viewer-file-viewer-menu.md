# ANSI Log Viewer, File Viewer Menu Bar, Wave Log Status, Search Highlighting

## Summary
Added ANSI escape code rendering in the file viewer, redesigned the file viewer menu bar,
added wave run status icons in the wave popup, and implemented backend-baked search
highlighting for ANSI log files with auto-populate STDERR on wave log open.

## Changes

### ANSI color support in file viewer
- `_ansi_to_html(text, search_query="", current_match_idx=-1) -> tuple[str, int]`:
  parses ANSI SGR sequences (standard 16 colors, 256-color 38;5;N, bold/dim/italic/underline)
  and returns (html_string, total_match_count)
- `@rx.var hcl_is_ansi_log`: True when `'\x1b['` in `hcl_content`
- `@rx.var hcl_content_html`: calls `_ansi_to_html(content, unit_file_search_query, ansi_search_idx)[0]`
- `@rx.var ansi_match_total`: calls `_ansi_to_html(content, query, -1)[1]` (no idx dependency
  so it only recomputes on content/query change, not on nav)
- `hcl_parsed_lines` short-circuits to `[]` for ANSI content
- Bottom panel renders `rx.html(AppState.hcl_content_html, id="file-viewer-ansi")` in dark
  terminal background (`#1e1e2e`) when `hcl_is_ansi_log`, else `rx.el.pre` with foreach

### Backend-baked search marks for ANSI logs
- `_inject_marks(raw_html, sq, match_counter, cur_idx)`: post-processes HTML-escaped text
  segments, wrapping matches in `<mark data-fs>` (yellow) or `<mark data-fs data-fs-current>`
  (orange, for the current match)
- Marks are baked into the HTML returned by `hcl_content_html`, so React renders them
  directly — no JS DOM mutation needed, no wipe-on-re-render issue
- **Why**: `rx.html()` uses `dangerouslySetInnerHTML`; any state update causes React to
  reset innerHTML, wiping JS-injected `<mark>` elements. Baking marks in backend HTML is
  the only reliable solution.
- `ansi_search_idx: int = 0` state var tracks current match (0-based)
- `_ansi_search_scroll_js()` private helper returns JS to scroll `mark[data-fs-current]`
  into view using `file_search_smooth_scroll` preference

### Search nav handlers updated for ANSI path
- `set_active_search_query`: if ANSI log, resets `ansi_search_idx=0`, updates
  `file_search_match_count`, returns scroll JS
- `file_search_next/prev`: if ANSI log, increments/decrements `ansi_search_idx` mod total,
  returns `rx.call_script(self._ansi_search_scroll_js())`
- `file_search_key_down`: Enter/Escape both handled for ANSI path
- Escape clears query → `hcl_content_html` recomputes without marks (no JS clear needed)

### Auto-populate STDERR on wave log open
- `open_wave_log`: sets `unit_file_search_query = "STDERR"` and `ansi_search_idx = 0`
  before returning scroll JS, so the first STDERR match is highlighted and scrolled to
  on open

### File viewer menu bar redesign
- New layout: `FILE VIEWER | Type: [label] | Editor: [selector] | Copy | Download | spacer`
- `@rx.var file_viewer_type_label`: `"Wave Log"` / `"Config Data"` / `"Unit File"`
- `_fv_divider()`, `_fv_type_selector()`, `_fv_editor_selector()` component helpers
- `copy_file_content_to_clipboard()`: returns `rx.set_clipboard(self.hcl_content)`
- `download_current_file()`: returns `rx.download(data=content, filename=filename)`
- `select_and_launch_in_editor(editor_id)`: saves selected editor and opens file

### Wave log status column in popup
- `wave_log_statuses: dict[str, dict]` state var maps wave name → `{status, log_path}`
- `refresh_wave_log_statuses()`: scans `~/.run-waves-logs/<YYYYMMDD-HHMMSS>/` dirs
  (newest-first), reads `run.log` for `--- [name] action done ---` success marker
- `_wave_status_icon(item)`: shows `–` for not-run, `✓` (green) or `✗` (red) button;
  clicking opens `run.log` in file viewer
- Destroy icon changed from `✕` to `🗑`

### Navbar removed
- `navbar()` returns `rx.box()` (empty); title text moved to top of explorer control_bar
- Layout `margin_top="0"`, `height="100vh"` (both normal and maximized)

## Bugs Fixed

### React wipes JS-injected marks (`dangerouslySetInnerHTML` issue)
- JS-injected `<mark>` elements in `#file-viewer-ansi` were wiped on every state update
  (including the `set_file_search_match_count` callback triggering re-render)
- Root cause: `rx.html()` uses `dangerouslySetInnerHTML`, React resets innerHTML on change
- Fix: bake marks into `_ansi_to_html()` output; React renders them as real DOM nodes

## Files Modified
- `homelab_gui/homelab_gui.py`
- `docs/ai-log/20260324180000-ansi-log-viewer-file-viewer-menu.md` (this file)
