# Fix build status refresh silently doing nothing

## Root cause

`do_refresh_unit_build_statuses` looked for the GCS bucket name in
`infra/pwy-home-lab-pkg/_config/gcp_seed.yaml`, but that file was moved to
`config/gcp_seed.yaml` in a recent refactor commit. The old path didn't exist,
`bucket` was `""`, the GCS listing was silently skipped, and no error was surfaced.

## Fix

1. **Bucket source**: read from `_STACK_CONFIG[_STACK_CONFIG_KEY]["backend"]["config"]["bucket"]`
   (i.e. `framework.backend.config.bucket`) — the same source used by the lock-removal
   terminal commands. This is always populated once `_load_stack_config()` runs at startup.

2. **Error surfacing**: added `build_status_error: str = ""` state var. The background
   task now sets it for each distinct failure mode:
   - No backend configured (framework.yaml not loaded)
   - Non-GCS backend type
   - Empty bucket name
   - `gsutil` not on PATH
   - `gsutil ls` non-zero exit (first error shown)
   - Unexpected exception
   The error is shown as red text below the "Refresh status" button in the appearance menu.

3. **Error cleared** on each new invocation of `refresh_unit_build_statuses` so stale
   messages disappear when the user retries after fixing the underlying issue.
