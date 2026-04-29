# 20260404-234046 — Module pill: direct click instead of hover card

## Problem

The module pill on each infra tree node was wrapped in `rx.hover_card`.
To open a module you had to hover (slow), wait for the popup, then click
"Open in Modules ↗" inside it.  The hover card was unreliable.

## Fix

Replaced the `rx.hover_card.root/trigger/content` wrapper with a plain
clickable `rx.text` pill that fires `AppState.navigate_to_module(node["module_tree_path"])`
directly on click.  The full path is shown as a `title=` tooltip on hover
(browser native, instant).  A subtle border highlight on hover signals
the pill is clickable.

The `navigate_to_module` handler already did the right thing: switches to
the Modules explorer view, expands ancestor paths, selects the node, and
loads its `.tf` file content.
