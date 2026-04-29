#!/usr/bin/env python3
"""
browser_test.py — Playwright-based DOM assertions for the Home Lab GUI.

Opens the app in a real browser (headless or visible), waits for Reflex to
hydrate, then evaluates each --check against the live DOM.

Check types (passed as --check <type>:<value>):
  node_visible:<name>       tree label with this exact text is present
  node_selected:<name>      that node has the selected highlight (#e0e7ff)
  right_panel_has:<text>    the right panel contains an element with this text
  no_element:<text>         assert text is NOT present anywhere in the page

Observation modes (--observation-mode):
  none          close immediately after checks (default)
  timer         sleep --observation-timeout seconds before closing
  interactive   inject a floating panel in the browser with two gates:
                1. "▶ Click to run N check(s)" — shows pending checks, advances to run them
                2. "✅ Exit test" / "❌ Exit test" — shows pass/fail results, closes browser
                Also listens for Enter on stdin at each gate.

Usage:
  python3 browser_test.py --url http://localhost:9080 \\
      --check node_visible:pve-1 \\
      --check node_selected:pve-1 \\
      --check right_panel_has:proxmox \\
      --screenshot /tmp/out.png \\
      --headless false \\
      --observation-mode interactive \\
      --observation-timeout 60

Exit 0 on all checks passing, 1 on any failure.
"""

import argparse
import json
import select
import sys
import tempfile
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium",
          file=sys.stderr)
    sys.exit(2)

# ms — total budget for Reflex to hydrate and tree to render.
# The backend/frontend being up doesn't mean the WebSocket has synced state;
# Reflex needs extra time to compile, connect, and push the tree to the browser.
READY_TIMEOUT = 120_000
# ms — per-attempt window inside wait_for_ready before reloading the page.
# The React Router dev server OOM-kills Node on first browser request (cold
# Vite cache) and auto-restarts.  Polling in short chunks and reloading between
# attempts lets the crash-restart-reconnect cycle complete without needing a
# single monolithic 120s wait.
READY_CHUNK_MS = 12_000
# ms — per-check wait (most checks)
CHECK_TIMEOUT = 8_000
# ms — timeout for no_element checks.  "Connection Error" can linger up to
# ~30s after the Reflex WebSocket reconnects post Vite HMR restart.
NO_ELEMENT_TIMEOUT = 60_000
# Selected node background (hex #e0e7ff == rgb 224,231,255)
SELECTED_BG = "rgb(224, 231, 255)"

# JavaScript to inject a persistent floating status panel with a "Continue" button.
# Shows two lines: next-step (what happens on click) and status (current activity).
# The panel stays visible until _pw_remove_btn() is called at the very end.
_INJECT_CONTINUE_BTN_JS = """
(() => {
    if (document.getElementById('pw-observe-btn')) return;
    const panel = document.createElement('div');
    panel.id = 'pw-observe-btn';
    Object.assign(panel.style, {
        position:     'fixed',
        top:          '16px',
        left:         '50%',
        transform:    'translateX(-50%)',
        zIndex:       '99999',
        padding:      '12px 18px',
        background:   '#4f46e5',
        color:        'white',
        border:       'none',
        borderRadius: '10px',
        cursor:       'grab',
        fontFamily:   'monospace, sans-serif',
        boxShadow:    '0 4px 16px rgba(0,0,0,0.35)',
        minWidth:     '320px',
        maxWidth:     '480px',
        userSelect:   'none',
    });

    const nextLine = document.createElement('div');
    nextLine.id = 'pw-observe-next';
    Object.assign(nextLine.style, {
        fontWeight:   '700',
        fontSize:     '13px',
        marginBottom: '5px',
    });
    nextLine.textContent = '\u25b6 Continue test';

    const statusLine = document.createElement('div');
    statusLine.id = 'pw-observe-status';
    Object.assign(statusLine.style, {
        fontSize:   '11px',
        opacity:    '0.85',
        whiteSpace: 'pre-wrap',
        wordBreak:  'break-word',
    });
    statusLine.textContent = 'waiting\u2026';

    panel.appendChild(nextLine);
    panel.appendChild(statusLine);
    document.body.appendChild(panel);

    // Drag support: switch to absolute positioning on first drag.
    let dragging = false, dragOffX = 0, dragOffY = 0;
    panel.addEventListener('mousedown', e => {
        // Don't start drag on a click (small movement threshold applied in mousemove).
        dragging = true;
        const r = panel.getBoundingClientRect();
        dragOffX = e.clientX - r.left;
        dragOffY = e.clientY - r.top;
        panel.style.cursor = 'grabbing';
        e.preventDefault();
    });
    document.addEventListener('mousemove', e => {
        if (!dragging) return;
        // Switch from centred to absolute position on first real move.
        panel.style.transform = '';
        panel.style.left = (e.clientX - dragOffX) + 'px';
        panel.style.top  = (e.clientY - dragOffY) + 'px';
    });
    document.addEventListener('mouseup', () => {
        dragging = false;
        panel.style.cursor = 'grab';
    });

    panel.onclick = () => {
        if (panel.dataset.clicked) return;
        panel.dataset.clicked = 'true';
        panel.style.cursor = 'default';
        nextLine.textContent = '\u2713 Continuing\u2026';
        statusLine.textContent = 'running checks\u2026';
        panel.style.background = '#16a34a';
    };

    // Global updater: set next/status text and optionally background colour.
    // Resets clicked state so the button can be used again for the next step.
    window._pwUpdateBtn = (next, status, color) => {
        const p = document.getElementById('pw-observe-btn');
        if (!p) return;
        const n = document.getElementById('pw-observe-next');
        const s = document.getElementById('pw-observe-status');
        if (n && next   !== null) n.textContent = next;
        if (s && status !== null) s.textContent = status;
        if (color) p.style.background = color;
        delete p.dataset.clicked;
        p.style.cursor = 'grab';
    };
})()
"""

