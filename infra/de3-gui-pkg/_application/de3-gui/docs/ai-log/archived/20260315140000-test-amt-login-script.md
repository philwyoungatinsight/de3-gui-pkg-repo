# scripts/test-amt-login: Ansible-based AMT Playwright login test

## What was created

New directory at `scripts/test-amt-login/` (in the pwy-home-lab repo, not the GUI repo),
following the same framework pattern as `scripts/run-ansible-hello-world/`.

Running `make` in the directory performs the full test.

## Files

```
scripts/test-amt-login/
├── Makefile                        default: |build test
├── run                             bash script (same boilerplate as hello-world)
├── requirements.txt                jmespath, playwright
├── playbook.test-amt-login.yaml    single localhost play
├── README.md
└── tasks/
    ├── resolve-amt-params.yaml     prefix-match param resolution
    ├── test-amt-login.yaml         invokes amt_login_test.py via ansible.builtin.script
    └── amt_login_test.py           Python: reachability check + Playwright Digest login
```

## Design

**Single localhost play** — unlike hello-world there is no remote SSH play; the
test runs entirely on the controller (localhost with `connection: local`).

**Config loading** — `config_base` role loads both public YAML and SOPS secrets
from `$_CONFIG_DIR`. After the role runs, both `terragrunt_lab_stack` and
`terragrunt_lab_stack_secrets` are available as Ansible variables.

**Prefix-match param resolution** (`tasks/resolve-amt-params.yaml`):
- Iterates `config_params` dict from both public and secret config
- Sorts keys alphabetically (shorter prefix paths sort before longer extensions)
- Merges values for all keys that are a prefix of `amt_node_path`
  (`when: (amt_node_path + '/').startswith(item.key + '/') or amt_node_path == item.key`)
- Secrets overlay public params (secrets merged second)
- Fails fast if `power_address`, `power_user`, or `power_pass` are missing

**Playwright test** (`tasks/amt_login_test.py`):
- Credentials passed as env vars (`AMT_URL`, `AMT_USERNAME`, `AMT_PASSWORD`)
- Never written to logs, files, or Ansible output (only URL + username shown)
- Exit code 2 = unreachable (machine off) — Ansible logs this but does not fail the run
- Exit code 1 = auth failure or unexpected page content
- Exit code 0 = PASS

`ansible.builtin.script` is called with `executable: "{{ ansible_playbook_python }}"` so
the test runs under the same venv Python that Ansible uses, ensuring playwright is available.

## build vs test

- `./run --build` sets up venv, installs playwright + chromium, generates inventory, runs full test
- `./run --test` runs just the Ansible playbook (assumes venv + inventory already exist)
- `make` = build then test

## Node path

Hard-coded to `cat-hmc/maas/pwy-homelab/machines/ms01-03` in the playbook vars.
Change `amt_node_path` in `playbook.test-amt-login.yaml` to test a different machine.
