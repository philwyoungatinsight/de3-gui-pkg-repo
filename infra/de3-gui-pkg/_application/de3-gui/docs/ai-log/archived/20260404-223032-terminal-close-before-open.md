# 20260404-223032 — Close existing terminal before opening a new shell action

## Problem

Clicking "SSH to host", "Open local shell", or "Kube shell" while a terminal was
already open would immediately replace the iframe URL (embedded) or start a new
ttyd process (ttyd), causing the old PTY/WebSocket to be abruptly torn down at the
same time a new one was being created. There was no clean close-first step.

## Fix

`open_shell` and `open_ssh_terminal` now close any running terminal before opening
a new one (embedded and ttyd backends only — native terminals are fire-and-forget
and don't need this):

```python
if self.terminal_backend in ("embedded", "ttyd") and (self.shell_cwd or self.ttyd_port):
    self.shell_cwd = ""
    self.shell_initial_cmd = ""
    self.ttyd_port = 0
    yield  # flush close to browser before opening new terminal
```

The `yield` sends the blank state to the browser so the current iframe navigates to
`about:blank` (clearing the old PTY WebSocket) before the subsequent state update
arrives with the new terminal URL. The guard `(self.shell_cwd or self.ttyd_port)`
skips the extra round-trip when no terminal is currently open.
