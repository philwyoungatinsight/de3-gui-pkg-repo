# 20260404-231031 — Fix Monaco scroll-sync: use getBoundingClientRect instead of offsetTop

## Problem

`_read_pre_top_line_js()` compared `spans[i].offsetTop` against the scroll
container's `scrollTop`. `offsetTop` is measured from the element to its
`offsetParent`, which is **not necessarily the scroll container** — intermediate
`position: relative` wrappers (Reflex/Radix panels) shift the origin, causing
the detected "top line" to be significantly wrong (e.g. reporting line 5 when
line 90 was at the top of the viewport).

## Fix

Replaced the `offsetTop + offsetHeight > scrollTop` comparison with
`getBoundingClientRect()` on both the scroll container and each line span.
Both measurements are now in **viewport coordinates**, so the origins always
match regardless of the DOM nesting depth.

```javascript
var contTop = cont.getBoundingClientRect().top;
for(var i = 0; i < spans.length; i++){
  if(spans[i].getBoundingClientRect().bottom > contTop) return i+1;
}
```
