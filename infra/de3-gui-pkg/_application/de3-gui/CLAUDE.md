# Claude Instructions — pwy-home-lab-GUI

## After every code change session — ALWAYS do this

1. Write an ai-log entry in `docs/ai-log/<YYYYMMDD-HHMMSS>-<slug>.md` summarising what changed.
2. Update `docs/ai-log-summary/README.ai-log-summary.md` to reflect the current state of the code (replace the summary section below the `---` divider).
3. Commit all changes (code + docs) in a single `git commit`.

Do **not** skip these steps. They are required at the end of every session that modifies code.

## File Paths — NEVER hard-code absolute paths

**Always use paths relative to environment variables set by `set_env.sh`.**

Before any shell command or path construction, source `set_env.sh`:

```bash
source $(git rev-parse --show-toplevel)/set_env.sh
```

### Available environment variables

| Variable     | Default value                                                                    | Purpose                                          |
|--------------|----------------------------------------------------------------------------------|--------------------------------------------------|
| `_STACK_DIR` | derived: `infra/de3-gui-pkg/_applications/de3-gui/../../../../` = repo root                              | Root of the pwy-home-lab repo (contains infra/, config/framework.yaml, etc.) |

All other paths (infra dir, config files, inventory files, etc.) must be expressed as:
- A path **relative to `_STACK_DIR`** — stored in `infra/de3-gui-pkg/_config/de3-gui-pkg.yaml` under `de3-gui-pkg.config:` and resolved in Python via `(_STACK_DIR / rel).resolve()`
- Or a path **relative to the repo root** — obtained via `git rev-parse --show-toplevel`

**Never write a path that starts with `/home/...`, `/Users/...`, or any other user-specific prefix into config files or source code.**

### Example: adding a new file path to de3-gui-pkg.yaml

Config lives at `infra/de3-gui-pkg/_config/de3-gui-pkg.yaml` with a `de3-gui-pkg:` top-level key.

Wrong:
```yaml
de3-gui-pkg:
  config:
    ansible_inventory_path: "/home/pyoung/git/pwy-home-lab/deploy/k8s-recipes/config/tmp/dynamic/ansible/inventory/hosts.yml"
```

Correct (relative to `_STACK_DIR`):
```yaml
de3-gui-pkg:
  config:
    ansible_inventory_path: "../../../../k8s-recipes/config/tmp/dynamic/ansible/inventory/hosts.yml"
```

The Python resolver in `homelab_gui.py` (`_read_inventory_file`, `_infra_path`, etc.) already handles relative-to-`_STACK_DIR` resolution via `Path(os.environ["_STACK_DIR"]) / rel`.

## Reflex event handlers — NEVER use underscore-prefixed names as callbacks

**Reflex does not register methods whose names start with `_` as events.** If you use such a method as a `callback=` argument to `rx.call_script` (or any other Reflex event reference), the lookup returns `None` and you get:

```
EventFnArgMismatchError: Event None only provides 1 arguments ...
```

### Rule

- `rx.call_script(..., callback=AppState.some_handler)` — **only works if `some_handler` is a public name** (no leading underscore).
- Methods named `_foo` are invisible to Reflex's event registry and **must not be used as callbacks**.

### Fix pattern

Wrong:
```python
def _set_wave_popup_x(self, x: int): ...   # underscore → not a Reflex event
rx.call_script("...", callback=AppState._set_wave_popup_x)  # broken
```

Correct:
```python
def save_wave_popup_x(self, x: int): ...   # public name → registered as event
rx.call_script("...", callback=AppState.save_wave_popup_x)  # works
```

### Corollary — never use Python string concatenation with Reflex vars

Inside `rx.foreach` component functions, `node["field"]` is a Reflex `ObjectItemOperation`, not a Python string. Using Python `+` to concatenate a literal with it fails at compile time:

```python
# WRONG — TypeError: can only concatenate str (not "ObjectItemOperation") to str
rx.text("(" + node["wave_num_str"] + ")")

# CORRECT — pass as separate children; Reflex renders them adjacently
rx.text("(", node["wave_num_str"], ")")
```

### Corollary — complex return values from `rx.call_script`

Reflex callbacks receive a **single scalar** (int, float, str, bool). Do **not** return a JS object `{x, y}` and try to deserialise it in the callback — Reflex cannot pass it through.

If you need two values back from JavaScript, use **two separate `rx.call_script` calls** each returning one scalar, with two separate public callback handlers:

```python
return [
    rx.call_script("window._someX || 0", callback=AppState.save_x),
    rx.call_script("window._someY || 0", callback=AppState.save_y),
]
```

## Reflex background tasks — correct decorator and naming (0.8.27)

**`rx.background` does not exist in Reflex 0.8.27.** Use `@rx.event(background=True)` instead.

```python
# WRONG — AttributeError: No reflex attribute background
@rx.background
async def my_task(self): ...

# CORRECT
@rx.event(background=True)
async def my_task(self): ...
```

**Background task methods must be public** (no leading underscore). Reflex raises
`ValueError: Event handlers cannot be private` if the method name starts with `_`.

```python
# WRONG — ValueError at startup
@rx.event(background=True)
async def _my_task(self): ...

# CORRECT
@rx.event(background=True)
async def my_task(self): ...
```
