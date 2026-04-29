# Add Playwright browser DOM assertions

## Problem

No test existed that could manipulate the GUI and verify what was actually rendered
in the browser. The Ansible assertions only checked API responses; they did not
confirm that the UI reflected the correct state.

## Changes

### New: `tests/browser_test.py`

Playwright CLI script that loads the GUI in Chrome, waits for React/Reflex hydration,
then runs named DOM assertions.

**Hydration wait:**
```python
page.wait_for_function(
    "document.body.innerText.includes('cat-')",
    timeout=READY_TIMEOUT,
)
```
Category nodes are always expanded on load, so their text appearing confirms the
WebSocket connected and state was applied.

**Check types:**

| Check | How |
|---|---|
| `node_visible:NAME` | `page.locator(f"text={name}").count() > 0` |
| `node_selected:NAME` | JS walks DOM ancestors from leaf text node, checks `background-color: rgb(224, 231, 255)` (`#e0e7ff`) |
| `right_panel_has:TEXT` | `page.locator(f"text={text}").count() > 0` |
| `no_element:SELECTOR` | `page.locator(selector).count() == 0` |

**`node_selected` implementation** (Reflex sets highlight as inline style on a wrapper box):
```python
found = page.evaluate("""(args) => {
    const [name, bg] = args;
    const textNodes = Array.from(document.querySelectorAll('*')).filter(
        el => el.children.length === 0 && el.textContent.trim() === name
    );
    for (const el of textNodes) {
        let node = el;
        while (node && node !== document.body) {
            const computed = window.getComputedStyle(node).backgroundColor;
            if (computed === bg) return true;
            node = node.parentElement;
        }
    }
    return false;
}""", [name, SELECTED_BG])
```

**CLI flags:**
- `--url` — GUI URL (default `http://localhost:8080`)
- `--headless` — run headless (default: false)
- `--profile-dir` — Chrome profile directory name (e.g. `Profile 1`)
- `--user-data-dir` — Chrome user data base directory
- `--incognito` — launch in incognito mode
- `--screenshot` — save PNG after checks
- `--check TYPE:VALUE ...` — one or more assertions to run

### New: `tests/roles/gui-test/tasks/browser_assert.yml`

Ansible task file that:
1. Resolves screenshot output path
2. Optionally runs `find_chrome_profile.py` to map email → profile dir
3. Builds `--check` args from `browser_checks` list using Jinja2 `map('regex_replace', ...)`
4. Runs `python3 browser_test.py` via `ansible.builtin.shell`
5. Reports `stdout_lines` via `ansible.builtin.debug`

### Modified: `tests/roles/gui-test/tasks/main.yml`

- Added call to `browser_assert.yml` when `browser_checks | length > 0`
- `take_screenshot` task now only runs when `browser_checks | length == 0`
  (browser_assert.yml takes its own screenshot when checks pass)

### Modified: `tests/unit-tests/test-tree-open-node.yml`

Added `browser_checks` to the existing `tree-proxmox-pve1-selected` test:

```yaml
browser_checks:
  - "node_visible:pve-1"
  - "node_selected:pve-1"
  - "right_panel_has:proxmox"
```

## Debugging notes

- **`selectattr('id', 'equalto', ...)` on graph elements fails**: Edge elements have no
  `data.id` key; Jinja2 `selectattr` raises `KeyError`. Fixed by replacing filter chain
  with `ansible.builtin.shell` + Python heredoc using `'id' in e.get('data', {})`.
- **Python multiline code collapsed by `cmd: >-`**: YAML `>-` folds newlines to spaces,
  causing `IndentationError`. Fixed by using `ansible.builtin.shell` with `<< 'PYEOF'` heredoc.
- **Ansible 2.10 + Jinja2 3.x incompatibility**: `environmentfilter` removed from Jinja2 3.x;
  system Ansible 2.10.8 breaks. Fixed by `pip install ansible-core>=2.14`.
