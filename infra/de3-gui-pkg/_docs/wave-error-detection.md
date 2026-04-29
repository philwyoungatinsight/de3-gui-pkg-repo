# Wave Error Detection — How the GUI Knows About Errors

The GUI's Waves panel shows a per-wave status icon (✓ green / ✗ red / – grey / spinner) next to each wave. This page explains exactly how those icons are derived.

## Log directory layout

The wave runner writes all logs under:

```
~/.run-waves-logs/
  20260412-183615/          ← timestamp of run start (YYYYMMDD-HHMMSS)
    run.log                  ← master log: orchestration decisions and wave markers
    wave-<name>-apply.log    ← stdout/stderr from `terragrunt run --all apply`
    wave-<name>-destroy.log  ← stdout/stderr from `terragrunt run --all destroy`
    wave-<name>-precheck.log ← pre-wave Ansible playbook output
    wave-<name>-test-playbook.log ← post-wave Ansible test output
  20260412-181518/          ← previous run
    ...
  latest -> 20260412-183615  ← symlink to newest run
```

A new timestamped directory is created for every `./run --build` or `./run --clean` invocation.

## Markers written to `run.log`

The wave runner writes explicit markers for each phase:

| Marker | Meaning |
|--------|---------|
| `--- [<wave>] terragrunt apply ---` | Wave apply started |
| `--- [<wave>] apply done ---` | Wave apply completed successfully |
| `[<wave>] apply failed` | Wave apply failed |
| `--- [<wave>] test-playbook: <name> ---` | Test playbook started |
| `--- [<wave>] test-playbook done ---` | Test playbook passed |
| `[<wave>] test-playbook failed` | Test playbook failed |
| `--- [<wave>] precheck: <name> ---` | Precheck playbook started |
| `--- [<wave>] precheck done ---` | Precheck passed |
| `[<wave>] precheck failed` | Precheck failed |
| `ERROR: command failed` | Unhandled error (any wave or the runner itself) |

## How `_wave_status()` maps log content to a status

The function `_wave_status()` in `homelab_gui.py` → `refresh_wave_log_statuses()` reads
`run.log` for a given run directory and returns one of four strings:

```
"ok"       done marker found
"fail"     fail marker found, OR "ERROR: command failed" anywhere in run.log
"running"  no terminal marker yet, AND run.log mtime < 300 s ago
"fail"     no terminal marker, run.log mtime ≥ 300 s ago (crashed/stale)
```

The 300-second (`_RUNNING_THRESHOLD_SECS`) threshold distinguishes a wave that is still
actively running from one whose process silently died without writing a terminal marker.

## Three log types — each resolved independently

Each wave has up to three tracked log types, stored as separate keys in `wave_log_statuses`:

| Key | Log file pattern | What it covers |
|-----|-----------------|----------------|
| `status` / `log_path` | `wave-<name>-apply.log` or `-destroy.log` | Terraform apply/destroy |
| `pre_status` / `pre_log_path` | `wave-<name>-precheck.log` | Pre-wave Ansible check |
| `test_status` / `test_log_path` | `wave-<name>-test-playbook.log` | Post-wave Ansible test |

Each type is resolved from the **newest run directory that contains that log file**,
independently of the other types. This means the main status can come from run A while
the test status comes from the older run B (if run A was interrupted before the test ran).

## Newest-first resolution

`refresh_wave_log_statuses()` iterates run directories newest-first and tracks three
`found` sets (`main_found`, `pre_found`, `test_found`). Once a wave name is added to a
set, older directories are skipped for that log type. This ensures:

- A completed wave always shows its most-recent result.
- An in-progress run's partial results take precedence over an older completed run.

## UI icon mapping

| Status string | Icon | Colour | Shown when |
|---------------|------|--------|-----------|
| `"ok"` | ✓ | green | done marker in run.log |
| `"fail"` | ✗ | red | fail marker or ERROR in run.log, or stale with no marker |
| `"running"` | spinner | — | no terminal marker and run.log < 5 min old |
| `"none"` | – | grey | no log file found for this wave in any run directory |

Each icon is clickable and opens the corresponding log file in the built-in log viewer.

## Where to look when debugging a wrong status

1. **GUI shows ✗ for a wave that should be ✓** — check whether the GUI has stale state
   from a previous failed run. Click the refresh button (↻) in the Waves panel header, or
   wait for the next auto-poll cycle (~10 s). If the current run completed the wave
   successfully, `--- [<wave>] apply done ---` will be in `~/.run-waves-logs/latest/run.log`
   and the icon will update.

2. **GUI shows ✗ for all waves after one fails** — this can happen because `"ERROR:
   command failed"` is a global check inside `_wave_status()`. Any wave in the same run
   directory that lacks a done marker will be treated as failed. Waves that did complete
   successfully (done marker present) are unaffected. After fixing the failing wave and
   re-running, the new run's done markers take precedence.

3. **GUI shows spinner that never resolves** — the wave runner process may have died
   without writing a terminal marker. After 300 seconds the status flips to ✗ automatically.

4. **GUI shows – for a wave that has run** — the wave name in `waves_ordering.yaml` may
   not match the `<name>` segment of the log file. The log file name is derived from the
   wave definition; verify with `ls ~/.run-waves-logs/latest/wave-<name>-*.log`.

## Source code references

| Symbol | File | Purpose |
|--------|------|---------|
| `refresh_wave_log_statuses()` | `homelab_gui/homelab_gui.py:7034` | Scans log dirs and populates `wave_log_statuses` |
| `_wave_status()` (inner fn) | `homelab_gui/homelab_gui.py:7067` | Maps run.log content → "ok"/"fail"/"running" |
| `_RUNNING_THRESHOLD_SECS` | `homelab_gui/homelab_gui.py:7065` | 300 s — running vs crashed threshold |
| `wave_log_statuses` | `homelab_gui/homelab_gui.py:3518` | Reflex state var holding per-wave status dicts |
| `_wave_status_icon()` | `homelab_gui/homelab_gui.py:11058` | UI component rendering the ✓/✗/spinner icon |
| `_wave_status_icon_card()` | `homelab_gui/homelab_gui.py:11004` | Compact card variant used in overview grid |