_REMOVE_CONTINUE_BTN_JS = "document.getElementById('pw-observe-btn')?.remove()"

# Translucent full-viewport overlay that tints the window to indicate test state.
# zIndex 9990 — below the control panel (99999) but above page content.
# pointerEvents none so clicks still reach the page.
# Defaults used when --tint-* / --btn-* args are not supplied.
_DEFAULT_COLORS = {
    "tint_waiting": "rgba(220,180,0,0.14)",  # yellow — any observation gate
    "tint_fail":    "rgba(200,30,30,0.18)",  # red    — checks failed
    "btn_running":  "#ca8a04",               # amber  — check in progress
    "btn_pass":     "#16a34a",               # green  — all checks passed
    "btn_fail":     "#dc2626",               # red    — checks failed
}


def _set_page_tint(page, rgba: str):
    """Apply a CSS color to the full-viewport tint overlay."""
    try:
        page.evaluate(f"""
(() => {{
    let ov = document.getElementById('pw-tint');
    if (!ov) {{
        ov = document.createElement('div');
        ov.id = 'pw-tint';
        Object.assign(ov.style, {{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            zIndex: '9990', pointerEvents: 'none',
            transition: 'background-color 0.4s ease',
        }});
        document.body.appendChild(ov);
    }}
    ov.style.backgroundColor = {json.dumps(rgba)};
}})()
""")
    except Exception:
        pass


def _btn_update(page, next_step: str = None, status: str = None, color: str = None):
    """Update the floating status panel text / colour from Python."""
    import json as _json
    js_next   = _json.dumps(next_step)   if next_step   is not None else "null"
    js_status = _json.dumps(status)      if status      is not None else "null"
    js_color  = _json.dumps(color)       if color       is not None else "null"
    try:
        page.evaluate(f"window._pwUpdateBtn && window._pwUpdateBtn({js_next}, {js_status}, {js_color})")
    except Exception:
        pass


def _chrome_user_data_dir() -> str:
    """Return the OS-appropriate Chrome user-data directory."""
    import platform
    home = Path.home()
    if platform.system() == "Darwin":
        return str(home / "Library" / "Application Support" / "Google" / "Chrome")
    return str(home / ".config" / "google-chrome")


def wait_for_ready(page):
    """Wait until Reflex has hydrated and the tree has content.

    All real infra packages are named *-pkg (e.g. aws-pkg, proxmox-pkg).
    Their appearance in innerText confirms on_load has finished.

    Polls in READY_CHUNK_MS windows and reloads the page between attempts.
    This handles the React Router dev-server OOM-kill on first browser request
    (cold Vite cache): Node crashes, Vite restarts, a page reload reconnects.
    Typical flow: attempt 1 times out → reload → attempt 2 succeeds.
    """
    start_ms = time.time() * 1000
    attempt = 0
    while True:
        attempt += 1
        elapsed_ms = time.time() * 1000 - start_ms
        remaining_ms = READY_TIMEOUT - elapsed_ms
        if remaining_ms <= 100:
            # Budget exhausted — one last try that will raise TimeoutError.
            page.wait_for_function(
                "document.body.innerText.includes('-pkg')",
                timeout=500,
            )
            return
        chunk_ms = min(READY_CHUNK_MS, remaining_ms)
        try:
            # Require BOTH the tree to be populated AND no "Connection Error"
            # banner.  This handles the Vite HMR cycle that can disconnect the
            # Reflex WebSocket briefly after the initial compile completes.
            page.wait_for_function(
                "document.body.innerText.includes('-pkg') "
                "&& !document.body.innerText.includes('Connection Error')",
                timeout=chunk_ms,
            )
            return  # success
        except PWTimeout:
            elapsed_ms = time.time() * 1000 - start_ms
            remaining_ms = READY_TIMEOUT - elapsed_ms
            if remaining_ms <= 100:
                raise  # nothing left — propagate TimeoutError
            print(f"  [ready] Attempt {attempt}: page not ready after "
                  f"{chunk_ms / 1000:.0f}s, reloading "
                  f"({remaining_ms / 1000:.0f}s remaining)...")
            try:
                page.reload(wait_until="domcontentloaded", timeout=15_000)
                # Re-inject the waiting panel (page reload removes injected JS).
                try:
                    page.evaluate(_INJECT_CONTINUE_BTN_JS)
                    _btn_update(page,
                                next_step=f"\u23f3 Reconnecting (attempt {attempt + 1})\u2026",
                                status=f"Vite restarted \u2014 waiting for Reflex to reconnect\u2026"
                                       f"\n({remaining_ms / 1000:.0f}s remaining)",
                                color="#6b7280")
                except Exception:
                    pass
            except Exception as exc:
                print(f"  [ready] Reload failed ({exc}), will retry...")


