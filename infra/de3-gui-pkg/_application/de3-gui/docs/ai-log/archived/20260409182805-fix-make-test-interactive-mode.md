# Fix make test with interactive observation mode

**Date:** 2026-04-09  
**Session continuation from:** previous context window

## What changed

### `tests/browser_test.py`

Three fixes to make `make test` pass reliably with `observation_mode: interactive`.

**1. `wait_for_ready` — poll in 12s chunks with page reloads between attempts**

Previously used a single `page.wait_for_function(..., timeout=120_000)`. On a cold
Vite cache, the React Router dev server OOM-kills Node on the first browser request
(compiling the >500KB JSX bundle), then auto-restarts. During the crash, the page
goes blank and `-pkg` never appears — the single 120s wait timed out.

New approach: loop in `READY_CHUNK_MS = 12_000` ms windows. On timeout, reload the
page and retry. Typical flow: attempt 1 times out (OOM crash window) → reload →
Vite has restarted → attempt 2 succeeds.

**2. `wait_for_ready` — combined ready condition (tree loaded AND no connection error)**

Changed the `wait_for_function` expression from:
```js
document.body.innerText.includes('-pkg')
```
to:
```js
document.body.innerText.includes('-pkg') && !document.body.innerText.includes('Connection Error')
```

After the Vite OOM restart and page reload, Vite HMR fires once compilation
completes, briefly disconnecting the Reflex WebSocket. During HMR, "Connection
Error" appears in `innerText` even though the tree is populated. The combined
condition ensures we don't declare the page "ready" until the HMR cycle settles
and the connection is stable.

**3. `check_no_element` — use `wait_for_function` on `innerText` instead of locator filter**

Previously: `page.get_by_text(text, exact=False).filter(visible=True).count()`.

Problems:
- Playwright's visible filter can match the Reflex `ConnectionPulser` div whose
  HTML `title` attribute always contains "Connection Error: ..." regardless of
  connection state.
- The one-shot count check has a race window between the page summary and the check.

New approach: `page.wait_for_function(f"!document.body.innerText.includes(...)",
timeout=CHECK_TIMEOUT)`. `innerText` respects `display:none` / `visibility:hidden`
and the polling wait handles any transient state that clears quickly.

## Result

`make test` passes end-to-end with `observation_mode: interactive` and
`observation_timeout_secs: 10`. The continue popup appears, the user can click it,
and the `no_element:Connection Error` check passes.
