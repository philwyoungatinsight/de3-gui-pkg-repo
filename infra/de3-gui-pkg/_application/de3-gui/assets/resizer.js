/**
 * resizer.js — panel drag-to-resize for the Home Lab GUI.
 *
 * Uses event delegation on document so React re-renders that replace
 * the resizer DOM node never break the listeners.
 */
(function () {
  if (window._panelResizerReady) return;
  window._panelResizerReady = true;

  var isResizing = false;
  var startX     = 0;
  var startLeftW = 0;

  /* mousedown anywhere — check if it hit the resizer */
  document.addEventListener('mousedown', function (e) {
    var resizer = document.getElementById('panel-resizer');
    if (!resizer) return;
    if (e.target !== resizer && !resizer.contains(e.target)) return;

    var left = document.getElementById('left-panel');
    if (!left) return;

    isResizing = true;
    startX     = e.clientX;
    startLeftW = left.getBoundingClientRect().width;
    document.body.style.cursor     = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });

  document.addEventListener('mousemove', function (e) {
    if (!isResizing) return;
    var cont = document.getElementById('main-panels');
    var left = document.getElementById('left-panel');
    if (!cont || !left) return;

    var contW = cont.getBoundingClientRect().width;
    var newW  = Math.max(200, Math.min(contW - 200, startLeftW + (e.clientX - startX)));
    left.style.width = newW + 'px';
    left.style.flex  = 'none';
  });

  document.addEventListener('mouseup', function () {
    if (!isResizing) return;
    isResizing = false;
    document.body.style.cursor     = '';
    document.body.style.userSelect = '';

    var trigger = document.getElementById('resize-complete-trigger');
    if (trigger) trigger.click();
  });
})();
