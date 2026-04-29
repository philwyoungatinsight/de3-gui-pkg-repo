# 20260413145643 — Build status: subtree refresh via right-click

## What changed

### Context menu — new item in Build group

Right-clicking any node when "Show build status" is enabled now shows:

> **Refresh build status (recursive)**

Only shown when `show_unit_build_status` is True (no point showing it if dots are hidden).
Available on all node types (leaf units, folders, providers, packages).

### New handlers

**`refresh_subtree_status(path)`** (sync entry point):
- Guards against double invocation with `is_refreshing_build_statuses`
- Sets spinner immediately, dispatches `do_refresh_subtree_status`

**`do_refresh_subtree_status(path)`** (`@rx.event(background=True)`):
Scoped to the directory tree rooted at `infra/<path>`. Runs both tiers:

**Tier 1 (local):** `find infra/<path> -path "*/.terragrunt-cache/*/terraform.tfstate"`
(no `-newer` marker — reads current state unconditionally for the subtree).
Recovers unit paths by stripping `.terragrunt-cache/...`; reads and parses state JSON.

**Tier 2 (GCS):** `gsutil ls -l -r gs://<bucket>/<path>/` scoped to the subtree prefix.
Reuses `gcs_state_mtimes` for incremental download — only changed files are fetched.
GCS result is authoritative and overrides Tier 1 for units where GCS data is fresher.
Updated mtimes are persisted back to `gcs_state_mtimes`.

Results are merged into `unit_build_statuses` via `{**existing, **updates}` — entries
for units outside the subtree are untouched.

## Behaviour

| Scenario | What happens |
|---|---|
| Right-click a leaf unit | Refreshes just that unit (local + GCS) |
| Right-click a provider folder (e.g. `pwy-home-lab-pkg/_stack/maas`) | Refreshes all MaaS units |
| Right-click a package root (e.g. `pwy-home-lab-pkg`) | Refreshes all units in that package |
| Right-click root `infra` | Effectively a full refresh (but scoped to that prefix) |
| Status toggle is off | Item not shown in context menu |
