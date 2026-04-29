# 20260405-005226 — Fix dispatch_action: use yield from for generator sub-calls

## Problem

`open_shell` and `open_ssh_terminal` both contain a `yield` statement (added for
the close-before-open flush pattern).  A Python function with any `yield` is a
**generator function** — calling it with `self.open_shell(value)` returns a
generator object but **never executes the body**.

`dispatch_action` was doing exactly this:

```python
elif action_type == "shell":
    self.open_shell(value)          # generator created, immediately discarded
elif action_type == "ssh":
    ...
    self.open_ssh_terminal(...)     # same
elif action_type == "expand_collapse":
    self.click_node(...)            # click_node also uses yield
elif action_type == "clipboard":
    return rx.call_script(...)      # plain return in what must now be a generator
```

## Fix

Convert `dispatch_action` to a generator by replacing the relevant lines:

```python
elif action_type == "clipboard":
    yield rx.call_script(...)
elif action_type == "expand_collapse":
    yield from self.click_node(self.ctx_menu_path)
elif action_type == "shell":
    yield from self.open_shell(value)
elif action_type == "ssh":
    data = _json.loads(value)
    yield from self.open_ssh_terminal(data["cwd"], data["cmd"])
```

`yield from` correctly delegates iteration through the sub-generator so every
state flush (`yield` in `open_shell`, etc.) propagates to the browser.
