# 20260405-103249 — Wave panel: configurable poll interval

## Feature

Wave log status poll interval is now configurable via `de-gui.yaml` instead of being
hardcoded to 3 seconds.  Default is 10 seconds (10 000 ms).

## Changes

### `homelab_gui/homelab_gui.py`

Module-level constant `_WAVE_POLL_INTERVAL_MS` read from config at import time:

```python
_WAVE_POLL_INTERVAL_MS: int = int(
    _load_config().get("config", {}).get("wave_poll_interval_ms", 10000)
)
```

`_WAVE_POLL_START_JS` changed from a plain string to an f-string so it embeds
`_WAVE_POLL_INTERVAL_MS` at startup:

```python
_WAVE_POLL_START_JS = (
    "window._waveStatusPollId = setInterval(function(){"
    "  var t=document.getElementById('wave-status-poll-trigger');"
    "  if(t) t.click();"
    f"}}, {_WAVE_POLL_INTERVAL_MS});"
)
```

### `config/de-gui.yaml`

New key under `config:`:

```yaml
# wave_poll_interval_ms: how often (in milliseconds) the browser polls for
# wave log status updates while a run is active.  Default: 10000 (10 s).
wave_poll_interval_ms: 10000
```
