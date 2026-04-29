# 20260403-163350 — Startup status banner

## What changed

### `app_status_message` computed var
Two-phase startup status:
- `"Initializing…"` while `is_loading == True` (on_load hasn't finished)
- `"Refreshing inventory…"` while `is_loading == False` but `inventory_refresh_counter == 0`
  (on_load done but the background inventory refresh hasn't completed yet)
- `""` when fully ready (banner hidden)

### `startup_status_banner()` component
Fixed bottom bar (position=fixed, bottom=0, z_index=9998) with a spinner and
`app_status_message` text. Uses `var(--accent-9)` background. Rendered via `rx.cond`
on `app_status_message != ""` — hidden when the app is fully ready.
Sits below the error banner (z_index 9999) at the bottom of the viewport.

### `index()`
`startup_status_banner()` injected after `backend_error_banner()`.
