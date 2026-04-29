# 2026-04-02 — SSH: suppress known-hosts warnings

## Change

Added `-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR`
to the SSH command built by `_get_ssh_command()`.

- `StrictHostKeyChecking=no` / `UserKnownHostsFile=/dev/null`: skip known-hosts
  checking; avoids the "Are you sure you want to continue connecting?" prompt for
  hosts not yet in `~/.ssh/known_hosts`.
- `LogLevel=ERROR`: suppresses warnings like "This key is not known by any other
  names" that appear when a host's key is present under a different name/IP.

MaaS hosts already carry these options in `ansible_ssh_common_args`; the duplication
is harmless (SSH uses last value; values are identical).

**File:** `homelab_gui/homelab_gui.py` — `_get_ssh_command()`
