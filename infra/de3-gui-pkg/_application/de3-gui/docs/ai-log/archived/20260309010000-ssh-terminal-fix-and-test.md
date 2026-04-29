# SSH terminal fix: initial_cmd not reaching PTY + GUI test

**Date:** 2026-03-09

---

## Root cause

`_terminal_html(cwd)` built the WebSocket URL as:
```javascript
const wsUrl = 'ws://' + window.location.host + '/ws/terminal?cwd=' +
              encodeURIComponent('{safe_cwd}');
```

The browser JS never included `initial_cmd` in the WebSocket URL, so
`_terminal_ws_handler` (which reads `initial_cmd` from WebSocket query params)
never received it — and never sent the SSH command to the PTY.

The HTML page was served from `/terminal?cwd=...&initial_cmd=...`, but
`_terminal_page_handler` didn't pass `initial_cmd` to `_terminal_html()`, and
even if it had, the JS hardcoded the WS URL without the param.

## Fix

**`homelab_gui/homelab_gui.py`**

1. `_terminal_html(cwd, initial_cmd="")` — added `initial_cmd` parameter and
   `safe_cmd` escaping.

2. WebSocket URL now embeds the param when present:
   ```javascript
   const wsUrl = 'ws://' + window.location.host + '/ws/terminal?cwd=' +
                 encodeURIComponent('{safe_cwd}') +
                 ('{safe_cmd}' ? '&initial_cmd=' + encodeURIComponent('{safe_cmd}') : '');
   ```
   The Python f-string substitutes `safe_cmd` at HTML-generation time, so the
   JS string literal already contains the encoded command.

3. `_terminal_page_handler` now reads `initial_cmd` from its own query params
   and passes it to `_terminal_html`:
   ```python
   initial_cmd = request.query_params.get("initial_cmd", "")
   return _HTMLResponse(_terminal_html(cwd, initial_cmd))
   ```

## End-to-end flow (after fix)

1. User right-clicks a node → `open_context_menu` builds `injected` list with
   `action_type: "ssh"` entry carrying `{"cwd": "...", "cmd": "ssh ..."}`.
2. User clicks "SSH to host" → `dispatch_action` calls `open_ssh_terminal(cwd, cmd)`.
3. `open_ssh_terminal` sets `shell_cwd` + `shell_initial_cmd` state vars.
4. `terminal_iframe_url` computed var appends `&initial_cmd=<encoded_cmd>` to the
   iframe src, e.g. `/terminal?cwd=/home/...&initial_cmd=ssh%20ubuntu%4010.0.10.1`.
5. Browser loads `/terminal?...&initial_cmd=...` → `_terminal_page_handler` reads
   both params, passes to `_terminal_html`.
6. `_terminal_html` generates JS with the WebSocket URL already containing
   `&initial_cmd=<encoded_cmd>`.
7. Browser connects WebSocket to `/ws/terminal?cwd=...&initial_cmd=...`.
8. `_terminal_ws_handler` reads `initial_cmd`, spawns bash, and after 0.6 s writes
   `ssh ... \n` to the PTY → SSH runs in the terminal.

## Test

**`tests/browser_test.py`** — added `check_ssh_terminal(page, args)`:
- `args` format: `<node_label>:<expected_hostname>`
- Right-clicks the node, clicks `#ssh_to_host`, waits for terminal iframe.
- Asserts `initial_cmd` is present in the iframe URL.
- Waits for WebSocket to open (readyState 1).
- Polls terminal buffer for SSH activity (`ssh `, `@`, or sufficient output).
- Sends `hostname\r` and verifies `expected_hostname` appears in the buffer.

**`tests/unit-tests/test-ssh-terminal.yml`** (new):
- Reuses `file-viewer-pve1-vm` GUI state (tree expanded to `pve-1/vms`).
- Browser checks: `node_visible:test-ubuntu-vm-1`, `ssh_terminal:test-ubuntu-vm-1:test-ubuntu-vm-1`.

**`tests/playbooks/unit-tests.yml`** — added `test-ssh-terminal` task.