# ---------------------------------------------------------------------------
# Observation helpers
# ---------------------------------------------------------------------------

def _wait_for_click_or_keypress(page, timeout_secs: int, post_pause_secs: int = 0):
    """
    Inject a "Continue" button into the page and wait for the first of:
      - user clicks the button in the browser
      - user presses Enter in the terminal (only when stdin is a real TTY)
      - timeout_secs elapses (0 = wait indefinitely)

    After detecting the continue action, pause post_pause_secs seconds so the
    user can read the green confirmation before checks run.

    Note: when launched from Ansible shell, stdin is a closed pipe (not a TTY).
    In that case only the browser button click and timeout are active.
    """
    try:
        page.evaluate(_INJECT_CONTINUE_BTN_JS)
    except Exception:
        pass  # page may not be interactive yet

    is_tty = sys.stdin.isatty()
    deadline = time.time() + timeout_secs if timeout_secs > 0 else None
    timeout_hint = f" (or wait {timeout_secs}s)" if timeout_secs > 0 else ""
    if is_tty:
        print(f"  [observe] Click '\u25b6 Continue test' in the browser "
              f"or press Enter in the terminal{timeout_hint}...")
    else:
        print(f"  [observe] Click '\u25b6 Continue test' in the browser{timeout_hint}...")
        print(f"  [observe] (stdin is not a TTY — keyboard input disabled)")

    while True:
        # Check for page button click
        try:
            clicked = page.evaluate(
                "document.getElementById('pw-observe-btn')?.dataset?.clicked"
            )
            if clicked == "true":
                print("  [observe] Continued via browser click.")
                break
        except Exception:
            break  # page closed or navigated away

        # Only poll stdin when it is a real interactive terminal.
        # When launched via Ansible shell, stdin is an EOF pipe and select
        # returns immediately — skipping this block avoids an instant break.
        if is_tty:
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0)
                if ready:
                    sys.stdin.readline()
                    print("  [observe] Continued via keyboard.")
                    break
            except Exception:
                pass

        # Check timeout
        if deadline and time.time() >= deadline:
            print(f"  [observe] Timeout ({timeout_secs}s) reached, continuing.")
            break

        time.sleep(0.25)

    if post_pause_secs > 0:
        print(f"  [observe] Pausing {post_pause_secs}s so you can see the result...")
        time.sleep(post_pause_secs)
    # Do NOT remove the button here — it stays visible until context.close().


