# Fix tests/Makefile and tests/run framework compliance

## Problem

`tests/Makefile` and `tests/run` did not follow the project framework pattern:
- `Makefile` was missing standard targets (`default`, `FORCE`, `deps`, `build`, `test`, `clean`)
- `run` lacked `_log()`/`_die()` helpers and named action functions
- `make test` only ran unit tests instead of all suites

## Changes

### Rewritten: `tests/Makefile`

```makefile
SHELL := bash
.PHONY: default
default: |build test

.PHONY: FORCE
FORCE:

.PHONY: clean
clean: FORCE
    ./run --clean

.PHONY: deps
deps: FORCE
    ./run --deps

.PHONY: build
build: FORCE
    ./run --build

.PHONY: test
test: FORCE
    ./run --test

# Fine-grained suite targets
.PHONY: unit integration performance
unit:        FORCE ; ./run --unit
integration: FORCE ; ./run --integration
performance: FORCE ; ./run --performance
```

### Rewritten: `tests/run`

- Added `_log()` / `_die()` / `_log_stdin()` helpers with `[gui-tests]` prefix
- Named action functions: `_deps`, `_build`, `_clean`, `_status`, `_test`, `_run_playbook`
- `_deps()`: installs `ansible-core>=2.14` and Playwright chromium
- `_build()`: verifies `ansible-playbook` is available, logs version
- `_clean()`: removes `screenshots/*.png`
- `_status()`: shows ansible version, playbooks, gui-states
- `_test()`: runs all three suites sequentially (unit → integration → performance)
- Case statement handles: `--deps`, `--build`, `--test`/`--all`, `--clean`, `--status`,
  `--unit`, `--integration`, `--performance`, `--tag`

### Modified: parent `run` script

- `_test()` updated to call `tests/run --test` (all suites) instead of `tests/run --unit`
