# 20260404-231226 — Fix Monaco scroll-sync: revealLineAtTop instead of revealLine

## Problem

`monaco.editor.getEditors()[0].revealLine(ln, 1)` scrolls only enough to make
the line *visible* — it can land anywhere in the viewport (often centred).
The target line appeared in the middle of the editor instead of the top.

## Fix

Changed to `revealLineAtTop(ln, 1)`, which pins the target line to the **top**
of the Monaco viewport, matching the position it had in the read-only viewer.
