#!/usr/bin/env python3
"""Launch a visible Playwright browser window, optionally with HTTP credentials.

Invoked as a subprocess by dispatch_action when browser_profile=="playwright"
and browser_embedded is False.  Credentials are passed via environment variables
so they never appear in the process argument list.

Environment variables:
  PL_URL                URL to navigate to (required)
  PL_SCHEME             auth scheme: digest | basic | form  (default: digest)
  PL_USERNAME           auth username
  PL_PASSWORD           auth password
  PL_USERNAME_SELECTOR  CSS selector for username field (form scheme)
  PL_PASSWORD_SELECTOR  CSS selector for password field (form scheme)
  PL_SUBMIT_SELECTOR    CSS selector for submit button (form scheme)
  PL_SUCCESS_URL        substring to wait for in URL after form login
"""
import os
import sys

url                = os.environ.get("PL_URL", "")
scheme             = os.environ.get("PL_SCHEME", "digest")
username           = os.environ.get("PL_USERNAME", "")
password           = os.environ.get("PL_PASSWORD", "")
username_selector  = os.environ.get("PL_USERNAME_SELECTOR", "input[name=username]")
password_selector  = os.environ.get("PL_PASSWORD_SELECTOR", "input[name=password]")
submit_selector    = os.environ.get("PL_SUBMIT_SELECTOR", "button[type=submit]")
success_url        = os.environ.get("PL_SUCCESS_URL", "")

if not url:
    print("playwright_launcher: PL_URL not set", file=sys.stderr)
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright_launcher: playwright not installed", file=sys.stderr)
    sys.exit(1)

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=False,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"],
    )

    if scheme == "form":
        ctx = browser.new_context(ignore_https_errors=True, no_viewport=True)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_selector(username_selector, timeout=10_000)
            page.fill(username_selector, username)
            page.fill(password_selector, password)
            page.click(submit_selector)
            if success_url:
                page.wait_for_url(f"**{success_url}**", timeout=15_000)
            else:
                page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception as e:
            print(f"playwright_launcher: form login error: {e}", file=sys.stderr)
    else:
        # digest / basic — pass credentials via HTTP context
        if username:
            ctx = browser.new_context(
                http_credentials={"username": username, "password": password},
                ignore_https_errors=True,
                no_viewport=True,
            )
        else:
            ctx = browser.new_context(ignore_https_errors=True, no_viewport=True)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            # Auto-click logon submit button if present (e.g. Intel AMT /logon.htm)
            btn = page.query_selector("input[type=submit]")
            if btn:
                btn.click()
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception as e:
            print(f"playwright_launcher: navigation error: {e}", file=sys.stderr)

    # Keep browser open until user closes it
    try:
        page.wait_for_event("close", timeout=0)
    except Exception:
        pass