def observe(page, mode: str, timeout_secs: int, prompt: str, post_pause_secs: int = 0):
    """
    Pause for human observation according to mode.
    mode: 'none', 'timer', or 'interactive'
    post_pause_secs: extra seconds to wait after the Continue click before proceeding.
    """
    if not mode or mode == "none":
        return
    print(f"\n  [observe] {prompt}")
    if mode == "timer":
        print(f"  [observe] Pausing {timeout_secs}s (timer mode)...")
        time.sleep(timeout_secs)
        print("  [observe] Continuing.")
    elif mode == "interactive":
        _wait_for_click_or_keypress(page, timeout_secs, post_pause_secs=post_pause_secs)
    else:
        print(f"  [observe] Unknown observation_mode '{mode}', skipping.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def check_node_visible(page, name: str):
    """Assert a tree label with exactly this text is visible."""
    loc = page.get_by_text(name, exact=True).first
    loc.wait_for(state="visible", timeout=CHECK_TIMEOUT)


def check_node_selected(page, name: str):
    """Assert the node label appears inside a row with the selection highlight."""
    found = page.evaluate(
        """(args) => {
            const [name, bg] = args;
            // Walk every leaf text node to find the label.
            const textNodes = Array.from(document.querySelectorAll('*')).filter(
                el => el.children.length === 0 && el.textContent.trim() === name
            );
            for (const el of textNodes) {
                // Walk up ancestors looking for the selection background.
                let node = el;
                while (node && node !== document.body) {
                    const computed = window.getComputedStyle(node).backgroundColor;
                    if (computed === bg) return true;
                    node = node.parentElement;
                }
            }
            return false;
        }""",
        [name, SELECTED_BG],
    )
    if not found:
        raise AssertionError(
            f"Node '{name}' is not highlighted as selected "
            f"(expected ancestor with background {SELECTED_BG})"
        )


def check_right_panel_has(page, text: str):
    """Assert text is visible somewhere in the right panel."""
    # The right panel is the second flex child of the main hstack.
    # Fallback: just check anywhere on the page — the right panel is distinctive
    # because it shows provider names and YAML keys not present elsewhere.
    loc = page.get_by_text(text, exact=False).first
    loc.wait_for(state="visible", timeout=CHECK_TIMEOUT)


def check_no_element(page, text: str):
    """Assert text is not persistently visible on the page.

    Polls document.body.innerText (which respects display:none and
    visibility:hidden) and waits up to NO_ELEMENT_TIMEOUT for the text to clear.
    This handles the Reflex ConnectionModal / ConnectionToaster which can linger
    up to ~30s after the WebSocket reconnects following a Vite HMR restart.

    Note: intentionally avoids Playwright's get_by_text().filter(visible=True)
    because that can match the Reflex ConnectionPulser div whose title attribute
    always contains "Connection Error: ..." regardless of connection state.
    """
    try:
        page.wait_for_function(
            f"!document.body.innerText.includes({json.dumps(text)})",
            timeout=NO_ELEMENT_TIMEOUT,
        )
    except PWTimeout:
        raise AssertionError(
            f"Text '{text}' was found on the page and did not clear "
            f"within {NO_ELEMENT_TIMEOUT / 1000:.0f}s"
        )


def check_terminal_shell(page, args: str):
    """Right-click a tree node, open a local shell, send a command, verify output.

    Value format: '<node_label>:<expected_output>'
    Sends 'echo <expected_output>' via the terminal WebSocket and verifies the
    text appears in the xterm buffer (read via window.getTerminalText()).
    """
    node_label, _, expected = args.partition(":")

    # Right-click the node
    node = page.get_by_text(node_label, exact=True).first
    node.wait_for(state="visible", timeout=CHECK_TIMEOUT)
    node.click(button="right")
    page.wait_for_timeout(800)

    # Click "Open local shell" in the context menu
    page.wait_for_selector("#open_local_shell", timeout=CHECK_TIMEOUT)
    page.locator("#open_local_shell").click()
    # Allow iframe to load and WebSocket to connect
    page.wait_for_timeout(4000)

    # Find the terminal iframe frame object
    terminal_frame = None
    for frame in page.frames:
        if "/terminal" in frame.url:
            terminal_frame = frame
            break
    if terminal_frame is None:
        raise AssertionError(
            "Terminal iframe not found after clicking 'Open local shell'. "
            f"Frames: {[f.url for f in page.frames]}"
        )
    print(f"  [terminal] terminal frame found: {terminal_frame.url}")

    # Wait for xterm to initialise and expose window._ws + window.getTerminalText
    try:
        terminal_frame.wait_for_function(
            "typeof window._ws !== 'undefined' && window._ws.readyState === 1",
            timeout=10_000,
        )
    except Exception as exc:
        ws_state = terminal_frame.evaluate("window._ws ? window._ws.readyState : 'missing'")
        raise AssertionError(
            f"Terminal WebSocket not open (readyState={ws_state}): {exc}"
        )
    print("  [terminal] WebSocket open")

    # Send the command directly via the WebSocket (bypasses xterm keyboard events)
    cmd = f"echo {expected}\r"
    terminal_frame.evaluate(f"window._ws.send({json.dumps(cmd)})")
    page.wait_for_timeout(2000)

    # Read terminal buffer via getTerminalText()
    text = terminal_frame.evaluate("window.getTerminalText ? window.getTerminalText() : ''")
    print(f"  [terminal] buffer snippet: {text[:200]!r}")

    if expected not in text:
        raise AssertionError(
            f"Expected '{expected}' in terminal output.\n"
            f"Buffer (first 400 chars): {text[:400]!r}"
        )
    print(f"  [terminal] '{expected}' confirmed in terminal output")


def check_ssh_terminal(page, args: str):
    """Right-click a tree node, click 'SSH to host', run hostname, verify output.

    Value format: '<node_label>:<expected_hostname>'
    Right-clicks the node, clicks 'SSH to host', waits for SSH to connect,
    sends 'hostname', and verifies the output contains expected_hostname.
    """
    node_label, _, expected = args.partition(":")

    # Right-click the node
    node = page.get_by_text(node_label, exact=True).first
    node.wait_for(state="visible", timeout=CHECK_TIMEOUT)
    node.click(button="right")
    page.wait_for_timeout(800)

    # Click "SSH to host" in the context menu
    page.wait_for_selector("#ssh_to_host", timeout=CHECK_TIMEOUT)
    page.locator("#ssh_to_host").click()
    # Allow terminal iframe to load and WebSocket to connect
    page.wait_for_timeout(4000)

    # Find the terminal iframe
    terminal_frame = None
    for frame in page.frames:
        if "/terminal" in frame.url:
            terminal_frame = frame
            break
    if terminal_frame is None:
        raise AssertionError(
            "Terminal iframe not found after clicking 'SSH to host'. "
            f"Frames: {[f.url for f in page.frames]}"
        )
    print(f"  [ssh_terminal] terminal frame found: {terminal_frame.url}")

    if "initial_cmd" not in terminal_frame.url:
        raise AssertionError(
            f"Terminal URL missing initial_cmd (SSH command not injected): {terminal_frame.url}"
        )

    # Wait for WebSocket to open
    try:
        terminal_frame.wait_for_function(
            "typeof window._ws !== 'undefined' && window._ws.readyState === 1",
            timeout=10_000,
        )
    except Exception as exc:
        ws_state = terminal_frame.evaluate("window._ws ? window._ws.readyState : 'missing'")
        raise AssertionError(
            f"Terminal WebSocket not open (readyState={ws_state}): {exc}"
        )
    print("  [ssh_terminal] WebSocket open")

    # Wait for SSH to connect — poll until the buffer stops containing only
    # the initial bash prompt (i.e., SSH output has started appearing).
    try:
        terminal_frame.wait_for_function(
            "() => { const t = window.getTerminalText ? window.getTerminalText() : ''; "
            "return t.includes('ssh ') || t.includes('@') || t.length > 80; }",
            timeout=15_000,
        )
    except Exception:
        pass  # proceed anyway — maybe SSH connected but produced no banner

    # Send hostname command
    cmd = "hostname\r"
    terminal_frame.evaluate(f"window._ws.send({json.dumps(cmd)})")
    page.wait_for_timeout(3000)

    # Read terminal buffer
    text = terminal_frame.evaluate("window.getTerminalText ? window.getTerminalText() : ''")
    print(f"  [ssh_terminal] buffer snippet: {text[:400]!r}")

    if expected and expected not in text:
        raise AssertionError(
            f"Expected '{expected}' in terminal output after SSH + hostname.\n"
            f"Buffer (first 600 chars): {text[:600]!r}"
        )
    print(f"  [ssh_terminal] '{expected}' confirmed in terminal output")


def check_click_node_file_viewer(page, args: str):
    """Click a tree node then verify the file viewer shows expected content.

    Value format: '<node_label>:<expected_text>'  (first colon is delimiter)
    Clicks the node label in the tree, waits for Reflex state update,
    then asserts the bottom-left panel shows expected_text.
    """
    node_label, _, expected_text = args.partition(":")

    # Expand ancestors if needed by clicking through the tree — the node
    # label must already be visible (caller's GUI state should expand ancestors).
    node = page.get_by_text(node_label, exact=True).first
    node.wait_for(state="visible", timeout=CHECK_TIMEOUT)
    node.click()
    # Wait for Reflex websocket round-trip to process click_node + _read_hcl_file
    page.wait_for_timeout(2000)

    found = page.evaluate(
        """(searchText) => {
            const allElements = Array.from(document.querySelectorAll('*'));
            for (const el of allElements) {
                if (el.children.length === 0 && el.textContent.includes(searchText)) {
                    return true;
                }
            }
            return false;
        }""",
        expected_text,
    )
    if not found:
        # Dump bottom-left panel text for debugging
        panel_text = page.evaluate(
            """() => {
                const els = Array.from(document.querySelectorAll('pre'));
                return els.map(e => e.textContent.slice(0, 200)).join(' | ');
            }"""
        )
        raise AssertionError(
            f"After clicking '{node_label}', expected '{expected_text}' in file viewer. "
            f"pre elements: {panel_text[:400]}"
        )
    print(f"  [file_viewer] '{expected_text}' found after clicking '{node_label}'")


def check_file_viewer_source_link(page, args: str):
    """Click a node, then click its source = "..." link, and verify the module loads.

    Value format: '<node_label>:<expected_text_in_module>'
    Steps:
      1. Click the node to load its terragrunt.hcl in the file viewer.
      2. Wait for the source link (id=hcl-source-link) to appear.
      3. Click the first source link.
      4. Wait for the file viewer to update.
      5. Assert expected_text appears in the file viewer.
    """
    node_label, _, expected_text = args.partition(":")

    node = page.get_by_text(node_label, exact=True).first
    node.wait_for(state="visible", timeout=CHECK_TIMEOUT)
    node.click()
    page.wait_for_timeout(2000)

    # Find the source link rendered by _render_hcl_line
    source_link = page.locator("#hcl-source-link").first
    try:
        source_link.wait_for(state="visible", timeout=CHECK_TIMEOUT)
    except Exception:
        raise AssertionError(
            f"After clicking '{node_label}', no source link (id=hcl-source-link) found in file viewer"
        )

    link_text = source_link.text_content()
    print(f"  [source_link] clicking source link: {link_text!r}")
    source_link.click()
    page.wait_for_timeout(2000)

    # Verify the module file loaded
    found = page.evaluate(
        """(searchText) => {
            const allElements = Array.from(document.querySelectorAll('*'));
            for (const el of allElements) {
                if (el.children.length === 0 && el.textContent.includes(searchText)) {
                    return true;
                }
            }
            return false;
        }""",
        expected_text,
    )
    if not found:
        panel_text = page.evaluate(
            """() => {
                const els = Array.from(document.querySelectorAll('pre'));
                return els.map(e => e.textContent.slice(0, 200)).join(' | ');
            }"""
        )
        raise AssertionError(
            f"After clicking source link '{link_text}', expected '{expected_text}' in file viewer. "
            f"pre elements: {panel_text[:400]}"
        )
    print(f"  [source_link] '{expected_text}' found in module after following source link")


def check_bottom_left_panel_has(page, text: str):
    """Assert text is visible somewhere in the bottom-left file viewer panel."""
    found = page.evaluate(
        """(searchText) => {
            // Look for the bottom-left panel by searching for the File Viewer label,
            // then check its sibling/ancestor for the text.
            const allElements = Array.from(document.querySelectorAll('*'));
            for (const el of allElements) {
                if (el.children.length === 0 && el.textContent.includes(searchText)) {
                    return true;
                }
            }
            return false;
        }""",
        text,
    )
    if not found:
        raise AssertionError(
            f"Text '{text}' was not found in the bottom-left file viewer panel"
        )


def check_bottom_left_path_has(page, text: str):
    """Assert the file path bar in the bottom-left panel contains the given text."""
    found = page.evaluate(
        """(searchText) => {
            const allElements = Array.from(document.querySelectorAll('*'));
            for (const el of allElements) {
                if (el.children.length === 0 && el.textContent.includes(searchText)) {
                    return true;
                }
            }
            return false;
        }""",
        text,
    )
    if not found:
        raise AssertionError(
            f"Path text '{text}' was not found in the bottom-left panel path bar"
        )


def check_panel_resize_works(page, delta_str: str):
    """Drag the panel resizer by delta pixels and verify the left panel expands.

    Value format: integer pixel delta, e.g. '200'.
    Asserts that #left-panel width increases by approximately delta px (±30px).
    """
    try:
        delta = int(delta_str)
    except (ValueError, TypeError):
        delta = 200

    # Diagnostics: confirm required DOM elements and JS sentinel are present.
    js_ready      = page.evaluate("!!window._panelResizerReady")
    resizer_exists = page.evaluate("!!document.getElementById('panel-resizer')")
    left_exists   = page.evaluate("!!document.getElementById('left-column')")
    main_exists   = page.evaluate("!!document.getElementById('main-panels')")

    print(f"  [resize] js_ready={js_ready}  #panel-resizer={resizer_exists}"
          f"  #left-column={left_exists}  #main-panels={main_exists}")

    if not resizer_exists:
        raise AssertionError("#panel-resizer not found in DOM")
    if not left_exists:
        raise AssertionError("#left-column not found in DOM")

    # Wait up to 10s for the resizer JS to initialise (loaded asynchronously
    # via Reflex's on_mount → call_script pathway).
    if not js_ready:
        print("  [resize] Waiting up to 10s for resizer JS to initialise...")
        try:
            page.wait_for_function("!!window._panelResizerReady", timeout=10_000)
            js_ready = True
            print("  [resize] Resizer JS is now ready.")
        except Exception:
            print("  [resize] WARNING: Resizer JS did not initialise within 10s — "
                  "drag will likely fail")

    initial_w = page.evaluate(
        "document.getElementById('left-column').getBoundingClientRect().width"
    )
    print(f"  [resize] initial left-column width: {initial_w:.0f}px")

    resizer_box = page.locator("#panel-resizer").bounding_box()
    if not resizer_box:
        raise AssertionError("#panel-resizer has no bounding box (invisible?)")

    cx = resizer_box["x"] + resizer_box["width"] / 2
    cy = resizer_box["y"] + resizer_box["height"] / 2
    print(f"  [resize] resizer centre: ({cx:.0f}, {cy:.0f})  "
          f"size: {resizer_box['width']:.0f}x{resizer_box['height']:.0f}px")

    # Low-level mouse drag so events reach document-level delegation in resizer.js.
    page.mouse.move(cx, cy)
    page.mouse.down()
    dbg_after_down = page.evaluate("JSON.stringify(window._resizerDbg || null)")
    print(f"  [resize] after mousedown — _resizerDbg={dbg_after_down}")
    page.mouse.move(cx + delta / 2, cy, steps=5)
    page.mouse.move(cx + delta,     cy, steps=5)
    page.mouse.up()

    # Allow JS handlers and Reflex state update to settle.
    page.wait_for_timeout(600)

    new_w = page.evaluate(
        "document.getElementById('left-column').getBoundingClientRect().width"
    )
    js_ready_after = page.evaluate("!!window._panelResizerReady")
    print(f"  [resize] new left-column width: {new_w:.0f}px  "
          f"(expected ~{initial_w + delta:.0f})  js_ready={js_ready_after}")

    if not js_ready:
        print("  [resize] WARNING: _panelResizerReady was False before drag — "
              "resizer.js may not have executed")

    tolerance = 30
    if abs(new_w - (initial_w + delta)) > tolerance:
        raise AssertionError(
            f"Left column did not resize: initial={initial_w:.0f}px "
            f"new={new_w:.0f}px expected≈{initial_w + delta:.0f}px "
            f"(±{tolerance}px tolerance)"
        )


def _right_click_node(page, label_text: str):
    """Right-click the first tree node with the given label text.

    Opens the Radix context menu and fires AppState.open_context_menu via the
    on_context_menu event on the tree row.  Waits briefly for Reflex to process
    the event before the caller inspects the menu.
    """
    node = page.get_by_text(label_text, exact=True).first
    node.wait_for(state="visible", timeout=CHECK_TIMEOUT)
    node.click(button="right")
    # Allow Reflex websocket round-trip to populate ctx_menu_rows
    page.wait_for_timeout(800)


def check_context_menu_visible(page, item_id: str):
    """Right-click pve-1, verify context menu item with id=<item_id> is present.

    Value format: '<item_id>'  e.g. 'ssh_pve'
    The context menu items are rendered with id=<action_id> (HTML id attribute).
    """
    _right_click_node(page, "pve-1")
    page.wait_for_selector(f"#{item_id}", timeout=CHECK_TIMEOUT)
    print(f"  [ctx_menu] item #{item_id} found in context menu")
    # Close menu by pressing Escape
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


def check_context_menu_url(page, id_and_url: str):
    """Right-click pve-1, click the action item, verify window.open URL.

    Value format: '<item_id>:<expected_url>'  (first colon is delimiter)
    """
    item_id, _, expected_url = id_and_url.partition(":")

    # Intercept window.open before right-clicking
    page.evaluate(
        "() => { window.__pwOpenedUrls = [];"
        " const orig = window.open.bind(window);"
        " window.open = function(u,...a){ window.__pwOpenedUrls.push(u); return orig(u,...a); }; }"
    )

    _right_click_node(page, "pve-1")
    page.wait_for_selector(f"#{item_id}", timeout=CHECK_TIMEOUT)
    page.locator(f"#{item_id}").click()
    page.wait_for_timeout(1500)

    urls = page.evaluate("window.__pwOpenedUrls") or []
    if expected_url not in urls:
        raise AssertionError(
            f"Expected window.open({expected_url!r}), got: {urls}"
        )
    print(f"  [ctx_menu] window.open({expected_url!r}) confirmed")


def check_context_menu_clipboard(page, id_and_text: str):
    """Right-click pve-1, click the action item, verify clipboard text.

    Value format: '<item_id>:<expected_text>'  (first colon is delimiter)
    """
    item_id, _, expected_text = id_and_text.partition(":")

    # Intercept navigator.clipboard.writeText
    page.evaluate(
        "() => { window.__pwClipboard = null;"
        " const orig = navigator.clipboard.writeText.bind(navigator.clipboard);"
        " navigator.clipboard.writeText = function(t){ window.__pwClipboard=t; return orig(t); }; }"
    )

    _right_click_node(page, "pve-1")
    page.wait_for_selector(f"#{item_id}", timeout=CHECK_TIMEOUT)
    page.locator(f"#{item_id}").click()
    page.wait_for_timeout(1500)

    actual = page.evaluate("window.__pwClipboard")
    if actual != expected_text:
        raise AssertionError(
            f"Expected clipboard {expected_text!r}, got: {actual!r}"
        )
    print(f"  [ctx_menu] clipboard = {expected_text!r} confirmed")


CHECK_MAP = {
    "node_visible":            check_node_visible,
    "node_selected":           check_node_selected,
    "right_panel_has":         check_right_panel_has,
    "no_element":              check_no_element,
    "panel_resize_works":      check_panel_resize_works,
    "context_menu_visible":    check_context_menu_visible,
    "context_menu_url":        check_context_menu_url,
    "context_menu_clipboard":  check_context_menu_clipboard,
    "bottom_left_panel_has":   check_bottom_left_panel_has,
    "bottom_left_path_has":    check_bottom_left_path_has,
    "click_node_file_viewer":  check_click_node_file_viewer,
    "file_viewer_source_link": check_file_viewer_source_link,
    "terminal_shell":          check_terminal_shell,
    "ssh_terminal":            check_ssh_terminal,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _page_summary(page, screenshot_path: str) -> None:
    """
    Print a summary of what Playwright can see in the page right now.
    Also saves a screenshot so there is always visual proof.
    """
    print("\n  --- Page Summary ---")
    try:
        title = page.title()
        print(f"  Title   : {title}")
        print(f"  URL     : {page.url}")
    except Exception as exc:
        print(f"  (could not read title/url: {exc})")

    # Dump up to 800 chars of visible text as proof the DOM is populated.
    try:
        body_text = page.evaluate("document.body.innerText") or ""
        sample = " ".join(body_text.split())[:800]
        print(f"  Content : {sample}")
    except Exception as exc:
        print(f"  (could not read body text: {exc})")

    # Always save a screenshot — visual proof that Playwright is connected.
    try:
        Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"  Screenshot: {screenshot_path}")
    except Exception as exc:
        print(f"  (screenshot failed: {exc})")

    print("  --------------------\n")


def run(args):
    headless = args.headless.lower() not in ("false", "0", "no")
    obs_mode = args.observation_mode if not headless else "none"
    obs_timeout = args.observation_timeout

    print(f"[browser_test] Playwright launching Chromium "
          f"(headless={headless}, observation={obs_mode})")
    print(f"[browser_test] Target URL: {args.url}")

    with sync_playwright() as p:
        if not headless and args.profile_dir:
            # Use the real Chrome user-data directory with the matched profile.
            user_data_dir = args.user_data_dir or _chrome_user_data_dir()
            print(f"[browser_test] Persistent context: {user_data_dir} / {args.profile_dir}")
            context = p.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    f"--profile-directory={args.profile_dir}",
                ],
            )
            page = context.new_page()
        else:
            browser = p.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()

        print(f"[browser_test] Navigating to {args.url} ...")
        page.goto(args.url, wait_until="domcontentloaded")

        # Inject a "waiting" panel immediately so the user sees feedback
        # during the Vite cold-cache OOM crash / restart cycle (can take ~25s).
        if not headless:
            try:
                page.evaluate(_INJECT_CONTINUE_BTN_JS)
                _btn_update(page,
                            next_step="\u23f3 Waiting for app to initialize\u2026",
                            status="Reflex + Vite starting (first run may take ~25s)\u2026",
                            color="#6b7280")
            except Exception:
                pass

        print("[browser_test] Waiting for Reflex to hydrate (tree loaded + no connection error)...")
        wait_for_ready(page)
        print("[browser_test] Page ready.")

        # Always print page summary + auto-screenshot so there is proof of what
        # Playwright sees, regardless of whether explicit --screenshot was given.
        auto_shot = args.screenshot or str(
            Path(tempfile.gettempdir()) / f"de3-gui-test-{int(time.time())}.png"
        )
        _page_summary(page, auto_shot)

        post_pause = args.post_continue_pause

        # Observation point 1: state applied, checks not yet run.
        # Show each pending check on its own line so the user knows what's coming.
        pending_lines = "\n".join(f"  \u25cb {c}" for c in args.checks)
        _btn_update(page,
                    next_step=f"\u25b6 Click to run {len(args.checks)} check(s)",
                    status=f"State applied — checks not yet run.\n\nWill check:\n{pending_lines}")
        _set_page_tint(page, args.tint_waiting)
        observe(page, obs_mode, obs_timeout,
                "Reviewing initial state — checks have NOT run yet.",
                post_pause_secs=post_pause)

        errors = []
        results = []
        total = len(args.checks)
        print(f"[browser_test] Running {total} check(s)...")
        for i, raw in enumerate(args.checks, 1):
            kind, _, value = raw.partition(":")
            fn = CHECK_MAP.get(kind)
            _btn_update(page,
                        next_step=f"\u23f3 Running check {i}/{total}",
                        status=f"running: {raw}",
                        color=args.btn_running)
            if fn is None:
                msg = f"FAIL [{raw}]: unknown check type '{kind}'"
                errors.append(msg)
                results.append(f"\u2717 {raw}")
                _btn_update(page, status="\n".join(results), color=args.btn_fail)
                continue
            try:
                fn(page, value)
                print(f"  OK   {raw}")
                results.append(f"\u2713 {raw}")
            except (PWTimeout, AssertionError) as exc:
                errors.append(f"  FAIL [{raw}]: {exc}")
                results.append(f"\u2717 {raw}")
            _btn_update(page,
                        next_step=f"\u23f3 Running checks ({i}/{total} done)",
                        status="\n".join(results),
                        color=args.btn_fail if errors else args.btn_running)

        # Observation point 2: all checks done — final gate before closing.
        if not errors:
            _btn_update(page,
                        next_step=f"\u2705 Exit test  ({total}/{total} passed)",
                        status="\n".join(results),
                        color=args.btn_pass)
            _set_page_tint(page, args.tint_waiting)  # keep yellow — waiting to confirm
            observe(page, obs_mode, obs_timeout,
                    "All checks passed — click Exit test to close.",
                    post_pause_secs=post_pause)
        else:
            _btn_update(page,
                        next_step=f"\u274c Exit test  ({len(errors)} FAILED / {total})",
                        status="\n".join(results),
                        color=args.btn_fail)
            _set_page_tint(page, args.tint_fail)  # red — something went wrong
            # On failure: dump current page state to help debug what went wrong.
            print("\n[browser_test] Checks failed — current page state:")
            fail_shot = str(Path(auto_shot).parent / f"fail-{int(time.time())}.png")
            _page_summary(page, fail_shot)
            observe(page, obs_mode, obs_timeout,
                    f"{len(errors)} check(s) FAILED — click Exit test to close.",
                    post_pause_secs=0)

        # Clear tint and remove panel just before closing the browser.
        _set_page_tint(page, "clear")
        try:
            page.evaluate(_REMOVE_CONTINUE_BTN_JS)
        except Exception:
            pass
        context.close()

    if errors:
        print("\n[browser_test] FAILED checks:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)

    print("[browser_test] All checks passed.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url",          default="http://localhost:9080")
    ap.add_argument("--check",        action="append", default=[], dest="checks",
                    metavar="TYPE:VALUE")
    ap.add_argument("--screenshot",   default="", metavar="PATH")
    ap.add_argument("--headless",     default="true")
    ap.add_argument("--profile-dir",  default="",
                    help="Chrome profile directory name, e.g. 'Profile 1'")
    ap.add_argument("--user-data-dir", default="",
                    help="Chrome user-data dir (auto-detected if empty)")
    ap.add_argument("--observation-mode", default="none",
                    choices=["none", "timer", "interactive"],
                    help="none=close immediately, timer=sleep N secs, "
                         "interactive=wait for browser click or Enter key")
    ap.add_argument("--observation-timeout", default=60, type=int,
                    metavar="SECS",
                    help="Seconds for timer mode, or max wait in interactive mode "
                         "(0=indefinite in interactive mode)")
    ap.add_argument("--post-continue-pause", default=3, type=int,
                    metavar="SECS",
                    help="Seconds to pause after clicking Continue before running checks "
                         "(lets you see the green confirmation; 0=skip)")
    # Colors — sourced from de3-gui-pkg.yaml via the Ansible playbook.
    ap.add_argument("--tint-waiting", default=_DEFAULT_COLORS["tint_waiting"],
                    help="CSS color for the window tint while waiting (both observation gates)")
    ap.add_argument("--tint-fail",    default=_DEFAULT_COLORS["tint_fail"],
                    help="CSS color for the window tint when checks fail")
    ap.add_argument("--btn-running",  default=_DEFAULT_COLORS["btn_running"],
                    help="Popup button background while a check is running")
    ap.add_argument("--btn-pass",     default=_DEFAULT_COLORS["btn_pass"],
                    help="Popup button background at the final gate when all checks passed")
    ap.add_argument("--btn-fail",     default=_DEFAULT_COLORS["btn_fail"],
                    help="Popup button background at the final gate when checks failed")
    args = ap.parse_args()

    if not args.checks:
        ap.error("At least one --check is required")

    run(args)
