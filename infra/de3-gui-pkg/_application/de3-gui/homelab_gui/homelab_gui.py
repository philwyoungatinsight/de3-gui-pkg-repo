"""Home Lab GUI — Reflex web app to visualize the home lab infrastructure DAG."""

import asyncio
import re
import hashlib
import json
import os
import pty
import sys
import threading as _threading
import select as _select_mod
import signal
import subprocess
import termios
import fcntl
import struct
import urllib.parse
import reflex as rx
from pydantic import BaseModel as _PydanticBase
import yaml
from datetime import datetime as _datetime
from pathlib import Path
from reflex_monaco import monaco as _monaco
from pydantic import BaseModel
from reflex.components.component import NoSSRComponent
from reflex.components.radix.themes.color_mode import set_color_mode as _set_color_mode
from reflex.vars.base import Var
from reflex.components.core.banner import has_connection_errors, connection_error
from typing import Any, ClassVar, Optional
from reflex.utils.imports import ImportDict


def _gui_log(msg: str) -> None:
    """Print a timestamped log line to stdout."""
    print(f"[{_datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_APP_DIR = Path(__file__).parent
_APP_ROOT = _APP_DIR.parent             # de3-gui/ (application root)
CONFIG_DIR = _APP_DIR.parent.parent.parent / "_config"  # de3-gui-pkg/_config/
STATE_DIR = _APP_ROOT / "state"         # de3-gui/state/
STATE_DIR.mkdir(exist_ok=True)

# External stack directory — contains infra/, config/, framework/, root.hcl, etc.
# Set _STACK_DIR in the environment to override the default.
def _find_repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "set_env.sh").exists():
            return p
    return start

_STACK_DIR = Path(os.environ.get("_STACK_DIR") or str(_find_repo_root(Path(__file__).resolve())))

# Temporary file written by the test framework to pre-load a GUI state.
# on_load reads and removes this file when it exists.
_TEST_STATE_FILE = STATE_DIR / ".test_state.yml"

# Marker file written by _apply_test_state() so ALL Reflex worker processes
# can detect that a test state was applied recently.  Reflex 0.8.27 fires
# on_load twice on fresh page load (WebSocket reconnect); the second worker
# call would reset test state to defaults without this cross-process flag.
import time as _time_module
_gui_dir_env = os.environ.get("_GUI_DIR")
if not _gui_dir_env:
    raise RuntimeError("_GUI_DIR is not set — source set_env.sh before starting the GUI")
_TEST_APPLIED_MARKER = Path(_gui_dir_env) / "test-applied"

# Framework repos diagram exporter — data source
_FW_REPOS_YAML    = _STACK_DIR / "config/tmp/fw_repos_diagram_exporter/known-fw-repos.yaml"
_FW_REPOS_VIZ_BIN = _STACK_DIR / "infra/_framework-pkg/_framework/_fw_repos_diagram_exporter/fw-repos-diagram-exporter"

# ---------------------------------------------------------------------------
# Panel resizer JavaScript
#
# Injected via rx.call_script on every page load so it executes through the
# Reflex websocket (guaranteed post-hydration).  Using rx.script(src=...) does
# not work because React Helmet injects the <script> tag via innerHTML, which
# browsers refuse to execute per the HTML spec.
# ---------------------------------------------------------------------------
_RESIZER_JS = """
(function () {
  if (window._panelResizerReady) return;
  window._panelResizerReady = true;

  var isResizing = false;
  var startX     = 0;
  var startLeftW = 0;

  // Debug object — read by browser_test.py to diagnose startX issues.
  window._resizerDbg = { clientX: null, targetId: null, startX: null };

  function _beginResize(e, sourceId) {
    var left = document.getElementById('left-column');
    if (!left) return;
    window._resizerDbg.clientX  = e.clientX;
    window._resizerDbg.targetId = sourceId;
    window._resizerDbg.startX   = e.clientX;
    isResizing = true;
    startX     = e.clientX;
    startLeftW = left.getBoundingClientRect().width;
    document.body.style.cursor     = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  }

  // Prefer direct attachment on the resizer element — avoids e.target check
  // failures that can occur when Playwright fires events via synthetic dispatch.
  function _bindResizerElement() {
    var resizer = document.getElementById('panel-resizer');
    if (!resizer || resizer._resizerBound) return;
    resizer._resizerBound = true;
    resizer.addEventListener('mousedown', function (e) {
      _beginResize(e, 'direct');
    });
  }
  _bindResizerElement();

  // Document-level fallback for cases where the element is replaced post-bind.
  document.addEventListener('mousedown', function (e) {
    if (isResizing) return;                          // direct listener already fired
    var resizer = document.getElementById('panel-resizer');
    if (!resizer) return;
    if (e.target !== resizer && !resizer.contains(e.target)) return;
    _beginResize(e, 'delegated');
  });

  function _endResize() {
    isResizing = false;
    document.body.style.cursor     = '';
    document.body.style.userSelect = '';
  }

  document.addEventListener('mousemove', function (e) {
    if (!isResizing) return;
    // Cancel if the primary button was released outside the viewport.
    if (!(e.buttons & 1)) { _endResize(); return; }
    var cont = document.getElementById('main-panels');
    var left = document.getElementById('left-column');
    if (!cont || !left) return;
    var contW = cont.getBoundingClientRect().width;
    var newW  = Math.max(200, Math.min(contW - 200, startLeftW + (e.clientX - startX)));
    left.style.width = newW + 'px';
    left.style.flex  = 'none';
    var leftB = document.getElementById('left-column-bottom');
    if (leftB) { leftB.style.width = newW + 'px'; leftB.style.flex = 'none'; }
    // Store the percentage so on_resize_complete can read it even after React re-renders.
    window._leftPanelWidthPct = contW > 0 ? newW / contW * 100 : 50;
  });

  document.addEventListener('mouseup', function () {
    if (!isResizing) return;
    _endResize();
    var trigger = document.getElementById('resize-complete-trigger');
    if (trigger) trigger.click();
  });
})();
"""

# ---------------------------------------------------------------------------
# Horizontal panel resizer JavaScript
# Dragging the bar between the top and bottom row adjusts their heights.
# ---------------------------------------------------------------------------
_HRESIZER_JS = """
(function () {
  if (window._panelHResizerReady) return;
  window._panelHResizerReady = true;

  var isResizing = false;
  var startY     = 0;
  var startTopH  = 0;

  document.addEventListener('mousedown', function (e) {
    var resizer = document.getElementById('panel-h-resizer');
    if (!resizer) return;
    if (e.target !== resizer && !resizer.contains(e.target)) return;
    var top = document.getElementById('top-left-panel');
    if (!top) return;
    isResizing = true;
    startY     = e.clientY;
    startTopH  = top.getBoundingClientRect().height;
    document.body.style.cursor     = 'row-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });

  function _endHResize() {
    isResizing = false;
    document.body.style.cursor     = '';
    document.body.style.userSelect = '';
  }

  document.addEventListener('mousemove', function (e) {
    if (!isResizing) return;
    // Cancel if the primary button was released outside the viewport.
    if (!(e.buttons & 1)) { _endHResize(); return; }
    var main = document.getElementById('main-panels');
    var top  = document.getElementById('top-left-panel');
    if (!main || !top) return;
    var hRes = document.getElementById('panel-h-resizer');
    var hResH = hRes ? hRes.getBoundingClientRect().height : 5;
    var colH = main.getBoundingClientRect().height - hResH;
    var newH = Math.max(100, Math.min(colH - 100,
                startTopH + (e.clientY - startY)));
    top.style.height = newH + 'px';
    top.style.flex   = 'none';
    // Store the percentage so on_hresize_complete can read it even after React re-renders.
    window._topRowHeightPct = colH > 0 ? newH / colH * 100 : 60;
  });

  document.addEventListener('mouseup', function () {
    if (!isResizing) return;
    _endHResize();
    var trigger = document.getElementById('hresize-complete-trigger');
    if (trigger) trigger.click();
  });
})();
"""

# ---------------------------------------------------------------------------
# Floating panel z-order JavaScript
#
# Installed once at page load (via install_resizer) rather than per-panel so
# that it survives React re-renders.  Uses two mechanisms:
#   1. document pointerdown capture — fires for clicks on any DOM element inside
#      a floating panel (including Reflex-rendered content).
#   2. window blur — fires when an <iframe> inside a floating panel steals focus
#      (iframe clicks do not propagate to the parent document, so the pointerdown
#      listener above never fires; blur / document.activeElement is the workaround).
# ---------------------------------------------------------------------------
_FLOAT_ZORDER_JS = """
(function () {
  if (window._floatZorderReady) return;
  window._floatZorderReady = true;

  var FLOAT_IDS = [
    'float-fv-window', 'float-term-window', 'float-ov-window',
    'float-refactor-window', 'float-pkg-op-dialog', 'hover-popup-window'
  ];

  function bringToFront(winEl) {
    FLOAT_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.zIndex = '9990';
    });
    winEl.style.zIndex = '9992';
  }

  // Clicks anywhere inside a floating panel (non-iframe content).
  document.addEventListener('pointerdown', function (e) {
    for (var i = 0; i < FLOAT_IDS.length; i++) {
      var el = document.getElementById(FLOAT_IDS[i]);
      if (el && el.contains(e.target)) {
        bringToFront(el);
        return;
      }
    }
  }, true);

  // Clicks inside an iframe (e.g. the terminal panel) steal focus from the
  // parent document.  The window 'blur' event fires at that moment and
  // document.activeElement is the iframe that just received focus.
  window.addEventListener('blur', function () {
    var active = document.activeElement;
    if (!active || active.tagName !== 'IFRAME') return;
    for (var i = 0; i < FLOAT_IDS.length; i++) {
      var el = document.getElementById(FLOAT_IDS[i]);
      if (el && el.contains(active)) {
        bringToFront(el);
        return;
      }
    }
  }, true);
})();
"""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROVIDER_COLOR: dict[str, str] = {
    "gcp": "blue",
    "aws": "orange",
    "azure": "cyan",
    "proxmox": "amber",
    "maas": "purple",
    "unifi": "indigo",
    "null": "gray",
}

# Hex accent colour per provider (used in unit-params panel headers)
PROVIDER_ACCENT: dict[str, str] = {
    "gcp":     "#4285F4",
    "aws":     "#FF9900",
    "azure":   "#0078D4",
    "proxmox": "#E07000",
    "maas":    "#7C3AED",
    "unifi":   "#4338CA",
    "null":    "#6B7280",
}

# Layer groupings for the component diagram view
COMPONENT_LAYERS = [
    ("On-Premise Infrastructure", ["proxmox", "unifi"]),
    ("Provisioning", ["maas", "null"]),
    ("Cloud", ["gcp", "aws", "azure"]),
]

# ---------------------------------------------------------------------------
# Arch-diagram config — loaded once at import
# ---------------------------------------------------------------------------

def _load_arch_diagram_config() -> dict:
    """Load arch_diagram_config.yaml; return 'arch_diagram' sub-dict or {}."""
    cfg_path = Path(__file__).parent.parent.parent.parent / "_config" / "arch_diagram_config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        raw = yaml.safe_load(cfg_path.read_text()) or {}
        return raw.get("arch_diagram_config", {})
    except Exception:
        return {}


_ARCH_DIAGRAM_CONFIG: dict = _load_arch_diagram_config()

# ---------------------------------------------------------------------------
# Cytoscape.js component — wraps react-cytoscapejs (NoSSRComponent pattern)
# No CDN, no iframe; bundled by Reflex's build system.
# ---------------------------------------------------------------------------

class _CytoscapeGraph(NoSSRComponent):
    """Low-level wrapper around react-cytoscapejs."""
    library: str = "react-cytoscapejs@2.0.0"
    lib_dependencies: list[str] = ["cytoscape@3.29.2"]
    tag: str = "CytoscapeComponent"
    is_default: bool = True

    # _rename_props maps camelCase Python attr names → JSX prop names.
    # Reflex converts snake_case to camelCase before _replace_prop_names runs.
    # cy_style → cyStyle → style  (avoids collision with Reflex's own style system)
    # cy_cb    → cyCb    → cy     (react-cytoscapejs instance callback)
    _rename_props: ClassVar[dict] = {"cyStyle": "style", "cyCb": "cy"}

    elements:         Var[list]
    stylesheet:       Var[list]
    layout:           Var[dict]
    cy_style:         Var[dict]
    cy_cb:            Var[Any]   # (cy: Core) => void — initialisation callback
    wheel_sensitivity: Var[float]



# ---------------------------------------------------------------------------
# React Flow component — wraps the reactflow npm package (NoSSRComponent pattern)
# ---------------------------------------------------------------------------

class _ReactFlowGraph(NoSSRComponent):
    """Low-level wrapper around the reactflow ReactFlow component."""
    library: str = "reactflow@11.11.4"
    tag: str = "ReactFlow"
    is_default: bool = True

    # rf_style → rfStyle → style  (avoids collision with Reflex's own style prop)
    # on_node_click_cb → onNodeClickCb → onNodeClick
    _rename_props: ClassVar[dict] = {
        "rfStyle":        "style",
        "onNodeClickCb":  "onNodeClick",
    }

    nodes:              Var[list]
    edges:              Var[list]
    fit_view:           Var[bool]
    nodes_draggable:    Var[bool]
    nodes_connectable:  Var[bool]
    rf_style:           Var[dict]
    on_node_click_cb:   Var[Any]   # (event, node) => void

    def add_imports(self) -> ImportDict:
        """Include the React Flow CSS so nodes/edges render at correct positions."""
        return {"": "reactflow/dist/style.css"}


# Synthetic compound graph — mirrors real infra structure.
# Used when _STACK_DIR/infra is unavailable (no real data).
_SYNTHETIC_COMPOUND_ELEMENTS: list[dict] = [
    # depth 0 — package/provider root (compound)
    {"data": {"id": "example-pkg/_stack/proxmox",  "label": "proxmox", "depth": 0, "provider": "proxmox"}, "classes": "proxmox"},
    {"data": {"id": "example-pkg/_stack/maas",     "label": "maas",    "depth": 0, "provider": "maas"},    "classes": "maas"},
    {"data": {"id": "example-pkg/_stack/unifi",    "label": "unifi",   "depth": 0, "provider": "unifi"},   "classes": "unifi"},
    # depth 1 — environment (compound)
    {"data": {"id": "example-pkg/_stack/proxmox/example-lab",   "parent": "example-pkg/_stack/proxmox",  "label": "example-lab", "depth": 1, "provider": "proxmox"}, "classes": "proxmox"},
    {"data": {"id": "example-pkg/_stack/maas/example-lab",      "parent": "example-pkg/_stack/maas",     "label": "example-lab", "depth": 1, "provider": "maas"},    "classes": "maas"},
    {"data": {"id": "example-pkg/_stack/unifi/example-lab",     "parent": "example-pkg/_stack/unifi",    "label": "example-lab", "depth": 1, "provider": "unifi"},   "classes": "unifi"},
    # depth 2 — groups (compound)
    {"data": {"id": "example-pkg/_stack/proxmox/example-lab/pve-nodes",  "parent": "example-pkg/_stack/proxmox/example-lab",  "label": "pve-nodes", "depth": 2, "provider": "proxmox"}, "classes": "proxmox"},
    {"data": {"id": "example-pkg/_stack/maas/example-lab/machines",      "parent": "example-pkg/_stack/maas/example-lab",     "label": "machines",  "depth": 2, "provider": "maas"},    "classes": "maas"},
    # depth 3 — leaf resources
    {"data": {"id": "example-pkg/_stack/proxmox/example-lab/pve-nodes/pve-1",     "parent": "example-pkg/_stack/proxmox/example-lab/pve-nodes",     "label": "pve-1",       "depth": 3, "provider": "proxmox", "has_terragrunt": True}, "classes": "proxmox"},
    {"data": {"id": "example-pkg/_stack/proxmox/example-lab/pve-nodes/pve-2",     "parent": "example-pkg/_stack/proxmox/example-lab/pve-nodes",     "label": "pve-2",       "depth": 3, "provider": "proxmox", "has_terragrunt": True}, "classes": "proxmox"},
    {"data": {"id": "example-pkg/_stack/maas/example-lab/machines/node-1",        "parent": "example-pkg/_stack/maas/example-lab/machines",         "label": "node-1",      "depth": 3, "provider": "maas",    "has_terragrunt": True}, "classes": "maas"},
    {"data": {"id": "example-pkg/_stack/maas/example-lab/machines/node-2",        "parent": "example-pkg/_stack/maas/example-lab/machines",         "label": "node-2",      "depth": 3, "provider": "maas",    "has_terragrunt": True}, "classes": "maas"},
    {"data": {"id": "example-pkg/_stack/unifi/example-lab/network",               "parent": "example-pkg/_stack/unifi/example-lab",                 "label": "network",     "depth": 2, "provider": "unifi",   "has_terragrunt": True}, "classes": "unifi"},
    {"data": {"id": "example-pkg/_stack/unifi/example-lab/port-profile",          "parent": "example-pkg/_stack/unifi/example-lab",                 "label": "port-profile","depth": 2, "provider": "unifi",   "has_terragrunt": True}, "classes": "unifi"},
]

# Cytoscape.js stylesheet for compound (nested) nodes.
# Uses the :parent selector for compound nodes and :childless for leaves.
_CYTOSCAPE_STYLESHEET: list[dict] = [
    # ── All nodes baseline ───────────────────────────────────────────────────
    {
        "selector": "node",
        "style": {
            "label":              "data(label)",
            "font-size":          "10px",
            "text-valign":        "center",
            "text-halign":        "center",
            "text-wrap":          "wrap",
            "text-max-width":     "100px",
            "color":              "#e2e8f0",
            "background-color":   "#1e293b",
            "shape":              "round-rectangle",
        },
    },
    # ── Compound / parent nodes — visually contain their children ────────────
    {
        "selector": ":parent",
        "style": {
            "font-size":                      "11px",
            "font-weight":                    "bold",
            "text-valign":                    "top",
            "text-margin-y":                  -8,
            "color":                          "#94a3b8",
            "background-opacity":             0.12,
            "background-color":               "#334155",
            "border-width":                   1,
            "border-color":                   "#475569",
            "padding":                        "18px",
            "shape":                          "round-rectangle",
            "compound-sizing-wrt-labels":     "include",
            "min-width":                      "80px",
            "min-height":                     "50px",
        },
    },
    # ── Depth-0 package box — outermost container ────────────────────────────
    {
        "selector": "node[depth = 0]",
        "style": {
            "font-size":           "13px",
            "font-weight":         "bold",
            "color":               "#f1f5f9",
            "background-color":    "#0f172a",
            "background-opacity":  0.6,
            "border-color":        "#334155",
            "border-width":        2,
            "padding":             "28px",
            "text-margin-y":       -10,
        },
    },
    # ── Leaf nodes ───────────────────────────────────────────────────────────
    {
        "selector": ":childless",
        "style": {
            "width":    70,
            "height":   26,
            "font-size": "9px",
        },
    },
    # ── Terragrunt resource indicator ────────────────────────────────────────
    {
        "selector": "node[?has_terragrunt]:childless",
        "style": {
            "border-width": 2,
            "border-color": "#4ade80",
        },
    },
    # ── Provider accent colours (applied via class name on each element) ─────
    *[
        {"selector": f"node.{p}:parent",    "style": {"background-color": c, "border-color": c}}
        for p, c in {
            "proxmox": "#e74c3c", "maas": "#2ecc71", "unifi": "#3498db",
            "gcp": "#4285f4", "aws": "#ff9900", "azure": "#0089d6",
        }.items()
    ],
    *[
        {"selector": f"node.{p}:childless",  "style": {"background-color": c}}
        for p, c in {
            "proxmox": "#c0392b", "maas": "#27ae60", "unifi": "#2980b9",
            "gcp": "#3b77db", "aws": "#e68a00", "azure": "#007bbf",
        }.items()
    ],
    # ── Collapsed compound node (children hidden) ────────────────────────────
    {
        "selector": ".cy-collapsed",
        "style": {
            "background-opacity": 0.4,
            "border-style":       "dashed",
        },
    },
    # ── Selected ─────────────────────────────────────────────────────────────
    {
        "selector": "node:selected",
        "style": {
            "overlay-color":   "#3b82f6",
            "overlay-opacity": 0.15,
        },
    },
    # ── Wave-colored override (added via class when color-by-wave is active) ─
    # These rules come after provider rules so they take precedence.
    {
        "selector": "node.wave-colored",
        "style": {
            "background-color": "data(wave_color)",
        },
    },
    {
        "selector": "node.wave-colored:parent",
        "style": {
            "background-color": "data(wave_color)",
            "border-color":     "data(wave_color)",
        },
    },
    # ── Dependency edges ──────────────────────────────────────────────────────
    {
        "selector": "edge",
        "style": {
            "width":                1.5,
            "line-color":           "#94a3b8",
            "target-arrow-color":   "#94a3b8",
            "target-arrow-shape":   "triangle",
            "curve-style":          "bezier",
            "opacity":              0.55,
            "arrow-scale":          0.8,
        },
    },
]


# Palette used when coloring nested-networks nodes by wave (cycles if > 12 waves).
_WAVE_PALETTE: list[str] = [
    "#ef4444", "#f97316", "#eab308", "#22c55e",
    "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899",
    "#14b8a6", "#f59e0b", "#84cc16", "#6366f1",
]

# Matches `config_path = "..."` inside terragrunt.hcl dependency blocks.
import re as _re
_DEPENDENCY_PATH_RE = _re.compile(r'^\s*config_path\s*=\s*"([^"]+)"', _re.MULTILINE)

# ---------------------------------------------------------------------------
# Visualization framework registry
# Each entry describes one pluggable left-panel visualization engine.
# To add a new framework:
#   1. Add an entry here with a unique "key".
#   2. Implement a `<key>_view() -> rx.Component` function below.
#   3. Add a case to `render_left_panel_content()`.
# ---------------------------------------------------------------------------
VIZ_FRAMEWORKS: list[dict] = [
    {
        "key": "reflex",
        "label": "Folder",
        "description": "Built-in tree view (Reflex native)",
    },
    {
        "key": "cytoscape",
        "label": "Nested Networks",
        "description": "Interactive network graph (Cytoscape.js)",
    },
    {
        "key": "reactflow",
        "label": "Tree",
        "description": "Hierarchical tree diagram (React Flow)",
    },
    {
        "key": "archdiagram",
        "label": "Arch Diagram",
        "description": "Architectural layers diagram, auto-derived from infra data",
    },
]


# ---------------------------------------------------------------------------
# Typed models (pydantic — required for nested rx.foreach type inference)
# ---------------------------------------------------------------------------

class ProviderCard(BaseModel):
    name: str
    resources: list[str]
    doc_url: str
    color: str
    count: str


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _deep_plain(obj):
    """Recursively convert Reflex state proxy objects to plain Python primitives.

    When values are read from Reflex state vars (dicts, lists), they are wrapped
    in proxy objects.  Passing proxied values directly to yaml.dump produces
    ``!!python/object/apply:reflex.istate.proxy._unwrap_for_pickle`` tags instead
    of the correct YAML representation.  This function strips those wrappers.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    # Iterate as dict first (covers both plain dicts and proxy dicts)
    try:
        return {_deep_plain(k): _deep_plain(v) for k, v in dict(obj).items()}
    except (TypeError, ValueError):
        pass
    # Iterate as sequence (covers plain lists and proxy lists)
    try:
        return [_deep_plain(v) for v in obj]
    except TypeError:
        pass
    return obj


_config_cache: dict = {}
_config_mtime: float = 0.0


def _load_config() -> dict:
    """Load _config/de3-gui-pkg.yaml (mtime-cached; re-reads only when the file changes).

    Returns the contents under the 'de3-gui-pkg:' top-level key so callers can
    access config["config"]["vm_ip"] etc. directly, without the package wrapper.
    """
    global _config_cache, _config_mtime
    config_file = CONFIG_DIR / "de3-gui-pkg.yaml"
    try:
        mtime = config_file.stat().st_mtime
        if mtime == _config_mtime and _config_cache:
            return _config_cache
        raw = yaml.safe_load(config_file.read_text()) or {}
        _config_cache = raw.get("de3-gui-pkg", {})
        _config_mtime = mtime
        return _config_cache
    except Exception:
        return _config_cache or {}


# ---------------------------------------------------------------------------
# Debounced background writer for state/current.yaml
#
# All writes go through _schedule_config_write() which debounces to 800 ms.
# A single threading.Lock prevents concurrent read-modify-write races.
# _save_ext_package_repos uses the same lock.
# ---------------------------------------------------------------------------

_state_write_lock = _threading.Lock()
_save_timer: "_threading.Timer | None" = None


def _do_write_menu(menu_data: dict) -> None:
    """Merge menu_data into current.yaml under current.menu. Runs in background."""
    current_path = STATE_DIR / "current.yaml"
    with _state_write_lock:
        try:
            raw: dict = yaml.safe_load(current_path.read_text()) or {} if current_path.exists() else {}
        except Exception:
            raw = {}
        raw.setdefault("current", {}).setdefault("menu", {}).update(menu_data)
        try:
            current_path.write_text(yaml.dump(raw, allow_unicode=True, default_flow_style=False))
        except Exception as exc:
            _gui_log(f"[homelab_gui] Warning: could not save current state: {exc}")


# ---------------------------------------------------------------------------
# Persistent unit-state.yaml — co-located with wave logs
# ---------------------------------------------------------------------------
# Schema (unit-state.yaml):
#   schema_version: 2
#   units:
#     <unit_path>:
#       status: ok | fail | destroyed | unknown | none
#       last_apply_exit_code: <int>     # 0 = success, non-0 = failure (None if unknown)
#       last_apply_at: <ISO-8601>       # timestamp of last detected apply/destroy completion
#       last_validated_at: <ISO-8601>   # timestamp of last Tier 2 GCS validate
#       details: ""                     # human-readable reason from exit-status YAML or MaaS status
#       maas_phase: ""                  # commissioning | ready | … | "" (cleared on final status)
#       maas_message: ""                # live progress message from MaaS script; "" when idle
#       maas_hostname: ""               # populated during MaaS intermediate status
#
# Written by: local_state_watcher (Tier 0: exit-status YAMLs from root.hcl hook;
#               Tier 1: local tfstate mtime → GCS cat fallback; Tier 3: /tmp exit files),
#             do_refresh_unit_build_statuses / do_refresh_subtree_status (Tier 2: GCS scan).
# Read by:    on_load (instant startup status), do_refresh_unit_build_statuses (fast path).

_unit_state_lock = _threading.Lock()


def _wave_logs_dir() -> Path:
    """Return the wave-logs base directory."""
    d = os.environ.get("_WAVE_LOGS_DIR")
    if not d:
        raise RuntimeError("_WAVE_LOGS_DIR is not set — source set_env.sh before starting the GUI")
    return Path(d)


def _unit_state_path() -> Path:
    """Return path to the persistent unit-state.yaml."""
    d = os.environ.get("_DYNAMIC_DIR")
    if not d:
        raise RuntimeError("_DYNAMIC_DIR is not set — source set_env.sh before starting the GUI")
    state_dir = Path(d) / "unit-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "unit-state.yaml"


def _read_unit_state() -> "dict[str, dict]":
    """Read unit-state.yaml and return the units dict.  Returns {} on any error.

    PyYAML parses bare ISO-8601 timestamps as datetime.datetime objects.  Normalise
    all timestamp fields to ISO-8601 strings so callers can safely compare them.
    """
    _TS_FIELDS = {"last_apply_at", "last_validated_at"}
    try:
        p = _unit_state_path()
        if not p.exists():
            return {}
        raw = yaml.safe_load(p.read_text()) or {}
        units = raw.get("units", {}) or {}
        for entry in units.values():
            if not isinstance(entry, dict):
                continue
            for field in _TS_FIELDS:
                val = entry.get(field)
                if isinstance(val, _datetime):
                    # datetime from yaml.safe_load — convert back to ISO-8601 string
                    entry[field] = val.strftime("%Y-%m-%dT%H:%M:%SZ")
        return units
    except Exception as exc:
        _gui_log(f"[unit-state] read error: {exc}")
        return {}


def _write_unit_state(updates: "dict[str, dict]") -> None:
    """Atomically merge `updates` into unit-state.yaml.

    Each value in `updates` is a dict of fields to set for that unit path.
    Existing fields not present in the update dict are preserved (deep per-unit merge).
    """
    import os as _os
    p = _unit_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".yaml.tmp")
    with _unit_state_lock:
        try:
            raw: dict = yaml.safe_load(p.read_text()) or {} if p.exists() else {}
        except Exception:
            raw = {}
        raw["schema_version"] = 2
        units: dict = raw.setdefault("units", {})
        for unit_path, fields in updates.items():
            entry = units.setdefault(unit_path, {})
            entry.update(fields)
        try:
            tmp.write_text(yaml.dump(raw, allow_unicode=True, default_flow_style=False))
            _os.rename(str(tmp), str(p))
        except Exception as exc:
            _gui_log(f"[unit-state] write error: {exc}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


def _schedule_config_write(menu_data: dict) -> None:
    """Debounce config writes: cancel any pending timer, schedule a new one 800 ms out."""
    global _save_timer
    if _save_timer is not None:
        _save_timer.cancel()
    t = _threading.Timer(0.8, _do_write_menu, args=(menu_data,))
    t.daemon = True
    _save_timer = t
    t.start()


def _load_state() -> dict:
    """Load state/current.yaml (runtime UI state).

    Falls back to state/defaults.yaml when current.yaml is absent (first boot,
    fresh clone, wiped container).  A corrupt current.yaml still returns {}.
    """
    state_file = STATE_DIR / "current.yaml"
    defaults_file = STATE_DIR / "defaults.yaml"
    if not state_file.exists() and defaults_file.exists():
        try:
            return yaml.safe_load(defaults_file.read_text()) or {}
        except Exception:
            return {}
    try:
        return yaml.safe_load(state_file.read_text()) or {}
    except Exception:
        return {}


def _infra_path(config: dict) -> Path:
    # Explicit override in config takes precedence, resolved relative to _STACK_DIR.
    rel = config.get("config", {}).get("infra_path")
    if rel:
        return (_STACK_DIR / rel).resolve()
    return _STACK_DIR / "infra"


def _fmt_duration(seconds: float, show_seconds: bool = True) -> str:
    """Format a duration, suppressing leading zero components while keeping alignment.

    Hours accumulate beyond 24 (no days field).
    Duration (show_seconds=True):  "51h-04m-07s" / "   04m-07s" / "      07s"
    Age     (show_seconds=False):  "51h-04m"     / "   04m"
    Zero components are replaced with spaces so columns stay aligned.
    The last field (seconds for duration, minutes for age) is always shown.
    """
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)

    _ = "\u00a0"  # non-breaking space — HTML won't collapse these
    if show_seconds:
        # widths: "00h-" = 4, "00m-" = 4, "00s" = 3  → max total 11
        h_part = f"{h:>2}h-".replace(" ", _) if h else _ * 4
        m_part = f"{m:02d}m-" if (m or h) else _ * 4
        return f"{h_part}{m_part}{sec:02d}s"
    else:
        # widths: "00h-" = 4, "00m" = 3  → max total 7
        h_part = f"{h:>2}h-".replace(" ", _) if h else _ * 4
        return f"{h_part}{m:02d}m"


def _build_unlock_file_cmd(node_path: str, mode: str = "unit") -> str:
    """Return a shell command that directly removes backend lock file(s) for node_path.

    mode="unit"      — removes one lock file at exactly node_path/default.tflock
    mode="recursive" — finds and removes all default.tflock files under node_path/

    Reads the backend type and config from _STACK_CONFIG at call time.
    Supported backends: gcs, s3 (including S3-compatible), local.
    """
    stack = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
    backend = stack.get("backend", {})
    btype = backend.get("type", "local")
    bcfg  = backend.get("config", {})

    if btype == "gcs":
        bucket = bcfg.get("bucket", "")
        if mode == "recursive":
            prefix_uri = f"gs://{bucket}/{node_path}/"
            return (
                f"echo '=== Scanning for GCS lock files under {prefix_uri} ===' && "
                f"LOCKS=$(gsutil ls -r \"{prefix_uri}\" 2>/dev/null | grep 'default\\.tflock$') && "
                f"if [ -z \"$LOCKS\" ]; then "
                f"  echo 'No lock files found.'; "
                f"else "
                f"  echo \"Found:\" && echo \"$LOCKS\" && "
                f"  echo \"$LOCKS\" | xargs -r gsutil -m rm && "
                f"  echo '=== Done ==='; "
                f"fi"
            )
        else:
            lock_uri = f"gs://{bucket}/{node_path}/default.tflock"
            return (
                f"echo '=== Removing GCS lock file ===' && "
                f"echo '{lock_uri}' && "
                f"gsutil stat {lock_uri} 2>/dev/null "
                f"  && gsutil rm {lock_uri} && echo '=== Done ===' "
                f"  || echo 'Lock file not found — already unlocked.'"
            )

    elif btype == "s3":
        bucket     = bcfg.get("bucket", "")
        endpoint   = bcfg.get("endpoint", "")
        key_prefix = bcfg.get("key", bcfg.get("prefix", ""))
        base_key   = f"{key_prefix}/{node_path}" if key_prefix else node_path
        ep_flag    = f"--endpoint-url {endpoint}" if endpoint else ""
        if mode == "recursive":
            return (
                f"echo '=== Scanning for S3 lock files under s3://{bucket}/{base_key}/ ===' && "
                f"LOCKS=$(aws s3 ls --recursive s3://{bucket}/{base_key}/ {ep_flag} 2>/dev/null"
                f"  | awk '{{print $4}}' | grep 'default\\.tflock$') && "
                f"if [ -z \"$LOCKS\" ]; then "
                f"  echo 'No lock files found.'; "
                f"else "
                f"  echo \"Found:\" && echo \"$LOCKS\" && "
                f"  echo \"$LOCKS\" | xargs -r -I{{}} aws s3 rm s3://{bucket}/{{}} {ep_flag} && "
                f"  echo '=== Done ==='; "
                f"fi"
            )
        else:
            lock_key = f"{base_key}/default.tflock"
            return (
                f"echo '=== Removing S3 lock file ===' && "
                f"echo 'Key: s3://{bucket}/{lock_key}' && "
                f"aws s3 rm s3://{bucket}/{lock_key} {ep_flag} "
                f"  && echo '=== Done ===' || echo 'Lock file not found or delete failed.'"
            )

    else:  # local
        if mode == "recursive":
            config = _load_config()
            infra_dir = _infra_path(config) / node_path
            return (
                f"echo '=== Scanning for local lock files under {infra_dir} ===' && "
                f"LOCKS=$(find \"{infra_dir}\" -name '.terraform.tfstate.lock.info' 2>/dev/null) && "
                f"if [ -z \"$LOCKS\" ]; then "
                f"  echo 'No lock files found.'; "
                f"else "
                f"  echo \"Found:\" && echo \"$LOCKS\" && "
                f"  echo \"$LOCKS\" | xargs -r rm && "
                f"  echo '=== Done ==='; "
                f"fi"
            )
        else:
            return (
                "echo '=== Removing local lock file ===' && "
                "LOCK_FILE=$(find .terragrunt-cache -name '.terraform.tfstate.lock.info' 2>/dev/null | head -1) && "
                "if [ -n \"$LOCK_FILE\" ]; then "
                "  echo \"Removing: $LOCK_FILE\" && rm \"$LOCK_FILE\" && echo '=== Done ==='; "
                "else "
                "  echo 'Lock file not found — already unlocked.'; "
                "fi"
            )


# ---------------------------------------------------------------------------
# Terminal support
# ---------------------------------------------------------------------------
_BACKEND_PORT  = int(os.environ.get("HOMELAB_GUI_BACKEND_PORT",  "9000"))  # mirrors rxconfig.py
_FRONTEND_PORT = int(os.environ.get("HOMELAB_GUI_FRONTEND_PORT", "9080"))  # mirrors rxconfig.py


def _get_vm_ip() -> str:
    try:
        return _load_config().get("config", {}).get("vm_ip", "localhost")
    except Exception:
        return "localhost"


def _terminal_html(cwd: str, initial_cmd: str = "") -> str:
    """Return a self-contained HTML page for the embedded terminal panel."""
    safe_cwd = cwd.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'")
    safe_cmd = initial_cmd.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'")
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Shell — {cwd}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css"/>
<style>
  body {{
    margin: 0; padding: 0; background: #1e1e2e; display: flex;
    flex-direction: column; height: 100vh; overflow: hidden;
  }}
  #info {{
    font-family: monospace; font-size: 11px; color: #6b7280;
    padding: 4px 8px; background: #111; border-bottom: 1px solid #333;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    flex-shrink: 0;
  }}
  #terminal {{ flex: 1; overflow: hidden; }}
</style>
</head>
<body>
<div id="info">$ bash &nbsp;·&nbsp; {cwd}</div>
<div id="terminal"></div>
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js"></script>
<script>
(function () {{
  const term = new Terminal({{
    cursorBlink: true,
    fontSize: 13,
    fontFamily: 'Menlo, Monaco, "Courier New", monospace',
    theme: {{ background: '#1e1e2e', foreground: '#cdd6f4' }},
  }});
  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(document.getElementById('terminal'));
  fitAddon.fit();

  const wsUrl = 'ws://' + window.location.host + '/ws/terminal?cwd=' +
                encodeURIComponent('{safe_cwd}') +
                ('{safe_cmd}' ? '&initial_cmd=' + encodeURIComponent('{safe_cmd}') : '');
  const ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';
  window._ws = ws;    // exposed for automated tests

  ws.onopen = function () {{
    const cols = term.cols, rows = term.rows;
    ws.send(JSON.stringify({{ type: 'resize', cols: cols, rows: rows }}));
  }};

  ws.onmessage = function (evt) {{
    if (typeof evt.data === 'string') {{
      term.write(evt.data);
    }} else {{
      term.write(new Uint8Array(evt.data));
    }}
  }};

  ws.onclose = function () {{
    term.write('\\r\\n\\x1b[31m[connection closed]\\x1b[0m\\r\\n');
  }};

  term.onData(function (data) {{
    if (ws.readyState === WebSocket.OPEN) ws.send(data);
  }});

  window.addEventListener('resize', function () {{
    fitAddon.fit();
    if (ws.readyState === WebSocket.OPEN) {{
      ws.send(JSON.stringify({{ type: 'resize', cols: term.cols, rows: term.rows }}));
    }}
  }});

  // Read terminal buffer as plain text — used by automated tests.
  window.getTerminalText = function () {{
    const buf = term.buffer.active;
    const lines = [];
    for (let i = 0; i < buf.length; i++) {{
      const line = buf.getLine(i);
      if (line) lines.push(line.translateToString(true).trimEnd());
    }}
    return lines.join('\\n');
  }};

  // ── Keyboard layout detection ────────────────────────────────────────────
  // Checks what the browser produces for a set of physical keys to identify
  // the active keyboard layout.  Results appear in the #info bar and console.
  (async function detectKeyboardLayout() {{
    const infoEl = document.getElementById('info');
    const baseText = infoEl.textContent;

    // Key probes: [KeyboardEvent.code, expected US char (no shift), expected US char (shift)]
    const probes = [
      ['Backquote', '`', '~'],
      ['Quote',     "'", '"'],
      ['Digit2',    '2', '@'],
    ];

    let layoutName = 'unknown';
    let mismatches = [];

    if (navigator.keyboard && navigator.keyboard.getLayoutMap) {{
      try {{
        const map = await navigator.keyboard.getLayoutMap();
        // Try to name the layout from the Backquote key value
        const bq = map.get('Backquote');
        if      (bq === '`') layoutName = 'US';
        else if (bq === '`') layoutName = 'US';  // same
        else                 layoutName = 'non-US (Backquote=' + bq + ')';

        for (const [code, usNoShift] of probes) {{
          const actual = map.get(code);
          if (actual !== undefined && actual !== usNoShift) {{
            mismatches.push(code + ':' + actual + '≠' + usNoShift);
          }}
        }}

        const detail = mismatches.length
          ? '⚠ ' + mismatches.join(' ')
          : '✓ matches US';
        const msg = 'kbd:' + layoutName + ' ' + detail;
        infoEl.textContent = baseText + '  ·  ' + msg;
        console.info('[keyboard-layout]', msg, Object.fromEntries(map));

        if (ws.readyState === WebSocket.OPEN) {{
          ws.send(JSON.stringify({{ type: 'keyboard_layout', layout: layoutName,
                                    map: Object.fromEntries(map) }}));
        }} else {{
          ws.addEventListener('open', function() {{
            ws.send(JSON.stringify({{ type: 'keyboard_layout', layout: layoutName,
                                      map: Object.fromEntries(map) }}));
          }}, {{ once: true }});
        }}
      }} catch(e) {{
        console.warn('[keyboard-layout] getLayoutMap failed:', e);
        infoEl.textContent = baseText + '  ·  kbd:detection-failed';
      }}
    }} else {{
      // Fallback: browser doesn't support Keyboard API — log a note
      console.info('[keyboard-layout] navigator.keyboard.getLayoutMap not available');
      infoEl.textContent = baseText + '  ·  kbd:api-unavailable';
    }}
  }})();
}})();
</script>
</body>
</html>"""


def _find_stack_configs() -> list[Path]:
    """Return all non-secrets engine config files, sorted for stable loading.

    New engine layout:
      _STACK_DIR/config/framework.yaml        — framework-level config (first)
      _STACK_DIR/infra/<pkg>/_config/<pkg>.yaml — per-package configs (alpha order)

    Falls back to de3-gui-pkg.yaml stack_config_path override if the above are absent.
    """
    framework = Path(os.environ['_FRAMEWORK_PKG_DIR']) / "_config" / "framework.yaml"
    infra_dir = _STACK_DIR / "infra"
    if framework.exists() or infra_dir.is_dir():
        pkg_configs = sorted(
            f for f in infra_dir.glob("*/_config/*.yaml")
            if "secrets" not in f.name
        )
        return ([framework] if framework.exists() else []) + pkg_configs
    try:
        config = _load_config()
        rel = config.get("config", {}).get("stack_config_path")
        if rel:
            p = (_STACK_DIR / rel).resolve()
            if p.exists():
                return [p]
    except Exception:
        pass
    return []


def _find_stack_config() -> Path | None:
    """Return the primary stack config path (framework.yaml or first result)."""
    files = _find_stack_configs()
    return files[0] if files else None


def _find_config_file_for_node(provider: str, node_path: str) -> "tuple[Path | None, bool]":
    """Find the package config file whose config_params best covers node_path.

    Searches each infra/<pkg>/_config/<pkg>.yaml for the longest config_params
    key that is a prefix of (or exactly matches) node_path.

    Returns (file, has_match).  has_match is True only when a real config_params
    entry was found; False means no entry exists in any file (fallback returned).
    """
    if not node_path:
        return _find_stack_config(), False
    best_file: "Path | None" = None
    best_depth = -1
    for cfg_path in _find_stack_configs():
        try:
            doc = yaml.safe_load(cfg_path.read_text()) or {}
            # Package configs have a single top-level key = package name
            pkg_key = next(
                (k for k in doc if k not in ("framework",) and "secrets" not in k),
                None,
            )
            if pkg_key is None:
                continue
            cfg = doc.get(pkg_key, {}) or {}
            for cp_key in (cfg.get("config_params") or {}):
                if node_path == cp_key or node_path.startswith(cp_key + "/"):
                    depth = len(cp_key.split("/"))
                    if depth > best_depth:
                        best_depth = depth
                        best_file = cfg_path
        except Exception:
            pass
    if best_file:
        return best_file, True
    return _find_stack_config(), False


def _find_source_config_file(provider: str, config_key: str) -> "Path | None":
    """Return the package config YAML that defines config_params[config_key].

    Searches infra/<pkg>/_config/<pkg>.yaml files for the first one that has
    the given config_params key.  Falls back to the primary config file.
    """
    if not config_key:
        return _find_stack_config()
    for path in _find_stack_configs():
        try:
            doc = yaml.safe_load(path.read_text()) or {}
            pkg_key = next(
                (k for k in doc if k not in ("framework",) and "secrets" not in k),
                None,
            )
            if pkg_key is None:
                continue
            cfg = doc.get(pkg_key, {}) or {}
            if config_key in (cfg.get("config_params") or {}):
                return path
        except Exception:
            pass
    return _find_stack_config()


# ---------------------------------------------------------------------------
# Stack config — loaded once at module import, NOT stored as a state var
# ---------------------------------------------------------------------------

_STACK_CONFIG: dict = {}
_STACK_CONFIG_KEY: str = "lab_stack"  # fixed sentinel for new engine layout


def _resolve_provider_inheritance(path: str, config_params: dict) -> str:
    """Resolve _provider for a path by walking ancestor config_params entries.

    Walks from the shortest ancestor to the full path; the most-specific
    ancestor that declares _provider wins.  Returns "null" if none found.
    """
    parts = path.split("/")
    resolved = "null"
    for length in range(1, len(parts) + 1):
        prefix = "/".join(parts[:length])
        entry = config_params.get(prefix)
        if isinstance(entry, dict) and "_provider" in entry:
            resolved = str(entry["_provider"])
    return resolved


def _load_stack_config():
    """Load engine config files and build a unified _STACK_CONFIG dict.

    New engine layout:
      config/framework.yaml            → framework config, ansible_inventory
      config/waves_ordering.yaml       → canonical wave order
      infra/<pkg>/_config/<pkg>.yaml   → per-package config_params + waves

    Synthesises the legacy ``providers.<provider>.config_params.<path>``
    structure so all downstream GUI code works without further changes.

    Also copies _region→region and _env→env for backward-compat with display
    and filter code that still reads the unprefixed key names.
    """
    global _STACK_CONFIG, _STACK_CONFIG_KEY
    fw = _STACK_DIR / "config" / "framework.yaml"
    _gui_log(f"[homelab_gui] _STACK_DIR={_STACK_DIR}  exists={_STACK_DIR.exists()}  framework={fw.exists()}")
    paths = _find_stack_configs()
    if not paths:
        _gui_log(f"[homelab_gui] WARNING: no stack config files found — infra/waves will be empty")
        return

    merged_providers: dict[str, dict] = {}
    framework_cfg: dict = {}
    all_waves_by_name: dict[str, dict] = {}

    # --- 1. Load framework.yaml for global settings ---
    framework_path = _STACK_DIR / "config" / "framework.yaml"
    if framework_path.exists():
        try:
            framework_cfg = yaml.safe_load(framework_path.read_text()) or {}
        except Exception as e:
            _gui_log(f"[homelab_gui] Warning: could not load framework.yaml: {e}")

    # --- 2. Load wave ordering (defines display order + _skip_on_wave_run) ---
    waves_ordering_path = Path(os.environ['_FRAMEWORK_PKG_DIR']) / "_config" / "waves_ordering.yaml"
    wave_order: list[str] = []
    wave_skip_on_wave_run: dict[str, bool] = {}
    if waves_ordering_path.exists():
        try:
            wo_doc = yaml.safe_load(waves_ordering_path.read_text()) or {}
            for entry in wo_doc.get("waves_ordering", []):
                if isinstance(entry, dict):
                    name = entry.get("name", "")
                    if name:
                        wave_order.append(name)
                        if entry.get("_skip_on_wave_run"):
                            wave_skip_on_wave_run[name] = True
                elif isinstance(entry, str) and entry:
                    wave_order.append(entry)
        except Exception as e:
            _gui_log(f"[homelab_gui] Warning: could not load waves_ordering.yaml: {e}")

    # --- 3. Load per-package configs ---
    pkg_count = 0
    for path in paths:
        if path.name == "framework.yaml":
            continue
        try:
            doc = yaml.safe_load(path.read_text()) or {}
            # Package config has a single top-level key = the package name
            pkg_key = next(
                (k for k in doc if k != "framework" and "secrets" not in k),
                None,
            )
            if pkg_key is None:
                continue
            pkg_cfg = doc.get(pkg_key, {}) or {}
            pkg_count += 1

            # 3a. Collect wave details from this package's waves: section
            for wave_entry in pkg_cfg.get("waves", []):
                if not isinstance(wave_entry, dict):
                    continue
                wname = wave_entry.get("name", "")
                if not wname:
                    continue
                if wname not in all_waves_by_name:
                    all_waves_by_name[wname] = dict(wave_entry)
                else:
                    # Merge extra keys (description, playbooks) without overwriting
                    for k, v in wave_entry.items():
                        all_waves_by_name[wname].setdefault(k, v)

            # 3b. Process config_params → synthesise providers structure
            raw_cp: dict = pkg_cfg.get("config_params") or {}
            # Sort shortest→longest so ancestor _provider is visible when resolving children
            for cp_path in sorted(raw_cp.keys(), key=lambda p: len(p.split("/"))):
                params = raw_cp.get(cp_path)
                if not isinstance(params, dict):
                    continue
                # Resolve provider via ancestor inheritance within this package
                provider = _resolve_provider_inheritance(cp_path, raw_cp)
                # Build backward-compat param dict: copy _region→region, _env→env
                compat_params = dict(params)
                if "_region" in params and "region" not in params:
                    compat_params["region"] = params["_region"]
                if "_env" in params and "env" not in params:
                    compat_params["env"] = params["_env"]
                # Place under providers[provider].config_params[path]
                prov_entry = merged_providers.setdefault(provider, {"config_params": {}})
                prov_entry.setdefault("config_params", {})[cp_path] = compat_params

        except Exception as e:
            _gui_log(f"[homelab_gui] Warning: could not load package config {path}: {e}")

    # --- 4. Build ordered waves list ---
    # waves_ordering.yaml defines order; package waves: sections supply details
    seen: set[str] = set()
    waves: list[dict] = []
    for name in wave_order:
        if name in seen:
            continue
        seen.add(name)
        entry = dict(all_waves_by_name.get(name, {"name": name}))
        entry["name"] = name
        if wave_skip_on_wave_run.get(name):
            entry["skip_on_wave_run"] = True
        waves.append(entry)
    # Append any waves declared in packages but absent from waves_ordering.yaml
    for name, entry in all_waves_by_name.items():
        if name not in seen:
            waves.append(dict(entry))

    # --- 5. Store unified config ---
    fw_section   = (framework_cfg.get("framework") or {})
    ansible_inv  = fw_section.get("ansible_inventory", {})
    backend_cfg  = fw_section.get("backend", {})
    _STACK_CONFIG = {
        _STACK_CONFIG_KEY: {
            "providers":       merged_providers,
            "waves":           waves,
            "ansible_inventory": ansible_inv,
            "backend":         backend_cfg,
        }
    }
    _gui_log(
        f"[homelab_gui] Stack config loaded: {pkg_count} package(s), "
        f"{len(waves)} wave(s), providers: {list(merged_providers)}"
    )


_load_stack_config()

# ---------------------------------------------------------------------------
# SOPS secrets — lazy-loaded, never written to state/logs/browser
# ---------------------------------------------------------------------------
_SOPS_SECRETS_CACHE: dict = {}
_SOPS_SECRETS_LOADED: bool = False


def _find_sops_secrets_files() -> "list[Path]":
    """Return all per-package secrets files: infra/<pkg>/_config/<pkg>_secrets.sops.yaml."""
    infra_dir = _STACK_DIR / "infra"
    if not infra_dir.exists():
        return []
    return sorted(infra_dir.glob("*/_config/*_secrets.sops.yaml"))


def _find_sops_secrets_file() -> "Path | None":
    """Return the first secrets file found (compat shim for single-file callers)."""
    files = _find_sops_secrets_files()
    return files[0] if files else None


def _load_sops_secrets() -> dict:
    """Decrypt and merge all per-package SOPS secrets (cached after first call).

    Merges all infra/<pkg>/_config/<pkg>_secrets.sops.yaml files into a single
    dict.  Each file's top-level key is kept as-is so callers that key on
    <pkg>_secrets can find them.  Also synthesises a legacy
    'stack_secrets' entry (providers merged across all packages)
    for backward-compat with _get_resolved_secret_params / _get_provider_level_secrets.
    """
    global _SOPS_SECRETS_CACHE, _SOPS_SECRETS_LOADED
    if _SOPS_SECRETS_LOADED:
        return _SOPS_SECRETS_CACHE
    _SOPS_SECRETS_LOADED = True
    import subprocess as _sp
    merged_providers: dict = {}
    for p in _find_sops_secrets_files():
        try:
            res = _sp.run(["sops", "--decrypt", str(p)], capture_output=True, text=True)
            if res.returncode != 0:
                _gui_log(f"[homelab_gui] SOPS decrypt failed for {p.name}: "
                      f"{res.stderr.strip()[:200]}")
                continue
            pkg_secrets = yaml.safe_load(res.stdout) or {}
            _SOPS_SECRETS_CACHE.update(pkg_secrets)
            # Merge into legacy providers compat structure
            for top_val in pkg_secrets.values():
                if not isinstance(top_val, dict):
                    continue
                # New engine format: config_params at top level (no providers: wrapper)
                raw_cp = top_val.get("config_params") or {}
                if raw_cp:
                    for cp_path in sorted(raw_cp.keys(), key=lambda p: len(p.split("/"))):
                        params = raw_cp.get(cp_path)
                        if not isinstance(params, dict):
                            continue
                        provider = _resolve_provider_inheritance(cp_path, raw_cp)
                        prov_entry = merged_providers.setdefault(provider, {"config_params": {}})
                        prov_entry.setdefault("config_params", {})[cp_path] = params
                else:
                    # Legacy fallback: old-style providers: structure
                    for prov_name, prov_data in (top_val.get("providers") or {}).items():
                        if not isinstance(prov_data, dict):
                            continue
                        prov_entry = merged_providers.setdefault(prov_name, {"config_params": {}})
                        existing_cp = prov_entry.setdefault("config_params", {})
                        for cp_key, cp_val in (prov_data.get("config_params") or {}).items():
                            existing_cp[cp_key] = cp_val
                        for k, v in prov_data.items():
                            if k != "config_params":
                                prov_entry.setdefault(k, v)
        except Exception as e:
            _gui_log(f"[homelab_gui] SOPS unavailable for {p.name}: {e}")
    # Synthesise legacy key so _get_resolved_secret_params still works
    _SOPS_SECRETS_CACHE["stack_secrets"] = {"providers": merged_providers}
    return _SOPS_SECRETS_CACHE


# ---------------------------------------------------------------------------
# Per-package config YAML write helpers
# ---------------------------------------------------------------------------

def _pkg_config_yaml_for_path(node_path: str) -> "Path | None":
    """Return the package config YAML path for a given infra node path.

    The package name is always the first segment of the node path
    (e.g. 'example-pkg' from 'example-pkg/_stack/proxmox/...').
    Returns None if the file cannot be determined or does not exist.
    """
    if not node_path:
        return None
    pkg = node_path.split("/")[0]
    if not pkg:
        return None
    p = _STACK_DIR / "infra" / pkg / "_config" / f"{pkg}.yaml"
    return p if p.exists() else None


def _write_pkg_config_param(node_path: str, params: dict) -> bool:
    """Write params into <pkg>.yaml under config_params[node_path].

    Creates the config_params entry if absent.  Returns True on success.
    """
    yaml_path = _pkg_config_yaml_for_path(node_path)
    if not yaml_path:
        return False
    pkg = node_path.split("/")[0]
    try:
        doc = yaml.safe_load(yaml_path.read_text()) or {}
        (doc.setdefault(pkg, {}).setdefault("config_params", {}))[node_path] = params
        yaml_path.write_text(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
        return True
    except Exception as e:
        _gui_log(f"[homelab_gui] Warning: could not write config_params for {node_path}: {e}")
        return False


def _delete_pkg_config_param(node_path: str) -> bool:
    """Remove config_params[node_path] from the owning package YAML.

    Returns True if a key was removed, False otherwise.
    """
    yaml_path = _pkg_config_yaml_for_path(node_path)
    if not yaml_path:
        return False
    pkg = node_path.split("/")[0]
    try:
        doc = yaml.safe_load(yaml_path.read_text()) or {}
        cp = doc.get(pkg, {}).get("config_params", {})
        if node_path in cp:
            del cp[node_path]
            yaml_path.write_text(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
            return True
        return False
    except Exception as e:
        _gui_log(f"[homelab_gui] Warning: could not delete config_params for {node_path}: {e}")
        return False


# ---------------------------------------------------------------------------
# Rename helpers — update config_params keys across all YAML and SOPS files
# ---------------------------------------------------------------------------

def _rename_in_config_params_dict(cp: dict, old_path: str, new_path: str) -> bool:
    """Rename all keys in a config_params dict that match old_path (exact or prefix).

    Modifies cp in-place.  Returns True if any key was changed.
    """
    keys_to_rename = [k for k in cp if k == old_path or k.startswith(old_path + "/")]
    for old_key in keys_to_rename:
        new_key = new_path + old_key[len(old_path):]
        cp[new_key] = cp.pop(old_key)
    return bool(keys_to_rename)


def _rename_config_keys_in_yaml_files(old_path: str, new_path: str) -> int:
    """Scan all non-SOPS YAML files under infra/ and rename config_params keys.

    Handles both:
      {pkg: {config_params: {...}}}                              (flat / new format)
      {pkg: {providers: {prov: {config_params: {...}}}}}         (legacy format)

    Returns the number of files that were modified.
    """
    infra_dir = _STACK_DIR / "infra"
    if not infra_dir.exists():
        return 0
    modified = 0
    for yaml_file in sorted(infra_dir.glob("*/_config/*.yaml")):
        if ".sops." in yaml_file.name:
            continue
        try:
            doc = yaml.safe_load(yaml_file.read_text())
            if not isinstance(doc, dict):
                continue
            changed = False
            for top_val in doc.values():
                if not isinstance(top_val, dict):
                    continue
                # Flat format: pkg.config_params
                cp = top_val.get("config_params")
                if isinstance(cp, dict):
                    changed |= _rename_in_config_params_dict(cp, old_path, new_path)
                # Legacy format: pkg.providers.<prov>.config_params
                for prov_val in (top_val.get("providers") or {}).values():
                    if not isinstance(prov_val, dict):
                        continue
                    cp2 = prov_val.get("config_params")
                    if isinstance(cp2, dict):
                        changed |= _rename_in_config_params_dict(cp2, old_path, new_path)
            if changed:
                yaml_file.write_text(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
                modified += 1
        except Exception as exc:
            _gui_log(f"[homelab_gui] rename: could not update {yaml_file}: {exc}")
    return modified


def _rename_config_keys_in_sops_file(sops_file: "Path", old_path: str, new_path: str) -> bool:
    """Decrypt sops_file, rename matching config_params keys, re-encrypt in place.

    The temp plaintext file is written into the same directory as sops_file so
    that the repo-root .sops.yaml creation rules apply when re-encrypting.

    Returns True if the file was modified.
    """
    import subprocess as _sp

    res = _sp.run(["sops", "--decrypt", str(sops_file)], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"sops --decrypt failed: {res.stderr.strip()[:300]}")

    plain = yaml.safe_load(res.stdout)
    if not isinstance(plain, dict):
        return False

    changed = False
    for top_val in plain.values():
        if not isinstance(top_val, dict):
            continue
        # Flat format
        cp = top_val.get("config_params")
        if isinstance(cp, dict):
            changed |= _rename_in_config_params_dict(cp, old_path, new_path)
        # Legacy providers format
        for prov_val in (top_val.get("providers") or {}).values():
            if not isinstance(prov_val, dict):
                continue
            cp2 = prov_val.get("config_params")
            if isinstance(cp2, dict):
                changed |= _rename_in_config_params_dict(cp2, old_path, new_path)

    if not changed:
        return False

    # Write plaintext to a temp file in the SAME directory so the .sops.yaml
    # path_regex matches it and SOPS knows which PGP keys to use.
    tmp_path = sops_file.parent / f"_tmp_rename_{sops_file.name}"
    try:
        tmp_path.write_text(yaml.dump(plain, default_flow_style=False, allow_unicode=True))
        enc_res = _sp.run(
            ["sops", "--encrypt", "--output", str(sops_file), str(tmp_path)],
            capture_output=True, text=True,
        )
        if enc_res.returncode != 0:
            raise RuntimeError(f"sops --encrypt failed: {enc_res.stderr.strip()[:300]}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    return True


# ---------------------------------------------------------------------------
# File-change helpers used by the background watcher
# ---------------------------------------------------------------------------

def _get_watched_mtimes() -> dict[str, float]:
    """Return {str(path): mtime} for all config files that should be watched."""
    result: dict[str, float] = {}
    for p in _find_stack_configs():
        try:
            result[str(p)] = p.stat().st_mtime
        except Exception:
            pass
    # Also watch waves_ordering.yaml separately (not in _find_stack_configs)
    wo = _STACK_DIR / "config" / "waves_ordering.yaml"
    if wo.exists():
        try:
            result[str(wo)] = wo.stat().st_mtime
        except Exception:
            pass
    for sops in _find_sops_secrets_files():
        try:
            result[str(sops)] = sops.stat().st_mtime
        except Exception:
            pass
    return result


def _get_resolved_secret_params(node_path: str) -> dict[str, str]:
    """Prefix-match inheritance over SOPS secret config_params (same logic as public params)."""
    if not node_path:
        return {}
    secrets = _load_sops_secrets()
    cfg = secrets.get("stack_secrets", {})
    providers = cfg.get("providers", {}) or {}
    result: dict[str, str] = {}
    for provider_data in providers.values():
        if not isinstance(provider_data, dict):
            continue
        config_params = provider_data.get("config_params") or {}
        for key in sorted(config_params.keys()):
            if node_path == key or node_path.startswith(key + "/"):
                params = config_params[key]
                if isinstance(params, dict):
                    for k, v in params.items():
                        result[k] = str(v) if v is not None else ""
    return result


def _get_provider_level_secrets(provider_name: str) -> dict[str, str]:
    """Return top-level scalar fields from SOPS providers.<provider_name>.

    Excludes 'config_params' and any nested dicts/lists.
    Used to surface provider-wide credentials like admin_password that are
    not nested under config_params path prefixes.
    """
    if not provider_name:
        return {}
    secrets = _load_sops_secrets()
    cfg = secrets.get("stack_secrets", {})
    provider_data = (cfg.get("providers", {}) or {}).get(provider_name, {})
    if not isinstance(provider_data, dict):
        return {}
    result: dict[str, str] = {}
    for k, v in provider_data.items():
        if k == "config_params" or isinstance(v, (dict, list)):
            continue
        result[k] = str(v) if v is not None else ""
    return result


# Populated by _init_path_param_maps(); rebuilt when stack config or infra changes.
_PATH_TO_REGION_CACHE: dict[str, str]        = {}   # full infra path → region value
_PATH_TO_ENV_CACHE:    dict[str, str]        = {}   # full infra path → env value
_PATH_TO_WAVE_CACHE:   dict[str, str]        = {}   # full infra path → _wave value
_PATH_TO_ROLES_CACHE:  dict[str, list[str]]  = {}   # full infra path → accumulated role tags


def _build_path_param_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, list[str]]]:
    """Derive region/env/_wave/roles for every infra node from config_params in the stack config.

    For each node path, walks all config_params entries (across all providers) from
    most-general prefix to most-specific; the last matching value wins (override
    semantics, same as _get_unit_params_flat), except additional_tags which uses
    union semantics (all matching ancestor tags are accumulated).

    Returns (path_to_region, path_to_env, path_to_wave, path_to_roles) using the
    full provider-inclusive path as key. Nodes with no value in any ancestor are
    absent from the maps (treated as unfiltered — always shown regardless of active filter).
    """
    if not _STACK_CONFIG or not _ALL_NODES_CACHE:
        return {}, {}, {}, {}
    cfg = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
    providers_cfg = cfg.get("providers", {}) or {}

    # Collect (prefix, params) across all providers; sort shortest→longest so more
    # specific prefixes override more general ones during the node walk below.
    all_prefixes: list[tuple[str, dict]] = []
    for prov_name, prov_data in providers_cfg.items():
        if not isinstance(prov_data, dict):
            continue
        for prefix, params in (prov_data.get("config_params") or {}).items():
            if isinstance(params, dict):
                all_prefixes.append((prefix, params))
    all_prefixes.sort(key=lambda t: len(t[0].split("/")))

    path_to_region: dict[str, str]        = {}
    path_to_env:    dict[str, str]        = {}
    path_to_wave:   dict[str, str]        = {}
    path_to_roles:  dict[str, list[str]]  = {}

    for node in _ALL_NODES_CACHE:
        node_path = node["path"]
        region = ""
        env    = ""
        wave   = ""
        roles: list[str] = []
        for prefix, params in all_prefixes:
            if node_path == prefix or node_path.startswith(prefix + "/"):
                if "region" in params:
                    region = str(params["region"])
                if "env" in params:
                    env = str(params["env"])
                if "_wave" in params:
                    wave = str(params["_wave"])
                raw_tags = params.get("additional_tags", [])
                if isinstance(raw_tags, list):
                    for t in raw_tags:
                        if isinstance(t, str) and t.startswith("role_") and t not in roles:
                            roles.append(t)
        if region:
            path_to_region[node_path] = region
        if env:
            path_to_env[node_path] = env
        if wave:
            path_to_wave[node_path] = wave
        if roles:
            path_to_roles[node_path] = roles

    return path_to_region, path_to_env, path_to_wave, path_to_roles


def _init_path_param_maps() -> None:
    global _PATH_TO_REGION_CACHE, _PATH_TO_ENV_CACHE, _PATH_TO_WAVE_CACHE, _PATH_TO_ROLES_CACHE
    _PATH_TO_REGION_CACHE, _PATH_TO_ENV_CACHE, _PATH_TO_WAVE_CACHE, _PATH_TO_ROLES_CACHE = _build_path_param_maps()
    # Build wave name → 1-based number from config declaration order
    cfg_waves = (_STACK_CONFIG.get(_STACK_CONFIG_KEY) or {}).get("waves") or []
    wave_name_to_num: dict[str, str] = {}
    for i, entry in enumerate(cfg_waves, 1):
        name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
        if name:
            wave_name_to_num[name] = str(i)
    # Stamp every cached node with its wave number string
    for node in _ALL_NODES_CACHE:
        wave_name = _PATH_TO_WAVE_CACHE.get(node["path"], "")
        node["wave_num_str"] = wave_name_to_num.get(wave_name, "") if wave_name else ""


def _build_initial_wave_filters() -> dict:
    """Build the wave_filters dict with all known wave names set to True.

    Includes waves from both sources the waves table can show:
      1. Declared waves in the stack config (may have no units assigned yet)
      2. _wave values in config_params (_PATH_TO_WAVE_CACHE)
    Without this union, config-declared waves that have no units are missing
    from wave_filters and always default to True (checked), making them
    impossible to uncheck via hide_all / solo_wave / etc.
    """
    cfg_waves = (_STACK_CONFIG.get(_STACK_CONFIG_KEY) or {}).get("waves") or []
    cfg_names = {
        (w.get("name") if isinstance(w, dict) else str(w))
        for w in cfg_waves
    } - {None, ""}
    all_names = cfg_names | set(_PATH_TO_WAVE_CACHE.values())
    return {"_none": True, **{v: True for v in all_names}}


# ---------------------------------------------------------------------------
# Provider actions config — loaded from de3-gui-pkg.yaml under provider_actions:
# ---------------------------------------------------------------------------

_PROVIDER_ACTIONS_CACHE: dict = {}

def _load_provider_actions() -> dict:
    """Load and return the provider_actions dict from _config/de3-gui-pkg.yaml (cached)."""
    global _PROVIDER_ACTIONS_CACHE
    if _PROVIDER_ACTIONS_CACHE:
        return _PROVIDER_ACTIONS_CACHE
    try:
        _PROVIDER_ACTIONS_CACHE = _load_config().get("provider_actions", {})
    except Exception as e:
        _gui_log(f"[homelab_gui] Warning: could not load provider_actions from de3-gui-pkg.yaml: {e}")
        _PROVIDER_ACTIONS_CACHE = {}
    return _PROVIDER_ACTIONS_CACHE


def _get_resolved_params(node_path: str) -> dict[str, str]:
    """
    Return a flat {key: str_value} dict for node_path by walking ALL providers'
    config_params from root → most-specific.  More-specific ancestor keys win.
    Values are str-coerced via _fmt_yaml to match what the display panel shows.
    """
    if not node_path or not _STACK_CONFIG:
        return {}
    cfg = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
    providers = cfg.get("providers", {}) or {}
    result: dict[str, str] = {}
    for provider_data in providers.values():
        if not isinstance(provider_data, dict):
            continue
        config_params = provider_data.get("config_params") or {}
        for key in sorted(config_params.keys()):
            if node_path == key or node_path.startswith(key + "/"):
                params = config_params[key]
                if isinstance(params, dict):
                    for k, v in params.items():
                        fmt_v, _ = _fmt_yaml(v)
                        result[k] = fmt_v
    return result


def _get_node_roles(node_path: str) -> set[str]:
    """Return the full set of role tags accumulated from all ancestor config_params.

    Scans every provider's config_params for ``additional_tags`` lists that
    cover node_path (exact or prefix match) and unions all tags found.
    """
    if not node_path or not _STACK_CONFIG:
        return set()
    cfg = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
    providers = cfg.get("providers", {}) or {}
    tags: set[str] = set()
    for provider_data in providers.values():
        if not isinstance(provider_data, dict):
            continue
        config_params = provider_data.get("config_params") or {}
        for key, params in config_params.items():
            if not isinstance(params, dict):
                continue
            if node_path != key and not node_path.startswith(key + "/"):
                continue
            raw_tags = params.get("additional_tags", [])
            if isinstance(raw_tags, list):
                tags.update(str(t) for t in raw_tags)
    return tags


def _get_node_actions(
    node_path: str,
    node_type: str,
    provider: str,
    has_terragrunt: bool,
) -> list[dict]:
    """Return resolved action dicts for node_path.  Each dict has:
        group, id, label, action_type, value

    Actions whose required params are missing from the resolved stack params
    are silently skipped.

    Filters supported in provider-actions.yaml:
      provider            — matches the node's provider
      node_type           — matches the node's type
      node_path_contains  — substring present in node_path
      requires_terragrunt — node has a terragrunt.hcl
      requires_role       — node has this tag in its accumulated additional_tags
    """
    cfg = _load_provider_actions()
    all_actions = cfg.get("actions", [])
    if not all_actions:
        return []

    resolved = _get_resolved_params(node_path)

    # Ansible inventory is the source of truth for ansible_host (live IP).
    # Override the stack-config value so URL templates use the correct address.
    inventory_hosts = _load_inventory_hosts()
    node_name = node_path.split("/")[-1]
    inv_vars = inventory_hosts.get(node_name) or {}
    if not inv_vars:
        # Try prefix match (same logic as _get_ssh_command)
        matches = {n: v for n, v in inventory_hosts.items() if n.startswith(node_name)}
        if len(matches) == 1:
            inv_vars = next(iter(matches.values()))
    if inv_vars.get("ansible_host"):
        resolved["ansible_host"] = str(inv_vars["ansible_host"])

    # Inject synthetic params always available in templates
    config = _load_config()
    infra_root = str(_infra_path(config))
    resolved["node_path"] = node_path
    resolved["infra_root"] = infra_root

    node_roles = _get_node_roles(node_path)

    result: list[dict] = []
    for action in all_actions:
        # Provider filter
        if action.get("provider", "") and action["provider"] != provider:
            continue
        # Node-type filter
        if action.get("node_type", "") and action["node_type"] != node_type:
            continue
        # Path substring filter
        if action.get("node_path_contains", "") and action["node_path_contains"] not in node_path:
            continue
        # Role filter
        if action.get("requires_role", "") and action["requires_role"] not in node_roles:
            continue
        # Terragrunt filter
        if action.get("requires_terragrunt") and not has_terragrunt:
            continue

        action_type = action.get("action_type", "clipboard")

        if action_type == "expand_collapse":
            result.append({
                "group": action["group"], "id": action["id"],
                "label": action["label"], "action_type": "expand_collapse", "value": "",
            })
            continue

        template_key = "url_template" if action_type == "url" else "command_template"
        template = action.get(template_key, "")
        if not template:
            continue

        # param_defaults are lower-priority than resolved stack params
        merged = {**action.get("param_defaults", {}), **resolved}

        # Skip if any required param is missing
        if any(not merged.get(p) for p in action.get("params", [])):
            continue

        try:
            value = template.format(**merged)
        except (KeyError, ValueError):
            continue

        # If the action declares an auth block, resolve credentials from SOPS secrets
        # and encode value as JSON {url, auth}.  Skip if credentials are missing.
        auth_block = action.get("auth")
        if auth_block:
            import json as _json
            # credential_path lets the auth block pull credentials from a different
            # node path (e.g. credentials stored under a 'null' provider config_params
            # key while the action itself is on a proxmox VM node).
            cred_lookup_path = auth_block.get("credential_path") or node_path
            secret_params = _get_resolved_secret_params(cred_lookup_path)
            # Also include provider-level secrets (e.g. maas.admin_password) that
            # are not nested under config_params path prefixes.
            provider_level = _get_provider_level_secrets(action.get("provider", ""))
            all_params = {**merged, **secret_params, **provider_level}
            username = all_params.get(auth_block.get("username_param", ""), "")
            password = all_params.get(auth_block.get("password_param", ""), "")
            if not username or not password:
                continue
            auth_dict: dict = {
                "scheme": auth_block.get("scheme", "digest"),
                "username": username,
                "password": password,
            }
            # Include form-specific selectors so they reach navigate_with_auth
            # and playwright_launcher without requiring extra plumbing.
            for _sel_key in ("username_selector", "password_selector",
                             "submit_selector", "success_url_contains"):
                if _sel_key in auth_block:
                    auth_dict[_sel_key] = auth_block[_sel_key]
            value = _json.dumps({"url": value, "auth": auth_dict})

        result.append({
            "group": action["group"], "id": action["id"],
            "label": action["label"], "action_type": action_type, "value": value,
        })
    return result


def _fmt_yaml(v) -> tuple[str, bool]:
    """
    Format a YAML value for display.
    Returns (text, is_multiline).
    Complex types (dict/list) are rendered as indented YAML block text.
    """
    if v is None:
        return "(not set)", False
    if isinstance(v, bool):
        return ("true" if v else "false"), False
    if isinstance(v, (int, float)):
        return str(v), False
    if isinstance(v, str):
        return v, ("\n" in v)
    try:
        s = yaml.dump(v, default_flow_style=False, allow_unicode=True).rstrip()
        return s, True
    except Exception:
        return str(v), False


# Identity param colour palette — assigned by position in the configured list.
_IDENTITY_COLOR_PALETTE: list[str] = [
    "#d97706",  # amber-600
    "#0d9488",  # teal-600
    "#4f46e5",  # indigo-600
    "#dc2626",  # red-600
    "#7c3aed",  # violet-600
    "#0891b2",  # cyan-600
    "#16a34a",  # green-600
]

# Special "identity" params shown first, in order, with distinct colours.
# Loaded from _config/de3-gui-pkg.yaml → de3-gui-pkg.unit_params.identity_params at import time.
def _load_identity_params() -> tuple[dict[str, int], dict[str, str]]:
    try:
        cfg = _load_config()
        keys: list[str] = cfg.get("unit_params", {}).get("identity_params", [])
        if not keys:
            keys = ["provider", "env", "region"]
    except Exception:
        keys = ["provider", "env", "region"]
    order  = {k: i for i, k in enumerate(keys)}
    colors = {k: _IDENTITY_COLOR_PALETTE[i % len(_IDENTITY_COLOR_PALETTE)]
              for i, k in enumerate(keys)}
    return order, colors

_SPECIAL_KEY_ORDER, _SPECIAL_KEY_COLORS = _load_identity_params()


def _load_app_title() -> str:
    """Read config.app_title from de3-gui-pkg.yaml; falls back to 'D.E. GUI'."""
    try:
        return _load_config().get("config", {}).get("app_title", "D.E. GUI") or "D.E. GUI"
    except Exception:
        return "D.E. GUI"


_APP_TITLE: str = _load_app_title()


_FILE_VIEWER_EDITOR_DEFAULTS: list[dict] = [
    {"id": "embedded-editor", "label": "Embedded Editor", "type": "embedded"},
    {"id": "vscode",   "label": "VS Code",  "type": "background_cmd", "cmd": "code {file_path}"},
    {"id": "pycharm",  "label": "PyCharm",  "type": "background_cmd", "cmd": "pycharm {file_path}"},
    {"id": "nvim",     "label": "nvim",     "type": "terminal_cmd",   "cmd": "nvim {file_path}"},
    {"id": "nano",     "label": "nano",     "type": "terminal_cmd",   "cmd": "nano {file_path}"},
    {"id": "hx",       "label": "Helix",    "type": "terminal_cmd",   "cmd": "hx {file_path}"},
]


def _load_file_viewer_editors() -> list[dict]:
    """Load editor definitions from de3-gui-pkg.yaml file_viewer.editors."""
    try:
        cfg = _load_config()
        editors = cfg.get("file_viewer", {}).get("editors", [])
        if editors:
            return editors
    except Exception:
        pass
    return _FILE_VIEWER_EDITOR_DEFAULTS


_FILE_VIEWER_EDITORS: list[dict] = _load_file_viewer_editors()

# Default for the "wrap node path in quotes" search toggle — configurable in _config/de3-gui-pkg.yaml
# under file_viewer.config_data_quote_path (bool, default false).
_DEFAULT_CONFIG_DATA_QUOTE_PATH: bool = bool(
    _load_config().get("file_viewer", {}).get("config_data_quote_path", False)
)

# Seconds a wave log must have been modified within to trigger the recent-wave highlight.
# Configurable in _config/de3-gui-pkg.yaml under config.wave_recent_highlight_secs (default: 30).
_WAVE_RECENT_HIGHLIGHT_SECS: int = int(
    _load_config().get("config", {}).get("wave_recent_highlight_secs", 30)
)

# Milliseconds between wave-status poll ticks (setInterval in the browser).
# Configurable in _config/de3-gui-pkg.yaml under config.wave_poll_interval_ms (default: 10000).
_WAVE_POLL_INTERVAL_MS: int = int(
    _load_config().get("config", {}).get("wave_poll_interval_ms", 10000)
)

# Maximum zoom level (%) for the fw-repos Mermaid diagram.
# Configurable in _config/de3-gui-pkg.yaml under config.fw_repos_zoom_max (default: 1600).
_FW_REPOS_ZOOM_MAX: int = int(
    _load_config().get("config", {}).get("fw_repos_zoom_max", 1600)
)

# Auto-preview in refactor panel: trigger Preview automatically when destination is set.
# Configurable via config.refactor_auto_preview / refactor_auto_preview_delay_ms.
_REFACTOR_AUTO_PREVIEW: bool = bool(
    _load_config().get("config", {}).get("refactor_auto_preview", True)
)
_REFACTOR_AUTO_PREVIEW_DELAY_MS: int = int(
    _load_config().get("config", {}).get("refactor_auto_preview_delay_ms", 2000)
)

# Shell command run by "Tail wave log" in the Waves panel.
# Configured via config.wave_tail_cmd in _config/de3-gui-pkg.yaml.
_WAVE_TAIL_CMD: str = (
    _load_config().get("config", {}).get("wave_tail_cmd", "").strip()
)


# Palette for underscore-prefixed keys — each prefix group (_foo_*) gets a stable colour.
# Colours chosen to be readable on white and distinct from the special-key colours above.
_UNDERSCORE_COLOR_PALETTE: list[str] = [
    "#0891b2",  # cyan-600
    "#16a34a",  # green-600
    "#dc2626",  # red-600
    "#9333ea",  # purple-600
    "#db2777",  # pink-600
    "#2563eb",  # blue-600
    "#ea580c",  # orange-600
    "#0f766e",  # teal-700
    "#be185d",  # pink-700
    "#1d4ed8",  # blue-700
    "#15803d",  # green-700
    "#b45309",  # amber-700
]
_REGULAR_KEY_COLOR = "var(--gui-text-muted)"  # gray-500 — unchanged baseline


def _underscore_key_color(key: str) -> str:
    """Return a stable colour for an underscore-prefixed key based on its prefix group.

    _foo_bar and _foo_baz share the same colour (group "foo").
    _baz gets group "baz".
    """
    suffix = key[1:]                   # strip leading _
    group  = suffix.split("_")[0]      # first segment = group name
    idx = int(hashlib.md5(group.encode()).hexdigest(), 16) % len(_UNDERSCORE_COLOR_PALETTE)
    return _UNDERSCORE_COLOR_PALETTE[idx]


def _param_sort_key(k: str) -> tuple:
    """Sort order: special keys → underscore keys → regular keys (alpha within each)."""
    if k in _SPECIAL_KEY_ORDER:
        return (0, _SPECIAL_KEY_ORDER[k], k)
    if k.startswith("_"):
        return (1, 0, k)
    return (2, 0, k)


def _get_unit_params_flat(node_path: str, is_merged: bool = False) -> list[dict]:
    """
    Return a flat list of display rows for *node_path*, preserving inheritance.

    Row types (field ``row_type``):
      "provider_header"  — coloured provider section divider
      "source_header"    — shows which ancestor path injected the following params
      "param"            — a single key → value pair

    In merged mode the provider segment is absent from node_path, so we
    reconstruct provider-specific lookup paths by inserting the provider name
    at depth-1 position before matching against config_params keys.
    """
    if not node_path or not _STACK_CONFIG:
        return []
    cfg = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
    providers = cfg.get("providers", {}) or {}
    result: list[dict] = []

    for provider_name, provider_data in providers.items():
        if not isinstance(provider_data, dict):
            continue
        config_params = provider_data.get("config_params") or {}

        # In merged mode, reconstruct provider-specific path from merged path.
        # Merged paths strip both "_stack" and provider; full path = <pkg>/_stack/<provider>/<rest>.
        if is_merged:
            parts = node_path.split("/")
            lookup_path = "/".join([parts[0], "_stack", provider_name] + parts[1:]) if parts else node_path
        else:
            lookup_path = node_path

        # Collect matching ancestor paths, root → most-specific
        sources: list[tuple[str, dict]] = []
        for key in sorted(config_params.keys()):
            if lookup_path == key or lookup_path.startswith(key + "/"):
                params = config_params[key]
                if isinstance(params, dict) and params:
                    sources.append((key, params))

        if not sources:
            continue

        accent = PROVIDER_ACCENT.get(provider_name, "#6B7280")
        result.append({
            "row_type": "provider_header",
            "provider": provider_name,
            "accent": accent,
            "source_label": "",
            "source_path": "",
            "source_display": "",
            "key": "",
            "key_color": "",
            "value": "",
            "is_multiline": False,
            "override_level": 0,
            "is_override": False,
        })

        # Track override depth per key as we walk root → most-specific
        seen_keys: dict[str, int] = {}  # key → times it has been overridden so far

        for source_path, params in sources:
            is_exact = source_path == lookup_path
            # Build display string: "provider:merged_path" so links work in both modes.
            # source_path is always provider-inclusive (e.g. pkg/_stack/proxmox/example-lab).
            # Strip _stack (parts[1]) + provider (parts[2]) and prefix with provider.
            if not is_exact:
                _parts = source_path.split("/")
                if len(_parts) >= 3:
                    _merged = _parts[0] + ("/" + "/".join(_parts[3:]) if len(_parts) > 3 else "")
                    source_display = f"{_parts[2]}:{_merged}"
                else:
                    source_display = source_path
            else:
                source_display = ""
            label = "defined here" if is_exact else "inherited from"
            result.append({
                "row_type": "source_header",
                "provider": provider_name,
                "accent": accent,
                "source_label": label,
                "source_path": "" if is_exact else source_path,
                "source_display": source_display,
                "key": "",
                "key_color": "",
                "value": "",
                "is_multiline": False,
                "override_level": 0,
                "is_override": False,
            })
            # Sort: special keys (provider/env/region) → underscore keys → rest
            sorted_params = sorted(params.items(), key=lambda kv: _param_sort_key(kv[0]))
            for k, v in sorted_params:
                if k in seen_keys:
                    seen_keys[k] += 1
                else:
                    seen_keys[k] = 0
                override_level = seen_keys[k]
                fmt_value, is_multiline = _fmt_yaml(v)
                if k in _SPECIAL_KEY_COLORS:
                    key_color = _SPECIAL_KEY_COLORS[k]
                elif k.startswith("_"):
                    key_color = _underscore_key_color(k)
                else:
                    key_color = _REGULAR_KEY_COLOR
                result.append({
                    "row_type": "param",
                    "provider": provider_name,
                    "accent": accent,
                    "source_label": "",
                    "source_path": source_path,   # provider-inclusive config_params key
                    "source_display": "",
                    "key": k,
                    "value": fmt_value,
                    "is_multiline": is_multiline,
                    "override_level": override_level,
                    "is_override": override_level > 0,  # pre-computed for rx.cond
                    "key_color": key_color,
                })

    return result


# ---------------------------------------------------------------------------
# Merged tree builder
# ---------------------------------------------------------------------------

def _build_merged_nodes(all_nodes: list[dict]) -> list[dict]:
    """
    Collapse the provider segment (depth 1) out of every node so resources
    from all providers are shown under a single unified hierarchy.

    e.g.  example-pkg/_stack/proxmox/example-lab/pve-nodes/pve-1
          example-pkg/_stack/maas/example-lab/machines/node-1
    become:
          example-pkg/_stack/example-lab/pve-nodes/pve-1    (providers_str="proxmox")
          example-pkg/_stack/example-lab/machines/node-1    (providers_str="maas")

    When two providers share the same merged path the node records both:
          example-lab  (providers_str="proxmox,maas,unifi,...")
    """
    seen: dict[str, dict] = {}   # merged_path -> merged node dict
    ordered: list[str] = []      # insertion order

    for node in all_nodes:
        depth = node["depth"]
        path  = node["path"]

        if depth == 0:
            # Category nodes: keep as-is, no provider association
            if path not in seen:
                ordered.append(path)
                seen[path] = {**node, "providers_str": ""}
            continue

        if depth == 1:
            # Provider nodes: skip — they become implicit in the merged tree
            continue

        # depth >= 2: strip "_stack" at position 1 AND provider at position 2
        # New paths: <pkg>/_stack/<provider>/... → merged: <pkg>/...
        parts = path.split("/")
        merged_parts = [parts[0]] + parts[3:]
        merged_path  = "/".join(merged_parts)
        merged_depth = depth - 1
        provider     = node.get("provider", "")

        if merged_path not in seen:
            ordered.append(merged_path)
            seen[merged_path] = {
                **node,
                "path":        merged_path,
                "depth":       merged_depth,
                "indent_px":   f"{merged_depth * 20}px",
                "is_bold":     merged_depth < 2,
                "show_badge":  merged_depth < 3,
                "is_expanded": False,
                "providers_str": provider,
            }
        else:
            existing = seen[merged_path]
            # Merge provider names
            existing_providers = set(existing["providers_str"].split(",")) if existing["providers_str"] else set()
            if provider:
                existing_providers.add(provider)
            existing["providers_str"] = ",".join(sorted(existing_providers))
            # Propagate flags
            if node.get("has_children"):
                existing["has_children"] = True
            if node.get("has_terragrunt"):
                existing["has_terragrunt"] = True

    # Recompute has_children using the final merged path set
    path_set = set(ordered)
    result: list[dict] = []
    for mp in ordered:
        node = seen[mp]
        has_children = any(p != mp and p.startswith(mp + "/") for p in path_set)
        result.append({**node, "has_children": has_children})
    return result


# ---------------------------------------------------------------------------
# Infra scanning
# ---------------------------------------------------------------------------

def _infer_type(parts: list[str], depth: int, name: str, parent: str) -> str:
    if depth == 0:
        return "package"
    if depth == 1:
        return "provider"
    # New engine layout: parts = [pkg, "_stack", provider, ...]
    provider = parts[2] if len(parts) > 2 else ""
    if provider in ("gcp", "aws", "azure"):
        if depth == 2:
            return "region"
        if depth == 3:
            return "environment"
        if name == "buckets":
            return "group"
        if parent == "buckets":
            return "bucket"
        return "resource"
    if provider == "proxmox":
        if depth == 2:
            return "environment"
        if name == "pve-nodes":
            return "group"
        if parent == "pve-nodes":
            return "pve-node"
        if name in ("isos", "snippets", "vms"):
            return "group"
        if parent == "isos":
            return "iso"
        if parent == "snippets":
            return "snippet"
        if parent == "vms":
            return "vm"
        return "resource"
    if provider == "maas":
        if depth == 2:
            return "environment"
        if name == "machines":
            return "group"
        if parent == "machines":
            return "machine"
        return "resource"
    if provider in ("unifi", "null"):
        if depth == 2:
            return "environment"
        return "resource"
    return "resource"


def _find_unit_hcl(dir_path: Path) -> Path | None:
    """Return the unit HCL file inside *dir_path*, or None if absent.

    Prefers ``terragrunt.hcl`` for backward-compatibility; falls back to the
    first ``*.hcl`` file found (excluding hidden files like ``.terraform.lock.hcl``)
    so that non-standard names (e.g. ``unit.hcl``) are also recognised.
    """
    canonical = dir_path / "terragrunt.hcl"
    if canonical.exists():
        return canonical
    try:
        hcl_files = sorted(
            f for f in dir_path.iterdir()
            if f.suffix == ".hcl" and f.is_file() and not f.name.startswith(".")
        )
    except (PermissionError, NotADirectoryError):
        return None
    return hcl_files[0] if hcl_files else None


def _extract_module_path(hcl_content: str) -> str:
    """Extract module path from a terragrunt source attribute.

    Matches the part of the source string that follows the last `}/`, which is
    the terragrunt convention for separating the module root interpolation from
    the relative module path.  Example:

        source = "${include.root.locals.modules_dir}/aws/native/aws_s3_bucket"
        → "aws/native/aws_s3_bucket"

    Returns "" if no matching source attribute is found.
    """
    import re as _re
    m = _re.search(r'source\s*=\s*"[^"]*\}/([^"]+)"', hcl_content)
    if m:
        return m.group(1).strip()
    return ""


def _scan_infra(path: Path, depth: int = 0, parts: list[str] | None = None) -> list[dict]:
    if parts is None:
        parts = []
    current_parts = parts + [path.name]
    try:
        children_dirs = sorted(
            d for d in path.iterdir()
            if d.is_dir() and not d.name.startswith(".") and not d.name.startswith("_")
        )
    except PermissionError:
        children_dirs = []

    # New engine layout: parts = [pkg, "_stack", provider, ...]
    provider = current_parts[2] if len(current_parts) > 2 else ""
    node_type = _infer_type(current_parts, depth, path.name, path.parent.name)
    has_terragrunt = _find_unit_hcl(path) is not None
    node_path = "/".join(current_parts)

    node: dict = {
        "name": path.name,
        "type": node_type,
        "depth": depth,
        "path": node_path,
        "has_children": len(children_dirs) > 0,
        "has_terragrunt": has_terragrunt,
        "provider": provider,
        "providers_str": provider,   # single provider for separated-mode nodes
        "indent_px": f"{depth * 20}px",
        "is_expanded": False,
        "is_bold": depth < 2,
        "show_badge": depth < 3,
        "module_source":       "",   # populated by _init_nodes_cache (bare name from HCL source)
        "module_source_short": "",
        "module_tree_path":    "",   # populated by _init_nodes_cache (full path in modules tree)
        "package":             "",   # populated by _populate_module_tree_paths (<provider>/<pkg>/<mod>[1])
        "is_host":             False,  # populated by _init_nodes_cache
        "wave_num_str":        "",   # populated by _init_path_param_maps
        "build_status":        "none",  # populated by visible_nodes from unit_build_statuses
    }
    result = [node]
    for child in children_dirs:
        result.extend(_scan_infra(child, depth + 1, current_parts))
    return result


# ---------------------------------------------------------------------------
# Chrome profile detection — runs once at import.
# ---------------------------------------------------------------------------

def _detect_chrome_profiles() -> list[dict]:
    """Return [{id, label}] for every Chrome/Chromium profile found on this machine.

    Always starts with {"id": "playwright", "label": "Playwright"} for the
    built-in screenshot browser, followed by any installed Chrome profiles.
    """
    import json as _json
    profiles: list[dict] = [{"id": "playwright", "label": "Playwright"}]
    _skip = {"System Profile", "Crash Reports", "ShaderCache", "GrShaderCache",
              "CrashpadMetrics", "component_crx_cache"}
    for chrome_dir_name in ("google-chrome", "chromium"):
        chrome_dir = Path.home() / ".config" / chrome_dir_name
        if not chrome_dir.exists():
            continue
        for d in sorted(chrome_dir.iterdir()):
            if not d.is_dir() or d.name in _skip:
                continue
            prefs = d / "Preferences"
            if not prefs.exists():
                continue
            try:
                name = _json.loads(prefs.read_text()).get("profile", {}).get("name", "")
            except Exception:
                name = ""
            _generic = {"Person", "Your Chrome", "Default", "Guest Profile"}
            if not name or any(name.lower().startswith(g.lower()) for g in _generic):
                continue
            profiles.append({"id": d.name, "label": name})
        break  # use first found browser dir
    return profiles


_CHROME_PROFILES_CACHE: list[dict] = _detect_chrome_profiles()


# ---------------------------------------------------------------------------
# Terminal backends — embedded xterm.js plus any native terminals found on PATH.

import sys as _sys
import socket as _socket

# Linux-only terminals (probe via shutil.which)
_LINUX_TERMINALS: list[dict] = [
    {"id": "gnome-terminal", "label": "gnome-terminal"},
    {"id": "xterm",          "label": "xterm"},
    {"id": "konsole",        "label": "konsole"},
    {"id": "tilix",          "label": "tilix"},
]

# Cross-platform terminals (probe via shutil.which on all platforms)
_CROSS_PLATFORM_TERMINALS: list[dict] = [
    {"id": "alacritty", "label": "alacritty"},
    {"id": "kitty",     "label": "kitty"},
    {"id": "wezterm",   "label": "WezTerm"},
]

# macOS-specific terminals (presence detected differently)
_MACOS_TERMINALS: list[dict] = [
    {"id": "iterm2",        "label": "iTerm2"},
    {"id": "terminal-app",  "label": "Terminal.app"},
]

# ttyd availability and install command — set by _detect_terminal_backends()
_TTYD_AVAILABLE: bool = False
_TTYD_INSTALL_CMD: str = ""


def _try_install_ttyd_background() -> None:
    """Attempt to install ttyd non-interactively in a background thread.

    Runs the platform-appropriate install command (apt/brew).  On success,
    re-detects backends so the next _TTYD_AVAILABLE / _TERMINAL_BACKENDS check
    sees ttyd as available.  Silently ignores all failures (no sudo, wrong
    distro, network error, etc.).  The install requires a page reload to fully
    activate since _TTYD_AVAILABLE is a module-level flag.
    """
    import subprocess as _sp
    import threading as _th

    def _run() -> None:
        global _TTYD_AVAILABLE, _TERMINAL_BACKENDS
        try:
            result = _sp.run(
                _TTYD_INSTALL_CMD.split(),
                timeout=120,
                capture_output=True,
            )
            if result.returncode == 0:
                _gui_log("[ttyd] auto-install succeeded — reload the page to use ttyd")
                # Re-detect so subsequent state reads pick up ttyd.
                _TERMINAL_BACKENDS[:] = _detect_terminal_backends()
            else:
                _gui_log(f"[ttyd] auto-install failed (rc={result.returncode}) — "
                         f"run '{_TTYD_INSTALL_CMD}' manually")
        except Exception as exc:
            _gui_log(f"[ttyd] auto-install error: {exc}")

    if not _TTYD_INSTALL_CMD:
        return  # detect not yet run; nothing to do
    _th.Thread(target=_run, daemon=True).start()


# Currently running ttyd subprocess (module-level; replaced on each new open)
_ttyd_proc: "subprocess.Popen | None" = None  # type: ignore[name-defined]

# Path to patched ttyd index (generated once at startup when ttyd is available)
_TTYD_PATCHED_INDEX: "str | None" = None


def _find_free_port() -> int:
    """Bind to port 0 and return the OS-assigned free port number."""
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _prepare_ttyd_custom_index() -> "str | None":
    """Fetch ttyd's self-contained index, patch out the resize overlay, cache to disk.

    ttyd 1.6.x embeds all JS inline. The resize overlay is controlled by
    `this.resizeOverlay=!0` in the constructor — we flip it to `!1`.
    The -t disableResizeOverlay=true server flag is NOT honoured in 1.6.3
    (it's a WebSocket command, not a constructor option).
    """
    import subprocess as _sp, urllib.request as _req, time as _time

    out_path = str(_APP_DIR / "ttyd_index_patched.html")
    port = _find_free_port()
    probe = _sp.Popen(
        ["ttyd", "--port", str(port), "--once", "bash"],
        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True,
    )
    try:
        for _ in range(20):
            _time.sleep(0.1)
            try:
                with _socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    break
            except OSError:
                continue
        with _req.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
    except Exception:
        return None
    finally:
        probe.terminate()
        try:
            probe.wait(timeout=2)
        except Exception:
            probe.kill()

    # Flip resizeOverlay initialisation from true (!0) to false (!1)
    patched = html.replace("this.resizeOverlay=!0", "this.resizeOverlay=!1", 1)
    if patched == html:
        return None  # pattern not found — version mismatch, don't use broken index
    Path(out_path).write_text(patched, encoding="utf-8")
    return out_path


def _start_ttyd(cwd: str, cmd: str = "", login: bool = True) -> int:
    """Kill any running ttyd, start a new one, and return its port.

    Prepares the patched index on first call (lazy — avoids blocking app startup).
    Does NOT use --once: ttyd stays alive across iframe reloads; killed on the
    next _start_ttyd() call or when open_shell("") closes the panel.

    login=False skips --login when wrapping cmd in bash, preventing ~/.bash_profile
    from running (and any 'clear' it may contain that causes a visual blink).
    """
    global _ttyd_proc, _TTYD_PATCHED_INDEX
    import subprocess as _sp
    # Prepare patched index lazily on first use — not at import time.
    if _TTYD_PATCHED_INDEX is None and _TTYD_AVAILABLE:
        _TTYD_PATCHED_INDEX = _prepare_ttyd_custom_index() or ""
    if _ttyd_proc is not None:
        try:
            _ttyd_proc.terminate()
            _ttyd_proc.wait(timeout=2)
        except Exception:
            pass
        _ttyd_proc = None
    port = _find_free_port()
    if cmd:
        bash_args = ["bash", "--login", "-c"] if login else ["bash", "-c"]
        shell_args = bash_args + [f"{cmd}; exec bash"]
    else:
        shell_args = ["bash", "--login"]
    args = ["ttyd", "--port", str(port)]
    if _TTYD_PATCHED_INDEX:
        args += ["--index", _TTYD_PATCHED_INDEX]
    _ttyd_proc = _sp.Popen(args + shell_args, cwd=cwd, start_new_session=True)
    return port


def _detect_terminal_backends() -> list[dict]:
    """Return list of available terminal backends (always includes 'embedded' and 'ttyd')."""
    global _TTYD_AVAILABLE, _TTYD_INSTALL_CMD
    import shutil
    is_mac = _sys.platform == "darwin"

    _TTYD_INSTALL_CMD = "brew install ttyd" if is_mac else "sudo apt install -y ttyd"
    _TTYD_AVAILABLE = bool(shutil.which("ttyd"))

    backends = [{"id": "embedded", "label": "Embedded (xterm.js)"}]
    # ttyd always offered — label indicates if not yet installed
    backends.append({
        "id": "ttyd",
        "label": "ttyd" if _TTYD_AVAILABLE else "ttyd (not installed)",
    })

    candidates = _CROSS_PLATFORM_TERMINALS[:]
    if not is_mac:
        candidates = _LINUX_TERMINALS + candidates
    for t in candidates:
        if shutil.which(t["id"]):
            backends.append({"id": t["id"], "label": t["label"]})

    if is_mac:
        import os as _os
        if _os.path.isdir("/Applications/iTerm.app"):
            backends.append({"id": "iterm2", "label": "iTerm2"})
        backends.append({"id": "terminal-app", "label": "Terminal.app"})

    return backends


_TERMINAL_BACKENDS: list[dict] = _detect_terminal_backends()


def _launch_native_terminal(terminal_id: str, cwd: str, cmd: str = "") -> None:
    """Launch a native terminal emulator, optionally running cmd then staying open."""
    import subprocess as _sp
    import shlex as _shlex

    # Inner bash invocation: run cmd then drop into an interactive shell.
    if cmd:
        inner = f"{cmd}; exec bash"
        bash_args = ["bash", "--login", "-c", inner]
    else:
        bash_args = ["bash", "--login"]

    if terminal_id == "gnome-terminal":
        if cmd:
            args = ["gnome-terminal", f"--working-directory={cwd}", "--"] + bash_args
        else:
            args = ["gnome-terminal", f"--working-directory={cwd}"]
    elif terminal_id == "xterm":
        # xterm has no --working-directory flag; prepend cd in the shell invocation
        if cmd:
            inner = f"cd {_shlex.quote(cwd)}; {cmd}; exec bash"
        else:
            inner = f"cd {_shlex.quote(cwd)}; exec bash"
        args = ["xterm", "-e", "bash", "--login", "-c", inner]
    elif terminal_id == "konsole":
        if cmd:
            args = ["konsole", f"--workdir={cwd}", "-e"] + bash_args
        else:
            args = ["konsole", f"--workdir={cwd}"]
    elif terminal_id == "tilix":
        if cmd:
            args = ["tilix", f"--working-directory={cwd}", "-e"] + bash_args
        else:
            args = ["tilix", f"--working-directory={cwd}"]
    elif terminal_id == "alacritty":
        args = ["alacritty", "--working-directory", cwd, "-e"] + bash_args
    elif terminal_id == "kitty":
        args = ["kitty", "--directory", cwd] + bash_args
    elif terminal_id == "wezterm":
        if cmd:
            args = ["wezterm", "start", "--cwd", cwd, "--"] + bash_args
        else:
            args = ["wezterm", "start", "--cwd", cwd]
    elif terminal_id == "iterm2":
        # iTerm2: use osascript to open a new window at cwd running the command
        if cmd:
            shell_cmd = f"cd {_shlex.quote(cwd)} && {cmd}; exec bash"
        else:
            shell_cmd = f"cd {_shlex.quote(cwd)}"
        script = (
            'tell application "iTerm2"\n'
            '  activate\n'
            '  set w to (create window with default profile)\n'
            f'  tell current session of w to write text "{shell_cmd}"\n'
            'end tell'
        )
        _sp.Popen(["osascript", "-e", script], start_new_session=True)
        return
    elif terminal_id == "terminal-app":
        # Terminal.app: open a new window at cwd; command via 'do script'
        if cmd:
            shell_cmd = f"cd {_shlex.quote(cwd)} && {cmd}"
        else:
            shell_cmd = f"cd {_shlex.quote(cwd)}"
        script = (
            'tell application "Terminal"\n'
            '  activate\n'
            f'  do script "{shell_cmd}"\n'
            'end tell'
        )
        _sp.Popen(["osascript", "-e", script], start_new_session=True)
        return
    else:
        return

    _sp.Popen(args, start_new_session=True, cwd=cwd)


# ---------------------------------------------------------------------------
# Module-level node cache — scanned once at import for the API endpoint.
# on_load reuses this cache instead of re-scanning.
# ---------------------------------------------------------------------------

_ALL_NODES_CACHE: list[dict] = []
# Two-level HCL file cache (populated lazily, cleared on _init_nodes_cache)
_hcl_path_cache: dict[str, str] = {}      # node_path → abs_path or "" (not found)
_hcl_content_cache: dict[str, dict] = {}  # abs_path  → {mtime, content}


def _init_nodes_cache() -> None:
    global _ALL_NODES_CACHE
    _hcl_path_cache.clear()
    _hcl_content_cache.clear()
    config = _load_config()
    infra = _infra_path(config)
    flat: list[dict] = []
    if infra.exists():
        _gui_log(f"[homelab_gui] Scanning infra: {infra}")
        try:
            for pkg_dir in sorted(
                d for d in infra.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ):
                stack_dir = pkg_dir / "_stack"
                if not stack_dir.exists():
                    continue
                # Synthetic package node at depth 0
                flat.append({
                    "name": pkg_dir.name,
                    "type": "package",
                    "depth": 0,
                    "path": pkg_dir.name,
                    "has_children": True,
                    "has_terragrunt": False,
                    "provider": "",
                    "providers_str": "",
                    "indent_px": "0px",
                    "is_expanded": False,
                    "is_bold": True,
                    "show_badge": True,
                    "module_source": "",
                    "module_source_short": "",
                    "module_tree_path": "",
                    "package": "",
                    "is_host": False,
                    "wave_num_str": "",
                    "build_status": "none",
                })
                # Scan each provider dir under _stack at depth=1
                for provider_dir in sorted(
                    d for d in stack_dir.iterdir()
                    if d.is_dir() and not d.name.startswith(".")
                ):
                    flat.extend(_scan_infra(
                        provider_dir,
                        depth=1,
                        parts=[pkg_dir.name, "_stack"],
                    ))
        except Exception:
            import traceback
            traceback.print_exc()
        _gui_log(f"[homelab_gui] Infra scan done — {len(flat)} nodes")
    _gui_log(f"[homelab_gui] Unit nodes: {[n['path'] for n in flat if n.get('has_terragrunt')]}")
    # Populate module_source / module_source_short / is_host from each unit's HCL
    infra_base = _infra_path(config)
    # modules_to_include: from ansible_inventory section of the stack config
    _stack_cfg = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
    _modules_to_include: list[str] = (
        _stack_cfg.get("ansible_inventory", {}) or {}
    ).get("modules_to_include") or []
    # own_params: exact-path config_params entries per node (no prefix inheritance)
    _own_params_by_path: dict[str, dict] = {}
    for _prov_data in (_stack_cfg.get("providers", {}) or {}).values():
        if not isinstance(_prov_data, dict):
            continue
        for _key, _pdata in (_prov_data.get("config_params") or {}).items():
            if isinstance(_pdata, dict):
                existing = _own_params_by_path.setdefault(_key, {})
                existing.update(_pdata)
    for node in flat:
        if node.get("has_terragrunt"):
            hcl_path = _find_unit_hcl(infra_base / node["path"])
            if hcl_path:
                try:
                    full = _extract_module_path(hcl_path.read_text())
                    node["module_source"]       = full
                    node["module_source_short"] = full.split("/")[-1] if full else ""
                    # Host detection: honour _is_host override, else check modules_to_include
                    own_params = _own_params_by_path.get(node["path"], {})
                    is_host_override = own_params.get("_is_host")
                    if is_host_override is not None:
                        node["is_host"] = bool(is_host_override)
                    elif _modules_to_include and full:
                        node["is_host"] = any(mod in full for mod in _modules_to_include)
                except Exception:
                    pass
    _ALL_NODES_CACHE = flat


_init_nodes_cache()
_init_path_param_maps()   # depends on _ALL_NODES_CACHE and _STACK_CONFIG

# Populated by _init_dependencies_cache(); maps infra node path → list of dep paths.
_DEPENDENCIES_CACHE: dict[str, list[str]] = {}


def _init_dependencies_cache() -> None:
    """Parse terragrunt.hcl files to extract dependency config_paths.

    Builds _DEPENDENCIES_CACHE: {source_node_path: [dep_node_path, ...]}
    where paths are relative to the infra root (matching Cytoscape node IDs).
    Only creates edges where both endpoints exist in _ALL_NODES_CACHE.
    """
    global _DEPENDENCIES_CACHE
    config   = _load_config()
    infra    = _infra_path(config).resolve()
    known    = {n["path"] for n in _ALL_NODES_CACHE}
    result: dict[str, list[str]] = {}
    if not infra.exists():
        _DEPENDENCIES_CACHE = result
        return
    for node in _ALL_NODES_CACHE:
        if not node.get("has_terragrunt"):
            continue
        hcl_file = _find_unit_hcl(infra / node["path"])
        if not hcl_file:
            continue
        try:
            content = hcl_file.read_text()
        except Exception:
            continue
        deps: list[str] = []
        for m in _DEPENDENCY_PATH_RE.finditer(content):
            cfg_path = m.group(1)
            try:
                dep_abs = (hcl_file.parent / cfg_path).resolve()
                dep_rel = str(dep_abs.relative_to(infra))
                if dep_rel in known and dep_rel != node["path"]:
                    deps.append(dep_rel)
            except (ValueError, OSError):
                pass
        if deps:
            result[node["path"]] = deps
    _DEPENDENCIES_CACHE = result
    _gui_log(f"[homelab_gui] Dependencies: {sum(len(v) for v in result.values())} edges across {len(result)} nodes")


_init_dependencies_cache()


# ---------------------------------------------------------------------------
# Generic directory-tree scanner — used for _modules/
# ---------------------------------------------------------------------------

def _scan_dir_tree(
    path: Path,
    depth: int = 0,
    parts: list[str] | None = None,
    type_map: dict[int, str] | None = None,
) -> list[dict]:
    """Recursively scan *path* and return a flat node list (same schema as _scan_infra).

    type_map — optional override for node types by depth; defaults to
    {0: 'provider', 1: 'package', 2: 'module'} and 'resource' beyond that.
    """
    if parts is None:
        parts = []
    if type_map is None:
        type_map = {0: "provider", 1: "package", 2: "module"}
    current_parts = parts + [path.name]
    try:
        children_dirs = sorted(
            d for d in path.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    except PermissionError:
        children_dirs = []

    node_type = type_map.get(depth, "resource")
    provider = current_parts[0] if current_parts else ""
    # A "module" node is considered to have terraform files if any .tf exist
    has_tf = any(path.glob("*.tf")) if not children_dirs else False
    node_path = "/".join(current_parts)

    node: dict = {
        "name": path.name,
        "type": node_type,
        "depth": depth,
        "path": node_path,
        "has_children": len(children_dirs) > 0,
        "has_terragrunt": has_tf,
        "provider": provider,
        "providers_str": provider,
        "indent_px": f"{depth * 20}px",
        "is_expanded": False,
        "is_bold": depth < 2,
        "show_badge": depth < 3,
        "module_source":       "",
        "module_source_short": "",
        "wave_num_str":        "",   # populated by _init_path_param_maps
    }
    result = [node]
    for child in children_dirs:
        result.extend(_scan_dir_tree(child, depth + 1, current_parts, type_map))
    return result


_MODULES_NODES_CACHE: list[dict] = []


class PackageModule(_PydanticBase):
    """A single Terraform module within a package."""

    provider: str = ""
    name: str = ""
    tf_path: str = ""
    tg_scripts_readme: str = ""  # README.md in relevant tg-scripts dir; "" if none


class PackageFileLink(_PydanticBase):
    """A labeled clickable file link used in package sections."""

    label: str = ""
    path: str = ""  # "" means non-clickable (display only)


class PackageInfo(_PydanticBase):
    """All metadata for one package."""

    name: str = ""
    config_yaml_path: str = ""
    secrets_yaml_path: str = ""
    providers_str: str = ""
    modules: list[PackageModule] = []
    provider_templates: list[str] = []  # absolute paths to *.tpl files
    tg_scripts_env_path: str = ""
    tg_scripts_readme_path: str = ""
    tg_scripts_sub_dirs: list[PackageFileLink] = []
    wave_scripts_env_path: str = ""
    wave_scripts_readme_path: str = ""
    wave_test_playbooks: list[PackageFileLink] = []
    source_repo: str = ""   # empty = built-in; name of cloned ext repo otherwise


_PACKAGES_CACHE: list[PackageInfo] = []

_EXT_PACKAGES_DIR     = _STACK_DIR / "_ext_packages"
_PKG_REPOS_CONFIG     = _STACK_DIR / "config" / "framework_package_repositories.yaml"
_FRAMEWORK_PKGS_CFG   = _STACK_DIR / "config" / "framework_packages.yaml"
_PKG_MGR              = Path(os.environ['_PKG_MGR'])


def _load_ext_package_repos() -> list[dict]:
    """Return [{name, url}] from state/current.yaml, silently on error."""
    try:
        state = _load_state()
        return [
            {"name": str(r.get("name", "")), "url": str(r.get("url", ""))}
            for r in state.get("current", {}).get("ext_package_repos", [])
            if r.get("name") and r.get("url")
        ]
    except Exception:
        return []


def _save_ext_package_repos(repos: list[dict]) -> None:
    """Persist ext_package_repos list to state/current.yaml."""
    current_path = STATE_DIR / "current.yaml"
    with _state_write_lock:
        try:
            raw = yaml.safe_load(current_path.read_text()) or {} if current_path.exists() else {}
        except Exception:
            raw = {}
        raw.setdefault("current", {})["ext_package_repos"] = repos
        try:
            current_path.write_text(yaml.dump(raw, allow_unicode=True, default_flow_style=False))
        except Exception as exc:
            _gui_log(f"[homelab_gui] Warning: could not save ext_package_repos: {exc}")


def _read_pkg_repos_config() -> list[dict]:
    """Return [{name, url, description}] from framework_package_repositories.yaml."""
    try:
        return yaml.safe_load(_PKG_REPOS_CONFIG.read_text()).get("framework_package_repositories", [])
    except Exception:
        return []


def _read_framework_pkgs() -> list[dict]:
    """Return [{name, public, repo, source, version}] from framework_packages.yaml."""
    try:
        return yaml.safe_load(_FRAMEWORK_PKGS_CFG.read_text()).get("framework_packages", [])
    except Exception:
        return []


def _run_pkg_mgr(*args: str) -> tuple[bool, str]:
    """Run pkg-mgr with the given args. Returns (success, combined stdout+stderr)."""
    try:
        result = subprocess.run(
            [str(_PKG_MGR)] + list(args),
            capture_output=True, text=True, env=os.environ,
        )
        out = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, out.strip()
    except Exception as exc:
        return False, str(exc)


def _run_pkg_mgr_yaml(*args: str):
    """Run pkg-mgr; on success parse stdout as YAML. Returns (True, data) or (False, err_str)."""
    try:
        result = subprocess.run(
            [str(_PKG_MGR)] + list(args),
            capture_output=True, text=True, env=os.environ,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "").strip()
        return True, yaml.safe_load(result.stdout or "") or {}
    except Exception as exc:
        return False, str(exc)


def _scan_packages() -> list[PackageInfo]:
    """Build PackageInfo list from infra/<pkg>/ directories in the engine repo.

    New engine layout (per package at infra/<pkg>/):
      _config/<pkg>.yaml              — package config YAML
      _config/<pkg>_secrets.sops.yaml — secrets
      _modules/<module>/              — Terraform modules (no provider subdir)
      _providers/*.tpl                — provider templates
      _tg_scripts/<role>/             — Terragrunt hook scripts
      _wave_scripts/test-ansible-playbooks/<cat>/<wave>/run — wave test scripts
    """
    acc: dict[str, dict] = {}

    def _entry(name: str) -> dict:
        return {"name": name, "config_yaml_path": "", "secrets_yaml_path": "",
                "providers_str": "", "modules": [], "provider_templates": [],
                "tg_scripts_env_path": "", "tg_scripts_readme_path": "",
                "tg_scripts_sub_dirs": [], "wave_scripts_env_path": "",
                "wave_scripts_readme_path": "", "wave_test_playbooks": [],
                "source_repo": ""}

    infra_dir = _STACK_DIR / "infra"

    # --- 1. Built-in packages: infra/<pkg>/ ---
    if infra_dir.exists():
        try:
            for pkg_dir in sorted(
                d for d in infra_dir.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ):
                pkg_name = pkg_dir.name
                if pkg_name not in acc:
                    acc[pkg_name] = _entry(pkg_name)
                pkg = acc[pkg_name]

                # Config YAML
                config_yaml = pkg_dir / "_config" / f"{pkg_name}.yaml"
                pkg["config_yaml_path"] = str(config_yaml) if config_yaml.exists() else ""

                # Determine providers_str from _stack/ subdirectory names
                stack_subdir = pkg_dir / "_stack"
                if stack_subdir.exists():
                    try:
                        providers_listed = sorted(
                            d.name for d in stack_subdir.iterdir()
                            if d.is_dir() and not d.name.startswith(".")
                        )
                        pkg["providers_str"] = ", ".join(providers_listed)
                    except Exception:
                        pass

                # Secrets YAML
                secrets_yaml = pkg_dir / "_config" / f"{pkg_name}_secrets.sops.yaml"
                pkg["secrets_yaml_path"] = str(secrets_yaml) if secrets_yaml.exists() else ""

                # Modules: _modules/<module>/  (no provider subdir)
                modules_dir = pkg_dir / "_modules"
                if modules_dir.exists():
                    for mod_dir in sorted(
                        d for d in modules_dir.iterdir()
                        if d.is_dir() and not d.name.startswith(".")
                    ):
                        tf_path = ""
                        for fname in ("main.tf", "variables.tf", "outputs.tf"):
                            f = mod_dir / fname
                            if f.exists():
                                tf_path = str(f)
                                break
                        if not tf_path:
                            tfs = sorted(mod_dir.glob("*.tf"))
                            tf_path = str(tfs[0]) if tfs else ""
                        # TG scripts README: look in _tg_scripts/<role>/README.md
                        tg_scripts_readme = ""
                        vars_tf = mod_dir / "variables.tf"
                        if vars_tf.exists():
                            try:
                                if "script_dir" in vars_tf.read_text():
                                    tg_base = pkg_dir / "_tg_scripts"
                                    for role_dir in sorted(tg_base.iterdir()
                                                           if tg_base.exists() else []):
                                        candidate = role_dir / "README.md"
                                        if candidate.exists():
                                            tg_scripts_readme = str(candidate)
                                            break
                            except Exception:
                                pass
                        # Use pkg_name as provider field (best available)
                        pkg["modules"].append({
                            "provider": pkg_name,
                            "name": mod_dir.name,
                            "tf_path": tf_path,
                            "tg_scripts_readme": tg_scripts_readme,
                        })

                # Provider templates: _providers/*.tpl
                prov_dir = pkg_dir / "_providers"
                if prov_dir.exists():
                    for tpl in sorted(prov_dir.glob("*.tpl")):
                        pkg["provider_templates"].append(str(tpl))

                # TG scripts: _tg_scripts/<group>/<role>/  (two levels deep)
                tg_base = pkg_dir / "_tg_scripts"
                if tg_base.exists():
                    readme = tg_base / "README.md"
                    pkg["tg_scripts_readme_path"] = str(readme) if readme.exists() else ""
                    for group_dir in sorted(
                        d for d in tg_base.iterdir()
                        if d.is_dir() and not d.name.startswith(".")
                    ):
                        # Group-level README
                        group_readme = group_dir / "README.md"
                        if group_readme.exists():
                            pkg["tg_scripts_sub_dirs"].append({
                                "label": group_dir.name,
                                "path": str(group_readme),
                            })
                        # Individual role dirs inside the group
                        for role_dir in sorted(
                            d for d in group_dir.iterdir()
                            if d.is_dir() and not d.name.startswith(".")
                        ):
                            role_readme = role_dir / "README.md"
                            pkg["tg_scripts_sub_dirs"].append({
                                "label": f"{group_dir.name}/{role_dir.name}",
                                "path": str(role_readme) if role_readme.exists() else "",
                            })

                # Wave scripts: _wave_scripts/**/<wave>/run (any subdir, not just test-ansible-playbooks)
                wave_base = pkg_dir / "_wave_scripts"
                if wave_base.exists():
                    wave_readme = wave_base / "README.md"
                    pkg["wave_scripts_readme_path"] = (
                        str(wave_readme) if wave_readme.exists() else ""
                    )
                    for run_script in sorted(wave_base.rglob("run")):
                        rel = run_script.relative_to(wave_base)
                        parts_rel = rel.parts  # e.g. ("test-ansible-playbooks", "cat", "wave", "run")
                        lbl = "/".join(parts_rel[:-1]) if len(parts_rel) > 1 else str(rel)
                        pkg["wave_test_playbooks"].append({
                            "label": lbl,
                            "path": str(run_script),
                        })
        except Exception as e:
            _gui_log(f"[homelab_gui] Warning: error scanning infra packages: {e}")

    # --- 2. External package repos (cloned under _STACK_DIR/_ext_packages/<name>/) ---
    for repo in _load_ext_package_repos():
        repo_name = repo["name"]
        ext_base = _EXT_PACKAGES_DIR / repo_name
        ext_infra = ext_base / "infra"
        if not ext_infra.exists():
            continue
        try:
            for pkg_dir in sorted(
                d for d in ext_infra.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ):
                pkg_name = pkg_dir.name
                if pkg_name not in acc:
                    acc[pkg_name] = _entry(pkg_name)
                acc[pkg_name]["source_repo"] = repo_name
                pkg = acc[pkg_name]
                modules_dir = pkg_dir / "_modules"
                if not modules_dir.exists():
                    continue
                for mod_dir in sorted(
                    d for d in modules_dir.iterdir()
                    if d.is_dir() and not d.name.startswith(".")
                ):
                    tf_path = ""
                    for fname in ("main.tf", "variables.tf", "outputs.tf"):
                        f = mod_dir / fname
                        if f.exists():
                            tf_path = str(f)
                            break
                    if not tf_path:
                        tfs = sorted(mod_dir.glob("*.tf"))
                        tf_path = str(tfs[0]) if tfs else ""
                    pkg["modules"].append({
                        "provider": pkg_name,
                        "name": mod_dir.name,
                        "tf_path": tf_path,
                        "tg_scripts_readme": "",
                    })
        except Exception:
            pass

    # Cross-reference framework_packages.yaml: for any package with repo: set whose
    # source_repo is still empty (scanned via infra/ symlink in section 1), fill it in.
    try:
        fw_pkgs = _read_framework_pkgs()
        fw_repo_map = {p["name"]: p.get("repo", "") for p in fw_pkgs if p.get("repo")}
        for name, repo in fw_repo_map.items():
            if name in acc and not acc[name].get("source_repo"):
                acc[name]["source_repo"] = repo
    except Exception:
        pass

    # Build typed objects; alphabetical
    ordered = sorted(acc.values(), key=lambda p: p["name"])
    return [
        PackageInfo(
            name=p["name"],
            config_yaml_path=p["config_yaml_path"],
            secrets_yaml_path=p["secrets_yaml_path"],
            providers_str=p["providers_str"],
            modules=[PackageModule(**m) for m in p["modules"]],
            provider_templates=p["provider_templates"],
            tg_scripts_env_path=p["tg_scripts_env_path"],
            tg_scripts_readme_path=p["tg_scripts_readme_path"],
            tg_scripts_sub_dirs=[PackageFileLink(**d) for d in p["tg_scripts_sub_dirs"]],
            wave_scripts_env_path=p["wave_scripts_env_path"],
            wave_scripts_readme_path=p["wave_scripts_readme_path"],
            wave_test_playbooks=[PackageFileLink(**t) for t in p["wave_test_playbooks"]],
            source_repo=p.get("source_repo", ""),
        )
        for p in ordered
    ]


def _init_modules_cache() -> None:
    """Build module node list from infra/<pkg>/_modules/<module>/ across all packages.

    New engine layout: modules live inside each package directory (no shared
    top-level _modules/).  Module tree path format: "<pkg>/<module>" (depth 0 =
    package, depth 1 = module).
    """
    global _MODULES_NODES_CACHE, _PACKAGES_CACHE
    infra_dir = _STACK_DIR / "infra"
    flat: list[dict] = []
    if infra_dir.exists():
        try:
            for pkg_dir in sorted(
                d for d in infra_dir.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ):
                modules_dir = pkg_dir / "_modules"
                if not modules_dir.exists():
                    continue
                # Collect module subdirs
                mod_dirs = sorted(
                    d for d in modules_dir.iterdir()
                    if d.is_dir() and not d.name.startswith(".")
                )
                if not mod_dirs:
                    continue
                # Synthetic package node at depth 0
                pkg_node: dict = {
                    "name": pkg_dir.name,
                    "type": "package",
                    "depth": 0,
                    "path": pkg_dir.name,
                    "has_children": True,
                    "has_terragrunt": False,
                    "provider": pkg_dir.name,
                    "providers_str": pkg_dir.name,
                    "indent_px": "0px",
                    "is_expanded": False,
                    "is_bold": True,
                    "show_badge": True,
                    "module_source": "",
                    "module_source_short": "",
                    "wave_num_str": "",
                }
                flat.append(pkg_node)
                # Module nodes at depth 1 (path = "<pkg>/<module>")
                for mod_dir in mod_dirs:
                    flat.extend(
                        _scan_dir_tree(
                            mod_dir,
                            depth=1,
                            parts=[pkg_dir.name],
                            type_map={1: "module"},
                        )
                    )
        except Exception:
            pass
    # Also scan framework/_modules/ — shared modules used by null-provider units
    fw_modules_dir = _STACK_DIR / "framework" / "_modules"
    if fw_modules_dir.exists():
        try:
            mod_dirs = sorted(
                d for d in fw_modules_dir.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            )
            if mod_dirs:
                flat.append({
                    "name": "framework",
                    "type": "package",
                    "depth": 0,
                    "path": "framework",
                    "has_children": True,
                    "has_terragrunt": False,
                    "provider": "framework",
                    "providers_str": "framework",
                    "indent_px": "0px",
                    "is_expanded": False,
                    "is_bold": True,
                    "show_badge": True,
                    "module_source": "",
                    "module_source_short": "",
                    "wave_num_str": "",
                })
                for mod_dir in mod_dirs:
                    flat.extend(
                        _scan_dir_tree(
                            mod_dir,
                            depth=1,
                            parts=["framework"],
                            type_map={1: "module"},
                        )
                    )
        except Exception:
            pass
    _MODULES_NODES_CACHE = flat
    _PACKAGES_CACHE = _scan_packages()


_init_modules_cache()


def _populate_module_tree_paths() -> None:
    """Stamp each infra node with the full modules-tree path for its module.

    Builds a reverse map {bare_name: full_path} from _MODULES_NODES_CACHE (depth-1
    nodes are the actual module directories — new engine: "<pkg>/<module>"), then
    writes the matched full path into node["module_tree_path"].

    When two modules share the same bare name across different packages, the
    package that matches the node's provider is preferred; falls back to first match.
    """
    # depth-1 nodes are module dirs in new layout: path = "<pkg>/<module>"
    by_name: dict[str, list[str]] = {}
    for n in _MODULES_NODES_CACHE:
        if n.get("depth", 0) == 1:
            bare = n["path"].split("/")[-1]
            by_name.setdefault(bare, []).append(n["path"])

    for node in _ALL_NODES_CACHE:
        bare = node.get("module_source", "")
        if not bare:
            continue
        candidates = by_name.get(bare, [])
        if not candidates:
            node["module_tree_path"] = ""
            node["package"] = ""
        elif len(candidates) == 1:
            node["module_tree_path"] = candidates[0]
            mtp_parts = candidates[0].split("/")
            # path = "<pkg>/<module>"; package is mtp_parts[0]
            node["package"] = mtp_parts[0] if mtp_parts else ""
        else:
            # Prefer the candidate whose package segment matches the node's provider
            provider = node.get("provider", "")
            preferred = next(
                (p for p in candidates if p.split("/")[0] == provider),
                candidates[0],
            )
            node["module_tree_path"] = preferred
            mtp_parts = preferred.split("/")
            node["package"] = mtp_parts[0] if mtp_parts else ""


_populate_module_tree_paths()


def _read_module_file(node_path: str) -> tuple[str, str]:
    """Read the first available .tf file for a module; return (content, abs_path).

    node_path format: "<pkg>/<module>"  (new engine: infra/<pkg>/_modules/<module>/)
    """
    if not node_path:
        return "", ""
    try:
        parts = node_path.split("/", 1)
        if len(parts) == 2:
            pkg, mod_name = parts
            mod_dir = _STACK_DIR / "infra" / pkg / "_modules" / mod_name
        else:
            # Fallback: treat as a bare module name and search all packages
            mod_dir = None
            for pkg_dir in (_STACK_DIR / "infra").iterdir() if (_STACK_DIR / "infra").exists() else []:
                candidate = pkg_dir / "_modules" / parts[0]
                if candidate.exists():
                    mod_dir = candidate
                    break
            if mod_dir is None:
                return "", ""
        for name in ("main.tf", "variables.tf", "outputs.tf"):
            f = mod_dir / name
            if f.exists():
                return f.read_text(), str(f.resolve())
        # Fallback: any .tf file
        for f in sorted(mod_dir.glob("*.tf")):
            return f.read_text(), str(f.resolve())
        return "", ""
    except Exception:
        return "", ""


def _build_cytoscape_elements() -> list[dict]:
    """Serialize the infra DAG as Cytoscape.js compound nodes.

    Uses the `parent` data field (not edges) so Cytoscape renders the
    hierarchy as visually nested compound nodes.  Returns an empty list
    when no infra data is available (caller should fall back to synthetic).
    Each node also carries `wave` and `wave_color` data so the wave-colored
    stylesheet rule can activate without changing the element list.
    """
    if not _ALL_NODES_CACHE:
        return []
    # Build wave → palette color mapping (ordered by config declaration)
    cfg_waves = (_STACK_CONFIG.get(_STACK_CONFIG_KEY) or {}).get("waves") or []
    wave_names = [
        (w.get("name") if isinstance(w, dict) else str(w))
        for w in cfg_waves if w
    ]
    wave_color_map = {name: _WAVE_PALETTE[i % len(_WAVE_PALETTE)] for i, name in enumerate(wave_names)}

    elements: list[dict] = []
    for node in _ALL_NODES_CACHE:
        path_parts = node["path"].split("/")
        wave       = _PATH_TO_WAVE_CACHE.get(node["path"], "")
        data: dict = {
            "id":             node["path"],
            "label":          node["name"],
            "type":           node["type"],
            "provider":       node.get("provider", ""),
            "has_terragrunt": node.get("has_terragrunt", False),
            "depth":          node["depth"],
            "wave":           wave,
            "wave_color":     wave_color_map.get(wave, "#475569") if wave else "#475569",
        }
        if node["depth"] > 0:
            data["parent"] = "/".join(path_parts[:-1])
        elements.append({
            "data":    data,
            "classes": node.get("provider", "root") or "root",
        })
    return elements


def _build_cytoscape_edges() -> list[dict]:
    """Return Cytoscape edge elements from the parsed dependency cache."""
    edges = []
    for source, targets in _DEPENDENCIES_CACHE.items():
        for target in targets:
            edges.append({
                "data": {
                    "id":     f"{source}\u2192{target}",
                    "source": source,
                    "target": target,
                }
            })
    return edges


def _compute_cytoscape_positions(
    elements: list[dict],
) -> dict[str, tuple[float, float]]:
    """Pre-compute non-overlapping (x, y) positions for every leaf node.

    Compound (parent) nodes don't need explicit positions — Cytoscape
    auto-sizes them to contain their children + CSS padding.

    Layout rules:
    - If a compound node has ≤3 children → single horizontal row.
    - If a compound node has >3 children → near-square grid:
        cols = ceil(sqrt(n)), rows = ceil(n / cols).
    - Leaf nodes use LEAF_W wide slots; depth increases downward by V_GAP.
    """
    import math as _math

    LEAF_W:   float = 90.0
    H_GAP:    float = 16.0   # horizontal gap between sibling subtrees / cells
    V_GAP:    float = 70.0   # vertical offset per compound level
    PADDING:  float = 22.0   # inward padding per compound wrapper
    ROOT_GAP: float = 60.0   # extra gap between root subtrees

    all_ids: set[str] = {e["data"]["id"] for e in elements}
    children_map: dict[str, list[str]] = {}
    roots: list[str] = []

    for e in elements:
        node_id = e["data"]["id"]
        parent  = e["data"].get("parent", "")
        if parent and parent in all_ids:
            children_map.setdefault(parent, []).append(node_id)
        else:
            roots.append(node_id)

    def subtree_w(node_id: str) -> float:
        children = children_map.get(node_id, [])
        if not children:
            return LEAF_W
        n = len(children)
        if n > 3:
            cols = _math.ceil(_math.sqrt(n))
            row_widths = []
            for r in range(_math.ceil(n / cols)):
                row_children = children[r * cols:(r + 1) * cols]
                w = sum(subtree_w(c) for c in row_children) + H_GAP * (len(row_children) - 1)
                row_widths.append(w)
            inner = max(row_widths)
        else:
            inner = sum(subtree_w(c) for c in children) + H_GAP * (n - 1)
        return inner + 2 * PADDING

    def subtree_h(node_id: str) -> float:
        """Total height contributed by this node's subtree (not including the node itself)."""
        children = children_map.get(node_id, [])
        if not children:
            return 0.0
        n = len(children)
        if n > 3:
            cols = _math.ceil(_math.sqrt(n))
            rows = _math.ceil(n / cols)
            # Each row may contain compound children; take max subtree_h per row
            row_extra: list[float] = []
            for r in range(rows):
                row_children = children[r * cols:(r + 1) * cols]
                row_extra.append(max(subtree_h(c) for c in row_children))
            return V_GAP * rows + sum(row_extra)
        else:
            return V_GAP + max(subtree_h(c) for c in children)

    positions: dict[str, tuple[float, float]] = {}

    def assign(node_id: str, left: float, top: float) -> None:
        children = children_map.get(node_id, [])
        if not children:
            positions[node_id] = (left + LEAF_W / 2, top)
            return
        n = len(children)
        if n > 3:
            cols = _math.ceil(_math.sqrt(n))
            rows = _math.ceil(n / cols)
            # Width of the widest row (used to centre narrower rows)
            total_w = subtree_w(node_id) - 2 * PADDING
            cy = top + V_GAP
            for r in range(rows):
                row_children = children[r * cols:(r + 1) * cols]
                row_w = sum(subtree_w(c) for c in row_children) + H_GAP * (len(row_children) - 1)
                # Left-align each row within the compound's inner area
                cx = left + PADDING + (total_w - row_w) / 2
                row_max_h: float = 0.0
                for child_id in row_children:
                    assign(child_id, cx, cy)
                    cx += subtree_w(child_id) + H_GAP
                    row_max_h = max(row_max_h, subtree_h(child_id))
                cy += V_GAP + row_max_h
        else:
            cx = left + PADDING
            cy = top + V_GAP
            for child_id in children:
                assign(child_id, cx, cy)
                cx += subtree_w(child_id) + H_GAP

    x = 0.0
    for root_id in roots:
        assign(root_id, x, 0.0)
        x += subtree_w(root_id) + ROOT_GAP

    return positions


# ---------------------------------------------------------------------------
# React Flow tree layout builder
# ---------------------------------------------------------------------------

# Synthetic node list in _ALL_NODES_CACHE format — shown when no infra dir.
_SYNTHETIC_RF_SOURCE: list[dict] = [
    {"path": "example-pkg/_stack/proxmox",                             "name": "proxmox",      "depth": 0, "type": "provider",    "provider": "proxmox"},
    {"path": "example-pkg/_stack/proxmox/example-lab",                "name": "example-lab",  "depth": 1, "type": "environment", "provider": "proxmox"},
    {"path": "example-pkg/_stack/proxmox/example-lab/pve-nodes",      "name": "pve-nodes",    "depth": 2, "type": "group",       "provider": "proxmox"},
    {"path": "example-pkg/_stack/proxmox/example-lab/pve-nodes/pve-1","name": "pve-1",        "depth": 3, "type": "resource",    "provider": "proxmox", "has_terragrunt": True},
    {"path": "example-pkg/_stack/proxmox/example-lab/pve-nodes/pve-2","name": "pve-2",        "depth": 3, "type": "resource",    "provider": "proxmox", "has_terragrunt": True},
    {"path": "example-pkg/_stack/maas",                                "name": "maas",         "depth": 0, "type": "provider",    "provider": "maas"},
    {"path": "example-pkg/_stack/maas/example-lab",                    "name": "example-lab",  "depth": 1, "type": "environment", "provider": "maas"},
    {"path": "example-pkg/_stack/maas/example-lab/machines",          "name": "machines",     "depth": 2, "type": "group",       "provider": "maas"},
    {"path": "example-pkg/_stack/maas/example-lab/machines/node-1",   "name": "node-1",       "depth": 3, "type": "resource",    "provider": "maas",    "has_terragrunt": True},
    {"path": "example-pkg/_stack/maas/example-lab/machines/node-2",   "name": "node-2",       "depth": 3, "type": "resource",    "provider": "maas",    "has_terragrunt": True},
    {"path": "example-pkg/_stack/unifi",                               "name": "unifi",        "depth": 0, "type": "provider",    "provider": "unifi"},
    {"path": "example-pkg/_stack/unifi/example-lab",                   "name": "example-lab",  "depth": 1, "type": "environment", "provider": "unifi"},
    {"path": "example-pkg/_stack/unifi/example-lab/network",           "name": "network",      "depth": 2, "type": "resource",    "provider": "unifi",   "has_terragrunt": True},
    {"path": "example-pkg/_stack/unifi/example-lab/port-profile",      "name": "port-profile", "depth": 2, "type": "resource",    "provider": "unifi",   "has_terragrunt": True},
]

_RF_PROVIDER_BG: dict[str, str] = {
    "proxmox": "#7c2d12", "maas": "#14532d", "unifi": "#1e3a5f",
    "gcp": "#1d3461", "aws": "#7c4700", "azure": "#003e6b",
}


def _build_reactflow_elements(source_nodes: list[dict]) -> dict:
    """Compute a top-down tree layout and return React Flow nodes + edges.

    Positions are computed in Python so the component renders immediately
    without a client-side layout pass.
    """
    if not source_nodes:
        return {"nodes": [], "edges": []}

    NODE_W: float = 140.0
    NODE_H: float = 36.0
    H_GAP:  float = 24.0
    V_GAP:  float = 80.0

    # Build parent→children index
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for n in source_nodes:
        path = n["path"]
        if n["depth"] == 0:
            roots.append(path)
        else:
            parts = path.split("/")
            parent = "/".join(parts[:-1])
            children.setdefault(parent, []).append(path)

    # Bottom-up: compute each subtree's pixel width
    subtree_w: dict[str, float] = {}

    def compute_width(path: str) -> float:
        kids = children.get(path, [])
        if not kids:
            subtree_w[path] = NODE_W
        else:
            total = sum(compute_width(k) for k in kids) + H_GAP * (len(kids) - 1)
            subtree_w[path] = max(NODE_W, total)
        return subtree_w[path]

    for r in roots:
        compute_width(r)

    # Top-down: assign positions (cx = horizontal centre of the subtree)
    positions: dict[str, tuple[float, float]] = {}

    def assign_pos(path: str, cx: float, y: float) -> None:
        positions[path] = (cx - NODE_W / 2, y)
        kids = children.get(path, [])
        if not kids:
            return
        total = sum(subtree_w[k] for k in kids) + H_GAP * (len(kids) - 1)
        x = cx - total / 2
        for kid in kids:
            w = subtree_w[kid]
            assign_pos(kid, x + w / 2, y + NODE_H + V_GAP)
            x += w + H_GAP

    x = 0.0
    for r in roots:
        w = subtree_w[r]
        assign_pos(r, x + w / 2, 0.0)
        x += w + H_GAP

    rf_nodes: list[dict] = []
    rf_edges: list[dict] = []

    for n in source_nodes:
        path = n["path"]
        px, py = positions.get(path, (0.0, 0.0))
        provider = n.get("provider", "")
        bg = _RF_PROVIDER_BG.get(provider, "#1e293b")
        border = "#4ade80" if n.get("has_terragrunt") else "#475569"

        rf_nodes.append({
            "id": path,
            "position": {"x": px, "y": py},
            "data": {"label": n["name"], "provider": provider, "path": path, "depth": n["depth"]},
            "style": {
                "background": bg,
                "color": "#e2e8f0",
                "border": f"1px solid {border}",
                "borderRadius": "4px",
                "fontSize": "11px",
                "padding": "4px 8px",
                "width": NODE_W,
            },
        })
        if n["depth"] > 0:
            parts = path.split("/")
            parent_path = "/".join(parts[:-1])
            rf_edges.append({
                "id": f"e-{parent_path}->{path}",
                "source": parent_path,
                "target": path,
                "type": "smoothstep",
                "style": {"stroke": "#475569", "strokeWidth": 1},
            })

    return {"nodes": rf_nodes, "edges": rf_edges}


# Pre-built at import time so computed vars just filter, not re-layout.
_RF_DATA_CACHE: dict = {}
_RF_SYNTHETIC_DATA: dict = {}


def _init_reactflow_cache() -> None:
    global _RF_DATA_CACHE, _RF_SYNTHETIC_DATA
    _RF_DATA_CACHE    = _build_reactflow_elements(_ALL_NODES_CACHE)
    _RF_SYNTHETIC_DATA = _build_reactflow_elements(_SYNTHETIC_RF_SOURCE)


_init_reactflow_cache()

# ---------------------------------------------------------------------------
# Arch diagram layout builder — auto-derives components from live infra data
# ---------------------------------------------------------------------------

_ARCH_PROVIDER_ACCENT: dict[str, str] = {
    "proxmox": "#E07000",
    "maas":    "#7C3AED",
    "unifi":   "#4338CA",
    "gcp":     "#4285F4",
    "aws":     "#FF9900",
    "azure":   "#0078D4",
    "null":    "#6B7280",
}


def _drawio_shape(module_source_short: str, provider: str, config: dict) -> str:
    """Return draw.io shape style fragment for a leaf node.

    Lookup order:
    1. Exact key match in config['icon_map']
    2. Wildcard prefix match (keys ending in '*') in config['icon_map']
    3. Provider fallback in config['provider_icon_fallbacks']
    4. Generic rounded rectangle
    """
    icon_map: dict[str, str]  = config.get("icon_map", {})
    fallbacks: dict[str, str] = config.get("provider_icon_fallbacks", {})

    if module_source_short in icon_map:
        return icon_map[module_source_short]

    for key, val in icon_map.items():
        if key.endswith("*") and module_source_short.startswith(key[:-1]):
            return val

    if provider in fallbacks:
        return fallbacks[provider]

    return "rounded=1;"


def _build_arch_diagram_elements(
    nodes_cache: list[dict],
    deps_cache: dict[str, list[str]],
    config: dict,
) -> dict:
    """Compute React Flow nodes + edges for the nested architectural diagram."""
    if not config:
        return {"nodes": [], "edges": []}

    direction   = config.get("direction", "LR")
    min_depth   = int(config.get("min_depth", 2))
    max_depth   = int(config.get("max_depth", 4))
    show_conns  = bool(config.get("show_connections", True))
    layers_cfg  = sorted(config.get("layers", []), key=lambda l: l.get("order", 99))
    prov_styles = config.get("provider_styles", {})

    if min_depth > max_depth:
        min_depth, max_depth = max_depth, min_depth

    shown = [n for n in nodes_cache if min_depth <= n["depth"] <= max_depth]
    node_by_path: dict[str, dict] = {n["path"]: n for n in shown}

    def _depth1_prefix(path: str) -> str:
        parts = path.split("/")
        return "/".join(parts[:3]) if len(parts) >= 3 else path

    def _match_zone(path: str) -> str:
        pfx = _depth1_prefix(path)
        for lc in layers_cfg:
            for p in lc.get("path_prefixes", []):
                if pfx == p or path.startswith(p + "/") or path == p:
                    return lc["id"]
        return "_other"

    children_by_path: dict[str, list[str]] = {}
    for n in shown:
        if n["depth"] > min_depth:
            parent_path = "/".join(n["path"].split("/")[:-1])
            if parent_path in node_by_path:
                children_by_path.setdefault(parent_path, []).append(n["path"])

    zone_to_tops: dict[str, list[str]] = {lc["id"]: [] for lc in layers_cfg}
    zone_to_tops["_other"] = []
    for n in shown:
        if n["depth"] == min_depth:
            zid = _match_zone(n["path"])
            zone_to_tops.setdefault(zid, []).append(n["path"])

    LEAF_W    = 160.0;  LEAF_H    = 38.0
    CHILD_GAP = 10.0;   NODE_PAD  = 14.0;  HEADER_H  = 26.0
    ZONE_GAP  = 28.0;   ZONE_PAD  = 18.0

    node_sizes: dict[str, tuple] = {}

    def _compute_size(path: str) -> tuple:
        if path in node_sizes:
            return node_sizes[path]
        kids = children_by_path.get(path, [])
        if not kids:
            node_sizes[path] = (LEAF_W, LEAF_H)
            return LEAF_W, LEAF_H
        child_sizes = [_compute_size(k) for k in kids]
        inner_w = max(w for w, h in child_sizes)
        inner_h = sum(h for w, h in child_sizes) + CHILD_GAP * (len(kids) - 1)
        w = inner_w + 2 * NODE_PAD
        h = HEADER_H + NODE_PAD + inner_h + NODE_PAD
        node_sizes[path] = (w, h)
        return w, h

    for path in node_by_path:
        _compute_size(path)

    def _zone_size(top_paths: list) -> tuple:
        if not top_paths:
            return (LEAF_W + 2 * ZONE_PAD, LEAF_H + 2 * ZONE_PAD + HEADER_H)
        sizes = [node_sizes[p] for p in top_paths]
        inner_w = max(w for w, h in sizes)
        inner_h = sum(h for w, h in sizes) + CHILD_GAP * (len(sizes) - 1)
        return (inner_w + 2 * ZONE_PAD, HEADER_H + ZONE_PAD + inner_h + ZONE_PAD)

    rf_nodes: list[dict] = []
    rf_edges: list[dict] = []

    active_zones = []
    for lc in layers_cfg:
        tops = zone_to_tops.get(lc["id"], [])
        if tops:
            active_zones.append((lc, tops))
    other_tops = zone_to_tops.get("_other", [])
    if other_tops:
        active_zones.append((
            {"id": "_other", "label": "Other", "color": "#F8FAFC", "stroke": "#94A3B8"},
            other_tops,
        ))

    def _place_subtree(path: str, rel_x: float, rel_y: float, parent_rf_id: str) -> None:
        n    = node_by_path[path]
        w, h = node_sizes[path]
        kids = children_by_path.get(path, [])
        provider = n.get("provider", "")
        pstyle   = prov_styles.get(provider, {})
        accent   = pstyle.get("color", _ARCH_PROVIDER_ACCENT.get(provider, "#64748B"))

        is_container = bool(kids)
        rf_node: dict = {
            "id":         path,
            "parentNode": parent_rf_id,
            "extent":     "parent",
            "position":   {"x": rel_x, "y": rel_y},
            "data":       {"label": n["name"], "provider": provider,
                           "path": path, "paths": [path]},
            "style": {"width": w, "height": h, "borderRadius": "6px"},
        }
        if is_container:
            rf_node["type"] = "group"
            rf_node["style"].update({
                "background": accent + "0D",
                "border":     f"1.5px solid {accent}88",
                "fontSize":   "11px", "fontWeight": "600", "color": accent,
            })
        else:
            rf_node["style"].update({
                "background": accent + "1A", "border": f"2px solid {accent}",
                "fontSize": "11px", "fontWeight": "500", "color": accent,
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "textAlign": "center", "padding": "4px 8px", "cursor": "pointer",
            })
        rf_nodes.append(rf_node)

        cy = HEADER_H + NODE_PAD
        for kid in kids:
            _, kh = node_sizes[kid]
            _place_subtree(kid, NODE_PAD, cy, path)
            cy += kh + CHILD_GAP

    zone_cursor = 0.0
    for lc, top_paths in active_zones:
        zid  = lc["id"]
        zw, zh = _zone_size(top_paths)
        zx = zone_cursor if direction == "LR" else 0.0
        zy = 0.0 if direction == "LR" else zone_cursor

        rf_nodes.append({
            "id": f"__zone__{zid}", "type": "group",
            "position": {"x": zx, "y": zy},
            "data": {"label": lc.get("label", zid)},
            "style": {
                "width": zw, "height": zh,
                "background": lc.get("color", "#F8FAFC"),
                "border": f"2px solid {lc.get('stroke', '#94A3B8')}",
                "borderRadius": "10px",
                "fontSize": "13px", "fontWeight": "700",
                "color": lc.get("stroke", "#334155"),
            },
        })

        cy = HEADER_H + ZONE_PAD
        for path in top_paths:
            _, ph = node_sizes[path]
            _place_subtree(path, ZONE_PAD, cy, f"__zone__{zid}")
            cy += ph + CHILD_GAP

        zone_cursor += (zw if direction == "LR" else zh) + ZONE_GAP

    if show_conns:
        leaf_paths = {n["path"] for n in shown if n["depth"] == max_depth}
        seen_edges: set[tuple[str, str]] = set()
        for src_path, targets in deps_cache.items():
            if src_path not in leaf_paths:
                continue
            for tgt_path in targets:
                if tgt_path not in leaf_paths or tgt_path == src_path:
                    continue
                key = (src_path, tgt_path)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                rf_edges.append({
                    "id": f"arch-dep-{src_path}--{tgt_path}",
                    "source": src_path, "target": tgt_path,
                    "type": "smoothstep",
                    "style": {"stroke": "#94A3B8", "strokeWidth": 1.5},
                    "markerEnd": {"type": "arrowclosed", "color": "#94A3B8"},
                })

    return {"nodes": rf_nodes, "edges": rf_edges}


# ---------------------------------------------------------------------------
# draw.io XML export
# ---------------------------------------------------------------------------

def _generate_drawio_xml(
    nodes_cache: list[dict],
    deps_cache: dict[str, list[str]],
    config: dict,
) -> str:
    """Generate draw.io XML using drawpyo with cloud-specific shape stencils."""
    import tempfile
    import os
    import drawpyo

    direction   = config.get("direction", "LR")
    min_depth   = int(config.get("min_depth", 2))
    max_depth   = int(config.get("max_depth", 4))
    show_conns  = bool(config.get("show_connections", True))
    layers_cfg  = sorted(config.get("layers", []), key=lambda l: l.get("order", 99))
    prov_styles = config.get("provider_styles", {})

    if min_depth > max_depth:
        min_depth, max_depth = max_depth, min_depth

    shown = [n for n in nodes_cache if min_depth <= n["depth"] <= max_depth]
    node_by_path: dict[str, dict] = {n["path"]: n for n in shown}

    def _depth1_prefix(path: str) -> str:
        parts = path.split("/")
        return "/".join(parts[:3]) if len(parts) >= 3 else path

    def _match_zone(path: str) -> str:
        pfx = _depth1_prefix(path)
        for lc in layers_cfg:
            for p in lc.get("path_prefixes", []):
                if pfx == p or path.startswith(p + "/") or path == p:
                    return lc["id"]
        return "_other"

    children_by_path: dict[str, list[str]] = {}
    for n in shown:
        if n["depth"] > min_depth:
            parent_path = "/".join(n["path"].split("/")[:-1])
            if parent_path in node_by_path:
                children_by_path.setdefault(parent_path, []).append(n["path"])

    zone_to_tops: dict[str, list[str]] = {lc["id"]: [] for lc in layers_cfg}
    zone_to_tops["_other"] = []
    for n in shown:
        if n["depth"] == min_depth:
            zid = _match_zone(n["path"])
            zone_to_tops.setdefault(zid, []).append(n["path"])

    LEAF_W    = 160;  LEAF_H    = 38
    CHILD_GAP = 10;   NODE_PAD  = 14;  HEADER_H  = 26
    ZONE_GAP  = 28;   ZONE_PAD  = 18

    node_sizes: dict[str, tuple] = {}

    def _compute_size(path: str) -> tuple:
        if path in node_sizes:
            return node_sizes[path]
        kids = children_by_path.get(path, [])
        if not kids:
            node_sizes[path] = (LEAF_W, LEAF_H)
            return LEAF_W, LEAF_H
        child_sizes = [_compute_size(k) for k in kids]
        inner_w = max(w for w, h in child_sizes)
        inner_h = sum(h for w, h in child_sizes) + CHILD_GAP * (len(kids) - 1)
        w = inner_w + 2 * NODE_PAD
        h = HEADER_H + NODE_PAD + inner_h + NODE_PAD
        node_sizes[path] = (w, h)
        return w, h

    for path in node_by_path:
        _compute_size(path)

    def _zone_size(top_paths: list) -> tuple:
        if not top_paths:
            return (LEAF_W + 2 * ZONE_PAD, LEAF_H + 2 * ZONE_PAD + HEADER_H)
        sizes = [node_sizes[p] for p in top_paths]
        inner_w = max(w for w, h in sizes)
        inner_h = sum(h for w, h in sizes) + CHILD_GAP * (len(sizes) - 1)
        return (inner_w + 2 * ZONE_PAD, HEADER_H + ZONE_PAD + inner_h + ZONE_PAD)

    tmp = tempfile.mktemp(suffix=".drawio")
    try:
        dfile = drawpyo.File()
        dfile.file_path = os.path.dirname(tmp)
        dfile.file_name = os.path.basename(tmp)
        page  = drawpyo.Page(file=dfile)

        drawpyo_objs: dict[str, object] = {}

        active_zones = []
        for lc in layers_cfg:
            tops = zone_to_tops.get(lc["id"], [])
            if tops:
                active_zones.append((lc, tops))
        other_tops = zone_to_tops.get("_other", [])
        if other_tops:
            active_zones.append((
                {"id": "_other", "label": "Other", "color": "#F8FAFC", "stroke": "#94A3B8"},
                other_tops,
            ))

        zone_cursor = 0
        for lc, top_paths in active_zones:
            zid = lc["id"]
            zw, zh = _zone_size(top_paths)
            zx = zone_cursor if direction == "LR" else 0
            zy = 0 if direction == "LR" else zone_cursor

            fill   = lc.get("color",  "#F8FAFC").lstrip("#")
            stroke = lc.get("stroke", "#94A3B8").lstrip("#")
            zone_obj = drawpyo.diagram.Object(
                page=page,
                value=lc.get("label", zid),
                width=zw, height=zh,
                position=(zx, zy),
            )
            zone_obj.apply_style_string(
                f"swimlane;startSize={HEADER_H};fillColor=#{fill};"
                f"strokeColor=#{stroke};fontStyle=1;fontSize=13;rounded=1;arcSize=4;"
            )
            drawpyo_objs[f"__zone__{zid}"] = zone_obj

            def _place_drawpyo(path: str, rel_x: int, rel_y: int, parent_obj: object) -> None:
                n    = node_by_path[path]
                w, h = node_sizes[path]
                kids = children_by_path.get(path, [])
                provider = n.get("provider", "")
                pstyle   = prov_styles.get(provider, {})
                accent   = pstyle.get("color", _ARCH_PROVIDER_ACCENT.get(provider, "#64748B"))
                a_hex    = accent.lstrip("#")
                mss      = n.get("module_source_short", "")

                obj = drawpyo.diagram.Object(
                    page=page,
                    value=n["name"],
                    width=w, height=h,
                )
                obj.parent = parent_obj
                obj.position_rel_to_parent = (rel_x, rel_y)
                if kids:
                    obj.apply_style_string(
                        f"swimlane;startSize={HEADER_H};"
                        f"fillColor=#{a_hex}11;strokeColor=#{a_hex}88;"
                        f"fontStyle=1;fontSize=11;rounded=1;arcSize=4;"
                    )
                else:
                    shape_frag = _drawio_shape(mss, provider, config)
                    obj.apply_style_string(
                        f"{shape_frag}fillColor=#{a_hex}1A;strokeColor=#{a_hex};"
                        f"fontColor=#{a_hex};fontSize=10;fontStyle=1;"
                        f"verticalLabelPosition=bottom;verticalAlign=top;"
                        f"align=center;rounded=1;arcSize=30;"
                    )
                drawpyo_objs[path] = obj

                cy = HEADER_H + NODE_PAD
                for kid in kids:
                    _, kh = node_sizes[kid]
                    _place_drawpyo(kid, NODE_PAD, cy, obj)
                    cy += kh + CHILD_GAP

            cy = HEADER_H + ZONE_PAD
            for path in top_paths:
                _, ph = node_sizes[path]
                _place_drawpyo(path, ZONE_PAD, cy, zone_obj)
                cy += ph + CHILD_GAP

            zone_cursor += (zw if direction == "LR" else zh) + ZONE_GAP

        if show_conns:
            leaf_paths = {n["path"] for n in shown if n["depth"] == max_depth}
            seen_edges: set[tuple[str, str]] = set()
            for src_path, targets in deps_cache.items():
                if src_path not in leaf_paths or src_path not in drawpyo_objs:
                    continue
                for tgt_path in targets:
                    if (tgt_path not in leaf_paths or tgt_path == src_path
                            or tgt_path not in drawpyo_objs):
                        continue
                    key = (src_path, tgt_path)
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    edge = drawpyo.diagram.Edge(
                        page=page,
                        source=drawpyo_objs[src_path],
                        target=drawpyo_objs[tgt_path],
                    )
                    edge.strokeColor = "#94A3B8"
                    edge.strokeWidth = 1.5
                    edge.endArrow    = "block"

        dfile.write()
        with open(tmp, "r", encoding="utf-8") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Arch diagram export format registry
# ---------------------------------------------------------------------------

# Default server-side directory for saved export files.
# Path(__file__) is homelab_gui.py; four .parent calls reach de3-gui-pkg/.
_ARCH_CONFIG_DIR:        Path = Path(__file__).parent.parent.parent.parent / "_config"
_ARCH_EXPORT_DEFAULT_DIR: str = str(_ARCH_CONFIG_DIR / "tmp")

# Metadata for each export format. The toolbar builds its "Export" menu from this list.
# 'open_url_template' is optional; if present, an "Open in browser" link is also shown.
# Use {api_url} as the URL-encoded API endpoint placeholder.
_ARCH_EXPORT_FORMATS: list[dict] = [
    {
        "id":       "drawio",
        "label":    "draw.io / diagrams.net (.drawio)",
        "filename": "arch-diagram.drawio",
        "mime":     "application/xml",
        "open_url_template": "https://app.diagrams.net/?url={api_url}",
    },
]

# Generator functions: format id → callable(nodes_cache, deps_cache, config) -> str
_ARCH_GENERATORS: dict[str, Any] = {
    "drawio": _generate_drawio_xml,
}


# Maximum depth across all infra nodes — drives the Depth slider range.
# Falls back to 4 when no infra is available (matches synthetic data depth).
_MAX_DEPTH: int = max((n["depth"] for n in _ALL_NODES_CACHE), default=4)


# ---------------------------------------------------------------------------
# Test state helper — reads .test_state.yml written by the Ansible test runner
# and applies the GUI state overrides to the given AppState instance.
# Called at the end of on_load; the temp file is removed after reading.
# ---------------------------------------------------------------------------

def _apply_test_state(state: "AppState") -> None:
    """Apply .test_state.yml overrides to state if the file exists."""
    if not _TEST_STATE_FILE.exists():
        return
    try:
        raw = yaml.safe_load(_TEST_STATE_FILE.read_text()) or {}
        ts = raw.get("gui_state", {})

        if "viz_framework" in ts:
            state.viz_framework = ts["viz_framework"]
        if "left_view" in ts:
            state.left_view = ts["left_view"]
        if "tree_mode" in ts:
            state.tree_mode = ts["tree_mode"]
        if "active_provider_tab" in ts:
            state.active_provider_tab = ts["active_provider_tab"]

        # Apply provider visibility overrides
        if "providers" in ts:
            updated = dict(state.provider_filters)
            for p in ts["providers"]:
                pname = p.get("provider-name", "")
                if pname:
                    updated[pname] = p.get("show", True)
            state.provider_filters = updated

        # Select a node and auto-expand its ancestors
        sel = ts.get("selected_node", "")
        if sel:
            state.selected_node_path = sel
            state.hcl_content, state.hcl_file_path = _read_hcl_file(sel)
            state.unit_hcl_path = state.hcl_file_path
            parts = sel.split("/")
            # Expand every ancestor prefix so the node is visible in the tree
            ancestors = ["/".join(parts[:i]) for i in range(1, len(parts))]
            current = list(state.expanded_paths)
            for anc in ancestors:
                if anc not in current:
                    current.append(anc)
            state.expanded_paths = current

        # Browser state overrides
        if "browser_profile" in ts:
            state.browser_profile = ts["browser_profile"]
        # Write a marker file so ALL Reflex worker processes (which don't share
        # in-process memory) can detect that a test state was recently applied.
        try:
            _TEST_APPLIED_MARKER.write_text(str(_time_module.time()))
        except Exception:
            pass
    except Exception:
        pass
    finally:
        _TEST_STATE_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AppState(rx.State):
    """Application state."""

    all_nodes: list[dict] = []
    expanded_paths: list[str] = []
    provider_filters: dict = {}
    package_filters: dict = {}
    region_filters: dict = {}
    env_filters: dict = {}
    wave_filters: dict = {}
    explorer_root: str = "infra"   # "infra" | "modules" | "packages"
    modules_nodes: list[dict] = []
    modules_expanded_paths: list[str] = []
    packages_data: list[PackageInfo] = []
    packages_expanded_names: list[str] = []   # names of currently-expanded package cards
    ext_package_repos: list[dict] = []         # [{name, url}] from state/current.yaml
    pkg_repos_config: list[dict] = []   # [{name, url, description}] — display only
    fw_repos_refreshing: bool = False
    pkg_sync_running: bool = False
    pkg_sync_output: str = ""           # full stdout+stderr from last pkg-mgr sync
    pkg_sync_ok: bool = True            # exit code of last sync
    left_view: str = "tree"
    supported_providers: list[dict] = []
    is_loading: bool = True
    inventory_refresh_counter: int = 0  # bumped after inventory refresh; triggers var recompute
    dag_refresh_status: str = "idle"   # "idle" | "running" | "error"
    dag_refresh_error: str = ""
    clipboard_message: str = ""          # status/error shown in toolbar (rename, delete, etc.); empty = hidden
    clipboard_message_is_error: bool = False
    delete_dialog_open: bool = False     # remove-unit confirmation dialog (rm + YAML only)
    delete_pending_path: str = ""        # node path of the unit to remove
    delete_pending_mode: str = ""        # "file" or "recursive"
    destroy_dialog_open: bool = False    # terragrunt destroy confirmation dialog
    destroy_pending_path: str = ""       # node path for the pending destroy
    destroy_pending_mode: str = ""       # "unit" or "recursive"
    taint_dialog_open: bool = False      # terragrunt taint confirmation dialog
    taint_pending_path: str = ""         # node path for the pending taint
    taint_pending_mode: str = ""         # "unit" or "recursive"
    unlock_file_dialog_open: bool = False   # direct lock-file delete confirmation dialog
    unlock_file_pending_path: str = ""      # node path for the pending lock-file delete
    unlock_file_pending_mode: str = ""      # "unit" or "recursive"
    rename_dialog_open: bool = False        # in-place rename dialog
    rename_pending_path: str = ""          # node path of the directory being renamed
    rename_pending_name: str = ""          # editable new name (last path segment)
    rename_error: str = ""                 # validation error shown inside dialog
    wave_run_dialog_open: bool = False      # wave destroy confirmation dialog
    wave_run_pending_name: str = ""         # wave name for the pending run
    wave_run_pending_mode: str = ""         # "apply" or "destroy"
    run_all_waves_dialog_open: bool = False  # "run all waves" confirmation dialog
    wave_folder_run_dialog_open: bool = False  # folder-level destroy confirmation dialog
    wave_folder_run_pending_path: str = ""     # folder_path for the pending folder run
    wave_folder_run_pending_mode: str = ""     # "apply" or "destroy"
    object_viewer_mode: str = "params"   # "params" or "waves"
    # Maps wave name → {"status": "ok"|"fail"|"none", "log_path": str}
    wave_log_statuses: dict[str, dict] = {}
    # ANSI log search navigation (index of the currently highlighted match)
    ansi_search_idx: int = 0
    apply_dialog_open: bool = False      # (unused — apply goes direct to terminal)
    apply_pending_path: str = ""         # (unused — kept to avoid state schema churn)
    # Refactor panel (unit-mgr CLI) — floating window opened via right-click
    float_refactor_open: bool = False      # transient; not persisted
    refactor_show_details: bool = False    # toggle unit-mgr detail explanation
    refactor_operation: str = "move"       # "copy" or "move"
    refactor_src_path: str = ""            # pre-filled from selected node
    refactor_dst_path: str = ""            # user types this
    refactor_preview_result: dict = {}            # parsed JSON from --dry-run
    refactor_preview_external_deps: list[dict] = []  # external_deps list from preview
    refactor_running: bool = False                # True while execute is in progress
    refactor_result: dict = {}                    # parsed JSON from actual run
    refactor_error: str = ""                      # non-empty if run failed
    refactor_status_op: str = ""                  # status bar row 1: current operation
    refactor_status_detail: str = ""              # status bar row 2: progress / log detail
    refactor_status_exit: str = ""                # status bar row 3: exit result (✓/✗)
    refactor_status_summary: str = ""             # status bar row 4: counts summary
    # pkg-mgr rename / copy dialog
    pkg_op_open: bool = False
    pkg_op_mode: str = ""           # "rename" or "copy"
    pkg_op_src: str = ""
    pkg_op_dst: str = ""
    pkg_op_state_flag: str = ""     # "skip" or "with" (copy only)
    pkg_op_running: bool = False
    pkg_op_output: str = ""
    pkg_op_error: str = ""
    available_roles: list[str] = []    # sorted role tags from inventory (e.g. "role_worker_vm")
    node_name_roles: dict = {}         # {node_name: [role_tag, ...]}
    selected_roles: list[str] = []     # active role filters; empty = All Roles
    # Help menu dialog
    help_dialog_open: bool = False
    help_dialog_title: str = ""
    help_dialog_body: str = ""

    # ── Framework Repos view ────────────────────────────────────────────────
    framework_repos_data:         dict = {}   # raw repos dict from known-fw-repos.yaml
    fw_repos_git:         str  = "show"    # Git section: hide / show
    fw_repos_config_pkg:  str  = "show"    # Config Package section: hide / show
    fw_repos_labels:      str  = "show"    # Labels section: hide / show
    fw_repos_inaccessible: str = "normal"  # how to treat inaccessible repos: normal/red/black/hide
    fw_repos_zoom:         int  = 100    # diagram zoom level in percent (10–fw_repos_zoom_max)
    fw_repos_backend:      str  = "summary"  # backend display: hide / summary (bucket only) / all (full config)
    fw_repos_packages:     str  = "a-z"     # packages display: hide / a-z / from-code

    # Active visualization framework for the left panel (key from VIZ_FRAMEWORKS)
    viz_framework: str = "reflex"

    # Arch diagram — live toolbar controls (seeded from arch_diagram_config.yaml)
    arch_direction:        str  = _ARCH_DIAGRAM_CONFIG.get("direction", "LR")
    arch_min_depth:        int  = int(_ARCH_DIAGRAM_CONFIG.get("min_depth", 2))
    arch_max_depth:        int  = int(_ARCH_DIAGRAM_CONFIG.get("max_depth", 4))
    arch_show_connections: bool = bool(_ARCH_DIAGRAM_CONFIG.get("show_connections", True))
    arch_export_dir:       str  = _ARCH_EXPORT_DEFAULT_DIR
    arch_export_status:    str  = ""

    # Tree display mode: "separated" (one subtree per provider) or "merged" (unified)
    tree_mode: str = "separated"
    merged_nodes_base: list[dict] = []   # pre-built on load, drives merged tree
    merged_expanded_paths: list[str] = []

    # Selected node — drives the right panel
    selected_node_path: str = ""

    # Active provider tab in right panel ("" = All)
    active_provider_tab: str = ""

    # Width of the left (explorer) panel as a percentage of the main area.
    # Persisted to current.yaml and restored on load.
    left_panel_width_pct: int = 50

    # Appearance — which controls to pin as standalone widgets in the controls bar.
    panel_show_view_selector: bool = True
    panel_show_merged:        bool = True
    panel_show_depth:         bool = True
    show_full_module_name:    bool = False  # Show full module path in tree vs. basename only
    show_wave_numbers:        bool = False  # Append "(N)" wave number after node name in tree
    wave_show_start_time:     bool = False
    wave_show_end_time:       bool = False
    wave_show_duration:       bool = False
    wave_show_age:            bool = False
    wave_show_log_update:     bool = False
    wave_highlight_recent:    bool = True   # highlight the most recently updated wave row
    recent_wave_name:         str  = ""     # wave name whose log was updated within last N secs (config: wave_recent_highlight_secs)
    auto_select_recent_unit:  bool = False  # auto-select the unit most recently changed by an apply
    recent_unit_path:         str  = ""     # path of the unit most recently seen by local_state_watcher
    # Per-unit build status derived from GCS state bucket + run logs.
    # Maps node path → "ok" | "fail" | "none" | "destroyed".
    # Populated by do_refresh_unit_build_statuses() (GCS scan) and local_state_watcher() (local cache scan).
    unit_build_statuses:          dict[str, str] = {}
    # GCS mtime cache: maps unit_path → ISO-8601 mtime string from "gsutil ls -l".
    # Used by do_refresh_unit_build_statuses to skip downloading unchanged state files.
    gcs_state_mtimes:             dict[str, str] = {}
    show_unit_build_status:       bool = False   # show coloured status dot on leaf units in tree
    is_refreshing_build_statuses: bool = False   # True while do_refresh_unit_build_statuses is running
    build_status_error:           str  = ""      # non-empty when last refresh failed; shown below button
    local_state_watcher_active:   bool = False   # True while local_state_watcher loop is alive
    # Auto-refresh unit statuses from unit-state.yaml (written by local_state_watcher + validate).
    # When enabled, the local_state_watcher reads the YAML and pushes updates to the UI
    # without the user pressing "⟳ Refresh".
    #   unit_status_auto_refresh_secs = 0  → trigger only on file-change (mtime check)
    #   unit_status_auto_refresh_secs = N  → also trigger every N seconds regardless of mtime
    unit_status_auto_refresh:      bool = False  # enable auto-refresh from unit-state.yaml
    unit_status_auto_refresh_secs: int  = 30     # interval in seconds (0 = on-change only)
    # GCS status sync cursors — ISO timestamps of last sync (empty = never synced).
    unit_status_sync_after: str = ""
    wave_status_sync_after: str = ""
    # Track whether each GCS sync background task is currently running.
    gcs_unit_sync_running: bool = False
    gcs_wave_sync_running: bool = False
    # GCS-derived wave statuses for sessions without a local run.log entry.
    # Maps wave_name → status dict with keys: status, phase, updated_at, finished_at.
    gcs_wave_statuses: dict[str, dict] = {}
    had_running_wave:       bool = False   # True when last wave-log poll saw at least one running wave
    terminal_hide_initial_cmd: bool = True  # suppress display of auto-sent commands in terminal
    terminal_backend: str = "ttyd" if _TTYD_AVAILABLE else "embedded"  # "embedded" | "ttyd" | native terminal id
    ttyd_port: int = 0                     # port of the running ttyd process (0 = none)
    cy_show_dependencies: bool = False  # show dependency arrows in Nested Networks view
    cy_color_by_wave:     bool = False  # color nodes by wave instead of provider
    # Waves popup display mode: "list" = flat wave checklist, "folder" = tree of infra paths.
    waves_view_mode: str = "list"
    # Collapsed folder paths in the waves folder view.
    # Empty by default = all folders expanded.  Not persisted — resets each session
    # so stale state can never hide a wave after wave names change.
    wave_folder_collapsed: list[str] = []
    # Pixel width/height of the panel-divider drag hit-target (4–24 px).
    resizer_drag_width: int = 5
    # Cytoscape wheel/zoom sensitivity (0.05–1.0; default 0.3).
    cy_wheel_sensitivity: float = 0.3

    # Top row height as % of the total panel area.
    top_row_height_pct: int = 60

    # Maximized panel id: "" = normal 4-panel layout,
    # or "top-left" | "bottom-left" | "top-right" | "bottom-right"
    maximized_panel: str = ""

    # Bottom-left: content of the selected node's terragrunt.hcl (empty = none)
    hcl_content: str = ""
    # Absolute path of the file shown in the bottom-left panel
    hcl_file_path: str = ""
    # Absolute path of the selected node's unit HCL file (never overwritten by config_data mode)
    unit_hcl_path: str = ""
    # Which file the viewer shows: "unit_file" (terragrunt.hcl) | "config_data" (stack config yaml)
    file_viewer_mode: str = "unit_file"
    ui_theme: str = "light"
    # In merged mode: the provider whose unit file is currently shown (e.g. "proxmox")
    file_viewer_provider: str = ""

    # Bottom-right: directory path for the embedded terminal ("" = no terminal)
    shell_cwd: str = ""
    # Optional command written to the PTY once bash has initialised (e.g. ssh login)
    shell_initial_cmd: str = ""
    # Optional label shown in the terminal panel header (e.g. "tail: run.log"); "" = show cwd
    shell_label: str = ""

    # Depth limit for all views.
    # 0 = "All" (show every node); k > 0 = show nodes where node.depth ≤ k.
    # Default 1 = show depth 0 and 1 (root + first child level), matching the
    # original tree behaviour where only depth-0 paths are in expanded_paths.
    depth_limit: int = 1

    # Context menu state — populated when a tree node is right-clicked.
    # Flat list of rows (row_type: separator | group_label | item) for rx.foreach.
    ctx_menu_path: str = ""
    ctx_menu_rows: list[dict] = []

    # Unit-params display options
    hide_special_params: bool = False
    hide_provider_underscore_params: bool = False
    param_wrap_values: bool = False  # Wrap long values instead of clipping with ellipsis

    # File viewer — remembered editor choice
    selected_editor_id: str = ""

    # Inline Monaco editor state
    file_editor_active: bool = False    # True = Monaco editor is shown instead of read-only pre
    file_editor_draft: str = ""         # Live content in the editor (separate from hcl_content)
    file_editor_save_error: str = ""    # Non-empty = write failed; shown inline

    # File viewer search — one query per mode, shown/maintained independently
    unit_file_search_query: str = ""    # active when file_viewer_mode == "unit_file"
    config_data_search_query: str = ""  # active when file_viewer_mode == "config_data"
    # Message shown in the file viewer content area when hcl_content is empty
    file_viewer_status_msg: str = "Select a node to view its file"
    # When True, node path placed in config-data search is wrapped in double quotes
    # (matches how YAML config_params keys appear in the file as quoted strings)
    config_data_quote_path: bool = _DEFAULT_CONFIG_DATA_QUOTE_PATH
    file_search_smooth_scroll: bool = False     # animate scroll when navigating search matches
    file_search_case_sensitive: bool = False    # case-sensitive search toggle
    file_viewer_render_markdown: bool = True    # render .md files as formatted markdown
    file_viewer_show_line_numbers: bool = False  # show line numbers in the file viewer
    file_search_match_count: int = 0  # number of matches for current search query
    # Unit params search
    unit_params_search: str = ""
    # Inline param editing dialog
    param_edit_dialog_open:  bool = False
    param_edit_provider:     str  = ""   # e.g. "proxmox"
    param_edit_config_key:   str  = ""   # provider-inclusive config_params key
    param_edit_param_key:    str  = ""   # YAML key being edited
    param_edit_draft:        str  = ""   # current text in the input
    param_edit_is_inherited: bool = False  # True = param came from ancestor, not this node
    param_edit_error:        str  = ""   # shown in dialog on save failure

    # Explorer search filter (not persisted — transient per session)
    explorer_search: str = ""

    # External browser: Chrome profile dir name, "default" (xdg-open), "playwright", or "none".
    browser_profile: str = "playwright"
    chrome_profiles: list[dict] = []

    # Unit detail popup — floats over the UI and tracks the selected node.
    # Visible when show_unit_popup is True (checkbox in Appearance menu).
    # Moveable (JS drag on header) and resizable (CSS resize handle).
    show_unit_popup:        bool = False   # Appearance checkbox — persisted
    hover_popup_open:       bool = False   # actual popup visibility (can be closed with ✕)
    hover_popup_node_path:  str  = ""      # path of the node shown in the popup
    hover_popup_unit_state: dict = {}      # unit-state.yaml data for hover_popup_node_path
    hover_popup_params:     list[dict] = []  # _get_unit_params_flat rows for hover_popup_node_path

    # ── Status bar ───────────────────────────────────────────────────────
    show_status_bar: bool = True   # persisted; reserve permanent strip at bottom for status

    # ── Panel layout mode ────────────────────────────────────────────────
    # "4-panels" | "floating" | "tabbed"  — persisted
    panel_mode:               str  = "4-panels"
    tabbed_panel_active:      str  = "file-viewer"   # active tab in tabbed mode — persisted
    float_file_viewer_open:    bool = True    # persisted; Panels menu checkbox
    float_terminal_open:       bool = True
    float_object_viewer_open:  bool = True
    # Saved positions — restored to CSS vars on init so panels reappear where left
    float_fv_saved_x:   str = ""   # e.g. "480px"  (empty = use default centre calc)
    float_fv_saved_y:   str = ""
    float_term_saved_x: str = ""
    float_term_saved_y: str = ""
    float_ov_saved_x:   str = ""
    float_ov_saved_y:   str = ""

    # ── Appearance menu accordion section open/closed state (persisted) ──
    appear_s_controls: bool = True   # "Show in controls bar" — open by default
    appear_s_infra:    bool = True   # "Infra tree"
    appear_s_wave:     bool = False
    appear_s_file:      bool = False
    appear_s_popup:     bool = False
    appear_s_terminal:  bool = False
    appear_s_params:    bool = False
    appear_s_networks:  bool = False
    appear_s_layout:    bool = False
    appear_s_theme:     bool = False
    appear_s_fw_repos:  bool = False

    # -----------------------------------------------------------------------
    # Computed vars
    # -----------------------------------------------------------------------

    @rx.var
    def fw_repos_iframe_src(self) -> str:
        return (
            f"/fw_repos_mermaid_viewer.html"
            f"?backendPort={_BACKEND_PORT}"
            f"&git={self.fw_repos_git}&configPkg={self.fw_repos_config_pkg}&labels={self.fw_repos_labels}"
            f"&backend={self.fw_repos_backend}&packages={self.fw_repos_packages}"
            f"&inaccessible={self.fw_repos_inaccessible}&zoom={self.fw_repos_zoom}"
        )

    @rx.var
    def top_row_height_style(self) -> str:
        """CSS height string for the top row panels."""
        return f"{self.top_row_height_pct}%"

    @rx.var
    def app_status_message(self) -> str:
        """Non-empty while the app is still initialising (shown in startup status banner).

        "Initializing…"                        — on_load hasn't finished (is_loading=True)
        "Refreshing inventory…"                — inventory refresh not yet complete
        "Refreshing inventory + syncing GCS…"  — inventory pending AND a GCS sync running
        "Syncing GCS status (unit + wave)…"   — both GCS syncs running
        "Syncing GCS unit status…"             — only unit sync running
        "Syncing GCS wave status…"             — only wave sync running
        ""                                      — fully ready; banner is hidden
        """
        if self.is_loading:
            return "Initializing\u2026"
        inv_pending  = self.inventory_refresh_counter == 0
        unit_syncing = self.gcs_unit_sync_running
        wave_syncing = self.gcs_wave_sync_running
        if inv_pending:
            if unit_syncing or wave_syncing:
                return "Refreshing inventory + syncing GCS\u2026"
            return "Refreshing inventory\u2026"
        if unit_syncing and wave_syncing:
            return "Syncing GCS status (unit + wave)\u2026"
        if unit_syncing:
            return "Syncing GCS unit status\u2026"
        if wave_syncing:
            return "Syncing GCS wave status\u2026"
        return ""

    @rx.var
    def app_activity_active(self) -> bool:
        """True while any startup/sync activity is in progress (status bar highlight gate)."""
        return self.app_status_message != ""

    @rx.var
    def shell_cwd_display(self) -> str:
        """shell_cwd trimmed to the path after infra/ for compact display."""
        if not self.shell_cwd:
            return ""
        marker = "/infra/"
        idx = self.shell_cwd.find(marker)
        if idx != -1:
            return self.shell_cwd[idx + len(marker):]
        return self.shell_cwd

    @rx.var
    def terminal_iframe_url(self) -> str:
        """URL of the terminal iframe — ttyd or the built-in xterm.js page."""
        if self.terminal_backend == "ttyd" and self.ttyd_port > 0:
            return f"http://localhost:{self.ttyd_port}"
        if not self.shell_cwd:
            return ""
        vm_ip = _get_vm_ip()
        url = f"http://{vm_ip}:{_BACKEND_PORT}/terminal?cwd={urllib.parse.quote(self.shell_cwd)}"
        if self.shell_initial_cmd:
            url += f"&initial_cmd={urllib.parse.quote(self.shell_initial_cmd)}"
            if self.terminal_hide_initial_cmd:
                url += "&hide_cmd=1"
        return url

    @rx.var
    def chrome_file_profiles(self) -> list[dict]:
        """Chrome profiles usable for file:// opens — excludes Playwright and special entries."""
        _special = {"playwright", "pycharm", "default", "none", ""}
        return [p for p in self.chrome_profiles if p["id"] not in _special]

    @rx.var
    def selected_node_browser_actions(self) -> list[dict]:
        """All actionable items for the selected node shown in the browser panel header.

        Includes injected Shell / SSH entries plus provider actions from YAML.
        Excludes expand_collapse (tree-only operation).
        """
        import json as _json
        _ = self.inventory_refresh_counter  # register as dependency so var recomputes post-refresh
        if not self.selected_node_path:
            return []
        node = next((n for n in self.all_nodes if n["path"] == self.selected_node_path), None)
        if not node:
            return []
        actions = _get_node_actions(
            self.selected_node_path,
            node.get("type", ""),
            node.get("provider", ""),
            node.get("has_terragrunt", False),
        )
        injected: list[dict] = []
        _, hcl_abs = _read_hcl_file(self.selected_node_path)
        # Shell CWD: unit file dir if it exists, otherwise the node's infra directory
        if hcl_abs:
            shell_dir = str(Path(hcl_abs).parent)
        else:
            try:
                shell_dir = str(_infra_path(_load_config()) / self.selected_node_path)
            except Exception:
                shell_dir = str(_STACK_DIR)
        injected.append({
            "group": "shell", "id": "open_local_shell",
            "label": "Shell", "action_type": "shell", "value": shell_dir,
        })
        ssh_cmd = _get_ssh_command(self.selected_node_path)
        if ssh_cmd:
            ssh_cwd = shell_dir
            injected.append({
                "group": "shell", "id": "ssh_to_host",
                "label": "SSH", "action_type": "ssh",
                "value": _json.dumps({"cwd": ssh_cwd, "cmd": ssh_cmd}),
            })
        _parts = self.selected_node_path.split("/")
        if _parts and _parts[-1] == "kubeconfig" and len(_parts) >= 2:
            _cluster_name = _parts[-2]
            injected.append({
                "group": "shell", "id": "open_kube_shell",
                "label": "Kube", "action_type": "ssh",
                "value": _json.dumps({"cwd": shell_dir, "cmd": _build_kube_shell_cmd(_cluster_name)}),
            })
        browser_url = _get_browser_url_for_node(
            self.selected_node_path, self.tree_mode == "merged"
        )
        if browser_url:
            injected.append({
                "group": "url", "id": "_browser_url",
                "label": "Open", "action_type": "url",
                "value": browser_url,
            })
        return injected + [a for a in actions if a["action_type"] != "expand_collapse"]

    @rx.var
    def max_depth(self) -> int:
        """Maximum node depth in the dataset (drives the Depth slider max)."""
        return _MAX_DEPTH

    @rx.var
    def depth_button_label(self) -> str:
        """Label shown on the Depth control button."""
        return "All" if self.depth_limit == 0 else str(self.depth_limit)

    @rx.var
    def depth_slider_value(self) -> list[int]:
        """Controlled value for rx.slider (must be a list[int] Var, not a Python list)."""
        return [self.depth_limit]

    @rx.var
    def view_mode(self) -> str:
        """Combined view-mode key: 'cytoscape', 'reactflow', 'archdiagram', or 'tree'."""
        if self.viz_framework == "cytoscape":
            return "cytoscape"
        if self.viz_framework == "reactflow":
            return "reactflow"
        if self.viz_framework == "archdiagram":
            return "archdiagram"
        return "tree"

    @rx.var
    def cytoscape_elements(self) -> list[dict]:
        """Compound-node elements for the Nested Networks view, filtered by provider and depth.

        Positions are pre-computed so the preset layout renders without overlaps.
        """
        base = _build_cytoscape_elements() or _SYNTHETIC_COMPOUND_ELEMENTS
        lim = self.depth_limit
        sel_roles = self.selected_roles

        # Pre-compute role keep-set (matching nodes + all ancestors)
        role_keep: set[str] = set()
        if sel_roles:
            nm_roles = self.node_name_roles
            for elem in base:
                node_id = elem["data"].get("id", "")
                if any(r in nm_roles.get(node_id, []) for r in sel_roles):
                    parts = node_id.split("/")
                    for i in range(1, len(parts) + 1):
                        role_keep.add("/".join(parts[:i]))

        filtered = []
        for elem in base:
            data     = elem["data"]
            provider = data.get("provider", "")
            if provider and not self.provider_filters.get(provider, True):
                continue
            if lim > 0 and data.get("depth", 0) > lim:
                continue
            parts = data["id"].split("/")
            cat_name = parts[0] if parts else ""
            if cat_name and not self.package_filters.get(cat_name, True):
                continue
            region_name = _PATH_TO_REGION_CACHE.get(data["id"], "")
            if region_name and not self.region_filters.get(region_name, True):
                continue
            if sel_roles and data["id"] not in role_keep:
                continue
            filtered.append(elem)

        # Apply wave-colored class when color-by-wave is active
        if self.cy_color_by_wave:
            filtered = [
                {**e, "classes": (e.get("classes", "") + " wave-colored").strip()}
                for e in filtered
            ]

        positions = _compute_cytoscape_positions(filtered)
        result = []
        for elem in filtered:
            node_id = elem["data"]["id"]
            if node_id in positions:
                x, y = positions[node_id]
                result.append({**elem, "position": {"x": x, "y": y}})
            else:
                result.append(elem)

        # Append dependency edges (no position needed for edges)
        if self.cy_show_dependencies:
            # Only include edges where both endpoints survived filtering
            visible_ids = {e["data"]["id"] for e in result}
            result.extend(
                e for e in _build_cytoscape_edges()
                if e["data"]["source"] in visible_ids and e["data"]["target"] in visible_ids
            )

        return result

    @rx.var
    def reactflow_nodes(self) -> list[dict]:
        """React Flow nodes filtered by provider, depth, and role."""
        base = _RF_DATA_CACHE.get("nodes") or _RF_SYNTHETIC_DATA.get("nodes", [])
        hidden = {p for p, v in self.provider_filters.items() if not v}
        lim = self.depth_limit
        sel_roles = self.selected_roles

        role_keep: set[str] = set()
        if sel_roles:
            nm_roles = self.node_name_roles
            for n in base:
                if any(r in nm_roles.get(n["id"], []) for r in sel_roles):
                    parts = n["id"].split("/")
                    for i in range(1, len(parts) + 1):
                        role_keep.add("/".join(parts[:i]))

        return [
            n for n in base
            if (not hidden or n["data"].get("provider", "") not in hidden)
            and (lim == 0 or n["data"].get("depth", 0) <= lim)
            and (not sel_roles or n["id"] in role_keep)
        ]

    @rx.var
    def reactflow_edges(self) -> list[dict]:
        """React Flow edges trimmed to only connect visible nodes."""
        base = _RF_DATA_CACHE.get("nodes") or _RF_SYNTHETIC_DATA.get("nodes", [])
        hidden = {p for p, v in self.provider_filters.items() if not v}
        lim = self.depth_limit
        sel_roles = self.selected_roles

        role_keep: set[str] = set()
        if sel_roles:
            nm_roles = self.node_name_roles
            for n in base:
                if any(r in nm_roles.get(n["id"], []) for r in sel_roles):
                    parts = n["id"].split("/")
                    for i in range(1, len(parts) + 1):
                        role_keep.add("/".join(parts[:i]))

        visible_ids = {
            n["id"] for n in base
            if (not hidden or n["data"].get("provider", "") not in hidden)
            and (lim == 0 or n["data"].get("depth", 0) <= lim)
            and (not sel_roles or n["id"] in role_keep)
        }
        all_edges = _RF_DATA_CACHE.get("edges") or _RF_SYNTHETIC_DATA.get("edges", [])
        return [e for e in all_edges if e["source"] in visible_ids and e["target"] in visible_ids]

    def _arch_cfg(self) -> dict:
        return {
            **_ARCH_DIAGRAM_CONFIG,
            "direction":        self.arch_direction,
            "min_depth":        self.arch_min_depth,
            "max_depth":        self.arch_max_depth,
            "show_connections": self.arch_show_connections,
        }

    @rx.var
    def arch_diagram_nodes(self) -> list[dict]:
        return _build_arch_diagram_elements(
            _ALL_NODES_CACHE, _DEPENDENCIES_CACHE, self._arch_cfg()
        )["nodes"]

    @rx.var
    def arch_diagram_edges(self) -> list[dict]:
        return _build_arch_diagram_elements(
            _ALL_NODES_CACHE, _DEPENDENCIES_CACHE, self._arch_cfg()
        )["edges"]

    @rx.var
    def arch_export_urls(self) -> list[dict]:
        """One entry per registered export format: {id, label, download_url, open_url}."""
        import urllib.parse
        sc = "true" if self.arch_show_connections else "false"
        qs = (f"format={{fmt_id}}"
              f"&direction={self.arch_direction}"
              f"&min_depth={self.arch_min_depth}"
              f"&max_depth={self.arch_max_depth}"
              f"&show_connections={sc}")
        result = []
        for fmt in _ARCH_EXPORT_FORMATS:
            fid          = fmt["id"]
            download_url = "/api/arch-diagram-export?" + qs.format(fmt_id=fid)
            open_url     = ""
            tmpl = fmt.get("open_url_template", "")
            if tmpl:
                full = "http://localhost:3000" + download_url
                open_url = tmpl.format(api_url=urllib.parse.quote(full, safe=""))
            result.append({
                "id":           fid,
                "label":        fmt["label"],
                "download_url": download_url,
                "open_url":     open_url,
            })
        return result

    @rx.var
    def arch_export_dir_label(self) -> str:
        """Show last two path segments so the toolbar stays compact."""
        parts = Path(self.arch_export_dir).parts
        return str(Path(*parts[-2:])) if len(parts) >= 2 else self.arch_export_dir

    @rx.var
    def providers_with_visibility(self) -> list[dict]:
        result = []
        for p in self.supported_providers:
            pname = p.get("provider-name", "")
            result.append({**p, "is_visible": self.provider_filters.get(pname, True)})
        return result

    @rx.var
    def packages_with_visibility(self) -> list[dict]:
        """Unique package names from infra nodes + package registry, with their current filter state.
        Includes a synthetic '_none' entry for units with no package assignment."""
        seen: list[str] = []
        for node in self.all_nodes:
            # Use the infra package (first segment of node path) not the module source package.
            pkg = node.get("path", "").split("/")[0]
            if pkg and pkg not in seen:
                seen.append(pkg)
        # Also include packages from the registry that have no infra nodes yet.
        for pkg_info in _PACKAGES_CACHE:
            if pkg_info.name and pkg_info.name not in seen:
                seen.append(pkg_info.name)
        seen.sort()
        result = [{"name": pkg, "is_visible": self.package_filters.get(pkg, True)} for pkg in seen]
        result.append({"name": "_none", "is_visible": self.package_filters.get("_none", True)})
        return result

    @rx.var
    def regions_with_visibility(self) -> list[dict]:
        """Unique region values from config_params, with their current filter state.
        Includes a synthetic '_none' entry for units with no region assignment."""
        seen: list[str] = []
        result = []
        for val in sorted(set(_PATH_TO_REGION_CACHE.values())):
            if val not in seen:
                seen.append(val)
                result.append({"name": val, "is_visible": self.region_filters.get(val, True)})
        result.append({"name": "_none", "is_visible": self.region_filters.get("_none", True)})
        return result

    @rx.var
    def envs_with_visibility(self) -> list[dict]:
        """Unique env values from config_params, with their current filter state.
        Includes a synthetic '_none' entry (first) for units with no env assignment."""
        result = [{"name": "_none", "is_visible": self.env_filters.get("_none", True)}]
        seen: list[str] = []
        for val in sorted(set(_PATH_TO_ENV_CACHE.values())):
            if val not in seen:
                seen.append(val)
                result.append({"name": val, "is_visible": self.env_filters.get(val, True)})
        return result

    @rx.var
    def waves_with_visibility(self) -> list[dict]:
        """All waves from the stack config waves list, in declaration order.
        Appends any _wave values found in config_params that are not in the list.
        Includes a synthetic '_none' entry for units with no wave assignment."""
        # Canonical order from the stack config waves list
        cfg_waves = (
            (_STACK_CONFIG.get(_STACK_CONFIG_KEY) or {}).get("waves") or []
        )
        # Build name → config entry map for attribute lookup
        wave_config: dict[str, dict] = {}
        for entry in cfg_waves:
            if isinstance(entry, dict):
                n = entry.get("name", "")
                if n:
                    wave_config[n] = entry

        def _wave_attrs(cfg: dict) -> dict:
            return {
                "description":          str(cfg.get("description",          "") or ""),
                "pre_ansible_playbook": str(cfg.get("pre_ansible_playbook", "") or ""),
                "test_ansible_playbook":str(cfg.get("test_ansible_playbook","") or ""),
                "test_action":          str(cfg.get("test_action",          "") or ""),
                "update_inventory":     "Yes" if cfg.get("update_inventory") else "",
                "skip_on_wave_run": "Yes" if cfg.get("skip_on_wave_run") else "",
            }

        _empty_attrs = _wave_attrs({})

        log_statuses = self.wave_log_statuses

        result = []
        seen: set[str] = set()
        num = 1
        _empty_ls = {"status": "none", "log_path": "",
                     "start_time": "", "end_time": "", "duration": "", "age": "",
                     "log_update_age": "",
                     "pre_status": "none", "pre_log_path": "",
                     "test_status": "none", "test_log_path": ""}

        cfg_wave_names = []
        for entry in cfg_waves:
            name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
            if name and name not in seen:
                cfg_wave_names.append(name)
                seen.add(name)

        _recent = self.recent_wave_name if self.wave_highlight_recent else ""
        for idx, name in enumerate(cfg_wave_names):
            ls = log_statuses.get(name, _empty_ls)
            result.append({
                "name": name,
                "row_id": f"wave-row-{name}",
                "is_visible": self.wave_filters.get(name, True),
                "wave_num":   str(num),
                "is_first":   idx == 0,
                "is_last":    idx == len(cfg_wave_names) - 1,
                "is_recent":      name == _recent,
                "log_status":     ls.get("status", "none"),
                "log_path":       ls.get("log_path", ""),
                "pre_log_status": ls.get("pre_status", "none"),
                "pre_log_path":   ls.get("pre_log_path", ""),
                "test_log_status":ls.get("test_status", "none"),
                "test_log_path":  ls.get("test_log_path", ""),
                "start_time":     ls.get("start_time", ""),
                "end_time":       ls.get("end_time", ""),
                "duration":        ls.get("duration", ""),
                "age":             ls.get("age", ""),
                "log_update_age":  ls.get("log_update_age", ""),
                **_wave_attrs(wave_config.get(name, {})),
            })
            num += 1
        # Any _wave values assigned in config_params but absent from the config wave list
        in_use = set(_PATH_TO_WAVE_CACHE.values())
        for val in sorted(in_use - seen):
            ls = log_statuses.get(val, _empty_ls)
            result.append({"name": val, "row_id": f"wave-row-{val}",
                           "is_visible": self.wave_filters.get(val, True),
                           "wave_num": "", "is_first": False, "is_last": False,
                           "is_recent":       val == _recent,
                           "log_status":      ls.get("status", "none"),
                           "log_path":        ls.get("log_path", ""),
                           "pre_log_status":  ls.get("pre_status", "none"),
                           "pre_log_path":    ls.get("pre_log_path", ""),
                           "test_log_status": ls.get("test_status", "none"),
                           "test_log_path":   ls.get("test_log_path", ""),
                           "start_time":      ls.get("start_time", ""),
                           "end_time":        ls.get("end_time", ""),
                           "duration":        ls.get("duration", ""),
                           "age":             ls.get("age", ""),
                           "log_update_age":  ls.get("log_update_age", ""),
                           **_empty_attrs})
        result.append({
            "name": "_none",
            "row_id": "wave-row-_none",
            "is_visible": self.wave_filters.get("_none", True),
            "wave_num": "", "is_first": False, "is_last": False,
            "is_recent": False,
            "log_status": "none", "log_path": "",
            "pre_log_status": "none", "pre_log_path": "",
            "test_log_status": "none", "test_log_path": "",
            "start_time": "", "end_time": "", "duration": "", "age": "", "log_update_age": "",
            "description": "Units with no wave assignment",
            "pre_ansible_playbook": "", "test_ansible_playbook": "",
            "test_action": "", "update_inventory": "",
        })
        return result

    @rx.var
    def waves_folder_rows(self) -> list[dict]:
        """Flat rows for the waves folder view.

        Wave names are treated as dot-delimited paths (e.g. "1.1", "1.2", "2").
        The tree is built from those paths, de-duplicating common prefixes.
        Rows where the node path exactly matches a known wave name get a
        checkbox (row_type="wave_node"); intermediate folder nodes get a
        folder icon only (row_type="folder_node").

        Rows are omitted when any ancestor folder path is in wave_folder_collapsed,
        so collapsing a folder hides its entire subtree.

        Row schema:
          row_type    – "wave_node" | "folder_node"
          wave        – the exact wave name (empty for folder_node)
          folder_path – the dot-path of this folder node (empty for wave_node)
          label       – last dot-component to display
          is_visible  – filter state (meaningful only for wave_node)
          indent      – nesting depth (0 = top level)
          has_children – True if this folder has at least one child row
          is_expanded  – True if this folder is not in wave_folder_collapsed
                         (always True for wave_node rows)
        """
        wave_items = self.waves_with_visibility
        wave_visibility: dict[str, bool] = {
            item["name"]: item["is_visible"] for item in wave_items
        }
        wave_attrs: dict[str, dict] = {
            item["name"]: {
                "description":           item["description"],
                "pre_ansible_playbook":  item["pre_ansible_playbook"],
                "test_ansible_playbook": item["test_ansible_playbook"],
                "test_action":           item["test_action"],
                "update_inventory":      item["update_inventory"],
                "wave_num":              item["wave_num"],
                "is_first":              item["is_first"],
                "is_last":               item["is_last"],
                "is_recent":             item["is_recent"],
                "log_status":            item["log_status"],
                "log_path":              item["log_path"],
                "pre_log_status":        item["pre_log_status"],
                "pre_log_path":          item["pre_log_path"],
                "test_log_status":       item["test_log_status"],
                "test_log_path":         item["test_log_path"],
                "start_time":            item["start_time"],
                "end_time":              item["end_time"],
                "duration":              item["duration"],
                "age":                   item["age"],
                "log_update_age":        item["log_update_age"],
            }
            for item in wave_items
        }

        # Build ordered, de-duplicated list of all dot-path prefixes
        seen: set[str] = set()
        tree_paths: list[str] = []
        for wave_name in wave_visibility:  # insertion order = config-file order from waves_with_visibility
            parts = wave_name.split(".")
            for depth in range(1, len(parts) + 1):
                prefix = ".".join(parts[:depth])
                if prefix not in seen:
                    seen.add(prefix)
                    tree_paths.append(prefix)

        _empty = {"description": "", "pre_ansible_playbook": "", "test_ansible_playbook": "",
                  "test_action": "", "update_inventory": "", "wave_num": "",
                  "is_first": False, "is_last": False, "is_recent": False,
                  "log_status": "none", "log_path": "",
                  "pre_log_status": "none", "pre_log_path": "",
                  "test_log_status": "none", "test_log_path": "",
                  "start_time": "", "end_time": "", "duration": "", "age": "",
                  "log_update_age": ""}

        collapsed: set[str] = set(self.wave_folder_collapsed)

        # Pre-compute which node paths have children (used for chevron visibility).
        children_of: set[str] = set()
        for p in tree_paths:
            parts = p.split(".")
            for depth in range(1, len(parts)):
                children_of.add(".".join(parts[:depth]))

        result: list[dict] = []
        for node_path in tree_paths:
            parts = node_path.split(".")
            indent = len(parts) - 1
            label = parts[-1]
            is_wave = node_path in wave_visibility

            # Skip this row if any ancestor folder is collapsed.
            ancestor_collapsed = any(
                ".".join(parts[:d]) in collapsed
                for d in range(1, len(parts))
            )
            if ancestor_collapsed:
                continue

            attrs = wave_attrs.get(node_path, _empty) if is_wave else _empty
            result.append({
                "row_type":    "wave_node" if is_wave else "folder_node",
                "name":        node_path,
                "row_id":      f"wave-row-{node_path}",
                "wave":        node_path if is_wave else "",
                "folder_path": "" if is_wave else node_path,
                "label":       label,
                "is_visible":  wave_visibility.get(node_path, True),
                "indent":      indent,
                "has_children": node_path in children_of,
                "is_expanded":  node_path not in collapsed,
                **attrs,
            })
        return result

    @rx.var
    def roles_with_selection(self) -> list[dict]:
        """List of {tag, label, selected} for the roles dropdown.
        Includes a synthetic '_none' entry (first) for units with no role assignments."""
        selected = self.selected_roles
        result = [{"tag": "_none", "label": "(none)", "selected": "_none" in selected}]
        for tag in self.available_roles:
            label = tag[5:] if tag.startswith("role_") else tag  # strip "role_" prefix
            result.append({"tag": tag, "label": label, "selected": tag in selected})
        return result

    @rx.var
    def role_filter_active(self) -> bool:
        return len(self.selected_roles) > 0

    @rx.var
    def package_filter_active(self) -> bool:
        return any(not v for v in self.package_filters.values())

    @rx.var
    def provider_filter_active(self) -> bool:
        return any(not v for v in self.provider_filters.values())

    @rx.var
    def region_filter_active(self) -> bool:
        return any(not v for v in self.region_filters.values())

    @rx.var
    def env_filter_active(self) -> bool:
        return any(not v for v in self.env_filters.values())

    @rx.var
    def roles_button_label(self) -> str:
        n = len(self.selected_roles)
        return f"Roles ({n}) ▾" if n else "Roles ▾"

    @rx.var
    def visible_nodes(self) -> list[dict]:
        search = self.explorer_search.lower().strip()
        sel_roles = self.selected_roles

        def _keep_paths_for(nodes: list[dict], match_fn) -> tuple[set[str], set[str]]:
            keep: set[str] = set()
            ancestors: set[str] = set()
            for node in nodes:
                if match_fn(node):
                    parts = node["path"].split("/")
                    for i in range(1, len(parts) + 1):
                        anc = "/".join(parts[:i])
                        keep.add(anc)
                        if i < len(parts):
                            ancestors.add(anc)
            return keep, ancestors

        search_keep: set[str] = set()
        search_anc:  set[str] = set()
        if search:
            search_keep, search_anc = _keep_paths_for(
                self.all_nodes,
                lambda n: search in n.get("name", "").lower() or search in n.get("path", "").lower(),
            )

        role_keep: set[str] = set()
        role_anc:  set[str] = set()

        # Region/env/wave: build keep-sets when any value is hidden.
        # Nodes with an assigned value match if that value is visible.
        # Unit nodes (has_terragrunt) with NO assigned value match if the
        # special "_none" key is visible — letting users filter for unassigned units.
        # Ancestor folder nodes appear only via the keep-set expansion step.
        rf = self.region_filters
        region_keep: set[str] | None = None
        if rf and any(not v for v in rf.values()):
            def _region_match(n: dict, _rf: dict = rf) -> bool:
                rv = _PATH_TO_REGION_CACHE.get(n["path"], "")
                if rv:
                    return _rf.get(rv, True)
                return n.get("has_terragrunt", False) and _rf.get("_none", True)
            region_keep, _ = _keep_paths_for(self.all_nodes, _region_match)

        ef = self.env_filters
        env_keep: set[str] | None = None
        if ef and any(not v for v in ef.values()):
            def _env_match(n: dict, _ef: dict = ef) -> bool:
                ev = _PATH_TO_ENV_CACHE.get(n["path"], "")
                if ev:
                    return _ef.get(ev, True)
                return n.get("has_terragrunt", False) and _ef.get("_none", True)
            env_keep, _ = _keep_paths_for(self.all_nodes, _env_match)

        wf = self.wave_filters
        wave_keep: set[str] | None = None
        if wf and any(not v for v in wf.values()):
            def _wave_match(n: dict, _wf: dict = wf) -> bool:
                wv = _PATH_TO_WAVE_CACHE.get(n["path"], "")
                if wv:
                    return _wf.get(wv, True)
                return n.get("has_terragrunt", False) and _wf.get("_none", True)
            wave_keep, _ = _keep_paths_for(self.all_nodes, _wave_match)

        pkf = self.package_filters
        package_keep: set[str] | None = None
        if pkf and any(not v for v in pkf.values()):
            def _pkg_match(n: dict, _pkf: dict = pkf) -> bool:
                pv = n.get("path", "").split("/")[0]
                if pv:
                    return _pkf.get(pv, True)
                return n.get("has_terragrunt", False) and _pkf.get("_none", True)
            package_keep, _ = _keep_paths_for(self.all_nodes, _pkg_match)

        # Roles: handle the synthetic "_none" tag (units with no role assignments).
        if sel_roles:
            nm_roles = self.node_name_roles
            non_none_roles = [r for r in sel_roles if r != "_none"]
            none_role = "_none" in sel_roles
            def _role_match(n: dict, _nm: dict = nm_roles,
                            _nnr: list = non_none_roles, _nn: bool = none_role) -> bool:
                roles = _nm.get(n.get("path", ""), [])
                if _nnr and any(r in roles for r in _nnr):
                    return True
                if _nn and not roles and n.get("has_terragrunt", False):
                    return True
                return False
            role_keep, role_anc = _keep_paths_for(self.all_nodes, _role_match)

        filtering = bool(search or sel_roles)

        _statuses = self.unit_build_statuses
        result = []
        for node in self.all_nodes:
            provider = node.get("provider", "")
            if provider and not self.provider_filters.get(provider, True):
                continue
            depth = node["depth"]
            path = node["path"]
            parts = path.split("/")
            # Category filter
            cat_name = parts[0] if parts else ""
            if cat_name and not self.package_filters.get(cat_name, True):
                continue
            # Region / env / wave / package keep-set filters (prune ancestors of hidden nodes too)
            if region_keep is not None and path not in region_keep:
                continue
            if env_keep is not None and path not in env_keep:
                continue
            if wave_keep is not None and path not in wave_keep:
                continue
            if package_keep is not None and path not in package_keep:
                continue
            # Search + role filters (both must pass if both active)
            if search and path not in search_keep:
                continue
            if sel_roles and path not in role_keep:
                continue
            # Expand/collapse is always respected — even when a search/role filter is
            # active.  Ancestors of matching nodes are auto-expanded by
            # set_explorer_search / clear_explorer_search (see below), so results
            # remain visible after a search.  This lets users collapse sub-trees
            # during search to organise the view.
            is_expanded = path in self.expanded_paths
            if depth == 0:
                result.append({**node, "is_expanded": is_expanded, "build_status": _statuses.get(path, "none")})
                continue
            visible = True
            check = ""
            for part in parts[:-1]:
                check = f"{check}/{part}" if check else part
                if part == "_stack":
                    # "_stack" is a virtual path segment with no node of its own;
                    # skip the expanded_paths check for this intermediate segment.
                    continue
                if check not in self.expanded_paths:
                    visible = False
                    break
            if visible:
                result.append({**node, "is_expanded": is_expanded, "build_status": _statuses.get(path, "none")})
        return result

    @rx.var
    def providers_c4(self) -> list[ProviderCard]:
        provider_map: dict[str, list[str]] = {}
        for node in self.visible_nodes:
            provider = node.get("provider", "")
            if provider and node.get("has_terragrunt", False):
                provider_map.setdefault(provider, []).append(node["name"])
        result = []
        for p_info in self.supported_providers:
            pname = p_info.get("provider-name", "")
            if pname in provider_map and self.provider_filters.get(pname, True):
                result.append(ProviderCard(
                    name=pname,
                    resources=provider_map[pname],
                    doc_url=p_info.get("provider-doc-url", ""),
                    color=PROVIDER_COLOR.get(pname, "gray"),
                    count=str(len(provider_map[pname])),
                ))
        return result

    @rx.var
    def layer_onprem(self) -> list[ProviderCard]:
        names = {"proxmox", "unifi"}
        return [c for c in self.providers_c4 if c.name in names]

    @rx.var
    def layer_provisioning(self) -> list[ProviderCard]:
        names = {"maas", "null"}
        return [c for c in self.providers_c4 if c.name in names]

    @rx.var
    def layer_cloud(self) -> list[ProviderCard]:
        names = {"gcp", "aws", "azure"}
        return [c for c in self.providers_c4 if c.name in names]

    @rx.var
    def is_merged(self) -> bool:
        return self.tree_mode == "merged"

    @rx.var
    def merged_visible_nodes(self) -> list[dict]:
        """Visible nodes for the merged tree (provider-stripped, deduplicated)."""
        search = self.explorer_search.lower().strip()
        sel_roles = self.selected_roles

        def _keep_paths_for(nodes: list[dict], match_fn) -> tuple[set[str], set[str]]:
            keep: set[str] = set()
            ancestors: set[str] = set()
            for node in nodes:
                if match_fn(node):
                    parts = node["path"].split("/")
                    for i in range(1, len(parts) + 1):
                        anc = "/".join(parts[:i])
                        keep.add(anc)
                        if i < len(parts):
                            ancestors.add(anc)
            return keep, ancestors

        search_keep: set[str] = set()
        search_anc:  set[str] = set()
        if search:
            search_keep, search_anc = _keep_paths_for(
                self.merged_nodes_base,
                lambda n: search in n.get("name", "").lower() or search in n.get("path", "").lower(),
            )

        role_keep: set[str] = set()
        role_anc:  set[str] = set()

        # Region/env/wave keep-sets for merged mode.
        # Full provider paths are reconstructed so the global caches (which use
        # separated paths) can be queried. Nodes with an assigned visible value
        # match; unit nodes with NO assigned value match when "_none" is visible.
        def _merged_full_paths(n: dict) -> list[str]:
            providers = [p for p in n.get("providers_str", "").split(",") if p]
            parts_mp = n["path"].split("/")
            # Reconstruct full path: <pkg>/_stack/<provider>/<rest>
            return (
                ["/".join([parts_mp[0], "_stack", p] + parts_mp[1:]) for p in providers]
                if providers else [n["path"]]
            )

        mrf = self.region_filters
        region_keep_m: set[str] | None = None
        if mrf and any(not v for v in mrf.values()):
            def _m_region_match(n: dict, _mrf: dict = mrf) -> bool:
                fps = _merged_full_paths(n)
                vals = [_PATH_TO_REGION_CACHE.get(fp, "") for fp in fps]
                assigned = [v for v in vals if v]
                if assigned:
                    return any(_mrf.get(v, True) for v in assigned)
                return n.get("has_terragrunt", False) and _mrf.get("_none", True)
            region_keep_m, _ = _keep_paths_for(self.merged_nodes_base, _m_region_match)

        mef = self.env_filters
        env_keep_m: set[str] | None = None
        if mef and any(not v for v in mef.values()):
            def _m_env_match(n: dict, _mef: dict = mef) -> bool:
                fps = _merged_full_paths(n)
                vals = [_PATH_TO_ENV_CACHE.get(fp, "") for fp in fps]
                assigned = [v for v in vals if v]
                if assigned:
                    return any(_mef.get(v, True) for v in assigned)
                return n.get("has_terragrunt", False) and _mef.get("_none", True)
            env_keep_m, _ = _keep_paths_for(self.merged_nodes_base, _m_env_match)

        mwf = self.wave_filters
        wave_keep_m: set[str] | None = None
        if mwf and any(not v for v in mwf.values()):
            def _m_wave_match(n: dict, _mwf: dict = mwf) -> bool:
                fps = _merged_full_paths(n)
                vals = [_PATH_TO_WAVE_CACHE.get(fp, "") for fp in fps]
                assigned = [v for v in vals if v]
                if assigned:
                    return any(_mwf.get(v, True) for v in assigned)
                return n.get("has_terragrunt", False) and _mwf.get("_none", True)
            wave_keep_m, _ = _keep_paths_for(self.merged_nodes_base, _m_wave_match)

        mpkf = self.package_filters
        package_keep_m: set[str] | None = None
        if mpkf and any(not v for v in mpkf.values()):
            def _m_pkg_match(n: dict, _mpkf: dict = mpkf) -> bool:
                pv = n.get("path", "").split("/")[0]
                if pv:
                    return _mpkf.get(pv, True)
                return n.get("has_terragrunt", False) and _mpkf.get("_none", True)
            package_keep_m, _ = _keep_paths_for(self.merged_nodes_base, _m_pkg_match)

        if sel_roles:
            nm_roles = self.node_name_roles
            non_none_roles = [r for r in sel_roles if r != "_none"]
            none_role = "_none" in sel_roles
            def _m_role_match(n: dict, _nm: dict = nm_roles,
                              _nnr: list = non_none_roles, _nn: bool = none_role) -> bool:
                roles = _nm.get(n.get("path", ""), [])
                if _nnr and any(r in roles for r in _nnr):
                    return True
                if _nn and not roles and n.get("has_terragrunt", False):
                    return True
                return False
            role_keep, role_anc = _keep_paths_for(self.merged_nodes_base, _m_role_match)

        filtering = bool(search or sel_roles)

        result = []
        for node in self.merged_nodes_base:
            providers = [p for p in node.get("providers_str", "").split(",") if p]
            if providers and not any(self.provider_filters.get(p, True) for p in providers):
                continue
            depth = node["depth"]
            path  = node["path"]
            parts = path.split("/")
            # Category filter
            cat_name = parts[0] if parts else ""
            if cat_name and not self.package_filters.get(cat_name, True):
                continue
            # Region / env / wave / package keep-set filters
            if region_keep_m is not None and path not in region_keep_m:
                continue
            if env_keep_m is not None and path not in env_keep_m:
                continue
            if wave_keep_m is not None and path not in wave_keep_m:
                continue
            if package_keep_m is not None and path not in package_keep_m:
                continue
            # Search + role filters
            if search and path not in search_keep:
                continue
            if sel_roles and path not in role_keep:
                continue
            # Expand/collapse is always respected (same as visible_nodes; see comment there).
            is_expanded = path in self.merged_expanded_paths
            if depth == 0:
                result.append({**node, "is_expanded": is_expanded})
                continue
            visible = True
            check = ""
            for part in parts[:-1]:
                check = f"{check}/{part}" if check else part
                if check not in self.merged_expanded_paths:
                    visible = False
                    break
            if visible:
                result.append({**node, "is_expanded": is_expanded})
        return result

    @rx.var
    def effective_nodes(self) -> list[dict]:
        """Whichever node list is active based on tree_mode."""
        if self.tree_mode == "merged":
            return self.merged_visible_nodes
        return self.visible_nodes

    @rx.var
    def visible_modules_nodes(self) -> list[dict]:
        """Modules tree: expand/collapse from modules_expanded_paths."""
        result = []
        for node in self.modules_nodes:
            path = node["path"]
            parts = path.split("/")
            is_expanded = path in self.modules_expanded_paths
            if node["depth"] == 0:
                result.append({**node, "is_expanded": is_expanded})
                continue
            visible = True
            check = ""
            for part in parts[:-1]:
                check = f"{check}/{part}" if check else part
                if check not in self.modules_expanded_paths:
                    visible = False
                    break
            if visible:
                result.append({**node, "is_expanded": is_expanded})
        return result

    @rx.var
    def explorer_search_active(self) -> bool:
        return self.explorer_search.strip() != ""

    @rx.var
    def modules_nodes_empty(self) -> bool:
        return len(self.modules_nodes) == 0

    @rx.var
    def packages_data_empty(self) -> bool:
        return len(self.packages_data) == 0

    @rx.var
    def packages_all_expanded(self) -> bool:
        return (
            len(self.packages_data) > 0
            and len(self.packages_expanded_names) >= len(self.packages_data)
        )

    @rx.var
    def selected_node_params_flat(self) -> list[dict]:
        """All param rows for the selected node across all providers."""
        rows = _get_unit_params_flat(self.selected_node_path, self.tree_mode == "merged")
        if self.hide_special_params:
            rows = [r for r in rows if r["key"] not in _SPECIAL_KEY_ORDER]
        if self.hide_provider_underscore_params:
            rows = [r for r in rows if not r["key"].startswith("_provider")]
        return rows

    @rx.var
    def available_provider_tabs(self) -> list[str]:
        """Provider names that have params for the selected node (for the tab bar)."""
        seen: list[str] = []
        for row in self.selected_node_params_flat:
            if row["row_type"] == "provider_header":
                p = row["provider"]
                if p not in seen:
                    seen.append(p)
        return seen

    @rx.var
    def selected_node_params_display(self) -> list[dict]:
        """Param rows filtered by active provider tab and unit_params_search query."""
        rows = self.selected_node_params_flat
        tab  = self.active_provider_tab
        if tab:
            rows = [r for r in rows if r["provider"] == tab]
        q = self.unit_params_search.lower().strip()
        if q:
            rows = [r for r in rows
                    if r["row_type"] == "param"
                    and (q in r.get("key", "").lower() or q in str(r.get("value", "")).lower())]
        return rows

    @rx.var
    def has_unit_params(self) -> bool:
        return len(self.selected_node_params_flat) > 0

    @rx.var
    def hover_popup_unit_state_rows(self) -> list[dict]:
        """Convert hover_popup_unit_state dict to an ordered list of {key, value} rows."""
        _ORDER = ["status", "maas_phase", "maas_message", "details", "last_apply_at", "last_validated_at", "last_apply_exit_code"]
        rows: list[dict] = []
        d = dict(self.hover_popup_unit_state)
        for k in _ORDER:
            if k in d:
                rows.append({"key": k, "value": str(d[k]) if d[k] is not None else "—"})
        for k, v in d.items():
            if k not in _ORDER:
                rows.append({"key": k, "value": str(v) if v is not None else "—"})
        return rows

    @rx.var
    def hover_popup_has_unit_state(self) -> bool:
        return len(self.hover_popup_unit_state_rows) > 0

    @rx.var
    def hover_popup_has_params(self) -> bool:
        return len(self.hover_popup_params) > 0

    @rx.var
    def has_stack_config(self) -> bool:
        """True when the stack config was successfully loaded (needed for region/env filters)."""
        return bool(_STACK_CONFIG)

    @rx.var
    def file_viewer_available_providers(self) -> list[str]:
        """Providers that have a terragrunt.hcl on disk for the current merged-mode node.

        Scans infra/<pkg>/<provider-dir>/<rel-path>/terragrunt.hcl for each
        sub-directory of the package, returning only providers where the file exists.
        Independent of stack config / config_params.
        """
        if self.tree_mode != "merged" or not self.selected_node_path:
            return []
        return _get_hcl_providers_for_merged(self.selected_node_path)

    @rx.var
    def show_file_viewer_provider_selector(self) -> bool:
        """True when the Provider dropdown should be visible in the File Viewer menu bar."""
        return (
            self.tree_mode == "merged"
            and self.file_viewer_mode == "unit_file"
            and self.selected_node_path != ""
            and len(_get_hcl_providers_for_merged(self.selected_node_path)) > 0
        )

    @rx.var
    def file_viewer_provider_options(self) -> list[dict]:
        """Dropdown options for the Provider selector: provider name + full reconstructed path.

        Full path = <pkg>/_stack/<provider>/<rel-path> (provider re-inserted into merged path).
        """
        if self.tree_mode != "merged" or not self.selected_node_path:
            return []
        parts = self.selected_node_path.split("/")
        return [
            {
                "provider": p,
                "full_path": "/".join([parts[0], "_stack", p] + parts[1:]),
            }
            for p in _get_hcl_providers_for_merged(self.selected_node_path)
        ]

    @rx.var
    def file_viewer_provider_full_path(self) -> str:
        """Full path for the currently active file viewer provider (for the button label)."""
        if not self.file_viewer_provider or not self.selected_node_path:
            return ""
        parts = self.selected_node_path.split("/")
        return "/".join([parts[0], "_stack", self.file_viewer_provider] + parts[1:])

    @rx.var
    def file_viewer_rel_path(self) -> str:
        """Path of the selected node's unit HCL file, relative to _STACK_DIR.

        E.g. infra/proxmox/example-lab/pve-nodes/pve-1/terragrunt.hcl
        Empty when no unit HCL exists for the selected node.
        """
        if not self.unit_hcl_path:
            return ""
        try:
            return str(Path(self.unit_hcl_path).relative_to(_STACK_DIR))
        except ValueError:
            return self.unit_hcl_path

    @rx.var
    def hcl_is_ansi_log(self) -> bool:
        """True when the current file content contains ANSI escape codes."""
        return '\x1b[' in self.hcl_content

    @rx.var
    def hcl_is_markdown(self) -> bool:
        """True when the current file is a .md file and markdown rendering is enabled."""
        return self.file_viewer_render_markdown and self.hcl_file_path.endswith(".md")

    @rx.var
    def hcl_content_html(self) -> str:
        """ANSI-to-HTML conversion of hcl_content for log files, with search marks baked in."""
        if '\x1b[' not in self.hcl_content:
            return ""
        html, _count = _ansi_to_html(self.hcl_content, self.unit_file_search_query,
                                      self.ansi_search_idx, self.file_search_case_sensitive)
        return html

    @rx.var
    def ansi_match_total(self) -> int:
        """Number of search matches in the current ANSI log. 0 when not an ANSI log.

        Intentionally does NOT depend on ansi_search_idx so it only recomputes when
        the content or query changes, not on every nav step.
        """
        if '\x1b[' not in self.hcl_content or not self.unit_file_search_query:
            return 0
        _html, count = _ansi_to_html(self.hcl_content, self.unit_file_search_query,
                                      -1, self.file_search_case_sensitive)
        return count

    @rx.var
    def hcl_parsed_lines(self) -> list[dict]:
        """Split hcl_content into per-line dicts; detect `source = "..."` lines.

        Each dict has:
          text        — full original line text
          prefix      — text before the source URL (e.g. '  source = "')
          source_val  — the raw source string value, or "" for non-source lines
          suffix      — text after the URL (typically '"')
          is_source   — bool (pre-computed for rx.cond)
          yaml_path   — dot-separated YAML ancestor path for this line (for breadcrumb)
        """
        # ANSI logs are rendered via hcl_content_html / rx.html() — skip this pipeline
        if '\x1b[' in self.hcl_content:
            return []
        _SOURCE_RE = re.compile(r'^(\s*source\s*=\s*")([^"]+)(")')
        yaml_paths = _build_yaml_line_paths(self.hcl_content)
        result = []
        for i, line in enumerate(self.hcl_content.split("\n")):
            yp = yaml_paths[i] if i < len(yaml_paths) else ""
            m = _SOURCE_RE.match(line)
            if m:
                result.append({
                    "text":       line,
                    "prefix":     m.group(1),
                    "source_val": m.group(2),
                    "suffix":     m.group(3),
                    "is_source":  True,
                    "yaml_path":  yp,
                    "line_num":   str(i + 1),
                })
            else:
                result.append({
                    "text":       line,
                    "prefix":     "",
                    "source_val": "",
                    "suffix":     "",
                    "is_source":  False,
                    "yaml_path":  yp,
                    "line_num":   str(i + 1),
                })
        return result

    @rx.var
    def file_editor_language(self) -> str:
        """Map the current file's extension to a Monaco language identifier."""
        if not self.hcl_file_path:
            return "plaintext"
        ext = Path(self.hcl_file_path).suffix.lower()
        return {
            ".hcl": "hcl",
            ".tf":  "hcl",
            ".yaml": "yaml",
            ".yml":  "yaml",
            ".json": "json",
            ".toml": "toml",
        }.get(ext, "plaintext")

    @rx.var
    def file_editor_monaco_theme(self) -> str:
        """Map ui_theme to a Monaco editor theme identifier."""
        return {"light": "vs", "dark": "vs-dark"}.get(self.ui_theme, "vs")

    @rx.var
    def selected_node_label(self) -> str:
        parts = self.selected_node_path.split("/")
        return parts[-1] if parts else ""

    @rx.var
    def left_panel_width_style(self) -> str:
        return f"{self.left_panel_width_pct}%"

    @rx.var
    def resizer_drag_width_px(self) -> str:
        return f"{self.resizer_drag_width}px"

    @rx.var
    def resizer_drag_width_list(self) -> list[int]:
        """Controlled value for rx.slider (must be list[int])."""
        return [self.resizer_drag_width]

    @rx.var
    def fw_repos_zoom_list(self) -> list[int]:
        return [self.fw_repos_zoom]

    @rx.var
    def fw_repos_zoom_label(self) -> str:
        return f"{self.fw_repos_zoom}%"

    @rx.var
    def cy_wheel_sensitivity_list(self) -> list[float]:
        """Controlled value for rx.slider (must be list[float])."""
        return [self.cy_wheel_sensitivity]

    @rx.var
    def cy_wheel_sensitivity_label(self) -> str:
        return f"{self.cy_wheel_sensitivity:.2f}"


    # -----------------------------------------------------------------------
    # Persistence helpers
    # -----------------------------------------------------------------------

    def _save_current_config(self) -> None:
        """Schedule a debounced background write of UI settings to state/current.yaml.

        Builds a snapshot of the current menu state and hands it off to
        _schedule_config_write(), which debounces to 800 ms so rapid node clicks
        produce only one disk write instead of one per click.  The providers list
        and other unmanaged keys are preserved by _do_write_menu().
        """
        _schedule_config_write({
            "panel_width_pct":        self.left_panel_width_pct,
            "viz_framework":          self.viz_framework,
            "left_view":              self.left_view,
            "tree_mode":              self.tree_mode,
            "panel_show_view_selector": self.panel_show_view_selector,
            "panel_show_merged":        self.panel_show_merged,
            "panel_show_depth":         self.panel_show_depth,
            "show_full_module_name":    self.show_full_module_name,
            "show_wave_numbers":        self.show_wave_numbers,
            "show_unit_build_status":          self.show_unit_build_status,
            "unit_status_auto_refresh":        self.unit_status_auto_refresh,
            "unit_status_auto_refresh_secs":   self.unit_status_auto_refresh_secs,
            "object_viewer_mode":       self.object_viewer_mode,
            "wave_show_start_time":     self.wave_show_start_time,
            "wave_show_end_time":       self.wave_show_end_time,
            "wave_show_duration":       self.wave_show_duration,
            "wave_show_age":            self.wave_show_age,
            "wave_show_log_update":     self.wave_show_log_update,
            "wave_highlight_recent":        self.wave_highlight_recent,
            "auto_select_recent_unit":      self.auto_select_recent_unit,
            "show_unit_popup":              self.show_unit_popup,
            "terminal_hide_initial_cmd":    self.terminal_hide_initial_cmd,
            "terminal_backend":             self.terminal_backend,
            "cy_show_dependencies":         self.cy_show_dependencies,
            "cy_color_by_wave":             self.cy_color_by_wave,
            "depth_limit":                  self.depth_limit,
            "top_row_height_pct":    self.top_row_height_pct,
            "resizer_drag_width":    self.resizer_drag_width,
            "selected_editor_id":    self.selected_editor_id,
            "explorer_root":         self.explorer_root,
            "hide_special_params":   self.hide_special_params,
            "hide_provider_underscore_params": self.hide_provider_underscore_params,
            "param_wrap_values":     self.param_wrap_values,
            "browser_profile":       self.browser_profile,
            "cy_wheel_sensitivity":  self.cy_wheel_sensitivity,
            "file_viewer_mode":      self.file_viewer_mode,
            "unit_file_search_query":   self.unit_file_search_query,
            "config_data_search_query": self.config_data_search_query,
            "config_data_quote_path":      self.config_data_quote_path,
            "file_search_smooth_scroll":   self.file_search_smooth_scroll,
            "file_search_case_sensitive":  self.file_search_case_sensitive,
            "file_viewer_render_markdown": self.file_viewer_render_markdown,
            "file_viewer_show_line_numbers": self.file_viewer_show_line_numbers,
            "explorer_search":    self.explorer_search,
            "unit_params_search": self.unit_params_search,
            "selected_node_path": self.selected_node_path,
            "ui_theme":           self.ui_theme,
            "show_status_bar":          self.show_status_bar,
            "panel_mode":               self.panel_mode,
            "tabbed_panel_active":      self.tabbed_panel_active,
            "float_file_viewer_open":   self.float_file_viewer_open,
            "float_terminal_open":      self.float_terminal_open,
            "float_object_viewer_open": self.float_object_viewer_open,
            "float_fv_saved_x":  self.float_fv_saved_x,
            "float_fv_saved_y":  self.float_fv_saved_y,
            "float_term_saved_x": self.float_term_saved_x,
            "float_term_saved_y": self.float_term_saved_y,
            "float_ov_saved_x":  self.float_ov_saved_x,
            "float_ov_saved_y":  self.float_ov_saved_y,
            "appear_s_controls": self.appear_s_controls,
            "appear_s_infra":    self.appear_s_infra,
            "appear_s_wave":     self.appear_s_wave,
            "appear_s_file":     self.appear_s_file,
            "appear_s_popup":    self.appear_s_popup,
            "appear_s_terminal": self.appear_s_terminal,
            "appear_s_params":   self.appear_s_params,
            "appear_s_networks":  self.appear_s_networks,
            "appear_s_layout":    self.appear_s_layout,
            "appear_s_theme":     self.appear_s_theme,
            "appear_s_fw_repos":   self.appear_s_fw_repos,
            "fw_repos_git":        self.fw_repos_git,
            "fw_repos_config_pkg": self.fw_repos_config_pkg,
            "fw_repos_labels":     self.fw_repos_labels,
            "fw_repos_inaccessible": self.fw_repos_inaccessible,
            "fw_repos_zoom":         self.fw_repos_zoom,
            "fw_repos_backend":   self.fw_repos_backend,
            "fw_repos_packages":  self.fw_repos_packages,
            # Persistence: provider show/hide state so toggles survive restarts.
            # Written as a list of {provider-name, show} dicts; load path merges
            # with supported_providers so newly-added providers default to show: true.
            "providers": [
                {"provider-name": k, "show": v}
                for k, v in self.provider_filters.items()
            ],
            # Filter persistence: wave/region/env/package/role filters.
            # Stored as dicts (bool values) or list (roles).  on_load merges
            # with the current set so newly-added entries default to visible.
            "wave_filters":    {k: v for k, v in self.wave_filters.items()},
            "region_filters":  {k: v for k, v in self.region_filters.items()},
            "env_filters":     {k: v for k, v in self.env_filters.items()},
            "package_filters": {k: v for k, v in self.package_filters.items()},
            "selected_roles":  list(self.selected_roles),
        })

    # -----------------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------------

    def on_load(self):
        import time as _time
        now = _time_module.time()

        # Check the cross-process marker file to detect a recently-applied test state.
        secs_since_test = 9999.0
        try:
            secs_since_test = now - float(_TEST_APPLIED_MARKER.read_text())
        except Exception:
            pass

        _gui_log(f"[on_load] fired at {_time.strftime('%H:%M:%S')} — "
              f"test_state_exists={_TEST_STATE_FILE.exists()} "
              f"secs_since_marker={secs_since_test:.1f}")

        # Skip re-initialization if a test state was applied within the last 5s.
        # Reflex 0.8.27 fires on_load twice on fresh page load; the second call
        # would overwrite test state with defaults.  In dev mode the frontend
        # recompiles mid-test, causing the double-fire to arrive up to ~3s later.
        # 5s catches that without blocking legitimate new sessions, because every
        # new test session that has state to set will have test_state_exists=True
        # (the condition below) and will never be skipped regardless of the window.
        if not _TEST_STATE_FILE.exists() and secs_since_test < 5.0:
            _gui_log(f"[on_load] Skipping re-init — marker is {secs_since_test:.1f}s old")
            self.is_loading = False
            return [AppState.install_resizer, AppState.signal_inventory_ready]

        self.is_loading = True
        config = _load_config()
        state = _load_state()
        self.supported_providers = config.get("supported", {}).get("providers", [])
        saved_menu = state.get("current", {}).get("menu", {})
        self.left_view       = saved_menu.get("left_view",       "tree")
        self.viz_framework   = saved_menu.get("viz_framework",   "reflex")
        self.tree_mode       = saved_menu.get("tree_mode",       "separated")
        self.left_panel_width_pct = int(saved_menu.get("panel_width_pct", 50))
        self.panel_show_view_selector = saved_menu.get("panel_show_view_selector", True)
        self.panel_show_merged        = saved_menu.get("panel_show_merged",        True)
        self.panel_show_depth         = saved_menu.get("panel_show_depth",         True)
        self.show_full_module_name    = bool(saved_menu.get("show_full_module_name", False))
        self.show_wave_numbers        = bool(saved_menu.get("show_wave_numbers",     False))
        self.show_unit_build_status        = bool(saved_menu.get("show_unit_build_status",        False))
        self.unit_status_auto_refresh      = bool(saved_menu.get("unit_status_auto_refresh",      False))
        self.unit_status_auto_refresh_secs = int( saved_menu.get("unit_status_auto_refresh_secs", 30))
        self.object_viewer_mode       = saved_menu.get("object_viewer_mode", "params")
        self.wave_show_start_time     = bool(saved_menu.get("wave_show_start_time",  False))
        self.wave_show_end_time       = bool(saved_menu.get("wave_show_end_time",    False))
        self.wave_show_duration       = bool(saved_menu.get("wave_show_duration",    False))
        self.wave_show_age            = bool(saved_menu.get("wave_show_age",         False))
        self.wave_show_log_update     = bool(saved_menu.get("wave_show_log_update",  False))
        self.wave_highlight_recent     = bool(saved_menu.get("wave_highlight_recent",     True))
        self.auto_select_recent_unit   = bool(saved_menu.get("auto_select_recent_unit",   False))
        self.show_unit_popup           = bool(saved_menu.get("show_unit_popup",           False))
        self.terminal_hide_initial_cmd = bool(saved_menu.get("terminal_hide_initial_cmd", True))
        _saved_backend = saved_menu.get("terminal_backend", "ttyd" if _TTYD_AVAILABLE else "embedded")
        _valid_ids = {b["id"] for b in _TERMINAL_BACKENDS}
        _default_backend = "ttyd" if _TTYD_AVAILABLE else "embedded"
        self.terminal_backend = _saved_backend if _saved_backend in _valid_ids else _default_backend
        self.cy_show_dependencies      = bool(saved_menu.get("cy_show_dependencies",      False))
        self.cy_color_by_wave          = bool(saved_menu.get("cy_color_by_wave",          False))
        depth_limit_raw = int(saved_menu.get("depth_limit", 1))
        self.depth_limit = depth_limit_raw
        self.top_row_height_pct = int(saved_menu.get("top_row_height_pct", 60))
        self.resizer_drag_width = int(saved_menu.get("resizer_drag_width", 5))
        self.selected_editor_id = saved_menu.get("selected_editor_id", "")
        self.explorer_root  = saved_menu.get("explorer_root", "infra")
        self.hide_special_params = bool(saved_menu.get("hide_special_params", False))
        self.hide_provider_underscore_params = bool(saved_menu.get("hide_provider_underscore_params", False))
        self.param_wrap_values = bool(saved_menu.get("param_wrap_values", False))
        self.browser_profile = saved_menu.get("browser_profile", "playwright")
        self.chrome_profiles = _CHROME_PROFILES_CACHE
        self.cy_wheel_sensitivity = float(saved_menu.get("cy_wheel_sensitivity", 0.3))
        self.file_viewer_mode  = saved_menu.get("file_viewer_mode",  "unit_file")
        # Migrate from the old single file_search_query key if present
        _old_q = saved_menu.get("file_search_query", "")
        self.unit_file_search_query   = saved_menu.get("unit_file_search_query",   _old_q)
        self.config_data_search_query = saved_menu.get("config_data_search_query", "")
        self.config_data_quote_path     = bool(saved_menu.get("config_data_quote_path", _DEFAULT_CONFIG_DATA_QUOTE_PATH))
        self.file_search_smooth_scroll   = bool(saved_menu.get("file_search_smooth_scroll",  False))
        self.file_search_case_sensitive  = bool(saved_menu.get("file_search_case_sensitive", False))
        self.file_viewer_render_markdown = bool(saved_menu.get("file_viewer_render_markdown", True))
        self.file_viewer_show_line_numbers = bool(saved_menu.get("file_viewer_show_line_numbers", False))
        self.explorer_search      = saved_menu.get("explorer_search",      "")
        self.unit_params_search   = saved_menu.get("unit_params_search",   "")
        _saved_theme = saved_menu.get("ui_theme", "light")
        self.ui_theme = _saved_theme if _saved_theme in ("light", "dark") else "dark"
        self.show_status_bar          = bool(saved_menu.get("show_status_bar",          True))
        _saved_mode = saved_menu.get("panel_mode", None)
        if _saved_mode is None:
            # Migrate from old boolean — users who had floating mode keep it
            _saved_mode = "floating" if bool(saved_menu.get("floating_panels_mode", False)) else "4-panels"
        self.panel_mode = _saved_mode if _saved_mode in ("4-panels", "floating", "tabbed") else "4-panels"
        self.tabbed_panel_active = saved_menu.get("tabbed_panel_active", "file-viewer")
        self.float_file_viewer_open   = bool(saved_menu.get("float_file_viewer_open",   True))
        self.float_terminal_open      = bool(saved_menu.get("float_terminal_open",      True))
        self.float_object_viewer_open = bool(saved_menu.get("float_object_viewer_open", True))
        self.float_fv_saved_x   = saved_menu.get("float_fv_saved_x",   "")
        self.float_fv_saved_y   = saved_menu.get("float_fv_saved_y",   "")
        self.float_term_saved_x = saved_menu.get("float_term_saved_x", "")
        self.float_term_saved_y = saved_menu.get("float_term_saved_y", "")
        self.float_ov_saved_x   = saved_menu.get("float_ov_saved_x",   "")
        self.float_ov_saved_y   = saved_menu.get("float_ov_saved_y",   "")
        self.appear_s_controls = bool(saved_menu.get("appear_s_controls", True))
        self.appear_s_infra    = bool(saved_menu.get("appear_s_infra",    True))
        self.appear_s_wave     = bool(saved_menu.get("appear_s_wave",     False))
        self.appear_s_file     = bool(saved_menu.get("appear_s_file",     False))
        self.appear_s_popup    = bool(saved_menu.get("appear_s_popup",    False))
        self.appear_s_terminal = bool(saved_menu.get("appear_s_terminal", False))
        self.appear_s_params   = bool(saved_menu.get("appear_s_params",   False))
        self.appear_s_networks = bool(saved_menu.get("appear_s_networks",  False))
        self.appear_s_layout   = bool(saved_menu.get("appear_s_layout",    False))
        self.appear_s_theme    = bool(saved_menu.get("appear_s_theme",     False))
        self.appear_s_fw_repos    = bool(saved_menu.get("appear_s_fw_repos",    False))
        self.fw_repos_git        = str(saved_menu.get("fw_repos_git",        "show"))
        self.fw_repos_config_pkg = str(saved_menu.get("fw_repos_config_pkg", "show"))
        self.fw_repos_labels     = str(saved_menu.get("fw_repos_labels",     "show"))
        self.fw_repos_inaccessible = str( saved_menu.get("fw_repos_inaccessible", "normal"))
        self.fw_repos_zoom         = int( saved_menu.get("fw_repos_zoom",          100))
        self.fw_repos_backend  = str(saved_menu.get("fw_repos_backend",  "summary"))
        self.fw_repos_packages = str(saved_menu.get("fw_repos_packages", "a-z"))
        _saved_node            = saved_menu.get("selected_node_path", "")

        # Persistence: load saved provider visibility, falling back to True for any
        # provider not yet in the saved list (handles newly-added providers gracefully).
        # supported_providers (from de3-gui-pkg.yaml) is the source of truth for which
        # providers exist; current.yaml only persists the show/hide toggle state.
        _saved_prov = {
            p["provider-name"]: p.get("show", True)
            for p in state.get("current", {}).get("menu", {}).get("providers", [])
        }
        self.provider_filters = {
            p["provider-name"]: _saved_prov.get(p["provider-name"], True)
            for p in self.supported_providers
        }

        # Always rescan so on_load sees current filesystem state (handles deletions, pastes, etc.)
        _init_nodes_cache()
        _populate_module_tree_paths()
        _init_path_param_maps()
        flat = list(_ALL_NODES_CACHE)
        self.all_nodes = flat
        merged = _build_merged_nodes(flat)
        self.merged_nodes_base = merged

        # Initialise package filter
        self.package_filters = {
            n["name"]: True for n in flat if n.get("depth", -1) == 0
        }
        self.package_filters = {"_none": True, **{
            n["path"].split("/")[0]: True for n in flat if n.get("path", "").split("/")[0]
        }, **{pi.name: True for pi in _PACKAGES_CACHE if pi.name}}
        # Region and env filters: derived from config_params (source of truth),
        # not from folder depth. All values visible by default.
        self.region_filters = {"_none": True, **{v: True for v in set(_PATH_TO_REGION_CACHE.values())}}
        self.env_filters    = {"_none": True, **{v: True for v in set(_PATH_TO_ENV_CACHE.values())}}
        self.wave_filters   = _build_initial_wave_filters()
        # Apply saved filter state: merge with current available keys so newly-added
        # waves/regions/envs/packages default to visible (True) while restoring
        # previous hide state for known entries.
        _sv_wave = saved_menu.get("wave_filters", {})
        if _sv_wave:
            self.wave_filters = {k: _sv_wave.get(k, True) for k in self.wave_filters}
        _sv_region = saved_menu.get("region_filters", {})
        if _sv_region:
            self.region_filters = {k: _sv_region.get(k, True) for k in self.region_filters}
        _sv_env = saved_menu.get("env_filters", {})
        if _sv_env:
            self.env_filters = {k: _sv_env.get(k, True) for k in self.env_filters}
        _sv_pkg = saved_menu.get("package_filters", {})
        if _sv_pkg:
            self.package_filters = {k: _sv_pkg.get(k, True) for k in self.package_filters}
        _sv_roles = saved_menu.get("selected_roles", [])
        if _sv_roles:
            self.selected_roles = [r for r in _sv_roles if r in self.available_roles]
        # Expand paths according to the restored (or default) depth_limit.
        dlim = self.depth_limit
        if dlim == 0:
            self.expanded_paths        = [n["path"] for n in flat]
            self.merged_expanded_paths = [n["path"] for n in merged]
        else:
            self.expanded_paths        = [n["path"] for n in flat   if n["depth"] < dlim]
            self.merged_expanded_paths = [n["path"] for n in merged if n["depth"] < dlim]
        # If a search was restored from state, auto-expand ancestors of matching
        # nodes so they are visible on load (same logic as set_explorer_search).
        if self.explorer_search:
            s = self.explorer_search.lower().strip()
            exps  = set(self.expanded_paths)
            mexps = set(self.merged_expanded_paths)
            for node in flat:
                p = node.get("path", "")
                if s in node.get("name", "").lower() or s in p.lower():
                    parts = p.split("/")
                    for i in range(1, len(parts)):
                        exps.add("/".join(parts[:i]))
            for node in merged:
                p = node.get("path", "")
                if s in node.get("name", "").lower() or s in p.lower():
                    parts = p.split("/")
                    for i in range(1, len(parts)):
                        mexps.add("/".join(parts[:i]))
            self.expanded_paths        = list(exps)
            self.merged_expanded_paths = list(mexps)

        # Modules and packages trees
        self.modules_nodes = _MODULES_NODES_CACHE
        self.modules_expanded_paths = [n["path"] for n in _MODULES_NODES_CACHE if n["depth"] == 0]
        self.packages_data = _PACKAGES_CACHE
        self.ext_package_repos = _load_ext_package_repos()
        self.pkg_repos_config  = _read_pkg_repos_config()

        # Framework repos data
        if _FW_REPOS_YAML.exists():
            _fw_raw = yaml.safe_load(_FW_REPOS_YAML.read_text()) or {}
            self.framework_repos_data = _fw_raw.get("data", {}).get("repos", {})

        # Load role maps from inventory
        avail_roles, nm_roles = _build_role_maps()
        self.available_roles = avail_roles
        self.node_name_roles = nm_roles

        # Refresh the Ansible inventory in the background (once per process).
        global _INVENTORY_REFRESH_DONE
        if not _INVENTORY_REFRESH_DONE:
            _INVENTORY_REFRESH_DONE = True
            _run_inventory_refresh(background=True)

        self.is_loading = False

        # Re-select the last-clicked node (loads its file, restores right panel).
        if _saved_node and any(n["path"] == _saved_node for n in self.all_nodes):
            self.select_node(_saved_node)
        # If config_data mode with no saved node (or select_node above left content empty),
        # still load the config file so the viewer isn't blank.
        if self.file_viewer_mode == "config_data" and not self.hcl_content:
            content, fpath = _read_stack_config_file()
            self.hcl_content = content
            self.hcl_file_path = fpath if fpath else "(stack config not found...)"

        # Apply test state AFTER select_node so it is not cleared by select_node's reset logic.
        _apply_test_state(self)
        # Refresh the marker so the double-fire guard's window is relative to
        # *this* on_load call, not the earlier API write.
        try:
            _TEST_APPLIED_MARKER.write_text(str(_time_module.time()))
        except Exception:
            pass

        # Populate build statuses from the local unit-state.yaml (zero-latency, no network).
        # The file is written by local_state_watcher on every detected apply and by the
        # validate path (do_validate_unit_build_statuses) after each GCS scan.
        # GCS mtime cache is intentionally cleared so the next validate does a full diff.
        if self.show_unit_build_status:
            unit_state = _read_unit_state()
            if unit_state:
                self.unit_build_statuses = {
                    path: entry["status"]
                    for path, entry in unit_state.items()
                    if "status" in entry
                }
                _gui_log(f"[on_load] loaded {len(unit_state)} unit statuses from unit-state.yaml")
            else:
                self.unit_build_statuses = {}
            self.gcs_state_mtimes = {}

        # If ttyd is not yet installed, attempt a background install so it's ready
        # after the user reloads the page (or within this session if install is fast).
        if not _TTYD_AVAILABLE:
            _try_install_ttyd_background()

        scripts = [
            AppState.install_resizer,
            rx.call_script(_apply_color_mode_js(self.ui_theme)),
            AppState.config_file_watcher,      # start per-client file watcher
            AppState.signal_inventory_ready,   # recompute action buttons once inventory is ready
            AppState.local_state_watcher,      # process-level singleton; no-op if already running
            AppState.sync_unit_status_from_gcs,  # recover unit statuses from GCS on startup
            AppState.sync_wave_status_from_gcs,  # recover wave history from GCS on startup
        ]
        if self.panel_mode == "floating":
            scripts.append(AppState.init_all_float_panels)
        if self.object_viewer_mode == "waves":
            self.refresh_wave_log_statuses()
            scripts.append(rx.call_script(self._WAVE_POLL_START_JS))
        q = self._active_file_search
        if q and self.hcl_content:
            if self.selected_node_path and self.file_viewer_mode == "config_data":
                # Use provider-anchored search for config-data with a selected node
                raw = q[1:-1] if (q.startswith('"') and q.endswith('"') and len(q) >= 2) else q
                scripts.append(self._search_script(_config_data_node_search_js(
                    raw, self._selected_node_provider, self.config_data_quote_path, self.file_search_smooth_scroll
                )))
            else:
                direction = "last" if self.selected_node_path else "init"
                scripts.append(self._search_script(_pre_search_js(q, direction, self.file_search_smooth_scroll, case_sensitive=self.file_search_case_sensitive)))
        return scripts

    def install_resizer(self):
        """Runs resizer JS through the websocket — guaranteed to execute post-hydration."""
        return rx.call_script(
            _RESIZER_JS + _HRESIZER_JS + _FLOAT_ZORDER_JS
            + _yaml_breadcrumb_install_js() + _markdown_link_interceptor_js()
        )

    def toggle_provider(self, provider: str):
        self.provider_filters = {
            **self.provider_filters,
            provider: not self.provider_filters.get(provider, True),
        }
        self._save_current_config()

    def solo_provider(self, provider: str):
        """Double-click handler: toggle solo for this provider filter.

        First double-click: check only this provider, uncheck all others.
        Second double-click (provider already soloed): invert — uncheck only
        this provider, check all others.
        """
        if provider not in self.provider_filters:
            return
        already_soloed = (
            self.provider_filters.get(provider, False)
            and all(not v for k, v in self.provider_filters.items() if k != provider)
        )
        if already_soloed:
            self.provider_filters = {k: (k != provider) for k in self.provider_filters}
        else:
            self.provider_filters = {k: (k == provider) for k in self.provider_filters}
        self._save_current_config()

    def set_viz_framework(self, fw: str):
        self.viz_framework = fw
        self.selected_node_path = ""
        self.active_provider_tab = ""
        self._save_current_config()

    def set_left_view(self, view: str):
        self.left_view = view
        self._save_current_config()

    def set_view_mode(self, mode: str):
        """Combined handler: 'tree' → reflex/tree, 'cytoscape' → cytoscape, 'reactflow' → reactflow, 'archdiagram' → archdiagram."""
        if mode == "cytoscape":
            self.viz_framework = "cytoscape"
        elif mode == "reactflow":
            self.viz_framework = "reactflow"
        elif mode == "archdiagram":
            self.viz_framework = "archdiagram"
        else:
            self.viz_framework = "reflex"
            self.left_view = "tree"
        self.selected_node_path = ""
        self.active_provider_tab = ""
        self._save_current_config()

    def set_tree_mode(self, mode: str):
        self.tree_mode = mode
        self.selected_node_path = ""
        self.active_provider_tab = ""
        self._save_current_config()

    def toggle_tree_mode(self, checked: bool):
        """Checkbox handler: checked → merged, unchecked → separated."""
        self.tree_mode = "merged" if checked else "separated"
        self.selected_node_path = ""
        self.active_provider_tab = ""
        self._save_current_config()

    def toggle_panel_view_selector(self, checked: bool):
        self.panel_show_view_selector = checked
        self._save_current_config()

    def flip_panel_view_selector(self):
        self.panel_show_view_selector = not self.panel_show_view_selector
        self._save_current_config()

    def toggle_panel_merged(self, checked: bool):
        self.panel_show_merged = checked
        self._save_current_config()

    def flip_panel_merged(self):
        self.panel_show_merged = not self.panel_show_merged
        self._save_current_config()

    def toggle_panel_depth(self, checked: bool):
        self.panel_show_depth = checked
        self._save_current_config()

    def flip_panel_depth(self):
        self.panel_show_depth = not self.panel_show_depth
        self._save_current_config()

    def toggle_show_full_module_name(self, checked: bool):
        self.show_full_module_name = checked
        self._save_current_config()

    def flip_show_full_module_name(self):
        self.show_full_module_name = not self.show_full_module_name
        self._save_current_config()

    def toggle_show_wave_numbers(self, checked: bool):
        self.show_wave_numbers = checked
        self._save_current_config()

    def flip_show_wave_numbers(self):
        self.show_wave_numbers = not self.show_wave_numbers
        self._save_current_config()

    def toggle_show_unit_build_status(self, checked: bool):
        self.show_unit_build_status = checked
        self._save_current_config()
        if checked:
            return AppState.refresh_unit_build_statuses

    def flip_show_unit_build_status(self):
        self.show_unit_build_status = not self.show_unit_build_status
        self._save_current_config()
        if self.show_unit_build_status:
            return AppState.refresh_unit_build_statuses

    def toggle_unit_status_auto_refresh(self, checked: bool):
        self.unit_status_auto_refresh = checked
        self._save_current_config()

    def flip_unit_status_auto_refresh(self):
        self.unit_status_auto_refresh = not self.unit_status_auto_refresh
        self._save_current_config()

    def set_unit_status_auto_refresh_secs(self, value: int):
        """Set the auto-refresh interval in seconds (0 = on-change only, ≥5 otherwise)."""
        # Clamp: 0 (on-change) or minimum 5 s to avoid hammering the YAML reader.
        self.unit_status_auto_refresh_secs = 0 if value <= 0 else max(5, value)
        self._save_current_config()

    def toggle_wave_show_start_time(self, checked: bool):
        self.wave_show_start_time = checked
        self._save_current_config()

    def flip_wave_show_start_time(self):
        self.wave_show_start_time = not self.wave_show_start_time
        self._save_current_config()

    def toggle_wave_show_end_time(self, checked: bool):
        self.wave_show_end_time = checked
        self._save_current_config()

    def flip_wave_show_end_time(self):
        self.wave_show_end_time = not self.wave_show_end_time
        self._save_current_config()

    def toggle_wave_show_duration(self, checked: bool):
        self.wave_show_duration = checked
        self._save_current_config()

    def flip_wave_show_duration(self):
        self.wave_show_duration = not self.wave_show_duration
        self._save_current_config()

    def toggle_wave_show_age(self, checked: bool):
        self.wave_show_age = checked
        self._save_current_config()

    def flip_wave_show_age(self):
        self.wave_show_age = not self.wave_show_age
        self._save_current_config()

    def toggle_wave_show_log_update(self, checked: bool):
        self.wave_show_log_update = checked
        self._save_current_config()

    def flip_wave_show_log_update(self):
        self.wave_show_log_update = not self.wave_show_log_update
        self._save_current_config()

    def toggle_wave_highlight_recent(self, checked: bool):
        self.wave_highlight_recent = checked
        self._save_current_config()

    def flip_wave_highlight_recent(self):
        self.wave_highlight_recent = not self.wave_highlight_recent
        self._save_current_config()

    def toggle_auto_select_recent_unit(self, checked: bool):
        self.auto_select_recent_unit = checked
        self._save_current_config()

    def flip_auto_select_recent_unit(self):
        self.auto_select_recent_unit = not self.auto_select_recent_unit
        self._save_current_config()
        if self.auto_select_recent_unit:
            # Immediately select the most recently applied unit so the user
            # sees feedback right away rather than waiting for the next apply.
            unit_state = _read_unit_state()
            best = max(
                (p for p in unit_state if "last_apply_at" in unit_state[p]),
                key=lambda p: str(unit_state[p]["last_apply_at"]),
                default="",
            )
            _gui_log(f"[auto-select] enabled — selecting {best!r}")
            if best:
                self.recent_unit_path = best
                # Switch to tree view so the selection is visible.
                self.left_view = "tree"
                # Expand ancestors so the node is in visible_nodes when
                # click_node fires.  _stack is virtual so include it anyway —
                # the visibility check skips it.
                parts = best.split("/")
                ancestors = {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}
                self.expanded_paths        = list(set(self.expanded_paths)        | ancestors)
                self.merged_expanded_paths = list(set(self.merged_expanded_paths) | ancestors)
                # Return click_node as an event spec so Reflex dispatches it as a
                # real event AFTER this event's state delta (expanded ancestors) is
                # flushed to the frontend.  click_node uses yield internally to
                # highlight the selection before loading HCL, which is why calling
                # select_node() as a plain Python method didn't work.
                # Also scroll the selected row (id="tree-selected-node") into the
                # centre of the panel; 300 ms gives click_node's two-phase yield
                # time to finish and React to commit the updated DOM.
                scroll_js = (
                    "requestAnimationFrame(function(){"
                    "var el=document.getElementById('tree-selected-node');"
                    "if(el)el.scrollIntoView({block:'center',behavior:'smooth'});"
                    "});"
                )
                return [AppState.click_node(best), rx.call_script(scroll_js)]

    # ---------------------------------------------------------------------------
    # Unit detail popup — checkbox-controlled floating window
    # ---------------------------------------------------------------------------

    def _load_hover_popup_for_path(self, path: str) -> None:
        """Populate popup state vars for the given path.  Plain Python helper —
        call only from within Reflex event handlers or async with self: blocks."""
        self.hover_popup_node_path = path
        unit_state = _read_unit_state()
        self.hover_popup_unit_state = unit_state.get(path, {})
        self.hover_popup_params = _get_unit_params_flat(path, self.tree_mode == "merged")
        self.hover_popup_open = True

    def toggle_show_unit_popup(self, checked: bool):
        self.show_unit_popup = checked
        self._save_current_config()
        if checked and self.selected_node_path:
            self._load_hover_popup_for_path(self.selected_node_path)
            return AppState.init_popup_drag
        elif not checked:
            self.hover_popup_open = False

    def flip_show_unit_popup(self):
        self.show_unit_popup = not self.show_unit_popup
        self._save_current_config()
        if self.show_unit_popup and self.selected_node_path:
            self._load_hover_popup_for_path(self.selected_node_path)
            return AppState.init_popup_drag
        elif not self.show_unit_popup:
            self.hover_popup_open = False

    def init_popup_drag(self):
        """Wire pointer-capture drag on the popup header after the popup appears.
        Uses a retry loop so the element exists in the DOM before the listeners
        are attached.  A guard flag prevents duplicate listeners on subsequent
        node selections.
        On first open the popup is positioned to cover the right panel (top-right-panel
        in normal mode) or to fill the right-side space (floating-panels mode)."""
        js = (
            "(function tryInit(){"
            "  var win=document.getElementById('hover-popup-window');"
            "  var hdr=document.getElementById('hover-popup-header');"
            "  if(!win||!hdr){setTimeout(tryInit,20);return;}"
            # Snap position/size to the right panel on first open (guard: _positionSet)
            "  if(!win._positionSet){"
            "    win._positionSet=true;"
            "    var panel=document.getElementById('top-right-panel');"
            "    if(panel){"
            "      var r=panel.getBoundingClientRect();"
            "      var x=r.left,y=r.top,w=r.width,h=r.height;"
            "      win.style.left=x+'px';win.style.top=y+'px';"
            "      win.style.width=w+'px';win.style.height=h+'px';"
            "      document.documentElement.style.setProperty('--popup-x',x+'px');"
            "      document.documentElement.style.setProperty('--popup-y',y+'px');"
            "    }else{"
            "      var leftCol=document.getElementById('left-column');"
            "      var lx=leftCol?(Math.round(leftCol.getBoundingClientRect().right)+8):Math.round(window.innerWidth*0.45);"
            "      var avw=Math.max(300,window.innerWidth-lx-16);"
            "      var avh=Math.max(200,window.innerHeight-56);"
            "      win.style.left=lx+'px';win.style.top='48px';"
            "      win.style.width=Math.min(avw,900)+'px';win.style.height=Math.min(avh,800)+'px';"
            "      document.documentElement.style.setProperty('--popup-x',lx+'px');"
            "      document.documentElement.style.setProperty('--popup-y','48px');"
            "    }"
            "  }"
            "  if(!win._zorderInstalled){"
            "    win._zorderInstalled=true;"
            "    win.addEventListener('pointerdown',function(){"
            "      ['float-fv-window','float-term-window','float-ov-window','float-refactor-window','hover-popup-window'].forEach(function(id){"
            "        var el=document.getElementById(id);if(el)el.style.zIndex='9990';"
            "      });"
            "      win.style.zIndex='9992';"
            "    },true);"
            "  }"
            "  if(hdr._dragInstalled)return;"
            "  hdr._dragInstalled=true;"
            "  var dragging=false,ox=0,oy=0,sl=0,st=0;"
            "  var onMove=function(e){"
            "    if(!dragging)return;"
            "    var nx=sl+e.clientX-ox,ny=st+e.clientY-oy;"
            "    win.style.left=nx+'px';win.style.top=ny+'px';"
            "    document.documentElement.style.setProperty('--popup-x',nx+'px');"
            "    document.documentElement.style.setProperty('--popup-y',ny+'px');"
            "  };"
            "  var onUp=function(){"
            "    if(!dragging)return;dragging=false;"
            "    document.removeEventListener('mousemove',onMove);"
            "    document.removeEventListener('mouseup',onUp);"
            "  };"
            "  hdr.addEventListener('mousedown',function(e){"
            "    if(e.button!==0)return;"
            "    if(e.target.closest('button'))return;"
            "    e.preventDefault();"
            "    dragging=true;ox=e.clientX;oy=e.clientY;"
            "    sl=parseInt(win.style.left)||win.getBoundingClientRect().left;"
            "    st=parseInt(win.style.top)||win.getBoundingClientRect().top;"
            "    document.addEventListener('mousemove',onMove);"
            "    document.addEventListener('mouseup',onUp);"
            "  });"
            "})()"
        )
        return rx.call_script(js)

    def close_hover_popup(self):
        """Close the floating unit-detail popup and uncheck the appearance toggle."""
        self.hover_popup_open = False
        self.hover_popup_node_path = ""
        self.hover_popup_unit_state = {}
        self.hover_popup_params = []
        self.show_unit_popup = False
        self._save_current_config()

    # ── Status bar ───────────────────────────────────────────────────────────

    def toggle_show_status_bar(self, value: bool):
        self.show_status_bar = value
        self._save_current_config()

    def flip_show_status_bar(self):
        self.show_status_bar = not self.show_status_bar
        self._save_current_config()

    # ── Panel layout mode ────────────────────────────────────────────────────

    def set_panel_mode(self, mode: str):
        self.panel_mode = mode
        self._save_current_config()
        if mode == "floating":
            return AppState.init_all_float_panels

    def set_tabbed_panel_active(self, tab: str):
        self.tabbed_panel_active = tab
        self._save_current_config()

    def init_all_float_panels(self):
        return [
            AppState.init_float_file_viewer,
            AppState.init_float_terminal,
            AppState.init_float_object_viewer,
        ]

    # ── Floating file viewer ─────────────────────────────────────────────────

    def toggle_float_file_viewer(self, checked: bool):
        self.float_file_viewer_open = checked
        self._save_current_config()
        if checked:
            return AppState.init_float_file_viewer

    def flip_float_file_viewer(self):
        self.float_file_viewer_open = not self.float_file_viewer_open
        self._save_current_config()
        if self.float_file_viewer_open:
            return AppState.init_float_file_viewer

    def close_float_file_viewer(self):
        """Close panel, save its current position, uncheck Panels menu."""
        self.float_file_viewer_open = False
        self._save_current_config()
        return [
            rx.call_script(
                "document.documentElement.style.getPropertyValue('--fv-x')||''",
                callback=AppState.save_float_fv_x,
            ),
            rx.call_script(
                "document.documentElement.style.getPropertyValue('--fv-y')||''",
                callback=AppState.save_float_fv_y,
            ),
        ]

    def save_float_fv_x(self, val: str):
        if val:
            self.float_fv_saved_x = val
            self._save_current_config()

    def save_float_fv_y(self, val: str):
        if val:
            self.float_fv_saved_y = val
            self._save_current_config()

    def init_float_file_viewer(self):
        sx = self.float_fv_saved_x or ""
        sy = self.float_fv_saved_y or ""
        js = (
            "(function tryInit(){"
            "  var win=document.getElementById('float-fv-window');"
            "  var hdr=document.getElementById('float-fv-header');"
            "  if(!win||!hdr){setTimeout(tryInit,20);return;}"
            "  if(!win._positionSet){"
            "    win._positionSet=true;"
            f"    var sx={repr(sx)},sy={repr(sy)};"
            "    if(sx&&sy){"
            "      win.style.left=sx;win.style.top=sy;"
            "      document.documentElement.style.setProperty('--fv-x',sx);"
            "      document.documentElement.style.setProperty('--fv-y',sy);"
            "    }else{"
            "      var leftCol=document.getElementById('left-column');"
            "      var lx=leftCol?(Math.round(leftCol.getBoundingClientRect().right)+8):Math.round(window.innerWidth*0.45);"
            "      var avw=Math.max(300,window.innerWidth-lx-16);"
            "      var avh=Math.max(200,window.innerHeight-56);"
            "      win.style.left=lx+'px';win.style.top='48px';"
            "      win.style.width=Math.min(avw,900)+'px';win.style.height=Math.min(avh,800)+'px';"
            "      document.documentElement.style.setProperty('--fv-x',lx+'px');"
            "      document.documentElement.style.setProperty('--fv-y','48px');"
            "    }"
            "  }"
            "  if(!win._zorderInstalled){"
            "    win._zorderInstalled=true;"
            "    win.addEventListener('pointerdown',function(){"
            "      ['float-fv-window','float-term-window','float-ov-window','float-refactor-window','hover-popup-window'].forEach(function(id){"
            "        var el=document.getElementById(id);if(el)el.style.zIndex='9990';"
            "      });"
            "      win.style.zIndex='9992';"
            "    },true);"
            "  }"
            "  if(hdr._dragInstalled)return;"
            "  hdr._dragInstalled=true;"
            "  var dragging=false,ox=0,oy=0,sl=0,st=0;"
            "  var onMove=function(e){"
            "    if(!dragging)return;"
            "    var nx=sl+e.clientX-ox,ny=st+e.clientY-oy;"
            "    win.style.left=nx+'px';win.style.top=ny+'px';"
            "    document.documentElement.style.setProperty('--fv-x',nx+'px');"
            "    document.documentElement.style.setProperty('--fv-y',ny+'px');"
            "  };"
            "  var onUp=function(){"
            "    if(!dragging)return;dragging=false;"
            "    document.removeEventListener('mousemove',onMove);"
            "    document.removeEventListener('mouseup',onUp);"
            "  };"
            "  hdr.addEventListener('mousedown',function(e){"
            "    if(e.button!==0)return;"
            "    if(e.target.closest('button'))return;"
            "    e.preventDefault();"
            "    dragging=true;ox=e.clientX;oy=e.clientY;"
            "    sl=parseInt(win.style.left)||win.getBoundingClientRect().left;"
            "    st=parseInt(win.style.top)||win.getBoundingClientRect().top;"
            "    document.addEventListener('mousemove',onMove);"
            "    document.addEventListener('mouseup',onUp);"
            "  });"
            "})()"
        )
        return rx.call_script(js)

    # ── Floating terminal ────────────────────────────────────────────────────

    def toggle_float_terminal(self, checked: bool):
        self.float_terminal_open = checked
        self._save_current_config()
        if checked:
            return AppState.init_float_terminal

    def flip_float_terminal(self):
        self.float_terminal_open = not self.float_terminal_open
        self._save_current_config()
        if self.float_terminal_open:
            return AppState.init_float_terminal

    def close_float_terminal(self):
        """Close panel, save its current position, uncheck Panels menu."""
        self.float_terminal_open = False
        self._save_current_config()
        return [
            rx.call_script(
                "document.documentElement.style.getPropertyValue('--term-x')||''",
                callback=AppState.save_float_term_x,
            ),
            rx.call_script(
                "document.documentElement.style.getPropertyValue('--term-y')||''",
                callback=AppState.save_float_term_y,
            ),
        ]

    def save_float_term_x(self, val: str):
        if val:
            self.float_term_saved_x = val
            self._save_current_config()

    def save_float_term_y(self, val: str):
        if val:
            self.float_term_saved_y = val
            self._save_current_config()

    def init_float_terminal(self):
        sx = self.float_term_saved_x or ""
        sy = self.float_term_saved_y or ""
        js = (
            "(function tryInit(){"
            "  var win=document.getElementById('float-term-window');"
            "  var hdr=document.getElementById('float-term-header');"
            "  if(!win||!hdr){setTimeout(tryInit,20);return;}"
            "  if(!win._positionSet){"
            "    win._positionSet=true;"
            f"    var sx={repr(sx)},sy={repr(sy)};"
            "    if(sx&&sy){"
            "      win.style.left=sx;win.style.top=sy;"
            "      document.documentElement.style.setProperty('--term-x',sx);"
            "      document.documentElement.style.setProperty('--term-y',sy);"
            "    }else{"
            "      var leftCol=document.getElementById('left-column');"
            "      var lx=leftCol?(Math.round(leftCol.getBoundingClientRect().right)+8):Math.round(window.innerWidth*0.45);"
            "      var avw=Math.max(300,window.innerWidth-lx-16);"
            "      var avh=Math.max(200,window.innerHeight-56);"
            "      win.style.left=lx+'px';win.style.top='48px';"
            "      win.style.width=Math.min(avw,900)+'px';win.style.height=Math.min(avh,800)+'px';"
            "      document.documentElement.style.setProperty('--term-x',lx+'px');"
            "      document.documentElement.style.setProperty('--term-y','48px');"
            "    }"
            "  }"
            "  if(!win._zorderInstalled){"
            "    win._zorderInstalled=true;"
            "    win.addEventListener('pointerdown',function(){"
            "      ['float-fv-window','float-term-window','float-ov-window','float-refactor-window','hover-popup-window'].forEach(function(id){"
            "        var el=document.getElementById(id);if(el)el.style.zIndex='9990';"
            "      });"
            "      win.style.zIndex='9992';"
            "    },true);"
            "  }"
            "  if(hdr._dragInstalled)return;"
            "  hdr._dragInstalled=true;"
            "  var dragging=false,ox=0,oy=0,sl=0,st=0;"
            "  var onMove=function(e){"
            "    if(!dragging)return;"
            "    var nx=sl+e.clientX-ox,ny=st+e.clientY-oy;"
            "    win.style.left=nx+'px';win.style.top=ny+'px';"
            "    document.documentElement.style.setProperty('--term-x',nx+'px');"
            "    document.documentElement.style.setProperty('--term-y',ny+'px');"
            "  };"
            "  var onUp=function(){"
            "    if(!dragging)return;dragging=false;"
            "    document.removeEventListener('mousemove',onMove);"
            "    document.removeEventListener('mouseup',onUp);"
            "  };"
            "  hdr.addEventListener('mousedown',function(e){"
            "    if(e.button!==0)return;"
            "    if(e.target.closest('button'))return;"
            "    e.preventDefault();"
            "    dragging=true;ox=e.clientX;oy=e.clientY;"
            "    sl=parseInt(win.style.left)||win.getBoundingClientRect().left;"
            "    st=parseInt(win.style.top)||win.getBoundingClientRect().top;"
            "    document.addEventListener('mousemove',onMove);"
            "    document.addEventListener('mouseup',onUp);"
            "  });"
            "})()"
        )
        return rx.call_script(js)

    # ── Floating object viewer ────────────────────────────────────────────────

    def toggle_float_object_viewer(self, checked: bool):
        self.float_object_viewer_open = checked
        self._save_current_config()
        if checked:
            return AppState.init_float_object_viewer

    def flip_float_object_viewer(self):
        self.float_object_viewer_open = not self.float_object_viewer_open
        self._save_current_config()
        if self.float_object_viewer_open:
            return AppState.init_float_object_viewer

    def close_float_object_viewer(self):
        """Close panel, save its current position, uncheck Panels menu."""
        self.float_object_viewer_open = False
        self._save_current_config()
        return [
            rx.call_script(
                "document.documentElement.style.getPropertyValue('--ov-x')||''",
                callback=AppState.save_float_ov_x,
            ),
            rx.call_script(
                "document.documentElement.style.getPropertyValue('--ov-y')||''",
                callback=AppState.save_float_ov_y,
            ),
        ]

    def save_float_ov_x(self, val: str):
        if val:
            self.float_ov_saved_x = val
            self._save_current_config()

    def save_float_ov_y(self, val: str):
        if val:
            self.float_ov_saved_y = val
            self._save_current_config()

    def init_float_object_viewer(self):
        sx = self.float_ov_saved_x or ""
        sy = self.float_ov_saved_y or ""
        js = (
            "(function tryInit(){"
            "  var win=document.getElementById('float-ov-window');"
            "  var hdr=document.getElementById('float-ov-header');"
            "  if(!win||!hdr){setTimeout(tryInit,20);return;}"
            "  if(!win._positionSet){"
            "    win._positionSet=true;"
            f"    var sx={repr(sx)},sy={repr(sy)};"
            "    if(sx&&sy){"
            "      win.style.left=sx;win.style.top=sy;"
            "      document.documentElement.style.setProperty('--ov-x',sx);"
            "      document.documentElement.style.setProperty('--ov-y',sy);"
            "    }else{"
            "      var leftCol=document.getElementById('left-column');"
            "      var lx=leftCol?(Math.round(leftCol.getBoundingClientRect().right)+8):Math.round(window.innerWidth*0.45);"
            "      var avw=Math.max(300,window.innerWidth-lx-16);"
            "      var avh=Math.max(200,window.innerHeight-56);"
            "      win.style.left=lx+'px';win.style.top='48px';"
            "      win.style.width=Math.min(avw,900)+'px';win.style.height=Math.min(avh,800)+'px';"
            "      document.documentElement.style.setProperty('--ov-x',lx+'px');"
            "      document.documentElement.style.setProperty('--ov-y','48px');"
            "    }"
            "  }"
            "  if(!win._zorderInstalled){"
            "    win._zorderInstalled=true;"
            "    win.addEventListener('pointerdown',function(){"
            "      ['float-fv-window','float-term-window','float-ov-window','float-refactor-window','hover-popup-window'].forEach(function(id){"
            "        var el=document.getElementById(id);if(el)el.style.zIndex='9990';"
            "      });"
            "      win.style.zIndex='9992';"
            "    },true);"
            "  }"
            "  if(hdr._dragInstalled)return;"
            "  hdr._dragInstalled=true;"
            "  var dragging=false,ox=0,oy=0,sl=0,st=0;"
            "  var onMove=function(e){"
            "    if(!dragging)return;"
            "    var nx=sl+e.clientX-ox,ny=st+e.clientY-oy;"
            "    win.style.left=nx+'px';win.style.top=ny+'px';"
            "    document.documentElement.style.setProperty('--ov-x',nx+'px');"
            "    document.documentElement.style.setProperty('--ov-y',ny+'px');"
            "  };"
            "  var onUp=function(){"
            "    if(!dragging)return;dragging=false;"
            "    document.removeEventListener('mousemove',onMove);"
            "    document.removeEventListener('mouseup',onUp);"
            "  };"
            "  hdr.addEventListener('mousedown',function(e){"
            "    if(e.button!==0)return;"
            "    if(e.target.closest('button'))return;"
            "    e.preventDefault();"
            "    dragging=true;ox=e.clientX;oy=e.clientY;"
            "    sl=parseInt(win.style.left)||win.getBoundingClientRect().left;"
            "    st=parseInt(win.style.top)||win.getBoundingClientRect().top;"
            "    document.addEventListener('mousemove',onMove);"
            "    document.addEventListener('mouseup',onUp);"
            "  });"
            "})()"
        )
        return rx.call_script(js)

    # ── Appearance accordion section toggles ─────────────────────────────────

    def flip_appear_s_controls(self): self.appear_s_controls = not self.appear_s_controls; self._save_current_config()
    def flip_appear_s_infra(self):    self.appear_s_infra    = not self.appear_s_infra;    self._save_current_config()
    def flip_appear_s_wave(self):     self.appear_s_wave     = not self.appear_s_wave;     self._save_current_config()
    def flip_appear_s_file(self):     self.appear_s_file     = not self.appear_s_file;     self._save_current_config()
    def flip_appear_s_popup(self):    self.appear_s_popup    = not self.appear_s_popup;    self._save_current_config()
    def flip_appear_s_terminal(self): self.appear_s_terminal = not self.appear_s_terminal; self._save_current_config()
    def flip_appear_s_params(self):   self.appear_s_params   = not self.appear_s_params;   self._save_current_config()
    def flip_appear_s_networks(self):  self.appear_s_networks = not self.appear_s_networks; self._save_current_config()
    def flip_appear_s_layout(self):    self.appear_s_layout   = not self.appear_s_layout;   self._save_current_config()
    def flip_appear_s_theme(self):     self.appear_s_theme    = not self.appear_s_theme;    self._save_current_config()
    def flip_appear_s_fw_repos(self):  self.appear_s_fw_repos = not self.appear_s_fw_repos; self._save_current_config()

    def set_fw_repos_git(self, val: str):        self.fw_repos_git = val;        self._save_current_config()
    def set_fw_repos_config_pkg(self, val: str): self.fw_repos_config_pkg = val; self._save_current_config()
    def set_fw_repos_labels(self, val: str):     self.fw_repos_labels = val;     self._save_current_config()
    def set_fw_repos_packages(self, val: str):   self.fw_repos_packages = val;   self._save_current_config()

    def set_fw_repos_inaccessible(self, val: str): self.fw_repos_inaccessible = val; self._save_current_config()
    def set_fw_repos_backend(self, val: str):      self.fw_repos_backend = val;      self._save_current_config()

    async def set_fw_repos_zoom(self, value: Any):
        """Set the fw-repos diagram zoom level and apply it to the live iframe."""
        try:
            pct = int(round(float(value[0]) if isinstance(value, list) else float(value)))
        except (TypeError, ValueError):
            return
        self.fw_repos_zoom = max(10, min(_FW_REPOS_ZOOM_MAX, pct))
        self._save_current_config()
        z = self.fw_repos_zoom / 100.0
        yield rx.call_script(
            "var f=document.querySelector('iframe[src*=\"fw_repos\"]');"
            "if(f&&f.contentWindow){"
            "var w=f.contentWindow,cx=w.innerWidth/2,cy=w.innerHeight/2;"
            f"if(w._applyZoom)w._applyZoom({z},cx,cy);"
            "}"
        )

    def toggle_terminal_hide_initial_cmd(self, checked: bool):
        self.terminal_hide_initial_cmd = checked
        self._save_current_config()

    def flip_terminal_hide_initial_cmd(self):
        self.terminal_hide_initial_cmd = not self.terminal_hide_initial_cmd
        self._save_current_config()

    def set_terminal_backend(self, backend: str):
        self.terminal_backend = backend
        self._save_current_config()

    def install_ttyd(self):
        """Run the platform-appropriate ttyd install command in the embedded terminal."""
        self.ttyd_port = 0  # ensure embedded path in terminal_iframe_url
        self.shell_cwd = str(Path.home())
        self.shell_initial_cmd = _TTYD_INSTALL_CMD

    def toggle_cy_show_dependencies(self, checked: bool):
        self.cy_show_dependencies = checked
        self._save_current_config()

    def flip_cy_show_dependencies(self):
        self.cy_show_dependencies = not self.cy_show_dependencies
        self._save_current_config()

    def toggle_cy_color_by_wave(self, checked: bool):
        self.cy_color_by_wave = checked
        self._save_current_config()

    def flip_cy_color_by_wave(self):
        self.cy_color_by_wave = not self.cy_color_by_wave
        self._save_current_config()

    def toggle_file_viewer_render_markdown(self, checked: bool):
        self.file_viewer_render_markdown = checked
        self._save_current_config()

    def flip_file_viewer_render_markdown(self):
        self.file_viewer_render_markdown = not self.file_viewer_render_markdown
        self._save_current_config()

    def toggle_file_viewer_show_line_numbers(self, checked: bool):
        self.file_viewer_show_line_numbers = checked
        self._save_current_config()

    def flip_file_viewer_show_line_numbers(self):
        self.file_viewer_show_line_numbers = not self.file_viewer_show_line_numbers
        self._save_current_config()

    def set_resizer_drag_width(self, value: Any):
        """Set the drag hit-target width for panel dividers (4–24 px)."""
        try:
            v = int(value[0]) if isinstance(value, list) else int(value)
            self.resizer_drag_width = max(4, min(24, v))
        except (TypeError, ValueError):
            return
        self._save_current_config()

    def set_cy_wheel_sensitivity(self, value: Any):
        """Set Cytoscape zoom/scroll sensitivity (0.05–1.0)."""
        try:
            v = float(value[0]) if isinstance(value, list) else float(value)
            self.cy_wheel_sensitivity = round(max(0.05, min(1.0, v)), 2)
        except (TypeError, ValueError):
            return
        self._save_current_config()

    def set_depth_limit(self, value: Any):
        """Set the depth limit from the slider (value may be a list from Radix slider)."""
        if isinstance(value, list):
            value = int(value[0]) if value else 0
        else:
            value = int(value)
        self.depth_limit = value
        # For tree views, update expanded_paths to match the new depth.
        # depth_limit=0 (All) → expand every node.
        # depth_limit=k → expand nodes at depth < k so that depth 0..k are visible.
        if value == 0:
            self.expanded_paths        = [n["path"] for n in self.all_nodes]
            self.merged_expanded_paths = [n["path"] for n in self.merged_nodes_base]
        else:
            self.expanded_paths        = [n["path"] for n in self.all_nodes        if n["depth"] < value]
            self.merged_expanded_paths = [n["path"] for n in self.merged_nodes_base if n["depth"] < value]
        self._save_current_config()

    def set_arch_direction(self, val: str) -> None:
        if val in ("LR", "TB"):
            self.arch_direction = val

    def set_arch_min_depth(self, val: Any) -> None:
        v = int(val[0]) if isinstance(val, list) and val else int(val)
        self.arch_min_depth = max(1, min(v, self.arch_max_depth))

    def set_arch_max_depth(self, val: Any) -> None:
        v = int(val[0]) if isinstance(val, list) and val else int(val)
        self.arch_max_depth = max(self.arch_min_depth, min(v, 6))

    def toggle_arch_connections(self) -> None:
        self.arch_show_connections = not self.arch_show_connections

    def set_arch_export_dir(self, path: str) -> None:
        stripped = path.strip()
        if stripped:
            self.arch_export_dir = stripped
            self.arch_export_status = ""

    def export_arch_diagram(self, fmt_id: str) -> None:
        """Save the current arch diagram to arch_export_dir on the server filesystem."""
        generator = _ARCH_GENERATORS.get(fmt_id)
        if not generator:
            self.arch_export_status = f"Error: unknown format '{fmt_id}'"
            return
        fmt_meta = next((f for f in _ARCH_EXPORT_FORMATS if f["id"] == fmt_id), {})
        try:
            cfg      = self._arch_cfg()
            content  = generator(_ALL_NODES_CACHE, _DEPENDENCIES_CACHE, cfg)
            out_dir  = Path(self.arch_export_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            filename = fmt_meta.get("filename", f"arch-diagram.{fmt_id}")
            out_path = out_dir / filename
            out_path.write_text(content, encoding="utf-8")
            self.arch_export_status = f"Saved → {out_path}"
        except Exception as exc:
            self.arch_export_status = f"Error: {exc}"

    def set_active_provider_tab(self, provider: str):
        """Switch provider tab; clicking the active tab toggles back to All."""
        self.active_provider_tab = "" if provider == self.active_provider_tab else provider

    @property
    def _active_file_search(self) -> str:
        """Return the search query for the currently active file viewer mode."""
        return self.config_data_search_query if self.file_viewer_mode == "config_data" else self.unit_file_search_query

    @property
    def _selected_node_provider(self) -> str:
        """Return the provider name for the currently selected node."""
        node = next((n for n in self.all_nodes if n["path"] == self.selected_node_path), None)
        if node:
            return node.get("provider", "")
        # Fallback: provider is at parts[2] (e.g. pkg/_stack/proxmox/... → proxmox)
        parts = self.selected_node_path.split("/")
        return parts[2] if len(parts) > 2 else ""

    def _search_reapply_script(self):
        """Return a call_script to clear the YAML breadcrumb and re-highlight the current query."""
        q = self._active_file_search
        if q and self.hcl_content:
            js = _CLEAR_CRUMB_JS + _pre_search_js(q, "init", self.file_search_smooth_scroll, case_sensitive=self.file_search_case_sensitive)
            return self._search_script(js)
        return rx.call_script(_CLEAR_CRUMB_JS)

    def select_node(self, path: str):
        """Select a node: update right panel, load HCL file, reset browser."""
        self._reset_file_editor()
        self.selected_node_path = path
        self.active_provider_tab = ""
        # Update the floating unit-detail popup whenever a node is selected,
        # if the popup is currently open (checkbox ON or manually kept open).
        if self.hover_popup_open and path:
            self._load_hover_popup_for_path(path)
        # Always track the unit HCL path regardless of viewer mode (used for shell CWD)
        self.unit_hcl_path = _read_hcl_file(path)[1]
        # Auto-populate the active mode's search field with the node path
        if self.file_viewer_mode == "config_data":
            # Always reload from disk so the viewer stays current with on-disk edits
            content, fpath = _read_stack_config_file()
            self.hcl_content = content
            self.hcl_file_path = fpath if fpath else "(stack config not found...)"
            search_str = f'"{path}"' if self.config_data_quote_path else path
            self.config_data_search_query = search_str
            provider = self._selected_node_provider
            self._save_current_config()
            # Defer search to a follow-up event so React commits the new
            # hcl_content to the DOM before the JS runs (same pattern as
            # set_file_viewer_mode → post_mode_switch_search).
            if self.hcl_content:
                return AppState.post_mode_switch_search
        else:
            self.unit_file_search_query = ""
            if self.tree_mode == "merged":
                providers = _get_hcl_providers_for_merged(path)
                first = providers[0] if providers else ""
                self.file_viewer_provider = first
                self.hcl_content, self.hcl_file_path = _read_hcl_file_for_merged(path, first)
            else:
                self.file_viewer_provider = ""
                self.hcl_content, self.hcl_file_path = _read_hcl_file(path)
            self._save_current_config()
            return rx.call_script(_CLEAR_CRUMB_JS)

    def _apply_auto_select(self, unit_path: str):
        """Auto-select a unit in the tree: expand ancestors so it is visible, load HCL.

        Called from local_state_watcher (inside async with self:) when
        auto_select_recent_unit is True and a unit status changes.
        Does NOT toggle expand/collapse like click_node — it only opens ancestors.
        """
        if not unit_path:
            return
        _gui_log(f"[auto-select] selecting unit: {unit_path}")
        self.recent_unit_path = unit_path
        self.selected_node_path = unit_path
        self.active_provider_tab = ""
        self.unit_hcl_path = _read_hcl_file(unit_path)[1]

        # Expand all ancestor prefixes so the node is visible in the tree.
        parts = unit_path.split("/")
        ancestors = {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}
        self.expanded_paths        = list(set(self.expanded_paths)        | ancestors)
        self.merged_expanded_paths = list(set(self.merged_expanded_paths) | ancestors)

        # Load HCL content for the right panel.
        if self.tree_mode == "merged":
            providers = _get_hcl_providers_for_merged(unit_path)
            first = providers[0] if providers else ""
            self.file_viewer_provider = first
            self.hcl_content, self.hcl_file_path = _read_hcl_file_for_merged(unit_path, first)
        else:
            self.file_viewer_provider = ""
            self.hcl_content, self.hcl_file_path = _read_hcl_file(unit_path)

    def set_ui_theme(self, theme: str):
        """Switch between 'light' and 'dark' UI theme."""
        self.ui_theme = theme
        self._save_current_config()

    def set_file_viewer_mode(self, mode: str):
        """Switch file viewer between 'unit_file' and 'config_data'.

        State (hcl_content, file_viewer_mode) is updated here; the search/scroll
        is dispatched as a separate follow-up event so it runs after React has
        committed the new file content to the DOM.
        """
        self._reset_file_editor()
        self.file_viewer_mode = mode
        if mode == "config_data":
            content, path = _read_stack_config_file()
            self.hcl_content = content
            self.hcl_file_path = path if path else "(stack config not found — set stack_config_path in _config/de3-gui-pkg.yaml)"
            # Auto-populate config-data search with (optionally quoted) node path
            if self.selected_node_path:
                search_str = f'"{self.selected_node_path}"' if self.config_data_quote_path else self.selected_node_path
                self.config_data_search_query = search_str
            self._save_current_config()
        else:
            # Reload the current node's hcl (or clear if nothing selected)
            if self.selected_node_path:
                if self.tree_mode == "merged":
                    providers = _get_hcl_providers_for_merged(self.selected_node_path)
                    provider = self.file_viewer_provider if self.file_viewer_provider in providers else (providers[0] if providers else "")
                    self.file_viewer_provider = provider
                    self.hcl_content, self.hcl_file_path = _read_hcl_file_for_merged(self.selected_node_path, provider)
                else:
                    self.hcl_content, self.hcl_file_path = _read_hcl_file(self.selected_node_path)
            else:
                self.hcl_content = ""
                self.hcl_file_path = ""
        # Return a follow-up event so the search runs after React commits the
        # new file content to the DOM (same technique as install_resizer).
        return AppState.post_mode_switch_search

    def post_mode_switch_search(self):
        """Run search/scroll after a mode switch — separate WS event ensures DOM is current."""
        if self.file_viewer_mode == "config_data":
            if self.selected_node_path and self.hcl_content:
                return self._search_script(_CLEAR_CRUMB_JS + _config_data_node_search_js(
                    self.selected_node_path, self._selected_node_provider,
                    self.config_data_quote_path, self.file_search_smooth_scroll,
                ))
        else:
            return self._search_reapply_script()

    def set_file_viewer_provider(self, provider: str):
        """Switch the file viewer to show a specific provider's unit file (merged mode)."""
        self._reset_file_editor()
        self.file_viewer_provider = provider
        if provider and self.file_viewer_mode == "unit_file":
            self.hcl_content, self.hcl_file_path = _read_hcl_file_for_merged(
                self.selected_node_path, provider
            )
            return self._search_reapply_script()

    def enter_file_edit_mode(self):
        """Switch the file viewer to inline Monaco editor, seeding draft from current content.

        Reads the top-visible line from the read-only pre BEFORE flipping to Monaco so the
        editor can open at the same scroll position the user was viewing.
        """
        if not self.hcl_file_path or self.hcl_file_path.startswith("("):
            return
        self.file_editor_draft = self.hcl_content
        self.file_editor_save_error = ""
        # Read the top-visible line first (pre is still in DOM); callback opens Monaco
        return rx.call_script(_read_pre_top_line_js(), callback=AppState.open_editor_at_line)

    def open_editor_at_line(self, line: int):
        """Callback from pre-scroll read: activate Monaco and reveal the captured line."""
        self.file_editor_active = True
        try:
            line_num = max(1, int(line))
        except (TypeError, ValueError):
            line_num = 1
        return rx.call_script(_monaco_reveal_line_js(line_num))

    def cancel_file_edit(self):
        """Discard in-progress edits and return to read-only view."""
        self.file_editor_active = False
        self.file_editor_draft = ""
        self.file_editor_save_error = ""

    def set_editor_draft(self, value: str):
        """Called by Monaco on_change — track the current editor content."""
        self.file_editor_draft = value

    def save_file_edit(self):
        """Write file_editor_draft to disk and return to read-only view."""
        if not self.hcl_file_path or self.hcl_file_path.startswith("("):
            return
        try:
            Path(self.hcl_file_path).write_text(self.file_editor_draft)
            self.hcl_content = self.file_editor_draft
            self.file_editor_active = False
            self.file_editor_draft = ""
            self.file_editor_save_error = ""
        except Exception as exc:
            self.file_editor_save_error = f"Save failed: {exc}"

    def _reset_file_editor(self):
        """Clear inline edit state when a new file is loaded (search query is preserved)."""
        self.file_editor_active = False
        self.file_editor_draft = ""
        self.file_editor_save_error = ""

    def set_active_search_query(self, query: str):
        """Update the search query for the active file viewer mode, seek to first match."""
        if self.file_viewer_mode == "config_data":
            self.config_data_search_query = query
        else:
            self.unit_file_search_query = query
        self._save_current_config()
        if self.hcl_is_ansi_log:
            self.ansi_search_idx = 0
            self.file_search_match_count = self.ansi_match_total
            if not query:
                return
            return rx.call_script(self._ansi_search_scroll_js())
        eid = "file-viewer-pre"
        if not query:
            return self._search_script(_pre_search_clear_js(eid))
        if self.file_editor_active:
            return self._search_script(_monaco_search_js(query, "init", self.file_search_smooth_scroll, case_sensitive=self.file_search_case_sensitive))
        return self._search_script(_pre_search_js(query, "init", self.file_search_smooth_scroll, eid, self.file_search_case_sensitive))

    def toggle_config_data_quote_path(self, value: bool):
        """Set whether node paths placed in config-data search are enclosed in double quotes."""
        self.config_data_quote_path = value
        # Re-wrap or strip quotes from the current query
        q = self.config_data_search_query
        is_quoted = q.startswith('"') and q.endswith('"') and len(q) >= 2
        raw = q[1:-1] if is_quoted else q
        if value and raw and not is_quoted:
            self.config_data_search_query = f'"{raw}"'
        elif not value and is_quoted:
            self.config_data_search_query = raw
        self._save_current_config()
        # Re-run the provider-anchored search with updated quoting
        if raw and self.hcl_content and self.file_viewer_mode == "config_data":
            return self._search_script(_config_data_node_search_js(raw, self._selected_node_provider, value, self.file_search_smooth_scroll))

    def flip_config_data_quote_path(self):
        """Button handler: flip the config_data_quote_path toggle."""
        return AppState.toggle_config_data_quote_path(not self.config_data_quote_path)

    def flip_file_search_smooth_scroll(self):
        """Button handler: toggle smooth scroll animation for search navigation."""
        self.file_search_smooth_scroll = not self.file_search_smooth_scroll
        self._save_current_config()

    def flip_file_search_case_sensitive(self):
        """Toggle case-sensitive search and re-run from position 0."""
        self.file_search_case_sensitive = not self.file_search_case_sensitive
        self._save_current_config()
        q = self._active_file_search
        if not q:
            return
        if self.hcl_is_ansi_log:
            self.ansi_search_idx = 0
            self.file_search_match_count = self.ansi_match_total
            return rx.call_script(self._ansi_search_scroll_js())
        eid = "file-viewer-pre"
        return self._search_script(_pre_search_js(q, "init", self.file_search_smooth_scroll,
                                                  eid, self.file_search_case_sensitive))

    def set_file_search_match_count(self, count: int):
        """Callback from search JS: store the number of matches found."""
        try:
            self.file_search_match_count = int(count)
        except (TypeError, ValueError):
            self.file_search_match_count = 0

    @rx.var
    def file_search_not_found(self) -> bool:
        """True when there is a non-empty search query, content to search, but zero matches."""
        if self.file_viewer_mode == "config_data":
            query = self.config_data_search_query
        else:
            query = self.unit_file_search_query
        return bool(query.strip()) and bool(self.hcl_content) and self.file_search_match_count == 0

    def _search_script(self, js: str):
        """Wrap a search JS string in call_script with the match-count callback."""
        return rx.call_script(js, callback=AppState.set_file_search_match_count)

    def _ansi_search_scroll_js(self) -> str:
        """Return JS that scrolls the ANSI viewer to the current (orange) mark."""
        behavior = "'smooth'" if self.file_search_smooth_scroll else "'instant'"
        return (
            f"(function(){{"
            f"var m=document.querySelector('#file-viewer-ansi mark[data-fs-current]');"
            f"if(m){{m.scrollIntoView({{behavior:{behavior},block:'center'}});}}"
            f"}})();"
        )

    def file_search_next(self):
        """Navigate to the next search match."""
        q = self._active_file_search
        if not q:
            return
        if self.file_editor_active:
            return self._search_script(_monaco_search_js(q, "next", self.file_search_smooth_scroll, case_sensitive=self.file_search_case_sensitive))
        if self.hcl_is_ansi_log:
            total = self.ansi_match_total
            if total > 0:
                self.ansi_search_idx = (self.ansi_search_idx + 1) % total
            self.file_search_match_count = total
            return rx.call_script(self._ansi_search_scroll_js())
        return self._search_script(_pre_search_js(q, "next", self.file_search_smooth_scroll, "file-viewer-pre", self.file_search_case_sensitive))

    def file_search_prev(self):
        """Navigate to the previous search match."""
        q = self._active_file_search
        if not q:
            return
        if self.file_editor_active:
            return self._search_script(_monaco_search_js(q, "prev", self.file_search_smooth_scroll, case_sensitive=self.file_search_case_sensitive))
        if self.hcl_is_ansi_log:
            total = self.ansi_match_total
            if total > 0:
                self.ansi_search_idx = (self.ansi_search_idx - 1) % total
            self.file_search_match_count = total
            return rx.call_script(self._ansi_search_scroll_js())
        return self._search_script(_pre_search_js(q, "prev", self.file_search_smooth_scroll, "file-viewer-pre", self.file_search_case_sensitive))

    def file_search_key_down(self, key: str):
        """Handle key events in the search input: Enter = next, Escape = clear."""
        q = self._active_file_search
        if key == "Enter":
            if not q:
                return
            if self.file_editor_active:
                return self._search_script(_monaco_search_js(q, "next", self.file_search_smooth_scroll, case_sensitive=self.file_search_case_sensitive))
            if self.hcl_is_ansi_log:
                total = self.ansi_match_total
                if total > 0:
                    self.ansi_search_idx = (self.ansi_search_idx + 1) % total
                self.file_search_match_count = total
                return rx.call_script(self._ansi_search_scroll_js())
            return self._search_script(_pre_search_js(q, "next", self.file_search_smooth_scroll, "file-viewer-pre", self.file_search_case_sensitive))
        if key == "Escape":
            if self.file_viewer_mode == "config_data":
                self.config_data_search_query = ""
            else:
                self.unit_file_search_query = ""
                self.ansi_search_idx = 0
                self.file_search_match_count = 0
            self._save_current_config()
            if not self.hcl_is_ansi_log:
                return self._search_script(_pre_search_clear_js())

    def show_inventory(self):
        """Load the ansible inventory file into the file viewer panel."""
        content, path = _read_inventory_file()
        self.hcl_content = content
        self.hcl_file_path = path if path else "(ansible inventory not configured)"
        self.selected_node_path = ""
        self.unit_file_search_query = ""
        self.config_data_search_query = ""
        self.file_viewer_status_msg = ""

    def update_inventory(self):
        """Run the inventory-refresh script and reload the file viewer when done."""
        _run_inventory_refresh(background=False)
        # Reload the file viewer if it's currently showing the inventory
        content, path = _read_inventory_file()
        if self.explorer_root == "ansible_inventory" or self.hcl_file_path == path:
            self.hcl_content = content
            self.hcl_file_path = path if path else "(ansible inventory not configured)"

    def update_inventory_and_dag(self):
        """Re-scan the infra dir, rebuild all node caches, refresh inventory — mimics app restart."""
        self.dag_refresh_status = "running"
        self.dag_refresh_error = ""
        yield  # push yellow state to UI before blocking

        try:
            # Re-build all module-level caches from disk
            _init_nodes_cache()
            _init_reactflow_cache()
            _init_modules_cache()
            _populate_module_tree_paths()
            _init_path_param_maps()   # rebuild region/env maps after infra rescan
            _init_dependencies_cache()

            # Refresh inventory (blocking); raises on script error
            err = _run_inventory_refresh(background=False)
            if err:
                raise RuntimeError(err)

            # Reload all DAG-related state vars (mirrors on_load logic)
            flat = _ALL_NODES_CACHE
            self.all_nodes = flat
            merged = _build_merged_nodes(flat)
            self.merged_nodes_base = merged

            self.package_filters = {
                n["name"]: True for n in flat if n.get("depth", -1) == 0
            }
            self.package_filters = {"_none": True, **{
                n["path"].split("/")[0]: True for n in flat if n.get("path", "").split("/")[0]
            }, **{pi.name: True for pi in _PACKAGES_CACHE if pi.name}}
            self.region_filters = {"_none": True, **{v: True for v in set(_PATH_TO_REGION_CACHE.values())}}
            self.env_filters    = {"_none": True, **{v: True for v in set(_PATH_TO_ENV_CACHE.values())}}

            dlim = self.depth_limit
            if dlim == 0:
                self.expanded_paths        = [n["path"] for n in flat]
                self.merged_expanded_paths = [n["path"] for n in merged]
            else:
                self.expanded_paths        = [n["path"] for n in flat   if n["depth"] < dlim]
                self.merged_expanded_paths = [n["path"] for n in merged if n["depth"] < dlim]

            self.modules_nodes = _MODULES_NODES_CACHE
            self.modules_expanded_paths = [n["path"] for n in _MODULES_NODES_CACHE if n["depth"] == 0]
            self.packages_data = _PACKAGES_CACHE

            # Rebuild role maps from refreshed inventory
            avail_roles, nm_roles = _build_role_maps()
            self.available_roles = avail_roles
            self.node_name_roles = nm_roles

            # Reload the file viewer if it's currently showing the inventory
            content, path = _read_inventory_file()
            if self.explorer_root == "ansible_inventory" or self.hcl_file_path == path:
                self.hcl_content = content
                self.hcl_file_path = path if path else "(ansible inventory not configured)"

            self.dag_refresh_status = "idle"
        except Exception as exc:
            self.dag_refresh_status = "error"
            self.dag_refresh_error = str(exc)

    def open_source_link(self, source_val: str):
        """Resolve a terragrunt source = "..." value and load the module in the file viewer.

        Resolution order:
          1. Skip remote sources (git::, https://, http://, registry.terraform.io).
          2. Strip any ${...} interpolation prefix (e.g. ${include.root.locals.modules_dir},
             ${get_terragrunt_dir()}) to get the sub-path after the closing '}'.
          3. Replace the Terragrunt '//' module-root separator with '/'.
          4. Try infra/<pkg>/_modules/<sub_path> across all packages (new engine layout).
          5. Fall back to relative resolution from the current file's directory.
        """
        if not self.hcl_file_path or not source_val:
            return
        stripped = source_val.strip()
        for prefix in ("git::", "https://", "http://", "github.com", "registry.terraform.io"):
            if stripped.startswith(prefix):
                return
        # Remove any leading ${...}/ interpolation to get the module sub-path
        sub_path = re.sub(r'^\$\{[^}]+\}/', '', stripped)
        # Replace the Terragrunt // module-root marker
        sub_path = sub_path.replace("//", "/").lstrip("/")

        def _load_dir(target_dir: Path) -> bool:
            if not target_dir.exists():
                return False
            for name in ("main.tf", "variables.tf", "outputs.tf"):
                candidate = target_dir / name
                if candidate.exists():
                    self.hcl_content = candidate.read_text()
                    self.hcl_file_path = str(candidate)
                    return True
            for ext in ("*.tf", "*.hcl"):
                files = sorted(target_dir.glob(ext))
                if files:
                    self.hcl_content = files[0].read_text()
                    self.hcl_file_path = str(files[0])
                    return True
            return False

        # 1. Try framework/_modules/<sub_path> (null-provider shared modules)
        fw_candidate = _STACK_DIR / "framework" / "_modules" / sub_path
        if _load_dir(fw_candidate.resolve()):
            return
        # 2. Try infra/<pkg>/_modules/<sub_path> across all packages
        infra_dir = _STACK_DIR / "infra"
        if infra_dir.exists():
            for pkg_dir in sorted(infra_dir.iterdir()):
                if not pkg_dir.is_dir():
                    continue
                candidate = pkg_dir / "_modules" / sub_path
                if _load_dir(candidate.resolve()):
                    return
        # 3. Try relative from current file directory (handles plain relative paths)
        base_dir = Path(self.hcl_file_path).parent
        _load_dir((base_dir / sub_path).resolve())

    def open_shell(self, cwd: str):
        """Open a local shell in the given directory (embedded panel, ttyd, or native terminal).
        Passing cwd='' closes the terminal panel."""
        if not cwd:
            self.shell_cwd = ""
            self.shell_initial_cmd = ""
            self.shell_label = ""
            self.ttyd_port = 0
            return
        # Close any existing terminal before opening the new one so the old
        # PTY/WebSocket disconnects cleanly before a new session starts.
        if self.terminal_backend in ("embedded", "ttyd") and (self.shell_cwd or self.ttyd_port):
            self.shell_cwd = ""
            self.shell_initial_cmd = ""
            self.shell_label = ""
            self.ttyd_port = 0
            yield  # flush close to browser before opening new terminal
        if self.terminal_backend == "ttyd":
            if _TTYD_AVAILABLE:
                self.ttyd_port = _start_ttyd(cwd)
            self.shell_cwd = cwd  # keeps panel visible; iframe URL driven by ttyd_port
            self.shell_initial_cmd = ""
            self.shell_label = ""
            return
        if self.terminal_backend != "embedded":
            _launch_native_terminal(self.terminal_backend, cwd)
            return
        self.shell_cwd = cwd
        self.shell_initial_cmd = ""
        self.shell_label = ""

    def tail_current_file(self):
        """Run `tail -99f <hcl_file_path>` in the terminal using the configured backend."""
        if not self.hcl_file_path:
            return
        p = Path(self.hcl_file_path)
        yield from self.open_ssh_terminal(str(p.parent), f"tail -99f {str(p)}", login=False)
        self.shell_label = f"tail: {p.name}"

    def tail_wave_log(self):
        """Run the configured wave_tail_cmd in the terminal using the configured backend."""
        if not _WAVE_TAIL_CMD:
            return
        yield from self.open_ssh_terminal(str(Path.home()), _WAVE_TAIL_CMD, login=False)
        self.shell_label = "tail: run.log"

    def open_ssh_terminal(self, cwd: str, ssh_cmd: str, login: bool = True):
        """Open a terminal in cwd and auto-run ssh_cmd (embedded panel, ttyd, or native terminal).

        login=False passes through to _start_ttyd to skip --login, preventing
        ~/.bash_profile from running (avoids 'clear' blink in tail terminals).
        """
        # Close any existing terminal before opening the new one.
        if self.terminal_backend in ("embedded", "ttyd") and (self.shell_cwd or self.ttyd_port):
            self.shell_cwd = ""
            self.shell_initial_cmd = ""
            self.shell_label = ""
            self.ttyd_port = 0
            yield  # flush close to browser before opening new terminal
        if self.terminal_backend == "ttyd":
            if _TTYD_AVAILABLE:
                self.ttyd_port = _start_ttyd(cwd, ssh_cmd, login=login)
            self.shell_cwd = cwd
            self.shell_initial_cmd = ssh_cmd
            self.shell_label = ""
            return
        if self.terminal_backend != "embedded":
            _launch_native_terminal(self.terminal_backend, cwd, ssh_cmd)
            return
        self.shell_cwd = cwd
        self.shell_initial_cmd = ssh_cmd
        self.shell_label = ""

    @rx.var
    def selected_editor_label(self) -> str:
        for e in _FILE_VIEWER_EDITORS:
            if e["id"] == self.selected_editor_id:
                return e["label"]
        return ""

    @rx.var
    def file_viewer_type_label(self) -> str:
        """Human label for the current file viewer type (shown in the menu bar)."""
        if self.hcl_is_ansi_log:
            return "Wave Log"
        if self.file_viewer_mode == "config_data":
            return "Config Data"
        return "Unit File"

    @rx.var
    def unlock_file_lock_uri(self) -> str:
        """Human-readable lock file URI (or pattern) for the current unlock_file_pending_path."""
        path = self.unlock_file_pending_path
        if not path:
            return ""
        mode  = self.unlock_file_pending_mode
        stack = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
        backend = stack.get("backend", {})
        btype = backend.get("type", "local")
        bcfg  = backend.get("config", {})
        if btype == "gcs":
            bucket = bcfg.get("bucket", "<bucket>")
            if mode == "recursive":
                return f"gs://{bucket}/{path}/**/default.tflock"
            return f"gs://{bucket}/{path}/default.tflock"
        elif btype == "s3":
            bucket = bcfg.get("bucket", "<bucket>")
            endpoint = bcfg.get("endpoint", "")
            key_prefix = bcfg.get("key", bcfg.get("prefix", ""))
            base_key = f"{key_prefix}/{path}" if key_prefix else path
            prefix = "s3-compat" if endpoint else "s3"
            if mode == "recursive":
                return f"{prefix}://{bucket}/{base_key}/**/default.tflock"
            return f"{prefix}://{bucket}/{base_key}/default.tflock"
        else:
            if mode == "recursive":
                return f"local:<infra>/{path}/**/.terraform.tfstate.lock.info"
            return f"local:.terragrunt-cache/.../.terraform.tfstate.lock.info"

    def set_selected_editor(self, editor_id: str):
        """Remember the chosen editor; does not open the file."""
        self.selected_editor_id = editor_id
        self._save_current_config()

    def select_and_launch_in_editor(self, editor_id: str):
        """Select an editor and immediately open the current file in it."""
        self.selected_editor_id = editor_id
        self._save_current_config()
        return self.open_file_in_editor(editor_id)

    def open_file_in_editor(self, editor_id: str):
        """Open the currently viewed file in the chosen editor."""
        import subprocess as _subprocess
        file_path = self.hcl_file_path
        if not file_path:
            return
        editor = next((e for e in _FILE_VIEWER_EDITORS if e["id"] == editor_id), None)
        if not editor:
            return
        if editor["type"] == "embedded":
            return AppState.enter_file_edit_mode
        cmd = editor["cmd"].replace("{file_path}", file_path)
        if editor["type"] == "terminal_cmd":
            cwd = str(Path(file_path).parent)
            self.shell_cwd = cwd
            self.shell_initial_cmd = cmd
        elif editor["type"] == "background_cmd":
            try:
                _subprocess.Popen(cmd.split())
            except Exception:
                pass

    def open_file_in_selected_editor(self):
        """Open file in the currently selected editor (quick-launch button)."""
        if self.selected_editor_id:
            return AppState.open_file_in_editor(self.selected_editor_id)

    def copy_file_content_to_clipboard(self):
        """Copy the currently viewed file content to the system clipboard."""
        if not self.hcl_content:
            return
        return rx.set_clipboard(self.hcl_content)

    def copy_file_path_to_clipboard(self):
        """Copy the currently viewed file path to the system clipboard."""
        if not self.hcl_file_path:
            return
        return rx.set_clipboard(self.hcl_file_path)

    def download_current_file(self):
        """Trigger a browser Save-As dialog for the currently viewed file."""
        if not self.hcl_content:
            return
        filename = Path(self.hcl_file_path).name if self.hcl_file_path else "file.txt"
        return rx.download(data=self.hcl_content, filename=filename)

    def open_file_in_chrome(self, profile_id: str):
        """Open the currently viewed file as a file:// URL in the given Chrome profile."""
        import subprocess as _sp
        if not self.hcl_file_path:
            return
        p = Path(self.hcl_file_path)
        if not p.exists():
            return
        file_url = p.as_uri()   # produces file:///absolute/path
        try:
            _sp.Popen(
                ["google-chrome", f"--profile-directory={profile_id}", file_url],
                start_new_session=True,
            )
        except Exception:
            pass

    def save_row_height(self, height_pct: float):
        """Called via rx.call_script callback after a horizontal panel resize."""
        try:
            pct = max(20, min(80, round(float(height_pct))))
        except (TypeError, ValueError):
            return
        self.top_row_height_pct = pct
        self._save_current_config()

    def on_hresize_complete(self):
        """Triggered by JS when the user finishes dragging the horizontal resizer."""
        return rx.call_script(
            "window._topRowHeightPct != null ? window._topRowHeightPct : 60",
            callback=AppState.save_row_height,
        )

    def save_panel_width(self, width_pct: float):
        """Called via rx.call_script callback after a panel resize drag ends."""
        try:
            pct = max(20, min(80, round(float(width_pct))))
        except (TypeError, ValueError):
            return
        self.left_panel_width_pct = pct
        self._save_current_config()

    def on_cy_node_click(self):
        """Triggered by the hidden cy-node-trigger div when a Cytoscape node is tapped.

        Reads window._cySelectedPath (set by the cy tap handler) and forwards
        it to select_node — same pattern as on_resize_complete / save_panel_width.
        """
        return rx.call_script(
            "window._cySelectedPath || ''",
            callback=AppState.select_node,
        )

    def on_rf_node_click(self):
        """Triggered by the hidden rf-node-trigger div when a React Flow node is clicked.

        Reads window._rfSelectedPath (set by the onNodeClick JS handler) and forwards
        it to select_node via rx.call_script callback.
        """
        return rx.call_script(
            "window._rfSelectedPath || ''",
            callback=AppState.select_node,
        )

    def on_resize_complete(self):
        """Triggered by JS when the user finishes dragging the panel resizer.

        Reads the percentage stored by the drag JS in window._leftPanelWidthPct,
        which is set during mousemove so it's immune to React re-renders that
        happen between mouseup and when this call_script executes on the client.
        """
        return rx.call_script(
            "window._leftPanelWidthPct != null ? window._leftPanelWidthPct : 50",
            callback=AppState.save_panel_width,
        )

    def click_node(self, path: str):
        """Click a tree row: select it, load HCL file, reset provider tab, toggle expand/collapse.

        Re-clicking an already-selected node toggles the file viewer between
        unit_file and config_data modes.
        """
        # When the refactor panel is open, clicking a node sets the destination path.
        if self.float_refactor_open and self.refactor_operation != "delete":
            self.refactor_dst_path = path
            if _REFACTOR_AUTO_PREVIEW:
                return AppState.run_refactor_preview
            return
        # Toggle file viewer mode when re-clicking the already-selected node
        toggling_mode = bool(path and path == self.selected_node_path)
        if toggling_mode:
            self.file_viewer_mode = (
                "config_data" if self.file_viewer_mode == "unit_file" else "unit_file"
            )
        self._reset_file_editor()
        self.selected_node_path = path
        self.active_provider_tab = ""
        # Update the floating unit-detail popup content when checkbox is ON.
        if self.show_unit_popup and path:
            self._load_hover_popup_for_path(path)
        # Expand/collapse (always runs regardless of file viewer mode).
        # Expanding opens the entire subtree all the way to leaf units so
        # a single click reveals the full hierarchy below the clicked node.
        if self.tree_mode == "merged":
            if path in self.merged_expanded_paths:
                # Collapse: remove this node and every descendant.
                self.merged_expanded_paths = [
                    p for p in self.merged_expanded_paths
                    if p != path and not p.startswith(path + "/")
                ]
            else:
                # Expand all the way to leaves: add this path and all
                # descendant paths found in the current node list.
                subtree = {
                    n["path"] for n in self.merged_nodes_base
                    if n["path"] == path or n["path"].startswith(path + "/")
                }
                self.merged_expanded_paths = list(
                    set(self.merged_expanded_paths) | subtree
                )
        else:
            if path in self.expanded_paths:
                # Collapse: remove this node and every descendant.
                self.expanded_paths = [
                    p for p in self.expanded_paths
                    if p != path and not p.startswith(path + "/")
                ]
            else:
                # Expand all the way to leaves: add this path and all
                # descendant paths found in the current node list.
                subtree = {
                    n["path"] for n in self.all_nodes
                    if n["path"] == path or n["path"].startswith(path + "/")
                }
                self.expanded_paths = list(
                    set(self.expanded_paths) | subtree
                )
        # Flush selection + expand state to the client immediately so the tree
        # highlight appears before the file I/O below blocks the event loop.
        yield
        if self.file_viewer_mode == "unit_file":
            if self.tree_mode == "merged":
                # Auto-select the first provider that actually has a unit file on disk
                providers = _get_hcl_providers_for_merged(path)
                first = providers[0] if providers else ""
                self.file_viewer_provider = first
                self.hcl_content, self.hcl_file_path = _read_hcl_file_for_merged(path, first)
            else:
                self.file_viewer_provider = ""
                self.hcl_content, self.hcl_file_path = _read_hcl_file(path)
            if not self.hcl_content:
                self.unit_file_search_query = ""
                self.file_viewer_status_msg = f"No unit file found for: {path}"
            else:
                self.file_viewer_status_msg = ""
        # Auto-populate the active mode's search field and navigate
        if self.file_viewer_mode == "config_data":
            provider = self._selected_node_provider
            # Reconstruct provider-inclusive path for file lookup.
            # Merged mode strips the provider segment from the path.
            if self.tree_mode == "merged" and provider:
                # Merged paths strip "_stack" + provider; full path = <pkg>/_stack/<provider>/<rest>
                _p = path.split("/")
                full_path = (_p[0] + "/_stack/" + provider + "/" + "/".join(_p[1:])
                             if len(_p) > 1 else path)
            else:
                full_path = path
                if not provider:
                    # New engine: path = <pkg>/_stack/<provider>/...
                    _segs = path.split("/")
                    provider = _segs[2] if len(_segs) > 2 else ""
            # Find the config file that best covers this node, then load it.
            # This ensures nodes defined in package-specific YAML files are found.
            src_file, has_match = _find_config_file_for_node(provider, full_path)
            if not has_match:
                self.hcl_content = ""
                self.hcl_file_path = ""
                self.config_data_search_query = ""
                self.file_viewer_status_msg = f"No config data found for: {path}"
                self._save_current_config()
                return
            if src_file and src_file.exists():
                try:
                    self.hcl_content = src_file.read_text()
                    self.hcl_file_path = str(src_file)
                    self.file_viewer_status_msg = ""
                except Exception:
                    pass
            if not self.hcl_content:
                content, fpath = _read_stack_config_file()
                self.hcl_content = content
                self.hcl_file_path = fpath if fpath else "(stack config not found...)"
                self.file_viewer_status_msg = ""
            search_str = f'"{path}"' if self.config_data_quote_path else path
            self.config_data_search_query = search_str
            self._save_current_config()
            # Defer search to a follow-up event so React commits the new
            # hcl_content to the DOM before the JS runs.
            if self.hcl_content:
                yield AppState.post_mode_switch_search
        else:
            self.unit_file_search_query = ""
            self._save_current_config()
            yield rx.call_script(_CLEAR_CRUMB_JS)

    def toggle_hide_special_params(self):
        self.hide_special_params = not self.hide_special_params
        self._save_current_config()

    def toggle_hide_provider_underscore_params(self):
        self.hide_provider_underscore_params = not self.hide_provider_underscore_params
        self._save_current_config()

    def toggle_param_wrap_values(self, checked: bool):
        self.param_wrap_values = checked
        self._save_current_config()

    def flip_param_wrap_values(self):
        self.param_wrap_values = not self.param_wrap_values
        self._save_current_config()

    def set_maximized_panel(self, panel: str):
        """Maximize a panel ('top-left' | 'bottom-left' | 'top-right' | 'bottom-right')
        or restore the 4-panel layout ('')."""
        self.maximized_panel = panel

    def navigate_to_source(self, full_path: str):
        """Open the stack config file that defines an 'inherited from' param entry.

        full_path is always provider-inclusive (e.g. example-pkg/_stack/proxmox/example-lab).
        Finds the specific package YAML file containing config_params[full_path] for
        the extracted provider, loads it in config_data mode, and searches for the
        entry using the full provider-inclusive path.
        Also selects the ancestor node in the tree.
        """
        if not full_path:
            return

        # ── Select ancestor node in the tree ───────────────────────────────
        parts = full_path.split("/")
        if self.tree_mode == "merged":
            # New paths: <pkg>/_stack/<provider>/... → merged: <pkg>/...
            if len(parts) >= 3:
                tree_path = parts[0] + ("/" + "/".join(parts[3:]) if parts[3:] else "")
            else:
                tree_path = full_path
        else:
            tree_path = full_path
        self.selected_node_path = tree_path

        # ── Find and load the config file that owns this entry ──────────────
        provider = parts[2] if len(parts) >= 3 else ""
        src_file = _find_source_config_file(provider, full_path)
        if src_file and src_file.exists():
            try:
                content = src_file.read_text()
            except Exception:
                content = ""
        else:
            content = ""

        if not content:
            return

        self._reset_file_editor()
        self.file_viewer_mode = "config_data"
        self.hcl_content = content
        self.hcl_file_path = str(src_file)
        self.config_data_search_query = full_path
        self.file_viewer_status_msg = ""
        self._save_current_config()
        yield self._search_script(
            _CLEAR_CRUMB_JS + _config_data_node_search_js(
                full_path,
                provider,
                self.config_data_quote_path,
                self.file_search_smooth_scroll,
            )
        )

    def show_all_providers(self):
        self.provider_filters = {k: True for k in self.provider_filters}

    def hide_all_providers(self):
        self.provider_filters = {k: False for k in self.provider_filters}

    def toggle_all_providers(self):
        if self.provider_filters and all(self.provider_filters.values()):
            self.provider_filters = {k: False for k in self.provider_filters}
        else:
            self.provider_filters = {k: True for k in self.provider_filters}

    def toggle_package(self, name: str):
        self.package_filters = {
            **self.package_filters,
            name: not self.package_filters.get(name, True),
        }
        self._save_current_config()

    def solo_package(self, name: str):
        if name not in self.package_filters:
            return
        already_soloed = (
            self.package_filters.get(name, False)
            and all(not v for k, v in self.package_filters.items() if k != name)
        )
        if already_soloed:
            self.package_filters = {k: (k != name) for k in self.package_filters}
        else:
            self.package_filters = {k: (k == name) for k in self.package_filters}
        self._save_current_config()

    def show_all_packages(self):
        self.package_filters = {k: True for k in self.package_filters}
        self._save_current_config()

    def hide_all_packages(self):
        self.package_filters = {k: False for k in self.package_filters}
        self._save_current_config()

    def toggle_all_packages(self):
        if self.package_filters and all(self.package_filters.values()):
            self.package_filters = {k: False for k in self.package_filters}
        else:
            self.package_filters = {k: True for k in self.package_filters}
        self._save_current_config()

    def toggle_region(self, name: str):
        self.region_filters = {
            **self.region_filters,
            name: not self.region_filters.get(name, True),
        }
        self._save_current_config()

    def solo_region(self, name: str):
        if name not in self.region_filters:
            return
        already_soloed = (
            self.region_filters.get(name, False)
            and all(not v for k, v in self.region_filters.items() if k != name)
        )
        if already_soloed:
            self.region_filters = {k: (k != name) for k in self.region_filters}
        else:
            self.region_filters = {k: (k == name) for k in self.region_filters}
        self._save_current_config()

    def show_all_regions(self):
        self.region_filters = {k: True for k in self.region_filters}
        self._save_current_config()

    def hide_all_regions(self):
        self.region_filters = {k: False for k in self.region_filters}
        self._save_current_config()

    def toggle_all_regions(self):
        if self.region_filters and all(self.region_filters.values()):
            self.region_filters = {k: False for k in self.region_filters}
        else:
            self.region_filters = {k: True for k in self.region_filters}
        self._save_current_config()

    def toggle_env(self, name: str):
        self.env_filters = {
            **self.env_filters,
            name: not self.env_filters.get(name, True),
        }
        self._save_current_config()

    def solo_env(self, name: str):
        if name not in self.env_filters:
            return
        already_soloed = (
            self.env_filters.get(name, False)
            and all(not v for k, v in self.env_filters.items() if k != name)
        )
        if already_soloed:
            self.env_filters = {k: (k != name) for k in self.env_filters}
        else:
            self.env_filters = {k: (k == name) for k in self.env_filters}
        self._save_current_config()

    def show_all_envs(self):
        self.env_filters = {k: True for k in self.env_filters}
        self._save_current_config()

    def hide_all_envs(self):
        self.env_filters = {k: False for k in self.env_filters}
        self._save_current_config()

    def toggle_all_envs(self):
        if self.env_filters and all(self.env_filters.values()):
            self.env_filters = {k: False for k in self.env_filters}
        else:
            self.env_filters = {k: True for k in self.env_filters}
        self._save_current_config()

    def toggle_wave_folder(self, folder_path: str):
        """Collapse or expand a folder node in the waves folder view.

        Collapsing adds folder_path to wave_folder_collapsed and also removes any
        descendant folder paths already in the set (they are hidden anyway while their
        ancestor is collapsed, so removing them prevents ghost-collapsed state when the
        parent is later re-expanded).

        Expanding removes folder_path from the set.  Descendant folders are NOT
        re-added on expand — they were cleaned up on collapse, so re-expanding a parent
        shows all its children fully expanded.

        wave_folder_collapsed is intentionally NOT persisted so stale state can never
        hide a wave after wave names change.
        """
        if not folder_path:
            return
        collapsed = set(self.wave_folder_collapsed)
        if folder_path in collapsed:
            # Expand: remove this folder (children become visible again).
            collapsed.discard(folder_path)
        else:
            # Collapse: add this folder; remove any already-collapsed descendants
            # so they don't ghost when this parent is later expanded.
            prefix = folder_path + "."
            collapsed = {p for p in collapsed if not p.startswith(prefix)}
            collapsed.add(folder_path)
        self.wave_folder_collapsed = list(collapsed)

    def toggle_wave(self, name: str):
        self.wave_filters = {
            **self.wave_filters,
            name: not self.wave_filters.get(name, True),
        }
        self._save_current_config()

    def show_all_waves(self):
        self.wave_filters = {k: True for k in self.wave_filters}
        self._save_current_config()

    def hide_all_waves(self):
        self.wave_filters = {k: False for k in self.wave_filters}
        self._save_current_config()

    def toggle_all_waves(self):
        if self.wave_filters and all(self.wave_filters.values()):
            self.wave_filters = {k: False for k in self.wave_filters}
        else:
            self.wave_filters = {k: True for k in self.wave_filters}
        self._save_current_config()

    def solo_wave(self, name: str):
        """Double-click handler: toggle solo for this wave.

        First double-click: check only this wave, uncheck all others.
        Second double-click (wave already soloed): invert — uncheck only this
        wave, check all others.
        """
        if name not in self.wave_filters:
            return
        already_soloed = (
            self.wave_filters.get(name, False)
            and all(not v for k, v in self.wave_filters.items() if k != name)
        )
        if already_soloed:
            self.wave_filters = {k: (k != name) for k in self.wave_filters}
        else:
            self.wave_filters = {k: (k == name) for k in self.wave_filters}
        self._save_current_config()

    def toggle_wave_skip_on_wave_run(self, name: str):
        """Toggle the _skip_on_wave_run flag for the named wave in waves_ordering.yaml."""
        try:
            wo_path = _STACK_DIR / "config" / "waves_ordering.yaml"
            if not wo_path.exists():
                return
            wo_doc = yaml.safe_load(wo_path.read_text()) or {}
            waves = wo_doc.setdefault("waves_ordering", [])
            for i, entry in enumerate(waves):
                entry_name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
                if entry_name == name:
                    if isinstance(entry, str):
                        # Promote bare string to dict so we can add _skip_on_wave_run
                        waves[i] = {"name": entry, "_skip_on_wave_run": True}
                    elif entry.get("_skip_on_wave_run"):
                        entry.pop("_skip_on_wave_run", None)
                        # Simplify back to bare string if no other keys remain
                        remaining = {k: v for k, v in entry.items() if k != "name"}
                        if not remaining:
                            waves[i] = name
                    else:
                        entry["_skip_on_wave_run"] = True
                    break
            wo_path.write_text(
                yaml.dump(wo_doc, default_flow_style=False, allow_unicode=True)
            )
            _load_stack_config()
            # Force waves_with_visibility to recompute (it reads self.wave_filters)
            self.wave_filters = dict(self.wave_filters)
        except Exception:
            pass

    def _move_wave(self, name: str, direction: int):
        """Shared impl for move_wave_up / move_wave_down. direction: -1 = up, +1 = down."""
        try:
            wo_path = _STACK_DIR / "config" / "waves_ordering.yaml"
            if not wo_path.exists():
                return
            wo_doc = yaml.safe_load(wo_path.read_text()) or {}
            waves = wo_doc.setdefault("waves_ordering", [])
            # Find index by name regardless of whether entry is str or dict
            idx = next(
                (i for i, w in enumerate(waves)
                 if (w.get("name") if isinstance(w, dict) else str(w)) == name),
                None,
            )
            if idx is None:
                return
            target = idx + direction
            if target < 0 or target >= len(waves):
                return
            waves[idx], waves[target] = waves[target], waves[idx]
            wo_path.write_text(
                yaml.dump(wo_doc, default_flow_style=False, allow_unicode=True)
            )
            _load_stack_config()
            _init_path_param_maps()
            self.wave_filters = dict(self.wave_filters)
        except Exception:
            pass

    def move_wave_up(self, name: str):
        self._move_wave(name, -1)

    def move_wave_down(self, name: str):
        self._move_wave(name, +1)

    def set_waves_view_mode(self, mode: str):
        self.waves_view_mode = mode

    def flip_waves_view_mode(self):
        self.waves_view_mode = "folder" if self.waves_view_mode == "list" else "list"

    @rx.var
    def wave_folders_collapsed(self) -> bool:
        """True when one or more wave folder nodes are currently collapsed."""
        return len(self.wave_folder_collapsed) > 0

    def toggle_wave_folder_all(self):
        """Toggle between fully-expanded and top-level-only views.

        Expand all: clears wave_folder_collapsed so every folder is open.
        Collapse to top level: collapses every top-level folder (first dot-segment
        of wave names that is not itself a wave name), hiding all child rows and
        leaving only the root folder nodes visible.
        """
        if self.wave_folder_collapsed:
            # Currently collapsed — expand everything.
            self.wave_folder_collapsed = []
        else:
            # Currently expanded — collapse all top-level folders.
            wave_names: set[str] = set(self.wave_filters.keys())
            top_folders: set[str] = set()
            for name in wave_names:
                parts = name.split(".")
                if len(parts) > 1:
                    top = parts[0]
                    if top not in wave_names:   # only a folder, not itself a wave
                        top_folders.add(top)
            self.wave_folder_collapsed = list(top_folders)

    # ---------------------------------------------------------------------------
    # External package repo management
    # ---------------------------------------------------------------------------

    def toggle_package_expanded(self, name: str):
        if name in self.packages_expanded_names:
            self.packages_expanded_names.remove(name)
        else:
            self.packages_expanded_names.append(name)

    def expand_all_packages(self):
        self.packages_expanded_names = [p.name for p in self.packages_data]

    def collapse_all_packages(self):
        self.packages_expanded_names = []

    def clear_pkg_sync_output(self):
        self.pkg_sync_output = ""

    @rx.event(background=True)
    async def sync_packages(self):
        import asyncio as _aio
        async with self:
            self.pkg_sync_running = True
            self.pkg_sync_output = ""
        ok, out = _run_pkg_mgr("sync")
        _init_modules_cache()
        async with self:
            self.pkg_sync_running = False
            self.pkg_sync_output = out
            self.pkg_sync_ok = ok
            self.pkg_repos_config = _read_pkg_repos_config()
            self.ext_package_repos = _load_ext_package_repos()
            self.packages_data = _PACKAGES_CACHE

    def open_pkg_repos_config_in_viewer(self):
        self.hcl_file_path = str(_PKG_REPOS_CONFIG)
        try:
            self.hcl_content = _PKG_REPOS_CONFIG.read_text()
        except Exception:
            self.hcl_content = ""
        self.float_file_viewer_open = True

    def open_framework_pkgs_in_viewer(self):
        self.hcl_file_path = str(_FRAMEWORK_PKGS_CFG)
        try:
            self.hcl_content = _FRAMEWORK_PKGS_CFG.read_text()
        except Exception:
            self.hcl_content = ""
        self.float_file_viewer_open = True

    def reload_pkg_state(self):
        self.pkg_repos_config = _read_pkg_repos_config()
        self.ext_package_repos = _load_ext_package_repos()
        _init_modules_cache()
        self.packages_data = _PACKAGES_CACHE

    @rx.event(background=True)
    async def remove_pkg_repo(self, name: str):
        ok, out = _run_pkg_mgr("remove-repo", name)
        _init_modules_cache()
        async with self:
            self.pkg_sync_output = out
            self.pkg_sync_ok = ok
            self.pkg_repos_config = _read_pkg_repos_config()
            self.ext_package_repos = _load_ext_package_repos()
            self.packages_data = _PACKAGES_CACHE
            if name in self.packages_expanded_names:
                self.packages_expanded_names.remove(name)

    # ---------------------------------------------------------------------------
    # Inventory-ready signal — background task started by on_load
    # ---------------------------------------------------------------------------

    @rx.event(background=True)
    async def signal_inventory_ready(self):
        """Wait for the inventory refresh to finish, then bump inventory_refresh_counter.

        This causes selected_node_browser_actions (which reads the inventory cache)
        to recompute, ensuring SSH buttons appear even when the cache was empty at
        initial page load (e.g. first-ever startup before the inventory file existed).
        Waits up to 120 s; exits silently on timeout.
        """
        import asyncio as _aio
        for _ in range(120):
            if _INVENTORY_REFRESH_COMPLETE:
                break
            await _aio.sleep(1)
        async with self:
            self.inventory_refresh_counter += 1

    # ---------------------------------------------------------------------------
    # Config file watcher — background task started by on_load
    # ---------------------------------------------------------------------------

    @rx.event(background=True)
    async def config_file_watcher(self):
        """Poll stack config YAML and SOPS secrets for changes; reload on modification.

        Runs as a long-lived background task (one per connected client).  Uses
        mtime polling — no extra dependencies.  Poll interval: 2 s.
        """
        global _SOPS_SECRETS_LOADED
        import asyncio as _aio

        last_mtimes: dict[str, float] = _get_watched_mtimes()

        while True:
            await _aio.sleep(2)

            current = _get_watched_mtimes()
            yaml_changed = False
            sops_changed = False

            yaml_paths = {str(p) for p in _find_stack_configs()}
            sops_path = str(_find_sops_secrets_file() or "")

            for key, mt in current.items():
                if last_mtimes.get(key, mt) != mt:
                    if key in yaml_paths:
                        yaml_changed = True
                    elif key == sops_path:
                        sops_changed = True
            last_mtimes = current

            if not yaml_changed and not sops_changed:
                continue

            _gui_log(
                f"[file-watcher] change detected — yaml={yaml_changed} sops={sops_changed}"
            )

            if sops_changed:
                _SOPS_SECRETS_LOADED = False  # force lazy re-decrypt on next access

            if yaml_changed:
                _load_stack_config()
                _init_path_param_maps()
                _init_nodes_cache()

            flat    = list(_ALL_NODES_CACHE)
            merged  = _build_merged_nodes(flat)

            async with self:
                if yaml_changed:
                    self.all_nodes          = flat
                    self.merged_nodes_base  = merged
                    self.region_filters     = {"_none": True, **{v: True for v in set(_PATH_TO_REGION_CACHE.values())}}
                    self.env_filters        = {"_none": True, **{v: True for v in set(_PATH_TO_ENV_CACHE.values())}}
                    self.wave_filters       = _build_initial_wave_filters()
                    # Refresh file viewer if it is currently showing the stack config
                    if self.file_viewer_mode == "config_data":
                        content, fpath = _read_stack_config_file()
                        self.hcl_content = content
                        if fpath:
                            self.hcl_file_path = fpath
                else:
                    # SOPS-only: just bump wave_filters to trigger a repaint
                    self.wave_filters = dict(self.wave_filters)

    # ---------------------------------------------------------------------------
    # Unit copy / paste clipboard
    # ---------------------------------------------------------------------------

    def clear_clipboard_message(self):
        self.clipboard_message = ""

    # ------------------------------------------------------------------
    # Refactor (unit-mgr CLI)
    # ------------------------------------------------------------------

    def begin_refactor(self, path: str, operation: str = "move"):
        """Open the Refactor floating panel pre-filled with the selected node path."""
        self.refactor_src_path = path
        self.refactor_operation = operation
        self.refactor_dst_path = ""
        self.refactor_preview_result = {}
        self.refactor_preview_external_deps = []
        self.refactor_result = {}
        self.refactor_error = ""
        self.refactor_status_op = ""
        self.refactor_status_detail = ""
        self.refactor_status_exit = ""
        self.refactor_status_summary = ""
        self.float_refactor_open = True
        return [rx.call_script(self._WAVE_POLL_STOP_JS), AppState.init_float_refactor]

    def close_float_refactor(self):
        self.float_refactor_open = False
        if _REFACTOR_AUTO_PREVIEW:
            return rx.call_script("clearTimeout(window._refactorAutoPreviewTimer);")

    def toggle_refactor_details(self):
        self.refactor_show_details = not self.refactor_show_details

    # ------------------------------------------------------------------
    # pkg-mgr rename / copy dialog
    # ------------------------------------------------------------------

    def begin_pkg_rename(self, name: str):
        self.pkg_op_mode = "rename"
        self.pkg_op_src = name
        self.pkg_op_dst = ""
        self.pkg_op_state_flag = ""
        self.pkg_op_output = ""
        self.pkg_op_error = ""
        self.pkg_op_open = True

    def begin_pkg_copy(self, name: str):
        self.pkg_op_mode = "copy"
        self.pkg_op_src = name
        self.pkg_op_dst = ""
        self.pkg_op_state_flag = ""
        self.pkg_op_output = ""
        self.pkg_op_error = ""
        self.pkg_op_open = True

    def close_pkg_op(self):
        self.pkg_op_open = False

    def set_pkg_op_dst(self, v: str):
        self.pkg_op_dst = v

    def set_pkg_op_state_flag(self, v: str):
        self.pkg_op_state_flag = v

    @rx.event(background=True)
    async def run_pkg_op(self):
        async with self:
            self.pkg_op_running = True
            self.pkg_op_output = ""
            self.pkg_op_error = ""

        mode = self.pkg_op_mode
        src = self.pkg_op_src
        dst = self.pkg_op_dst
        state_flag = self.pkg_op_state_flag

        args = [mode, src, dst]
        if mode == "copy":
            if state_flag == "skip":
                args.append("--skip-state")
            elif state_flag == "with":
                args.append("--with-state")
            else:
                async with self:
                    self.pkg_op_error = "Select --skip-state or --with-state before copying."
                    self.pkg_op_running = False
                return

        ok, out = _run_pkg_mgr(*args)

        async with self:
            self.pkg_op_output = out
            self.pkg_op_error = "" if ok else out
            self.pkg_op_running = False
            if ok:
                global _PACKAGES_CACHE
                _PACKAGES_CACHE = _scan_packages()
                self.packages_data = _PACKAGES_CACHE

    def init_float_refactor(self):
        js = (
            "(function tryInit(){"
            "  var win=document.getElementById('float-refactor-window');"
            "  var hdr=document.getElementById('float-refactor-header');"
            "  if(!win||!hdr){setTimeout(tryInit,20);return;}"
            "  if(!win._positionSet){"
            "    win._positionSet=true;"
            "    var leftCol=document.getElementById('left-column');"
            "    var lx=leftCol?(Math.round(leftCol.getBoundingClientRect().right)+8):Math.round(window.innerWidth*0.45);"
            "    var x=lx,y=Math.round(window.innerHeight/2-200);"
            "    win.style.left=x+'px';win.style.top=y+'px';"
            "    document.documentElement.style.setProperty('--refactor-x',x+'px');"
            "    document.documentElement.style.setProperty('--refactor-y',y+'px');"
            "  }"
            "  if(!win._zorderInstalled){"
            "    win._zorderInstalled=true;"
            "    win.addEventListener('pointerdown',function(){"
            "      ['float-fv-window','float-term-window','float-ov-window',"
            "       'float-refactor-window','hover-popup-window'].forEach(function(id){"
            "        var el=document.getElementById(id);if(el)el.style.zIndex='9990';"
            "      });"
            "      win.style.zIndex='9992';"
            "    },true);"
            "  }"
            "  if(hdr._dragInstalled)return;"
            "  hdr._dragInstalled=true;"
            "  var dragging=false,ox=0,oy=0,sl=0,st=0;"
            "  var onMove=function(e){"
            "    if(!dragging)return;"
            "    var nx=sl+e.clientX-ox,ny=st+e.clientY-oy;"
            "    win.style.left=nx+'px';win.style.top=ny+'px';"
            "    document.documentElement.style.setProperty('--refactor-x',nx+'px');"
            "    document.documentElement.style.setProperty('--refactor-y',ny+'px');"
            "  };"
            "  var onUp=function(){"
            "    if(!dragging)return;dragging=false;"
            "    document.removeEventListener('mousemove',onMove);"
            "    document.removeEventListener('mouseup',onUp);"
            "  };"
            "  hdr.addEventListener('mousedown',function(e){"
            "    if(e.button!==0)return;"
            "    if(e.target.closest('button'))return;"
            "    e.preventDefault();"
            "    dragging=true;ox=e.clientX;oy=e.clientY;"
            "    sl=parseInt(win.style.left)||win.getBoundingClientRect().left;"
            "    st=parseInt(win.style.top)||win.getBoundingClientRect().top;"
            "    document.addEventListener('mousemove',onMove);"
            "    document.addEventListener('mouseup',onUp);"
            "  });"
            "})()"
        )
        return rx.call_script(js)

    def set_refactor_operation(self, op: str):
        self.refactor_operation = op
        if _REFACTOR_AUTO_PREVIEW and op == "delete":
            return rx.call_script("clearTimeout(window._refactorAutoPreviewTimer);")

    def set_refactor_dst_path(self, v: str):
        self.refactor_dst_path = v
        if _REFACTOR_AUTO_PREVIEW and self.refactor_operation != "delete" and v:
            return rx.call_script(
                f"clearTimeout(window._refactorAutoPreviewTimer);"
                f"window._refactorAutoPreviewTimer = setTimeout(function(){{"
                f"  var btn = document.getElementById('refactor-auto-preview-trigger');"
                f"  if (btn) btn.click();"
                f"}}, {_REFACTOR_AUTO_PREVIEW_DELAY_MS});"
            )

    def clear_refactor_result(self):
        self.refactor_preview_result = {}
        self.refactor_preview_external_deps = []
        self.refactor_result = {}
        self.refactor_error = ""
        self.refactor_status_op = ""
        self.refactor_status_detail = ""
        self.refactor_status_exit = ""
        self.refactor_status_summary = ""

    @rx.event(background=True)
    async def run_refactor_preview(self):
        import json as _json_mod
        import subprocess as _sp
        import shutil

        async with self:
            self.refactor_preview_result = {}
            self.refactor_error = ""
            self.refactor_running = True
            src = self.refactor_src_path
            dst = self.refactor_dst_path.strip()
            op = self.refactor_operation
            self.refactor_status_op = f"Preview ({op})"
            self.refactor_status_detail = "Starting…"

        if op == "delete":
            async with self:
                self.refactor_error = "Preview not available for Delete — click Execute to confirm deletion."
                self.refactor_running = False
                self.refactor_status_op = ""
                self.refactor_status_detail = ""
            return

        if not dst:
            async with self:
                self.refactor_error = "Destination path is required."
                self.refactor_running = False
                self.refactor_status_op = ""
                self.refactor_status_detail = ""
            return

        import subprocess as _sp
        import shutil

        run_script = _find_unit_mgr_run()
        if not run_script:
            async with self:
                self.refactor_error = "unit-mgr run script not found."
                self.refactor_running = False
                self.refactor_status_detail = "unit-mgr not found."
            return

        async with self:
            self.refactor_status_detail = f"unit-mgr {op} --dry-run  {src}  →  {dst}"

        try:
            result = _sp.run(
                [run_script, op, src, dst, "--dry-run", "--json-report", "--skip-state"],
                capture_output=True, text=True,
            )
            parsed = _parse_unit_mgr_json(result.stdout)
            stderr = result.stderr.strip()
            if result.returncode != 0:
                async with self:
                    self.refactor_error = (parsed.get("errors") or [stderr or "Preview failed"])[0]
                    self.refactor_running = False
                    self.refactor_status_detail = "unit-mgr exited non-zero."
                    self.refactor_status_exit = "✗ Preview failed"
                    self.refactor_status_summary = ""
                return
            async with self:
                self.refactor_preview_result = parsed
                self.refactor_preview_external_deps = parsed.get("external_deps") or []
                self.refactor_running = False
                units = parsed.get("units_found", "?")
                keys  = parsed.get("config_keys_found", "?")
                self.refactor_status_detail = "Dry-run complete — no changes made."
                self.refactor_status_exit = "✓ Preview complete"
                self.refactor_status_summary = f"{units} unit(s)  ·  {keys} config key(s)"
        except Exception as exc:
            async with self:
                self.refactor_error = f"Preview failed: {exc}"
                self.refactor_running = False
                self.refactor_status_detail = f"Exception: {exc}"
                self.refactor_status_exit = "✗ Preview failed"
                self.refactor_status_summary = ""

    @rx.event(background=True)
    async def run_refactor_execute(self):
        import json as _json_mod
        import subprocess as _sp

        async with self:
            self.refactor_result = {}
            self.refactor_error = ""
            self.refactor_running = True
            src = self.refactor_src_path
            dst = self.refactor_dst_path.strip()
            op = self.refactor_operation
            self.refactor_status_op = f"Execute ({op})"
            self.refactor_status_detail = "Starting…"

        if op == "delete":
            async with self:
                self.refactor_running = False
                self.delete_pending_path = src
                self.delete_pending_mode = "recursive"
                self.refactor_status_op = "Execute (delete)"
                self.refactor_status_detail = f"Deleting {src}…"
            return AppState.confirm_delete

        if op != "delete" and not dst:
            async with self:
                self.refactor_error = "Destination path is required."
                self.refactor_running = False
                self.refactor_status_op = ""
                self.refactor_status_detail = ""
            return

        run_script = _find_unit_mgr_run()
        if not run_script:
            async with self:
                self.refactor_error = "unit-mgr run script not found."
                self.refactor_running = False
                self.refactor_status_detail = "unit-mgr not found."
            return

        async with self:
            self.refactor_status_detail = f"unit-mgr {op}  {src}  →  {dst}"

        try:
            result = _sp.run(
                [run_script, op, src, dst, "--json-report"],
                capture_output=True, text=True,
            )
            parsed = _parse_unit_mgr_json(result.stdout)
            stderr = result.stderr.strip()
            if result.returncode != 0:
                async with self:
                    self.refactor_error = (parsed.get("errors") or [stderr or "Execute failed"])[0]
                    self.refactor_running = False
                    self.refactor_status_detail = "unit-mgr exited non-zero."
                    self.refactor_status_exit = "✗ Failed"
                    self.refactor_status_summary = ""
                return
            async with self:
                self.refactor_result = parsed
                self.refactor_running = False
                units = parsed.get("units_found", "?")
                keys  = parsed.get("config_keys_migrated", "?")
                state = parsed.get("state_files_migrated", "?")
                self.refactor_status_exit = "✓ Complete"
                self.refactor_status_summary = f"{units} unit(s)  ·  {keys} config key(s)  ·  {state} state file(s) migrated"
                self.refactor_status_detail = "Reloading infra tree…"
            # Reload infra tree to reflect moved/copied paths
            async with self:
                _init_nodes_cache()
                _init_path_param_maps()
                _load_stack_config()
                flat = list(_ALL_NODES_CACHE)
                merged = _build_merged_nodes(flat)
                self.all_nodes = flat
                self.merged_nodes_base = merged
                self.package_filters = {"_none": True, **{
                    n["path"].split("/")[0]: True for n in flat if n.get("path", "").split("/")[0]
                }, **{pi.name: True for pi in _PACKAGES_CACHE if pi.name}}
                self.region_filters = {"_none": True, **{v: True for v in set(_PATH_TO_REGION_CACHE.values())}}
                self.env_filters    = {"_none": True, **{v: True for v in set(_PATH_TO_ENV_CACHE.values())}}
                self.wave_filters   = _build_initial_wave_filters()
                dlim = self.depth_limit
                if dlim == 0:
                    self.expanded_paths        = [n["path"] for n in flat]
                    self.merged_expanded_paths = [n["path"] for n in merged]
                else:
                    self.expanded_paths        = [n["path"] for n in flat   if n["depth"] < dlim]
                    self.merged_expanded_paths = [n["path"] for n in merged if n["depth"] < dlim]
                self.refactor_status_detail = "Done."
        except Exception as exc:
            async with self:
                self.refactor_error = f"Execute failed: {exc}"
                self.refactor_running = False
                self.refactor_status_detail = f"Exception: {exc}"
                self.refactor_status_exit = "✗ Failed"
                self.refactor_status_summary = ""

    # ------------------------------------------------------------------
    # Delete unit
    # ------------------------------------------------------------------

    # ── Remove (rm + YAML only — no terragrunt) ───────────────────────

    def begin_delete_file(self, path: str):
        """Open confirmation to remove unit dir + config block (non-recursive)."""
        self.delete_pending_path = path
        self.delete_pending_mode = "file"
        self.delete_dialog_open = True

    def begin_delete_recursive(self, path: str):
        """Open confirmation to remove unit dir + config block (recursive subtree)."""
        self.delete_pending_path = path
        self.delete_pending_mode = "recursive"
        self.delete_dialog_open = True

    def cancel_delete(self):
        self.delete_dialog_open = False

    # ── Rename (mv directory + rewrite all config_params keys) ───────────

    def begin_rename(self, path: str):
        """Open the rename dialog for the given tree node."""
        self.rename_pending_path = path
        self.rename_pending_name = path.split("/")[-1]
        self.rename_error = ""
        self.rename_dialog_open = True

    def set_rename_name(self, name: str):
        self.rename_pending_name = name
        self.rename_error = ""

    def rename_name_keydown(self, key: str):
        if key == "Enter":
            return AppState.confirm_rename

    def cancel_rename(self):
        self.rename_dialog_open = False
        self.rename_error = ""

    def confirm_rename(self):
        """Rename a tree node: mv the directory on disk and update every
        config_params key in all package YAML files and SOPS secrets files
        that references the old path (exact match or as a prefix).
        """
        import subprocess as _sp

        old_path = self.rename_pending_path
        new_name = self.rename_pending_name.strip()

        # ── Validate ───────────────────────────────────────────────────
        if not new_name:
            self.rename_error = "Name cannot be empty"
            return
        if "/" in new_name or new_name in (".", ".."):
            self.rename_error = "Name must not contain '/' or be '.' / '..'"
            return

        old_name = old_path.split("/")[-1]
        if new_name == old_name:
            self.rename_dialog_open = False
            return

        parent_path = "/".join(old_path.split("/")[:-1])
        new_path = f"{parent_path}/{new_name}" if parent_path else new_name

        config   = _load_config()
        infra_base = _infra_path(config)
        old_dir  = infra_base / old_path
        new_dir  = infra_base / new_path

        if not old_dir.exists():
            self.rename_error = f"Directory not found: {old_path}"
            return
        if new_dir.exists():
            self.rename_error = f"Destination already exists: {new_path}"
            return

        self.rename_dialog_open = False
        self.rename_error = ""

        # ── Step 1: rewrite config_params keys in all package YAML files ──
        try:
            _rename_config_keys_in_yaml_files(old_path, new_path)
        except Exception as exc:
            self.clipboard_message = f"Rename: YAML config update failed: {exc}"
            self.clipboard_message_is_error = True
            return

        # ── Step 2: rewrite config_params keys in all SOPS secrets files ──
        sops_errors: list[str] = []
        for sops_file in _find_sops_secrets_files():
            try:
                _rename_config_keys_in_sops_file(sops_file, old_path, new_path)
            except Exception as exc:
                sops_errors.append(f"{sops_file.name}: {exc}")

        # ── Step 3: rename the directory on disk ──────────────────────────
        try:
            old_dir.rename(new_dir)
        except Exception as exc:
            self.clipboard_message = f"Rename: mv failed: {exc}"
            self.clipboard_message_is_error = True
            return

        # ── Step 4: invalidate SOPS cache so secrets reload with new keys ──
        global _SOPS_SECRETS_CACHE, _SOPS_SECRETS_LOADED
        _SOPS_SECRETS_CACHE = {}
        _SOPS_SECRETS_LOADED = False

        # ── Step 5: reload stack config and tree ──────────────────────────
        _load_stack_config()
        try:
            _init_nodes_cache()
            _init_path_param_maps()
            flat   = list(_ALL_NODES_CACHE)
            merged = _build_merged_nodes(flat)
            self.all_nodes         = flat
            self.merged_nodes_base = merged
            self.package_filters   = {n["name"]: True for n in flat if n.get("depth", -1) == 0}
            self.region_filters    = {"_none": True, **{v: True for v in set(_PATH_TO_REGION_CACHE.values())}}
            self.env_filters       = {"_none": True, **{v: True for v in set(_PATH_TO_ENV_CACHE.values())}}
            self.wave_filters      = _build_initial_wave_filters()
            dlim = self.depth_limit
            if dlim == 0:
                self.expanded_paths        = [n["path"] for n in flat]
                self.merged_expanded_paths = [n["path"] for n in merged]
            else:
                self.expanded_paths        = [n["path"] for n in flat   if n["depth"] < dlim]
                self.merged_expanded_paths = [n["path"] for n in merged if n["depth"] < dlim]
            # Keep selection pointing at the renamed node
            if self.selected_node_path == old_path:
                self.selected_node_path = new_path
            elif self.selected_node_path.startswith(old_path + "/"):
                self.selected_node_path = new_path + self.selected_node_path[len(old_path):]
        except Exception as exc:
            self.clipboard_message = f"Renamed but tree reload failed: {exc}"
            self.clipboard_message_is_error = True
            return

        msg = f"Renamed: {old_name} → {new_name}"
        if sops_errors:
            msg += f" (SOPS warnings: {'; '.join(sops_errors)})"
        self.clipboard_message = msg
        self.clipboard_message_is_error = bool(sops_errors)

    # ── Destroy (terragrunt destroy only — no file changes) ───────────

    def begin_destroy_unit(self, path: str):
        """Open confirmation to run terragrunt destroy on a single unit."""
        self.destroy_pending_path = path
        self.destroy_pending_mode = "unit"
        self.destroy_dialog_open = True

    def begin_destroy_recursive(self, path: str):
        """Open confirmation to run terragrunt run --all destroy from a directory."""
        self.destroy_pending_path = path
        self.destroy_pending_mode = "recursive"
        self.destroy_dialog_open = True

    def cancel_destroy(self):
        self.destroy_dialog_open = False

    def confirm_destroy(self):
        """Run terragrunt destroy in the action terminal. No files are changed."""
        self.destroy_dialog_open = False
        path = self.destroy_pending_path
        mode = self.destroy_pending_mode
        if not path:
            return
        config   = _load_config()
        unit_dir = _infra_path(config) / path
        set_env  = "source $(git rev-parse --show-toplevel)/set_env.sh"
        if mode == "recursive":
            tg_cmd = (
                "terragrunt run --all destroy --non-interactive"
                " -- -lock=false -lock-timeout=0s"
            )
        else:
            tg_cmd = "terragrunt destroy --non-interactive -- -lock=false -lock-timeout=0s"
        self.shell_cwd         = str(unit_dir)
        self.shell_initial_cmd = f"{set_env} && {tg_cmd}"

    # ------------------------------------------------------------------
    # Taint unit (terragrunt taint via state list | xargs)
    # ------------------------------------------------------------------

    def begin_taint_unit(self, path: str):
        """Open confirmation to taint all resources in a single unit."""
        self.taint_pending_path = path
        self.taint_pending_mode = "unit"
        self.taint_dialog_open = True

    def begin_taint_recursive(self, path: str):
        """Open confirmation to taint all resources under a directory recursively."""
        self.taint_pending_path = path
        self.taint_pending_mode = "recursive"
        self.taint_dialog_open = True

    def cancel_taint(self):
        self.taint_dialog_open = False

    def confirm_taint(self):
        """Run the taint command in the action terminal. No files are changed."""
        self.taint_dialog_open = False
        path = self.taint_pending_path
        mode = self.taint_pending_mode
        if not path:
            return
        config   = _load_config()
        unit_dir = _infra_path(config) / path
        set_env  = "source $(git rev-parse --show-toplevel)/set_env.sh"
        if mode == "recursive":
            tg_cmd = (
                "terragrunt run --all -- state list"
                " | xargs -r -I{} terragrunt run -- taint {}"
            )
        else:
            tg_cmd = "terragrunt state list | xargs -r -I{} terragrunt run -- taint {}"
        self.shell_cwd         = str(unit_dir)
        self.shell_initial_cmd = f"{set_env} && {tg_cmd}"

    # ------------------------------------------------------------------
    # State lock file removal (direct backend delete)
    # ------------------------------------------------------------------

    def begin_unlock_file(self, path: str):
        """Open direct lock-file delete confirmation dialog for a single unit."""
        self.unlock_file_pending_path = path
        self.unlock_file_pending_mode = "unit"
        self.unlock_file_dialog_open = True

    def begin_unlock_file_recursive(self, path: str):
        """Open direct lock-file delete confirmation dialog for all units under path."""
        self.unlock_file_pending_path = path
        self.unlock_file_pending_mode = "recursive"
        self.unlock_file_dialog_open = True

    def cancel_unlock_file(self):
        self.unlock_file_dialog_open = False

    def confirm_unlock_file(self):
        """Delete backend lock file(s) directly (GCS/S3/local) in the action terminal."""
        self.unlock_file_dialog_open = False
        path = self.unlock_file_pending_path
        mode = self.unlock_file_pending_mode
        if not path:
            return
        config   = _load_config()
        unit_dir = _infra_path(config) / path
        set_env  = "source $(git rev-parse --show-toplevel)/set_env.sh"
        cmd = _build_unlock_file_cmd(path, mode)
        self.shell_cwd         = str(unit_dir)
        self.shell_initial_cmd = f"{set_env} && {cmd}"

    # ------------------------------------------------------------------
    # Wave run / destroy (opens terminal or confirm dialog)
    # ------------------------------------------------------------------

    def begin_wave_run(self, name: str, mode: str):
        """Apply: open terminal immediately. Destroy: open confirmation dialog."""
        self.wave_run_pending_name = name
        self.wave_run_pending_mode = mode
        if mode == "apply":
            return self._open_wave_terminal(name, mode)
        else:
            self.wave_run_dialog_open = True

    def cancel_wave_run(self):
        self.wave_run_dialog_open = False

    def confirm_wave_run(self):
        """Confirmed destroy — open terminal and run the wave destroy command."""
        self.wave_run_dialog_open = False
        return self._open_wave_terminal(self.wave_run_pending_name, self.wave_run_pending_mode)

    def begin_wave_folder_run(self, folder_path: str, mode: str):
        """Apply or destroy all waves under a folder node.

        Apply opens the terminal immediately (no confirmation needed).
        Destroy opens a confirmation dialog first.

        The run script receives  -w "<folder_path>.*"  which uses fnmatch to
        match every wave whose name starts with folder_path + ".".
        """
        self.wave_folder_run_pending_path = folder_path
        self.wave_folder_run_pending_mode = mode
        if mode == "apply":
            return self._open_wave_folder_terminal(folder_path, mode)
        else:
            self.wave_folder_run_dialog_open = True

    def cancel_wave_folder_run(self):
        self.wave_folder_run_dialog_open = False

    def confirm_wave_folder_run(self):
        """Confirmed destroy — run the wave destroy command for the folder."""
        self.wave_folder_run_dialog_open = False
        return self._open_wave_folder_terminal(
            self.wave_folder_run_pending_path,
            self.wave_folder_run_pending_mode,
        )

    def _open_wave_folder_terminal(self, folder_path: str, mode: str):
        """Open terminal with ./run scoped to all waves under folder_path.

        Uses -w "<folder_path>.*" so fnmatch matches every wave whose name
        starts with the folder prefix (e.g. "network.*" matches "network.unifi",
        "network.mikrotik", etc.).
        """
        run_script = str(_STACK_DIR / "run")
        pattern = f"{folder_path}.*"
        if mode == "destroy":
            cmd = f"{run_script} --clean -w '{pattern}'"
        else:
            cmd = f"{run_script} -a -w '{pattern}' --skip-test"
        self.shell_cwd = str(_STACK_DIR)
        self.shell_initial_cmd = cmd
        return rx.call_script(self._WAVE_POLL_START_JS)

    def begin_run_all_waves(self):
        """Open the 'run all waves' confirmation dialog."""
        self.run_all_waves_dialog_open = True

    def cancel_run_all_waves(self):
        self.run_all_waves_dialog_open = False

    def confirm_run_all_waves(self):
        """Confirmed — run all waves via ./run -a."""
        self.run_all_waves_dialog_open = False
        run_script = str(_STACK_DIR / "run")
        self.shell_cwd = str(_STACK_DIR)
        self.shell_initial_cmd = f"{run_script} -a"
        return rx.call_script(self._WAVE_POLL_START_JS)

    _WAVE_POLL_START_JS = (
        "window._waveStatusPollId = setInterval(function(){"
        "  var t=document.getElementById('wave-status-poll-trigger');"
        "  if(t) t.click();"
        f"}}, {_WAVE_POLL_INTERVAL_MS});"
    )

    def _open_wave_terminal(self, name: str, mode: str):
        run_script = str(_STACK_DIR / "run")
        if mode == "destroy":
            cmd = f"{run_script} --clean -w {name}"
        else:
            cmd = f"{run_script} -a -w {name} --skip-test"
        self.shell_cwd         = str(_STACK_DIR)
        self.shell_initial_cmd = cmd
        return rx.call_script(self._WAVE_POLL_START_JS)

    def refresh_wave_log_statuses(self):
        """Scan $WAVE_LOGS_DIR and update wave_log_statuses with per-wave results.

        When recent_wave_name changes, yields a call_script to scroll that wave row
        into view at the top of the table viewport.

        For each wave we track three independent log types:
          main     — apply/destroy log  (keys: status, log_path, start_time, end_time, duration, age)
          precheck — pre-run ansible    (keys: pre_status, pre_log_path)
          test     — test-playbook      (keys: test_status, test_log_path)
        Each type is resolved independently from the newest dir that has that log file.
        """
        import re as _re
        from datetime import datetime as _dt
        old_recent = self.recent_wave_name  # capture before update for scroll-to detection
        log_base = _wave_logs_dir()
        if not log_base.exists():
            return
        ts_pattern = _re.compile(r"^\d{8}-\d{6}$")
        dirs = sorted(
            [d for d in log_base.iterdir()
             if d.is_dir() and not d.is_symlink() and ts_pattern.match(d.name)],
            key=lambda d: d.name,
            reverse=True,
        )

        # Track which wave names have already been resolved for each log type
        main_found:  set[str] = set()
        pre_found:   set[str] = set()
        test_found:  set[str] = set()
        statuses: dict[str, dict] = {}
        now = _dt.now()

        # A log with no done/fail marker is "running" if run.log was touched
        # within this many seconds; otherwise treat it as a crashed/failed run.
        _RUNNING_THRESHOLD_SECS = 300

        def _wave_status(run_content: str, wave_name: str, action: str,
                         run_log_mtime: float | None = None) -> str:
            done_marker = f"--- [{wave_name}] {action} done ---"
            fail_marker = f"[{wave_name}] {action} failed"
            if done_marker in run_content:
                return "ok"
            if fail_marker in run_content or "ERROR: command failed" in run_content:
                return "fail"
            # Log exists but no terminal marker yet — still running or crashed
            if run_log_mtime is not None:
                age = (now - _dt.fromtimestamp(run_log_mtime)).total_seconds()
                if age < _RUNNING_THRESHOLD_SECS:
                    return "running"
            return "fail"

        for d in dirs:
            try:
                start_dt = _dt.strptime(d.name, "%Y%m%d-%H%M%S")
            except ValueError:
                start_dt = None

            run_log = d / "run.log"
            run_content = run_log.read_text(errors="replace") if run_log.exists() else ""
            try:
                run_log_mtime: float | None = run_log.stat().st_mtime if run_log.exists() else None
            except OSError:
                run_log_mtime = None

            for log_file in d.iterdir():
                fname = log_file.name
                # ── main: apply / destroy ─────────────────────────────────
                mm = _re.match(r"^wave-(.+)-(apply|destroy)\.log$", fname)
                if mm:
                    wave_name = mm.group(1)
                    action    = mm.group(2)
                    if wave_name not in main_found:
                        main_found.add(wave_name)
                        try:
                            end_dt = _dt.fromtimestamp(log_file.stat().st_mtime)
                        except OSError:
                            end_dt = None
                        entry = statuses.setdefault(wave_name, {})
                        entry["status"]     = _wave_status(run_content, wave_name, action, run_log_mtime)
                        entry["log_path"]   = str(run_log)
                        entry["start_time"] = start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else ""
                        entry["end_time"]   = end_dt.strftime("%Y-%m-%d %H:%M:%S")   if end_dt   else ""
                        entry["duration"]   = (
                            _fmt_duration((end_dt - start_dt).total_seconds())
                            if start_dt and end_dt else ""
                        )
                        entry["age"] = (
                            _fmt_duration((now - end_dt).total_seconds())   if end_dt   else
                            _fmt_duration((now - start_dt).total_seconds()) if start_dt else ""
                        )
                        # log_update_age: time since this wave's own apply/destroy log was
                        # last written (= end_dt for completed waves; very recent for running).
                        # Deliberately NOT run_log_mtime, which is shared across all waves
                        # in the same run directory and would be uniformly recent.
                        entry["log_update_age"] = (
                            _fmt_duration((now - end_dt).total_seconds()) if end_dt else ""
                        )
                    continue

                # ── precheck ─────────────────────────────────────────────
                mp = _re.match(r"^wave-(.+)-precheck\.log$", fname)
                if mp:
                    wave_name = mp.group(1)
                    if wave_name not in pre_found:
                        pre_found.add(wave_name)
                        entry = statuses.setdefault(wave_name, {})
                        entry["pre_status"]   = _wave_status(run_content, wave_name, "precheck", run_log_mtime)
                        entry["pre_log_path"] = str(log_file)
                    continue

                # ── test-playbook ─────────────────────────────────────────
                mt = _re.match(r"^wave-(.+)-test-playbook\.log$", fname)
                if mt:
                    wave_name = mt.group(1)
                    if wave_name not in test_found:
                        test_found.add(wave_name)
                        entry = statuses.setdefault(wave_name, {})
                        entry["test_status"]   = _wave_status(run_content, wave_name, "test-playbook", run_log_mtime)
                        entry["test_log_path"] = str(log_file)

        # Merge GCS wave history: add entries for waves not found in local run logs.
        # run.log data takes precedence — only fill gaps.
        for gcs_wave, gcs_entry in self.gcs_wave_statuses.items():
            if gcs_wave not in statuses:
                gcs_status = gcs_entry.get("status", "")
                gcs_phase  = gcs_entry.get("phase", "apply")
                gcs_time   = gcs_entry.get("updated_at", "")
                if gcs_status in ("ok", "fail", "running"):
                    entry = {}
                    if gcs_phase in ("apply", "destroy"):
                        entry["status"]   = gcs_status
                        entry["log_path"] = ""
                        entry["start_time"] = gcs_entry.get("started_at", "")
                        entry["end_time"]   = gcs_entry.get("finished_at", gcs_time)
                        entry["duration"]   = ""
                        entry["age"]        = ""
                        entry["log_update_age"] = ""
                    elif gcs_phase == "precheck":
                        entry["pre_status"]   = gcs_status
                        entry["pre_log_path"] = ""
                    elif gcs_phase == "test-playbook":
                        entry["test_status"]   = gcs_status
                        entry["test_log_path"] = ""
                    if entry:
                        statuses[gcs_wave] = entry

        self.wave_log_statuses = statuses

        # recent_wave_name: currently-running wave takes priority; otherwise the
        # wave whose apply/destroy log was most recently modified within
        # _WAVE_RECENT_HIGHLIGHT_SECS.
        running_names = [
            name for name, entry in statuses.items()
            if "running" in (
                entry.get("status"),
                entry.get("pre_status"),
                entry.get("test_status"),
            )
        ]
        if running_names:
            # dirs is newest-first; statuses insertion order mirrors it, so
            # running_names[0] is the wave from the most recent run directory.
            self.recent_wave_name = running_names[0]
        else:
            best_name = ""
            best_dt = None
            for d2 in dirs:
                for lf in d2.iterdir():
                    m2 = _re.match(r"^wave-(.+)-(apply|destroy)\.log$", lf.name)
                    if not m2 or m2.group(1) not in statuses:
                        continue
                    try:
                        ts = _dt.fromtimestamp(lf.stat().st_mtime)
                    except OSError:
                        continue
                    if best_dt is None or ts > best_dt:
                        best_dt = ts
                        best_name = m2.group(1)
            if best_dt is not None and (now - best_dt).total_seconds() <= _WAVE_RECENT_HIGHLIGHT_SECS:
                self.recent_wave_name = best_name
            else:
                self.recent_wave_name = ""

        # Scroll the active wave into view at the top of the table when it changes.
        if self.recent_wave_name and self.recent_wave_name != old_recent:
            wave_id = f"wave-row-{self.recent_wave_name}"
            yield rx.call_script(
                f"(function(){{var el=document.getElementById('{wave_id}');"
                f"if(el)el.scrollIntoView({{block:'start',behavior:'smooth'}});}})();"
            )

        # Auto-refresh unit build status when a run finishes.
        # Triggered by the transition: had_running_wave (True on last poll) → no running waves now.
        any_running = bool(running_names)
        if self.had_running_wave and not any_running and self.show_unit_build_status:
            self.had_running_wave = False
            yield AppState.refresh_unit_build_statuses
        else:
            self.had_running_wave = any_running

    def refresh_unit_build_statuses(self):
        """Fast path: read unit-state.yaml and update the UI immediately (no GCS calls).

        Sets is_refreshing_build_statuses = True synchronously so the button shows
        "⟳ Updating…" immediately, then dispatches the background reader.
        Guards against double invocation so rapid clicks are ignored.

        To perform a full GCS validation instead, call validate_unit_build_statuses.
        """
        if self.is_refreshing_build_statuses:
            return
        self.is_refreshing_build_statuses = True
        self.build_status_error = ""
        return AppState.do_refresh_unit_build_statuses

    @rx.event(background=True)
    async def do_refresh_unit_build_statuses(self):
        """Background task — read unit-state.yaml and populate unit_build_statuses.

        Fast path: reads the local persistent cache written by local_state_watcher
        and do_validate_unit_build_statuses.  No GCS calls; completes in milliseconds.

        Status values come from the 'status' field in unit-state.yaml:
          "ok"        — resources > 0 confirmed by GCS or local watcher
          "destroyed" — resources = [] confirmed by GCS or local watcher
          "fail"      — apply exited non-zero
          "unknown"   — detected apply but GCS unreachable at the time
        """
        try:
            unit_state = _read_unit_state()
            if unit_state:
                statuses = {
                    path: entry["status"]
                    for path, entry in unit_state.items()
                    if "status" in entry
                }
                async with self:
                    # Merge: local_state_watcher may have in-flight entries not yet on disk.
                    self.unit_build_statuses = {**self.unit_build_statuses, **statuses}
                    _gui_log(f"[refresh-statuses] loaded {len(statuses)} statuses from unit-state.yaml")
            else:
                async with self:
                    self.build_status_error = (
                        "unit-state.yaml is empty — run '⟳ Validate (GCS)' to populate it."
                    )
        except Exception as exc:
            async with self:
                self.build_status_error = str(exc)
        finally:
            async with self:
                self.is_refreshing_build_statuses = False

    def validate_unit_build_statuses(self):
        """Entry point for the GCS validate button.

        Performs the full GCS state-bucket scan, writes results to unit-state.yaml,
        and updates the UI.  Slower than refresh_unit_build_statuses (network I/O)
        but authoritative — detects changes made outside the GUI.
        """
        if self.is_refreshing_build_statuses:
            return
        self.is_refreshing_build_statuses = True
        self.build_status_error = ""
        return AppState.do_validate_unit_build_statuses

    @rx.event(background=True)
    async def do_validate_unit_build_statuses(self):
        """Background task — full GCS scan to validate unit-state.yaml.

        Equivalent to the old do_refresh_unit_build_statuses GCS logic.
        On completion, writes authoritative statuses + last_validated_at to
        unit-state.yaml so future fast-path refreshes see up-to-date data.

        Status values written:
          "ok"        — resources > 0 in the GCS state file
          "destroyed" — state file exists in GCS but resources = []
          "fail"      — unit in run.log queue but no GCS state file
        """
        import json as _json
        import re as _re
        import subprocess as _sp

        error_msg = ""
        try:
            # Read saved mtime cache from state (outside lock — snapshot copy only).
            prev_mtimes: dict[str, str] = dict(self.gcs_state_mtimes)
            prev_statuses: dict[str, str] = dict(self.unit_build_statuses)

            new_mtimes:   dict[str, str] = {}   # all paths seen in this scan
            gcs_paths:    set[str]       = set() # all paths with a state file
            statuses:     dict[str, str] = {}    # updates to merge
            resources_counts: dict[str, int] = {}  # unused; kept for local variable symmetry

            # 1. Read the GCS state bucket from _STACK_CONFIG.
            stack  = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
            backend = stack.get("backend", {})
            btype   = backend.get("type", "")
            bucket  = backend.get("config", {}).get("bucket", "")

            if not btype:
                error_msg = "No backend configured — framework.yaml not loaded yet. Try refreshing the page."
            elif btype != "gcs":
                error_msg = f"Build status check only supports GCS backends (configured: {btype!r})."
            elif not bucket:
                error_msg = "No GCS bucket found in framework.backend.config.bucket."
            else:
                if _sp.run(["which", "gsutil"], capture_output=True).returncode != 0:
                    error_msg = "gsutil not found on PATH — install Google Cloud SDK to enable status checks."
                else:
                    cached_nodes = list(_ALL_NODES_CACHE)
                    stack_prefixes: set[str] = set()
                    for node in cached_nodes:
                        if node.get("has_terragrunt"):
                            parts = node["path"].split("/")
                            if len(parts) >= 2 and parts[1] == "_stack":
                                stack_prefixes.add(f"gs://{bucket}/{parts[0]}/_stack/")

                    ansi_escape = _re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
                    prefix_str  = f"gs://{bucket}/"
                    suffix      = "/default.tfstate"
                    gsutil_errors: list[str] = []

                    ls_re = _re.compile(r"^\s*\d+\s+(\S+)\s+(gs://.+)$")

                    for gcs_prefix in sorted(stack_prefixes):
                        try:
                            result = _sp.run(
                                ["gsutil", "ls", "-l", "-r", gcs_prefix],
                                capture_output=True, text=True, timeout=30,
                            )
                            if result.returncode != 0:
                                err = result.stderr.strip().splitlines()[0] if result.stderr.strip() else "unknown error"
                                gsutil_errors.append(f"{gcs_prefix}: {err}")
                            for raw_line in result.stdout.splitlines():
                                raw_line = ansi_escape.sub("", raw_line)
                                m = ls_re.match(raw_line)
                                if not m:
                                    continue
                                mtime, gcs_uri = m.group(1), m.group(2)
                                if not (gcs_uri.startswith(prefix_str) and gcs_uri.endswith(suffix)):
                                    continue
                                unit_path = gcs_uri[len(prefix_str):-len(suffix)]
                                if not unit_path:
                                    continue
                                gcs_paths.add(unit_path)
                                new_mtimes[unit_path] = mtime

                                if mtime == prev_mtimes.get(unit_path):
                                    # Unchanged since last scan — carry forward cached status.
                                    if unit_path in prev_statuses:
                                        statuses[unit_path] = prev_statuses[unit_path]
                                    else:
                                        statuses[unit_path] = "ok"
                                    continue

                                # mtime changed (or first scan) — download and parse.
                                try:
                                    cat = _sp.run(
                                        ["gsutil", "cat", gcs_uri],
                                        capture_output=True, text=True, timeout=15,
                                    )
                                    if cat.returncode == 0:
                                        data      = _json.loads(cat.stdout)
                                        resources = data.get("resources", [])
                                        statuses[unit_path] = "ok" if resources else "destroyed"
                                        pass  # resources_count removed in schema v2
                                    else:
                                        statuses[unit_path] = prev_statuses.get(unit_path, "ok")
                                except Exception:
                                    statuses[unit_path] = prev_statuses.get(unit_path, "ok")

                        except _sp.TimeoutExpired:
                            gsutil_errors.append(f"{gcs_prefix}: timed out after 30s")
                        except Exception as exc:
                            gsutil_errors.append(f"{gcs_prefix}: {exc}")

                    if gsutil_errors and not gcs_paths:
                        error_msg = "gsutil error — " + gsutil_errors[0]

            # 2. Parse run.log for attempted units not present in GCS → fail.
            config = _load_config()
            attempted_paths: set[str] = set()
            log_base   = _wave_logs_dir()
            latest_log = log_base / "latest" / "run.log"
            if latest_log.exists():
                try:
                    log_clean = _re.compile(r"\x1b\[[0-9;]*[a-zA-Z]").sub(
                        "", latest_log.read_text(errors="replace")
                    )
                    for m in _re.finditer(r"^- Unit (.+)$", log_clean, _re.MULTILINE):
                        unit_path = m.group(1).strip()
                        if "_stack" in unit_path and "/" in unit_path:
                            attempted_paths.add(unit_path)
                except Exception:
                    pass

            for unit_path in attempted_paths:
                if unit_path not in gcs_paths:
                    statuses[unit_path] = "fail"

            # 3. Merge with existing statuses: local_state_watcher may have set entries
            #    not yet seen by GCS (in-flight apply).  GCS is authoritative when it has data.
            merged = {**prev_statuses, **statuses}

            # 4. Persist validated statuses to unit-state.yaml.
            if statuses and not error_msg:
                now_iso = _datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                yaml_updates: dict[str, dict] = {}
                for unit_path, status in statuses.items():
                    yaml_updates[unit_path] = {"status": status, "last_validated_at": now_iso}
                try:
                    _write_unit_state(yaml_updates)
                    _gui_log(f"[validate-statuses] wrote {len(yaml_updates)} entries to unit-state.yaml")
                except Exception as exc:
                    _gui_log(f"[validate-statuses] unit-state.yaml write failed: {exc}")

            async with self:
                self.unit_build_statuses = merged
                self.gcs_state_mtimes    = new_mtimes
                self.build_status_error  = error_msg
        except Exception as exc:
            async with self:
                self.build_status_error = str(exc)
        finally:
            async with self:
                self.is_refreshing_build_statuses = False

    def refresh_subtree_status(self, path: str):
        """Entry point for right-click 'Refresh build status (recursive)'.

        Scoped to the subtree rooted at `path` — only units under that directory
        are re-checked. Uses the same spinner flag as the full bulk refresh so the
        user sees the "Updating…" indicator while it runs.
        """
        if self.is_refreshing_build_statuses:
            return
        self.is_refreshing_build_statuses = True
        self.build_status_error = ""
        return AppState.do_refresh_subtree_status(path)

    @rx.event(background=True)
    async def do_refresh_subtree_status(self, path: str):
        """Background task: refresh build status for one subtree only.

        Uses a targeted GCS scan (Tier 2 logic) scoped to the given unit path prefix.
        Results are merged into unit_build_statuses without touching entries for other
        subtrees.

        Note: local .terragrunt-cache files are NOT read for content. With a GCS
        backend, the local terraform.tfstate in the cache is always empty (resources=[])
        because the actual state lives in GCS. Use the GCS scan exclusively.

        Args:
            path: unit path relative to infra/, e.g. "example-pkg/_stack/maas/example-lab/machines"
        """
        import json as _json
        import re as _re
        import subprocess as _sp

        error_msg = ""
        updates: dict[str, str] = {}

        try:
            config = _load_config()

            # ── GCS scan scoped to this subtree ───────────────────────────────────
            stack   = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
            backend = stack.get("backend", {})
            btype   = backend.get("type", "")
            bucket  = backend.get("config", {}).get("bucket", "")

            if btype == "gcs" and bucket:
                if _sp.run(["which", "gsutil"], capture_output=True).returncode == 0:
                    gcs_prefix  = f"gs://{bucket}/{path}/"
                    prefix_str  = f"gs://{bucket}/"
                    suffix      = "/default.tfstate"
                    ansi_escape = _re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
                    ls_re       = _re.compile(r"^\s*\d+\s+(\S+)\s+(gs://.+)$")

                    # Read saved mtimes from state for incremental download.
                    prev_mtimes:   dict[str, str] = dict(self.gcs_state_mtimes)
                    prev_statuses: dict[str, str] = dict(self.unit_build_statuses)
                    new_mtimes:    dict[str, str] = dict(prev_mtimes)  # will be updated below
                    gcs_paths:     set[str]        = set()

                    try:
                        result = _sp.run(
                            ["gsutil", "ls", "-l", "-r", gcs_prefix],
                            capture_output=True, text=True, timeout=30,
                        )
                        for raw_line in result.stdout.splitlines():
                            raw_line = ansi_escape.sub("", raw_line)
                            m = ls_re.match(raw_line)
                            if not m:
                                continue
                            mtime, gcs_uri = m.group(1), m.group(2)
                            if not (gcs_uri.startswith(prefix_str) and gcs_uri.endswith(suffix)):
                                continue
                            unit_path_str = gcs_uri[len(prefix_str):-len(suffix)]
                            if not unit_path_str:
                                continue
                            gcs_paths.add(unit_path_str)
                            new_mtimes[unit_path_str] = mtime

                            if mtime == prev_mtimes.get(unit_path_str):
                                # Unchanged — carry forward cached GCS status if it exists,
                                # but don't override a fresher Tier 1 result in `updates`.
                                if unit_path_str not in updates and unit_path_str in prev_statuses:
                                    updates[unit_path_str] = prev_statuses[unit_path_str]
                                continue

                            # mtime changed — download and parse.
                            try:
                                cat = _sp.run(
                                    ["gsutil", "cat", gcs_uri],
                                    capture_output=True, text=True, timeout=15,
                                )
                                if cat.returncode == 0:
                                    data      = _json.loads(cat.stdout)
                                    resources = data.get("resources", [])
                                    # GCS authoritative: override Tier 1 result.
                                    updates[unit_path_str] = "ok" if resources else "destroyed"
                                    new_mtimes[unit_path_str] = mtime
                            except Exception:
                                pass

                    except _sp.TimeoutExpired:
                        error_msg = f"gsutil timed out scanning {gcs_prefix}"
                    except Exception as exc:
                        error_msg = str(exc)

                    async with self:
                        # Persist updated mtime cache
                        self.gcs_state_mtimes = new_mtimes

            async with self:
                self.unit_build_statuses = {**self.unit_build_statuses, **updates}
                self.build_status_error  = error_msg

            # Persist subtree scan results to unit-state.yaml.
            if updates and not error_msg:
                now_iso = _datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                yaml_updates: dict[str, dict] = {
                    unit_path: {"status": status, "last_validated_at": now_iso}
                    for unit_path, status in updates.items()
                }
                try:
                    _write_unit_state(yaml_updates)
                except Exception as exc:
                    _gui_log(f"[subtree-status] unit-state.yaml write error: {exc}")

        except Exception as exc:
            async with self:
                self.build_status_error = str(exc)
        finally:
            async with self:
                self.is_refreshing_build_statuses = False

    # -----------------------------------------------------------------------
    # Local state watcher — real-time build status from .terragrunt-cache
    # -----------------------------------------------------------------------

    @rx.event(background=True)
    async def local_state_watcher(self):
        """Process-level singleton loop: detect apply/destroy activity and update unit_build_statuses.

        Triggered by on_load; only one instance runs per server process (_LOCAL_STATE_WATCHER_RUNNING guard).

        Four-tier detection strategy (highest priority first):

        Tier 0 — exit-status YAMLs (primary, no network calls):
          Scans $_DYNAMIC_DIR/unit-status/exit-*.yaml written by root.hcl after_hook
          (utilities/tg-scripts/write-exit-status/write-exit-status). Files are consumed (deleted) on
          first read. Sets status: ok or fail with finished_at timestamp.

        Tier 0b — MaaS intermediate-status YAMLs (live phase during long MaaS operations):
          Scans $_DYNAMIC_DIR/unit-status/maas-*.yaml written every poll iteration by
          commission-and-wait.sh, wait-for-ready.sh, and wait-for-deployed.sh. Files are
          NOT consumed — re-read each cycle until apply completes (file deleted by Tier 0
          write-exit-status/write-exit-status). Writes maas_phase and maas_message to unit-state.yaml.

        Tier 1 — .terragrunt-cache tfstate mtime (fallback for pre-Tier-0 applies):
          Detects mtime changes on local terraform.tfstate files (always empty with GCS
          backend — used only as a change detector). On change, calls gsutil cat to read
          the real GCS state and determine ok/destroyed/unknown. Skips units resolved by Tier 0.

        Tier 3 — $_GUI_DIR/homelab_gui_apply_*.exit (GUI-initiated applies):
          Reads exit files written by apply_unit(). Kept for backward compatibility.

        Poll intervals:
          Normal:      8 s — steady-state background polling
          Accelerated: 2 s — for 60 s when apply_unit / apply_recursive fires
                             (_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL timestamp)
        """
        import asyncio as _aio
        import glob as _glob
        import json as _json
        import subprocess as _sp
        import time as _t

        global _LOCAL_STATE_WATCHER_RUNNING

        # Process-level singleton: only one watcher per process lifetime.
        if _LOCAL_STATE_WATCHER_RUNNING:
            return
        _LOCAL_STATE_WATCHER_RUNNING = True

        async with self:
            self.local_state_watcher_active = True

        MARKER      = Path(os.environ.get("_GUI_DIR") or "/tmp") / "homelab_gui_state_check.marker"
        NORMAL_SECS = 8.0
        FAST_SECS   = 2.0

        try:
            while True:
                now          = _t.time()
                accelerating = now < _LOCAL_STATE_WATCHER_ACCELERATE_UNTIL
                await _aio.sleep(FAST_SECS if accelerating else NORMAL_SECS)

                config    = _load_config()
                infra_dir = _infra_path(config)
                if not infra_dir.exists():
                    continue

                # ── Auto-refresh from unit-state.yaml ────────────────────────
                # Reads the YAML and pushes updates to unit_build_statuses when:
                #   • unit_status_auto_refresh is True, AND either:
                #     – the YAML file mtime changed since the last read (on-change), OR
                #     – unit_status_auto_refresh_secs > 0 and the interval has elapsed.
                global _UNIT_STATE_YAML_MTIME, _UNIT_STATE_LAST_AUTO_REFRESH
                auto_refresh     = self.unit_status_auto_refresh
                auto_refresh_interval = self.unit_status_auto_refresh_secs
                if auto_refresh and self.show_unit_build_status:
                    try:
                        yaml_path = _unit_state_path()
                        current_mtime = yaml_path.stat().st_mtime if yaml_path.exists() else 0.0
                        mtime_changed    = current_mtime != _UNIT_STATE_YAML_MTIME
                        interval_elapsed = (
                            auto_refresh_interval > 0
                            and (now - _UNIT_STATE_LAST_AUTO_REFRESH) >= auto_refresh_interval
                        )
                        if mtime_changed or interval_elapsed:
                            unit_state = _read_unit_state()
                            if unit_state:
                                auto_statuses = {
                                    path: entry["status"]
                                    for path, entry in unit_state.items()
                                    if "status" in entry
                                }
                                async with self:
                                    self.unit_build_statuses = {
                                        **self.unit_build_statuses, **auto_statuses
                                    }
                                    if self.auto_select_recent_unit and mtime_changed:
                                        # Pick the unit with the most recent last_apply_at.
                                        best = max(
                                            (p for p in unit_state if "last_apply_at" in unit_state[p]),
                                            key=lambda p: str(unit_state[p]["last_apply_at"]),
                                            default="",
                                        )
                                        if best:
                                            self._apply_auto_select(best)
                                if mtime_changed:
                                    _gui_log(
                                        f"[auto-refresh] unit-state.yaml changed → "
                                        f"updated {len(auto_statuses)} statuses"
                                    )
                            _UNIT_STATE_YAML_MTIME = current_mtime
                            _UNIT_STATE_LAST_AUTO_REFRESH = now
                    except Exception as exc:
                        _gui_log(f"[auto-refresh] error reading unit-state.yaml: {exc}")

                # ── Tier 0: consume exit-status YAMLs from root.hcl after_hook ──
                # Written by utilities/tg-scripts/write-exit-status/write-exit-status on every
                # apply/destroy in ALL execution contexts (GUI, wave runner, manual).
                # Each file is one-shot: read → write unit-state → delete.
                # Paths already resolved here are skipped in the Tier 1 GCS cat below.
                import os as _os
                _dyn_dir_str = _os.environ.get("_DYNAMIC_DIR", "")
                if not _dyn_dir_str:
                    try:
                        _repo_root = _sp.run(
                            ["git", "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True, cwd=str(infra_dir),
                        ).stdout.strip()
                        _dyn_dir_str = str(Path(_repo_root) / "config" / "tmp" / "dynamic")
                    except Exception:
                        _dyn_dir_str = ""

                tier0_resolved: set[str] = set()
                if _dyn_dir_str:
                    _unit_status_dir = Path(_dyn_dir_str) / "unit-status"
                    _tier0_updates: dict[str, str] = {}
                    _tier0_yaml_updates: dict[str, dict] = {}
                    try:
                        for _ef in _unit_status_dir.glob("exit-*.yaml"):
                            try:
                                _ef_data = yaml.safe_load(_ef.read_text()) or {}
                                _unit_path = _ef_data.get("unit_path", "")
                                _status = _ef_data.get("status", "")
                                _finished_at = _ef_data.get("finished_at", "")
                                if _unit_path and _status in ("ok", "fail"):
                                    _tier0_updates[_unit_path] = _status
                                    tier0_resolved.add(_unit_path)
                                    _tier0_yaml_updates[_unit_path] = {
                                        "status": _status,
                                        "last_apply_at": _finished_at or _datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "last_apply_exit_code": 0 if _status == "ok" else 1,
                                    }
                                    _gui_log(f"[local-state-watcher] exit-status YAML: {_unit_path} → {_status}")
                                _ef.unlink(missing_ok=True)
                            except Exception as _ef_exc:
                                _gui_log(f"[local-state-watcher] exit-status read error {_ef}: {_ef_exc}")
                                try:
                                    _ef.unlink(missing_ok=True)
                                except Exception:
                                    pass
                    except Exception:
                        pass  # unit-status dir not yet created; ignore

                    if _tier0_updates:
                        async with self:
                            self.unit_build_statuses = {**self.unit_build_statuses, **_tier0_updates}
                            if self.auto_select_recent_unit:
                                _most_recent = max(
                                    _tier0_yaml_updates,
                                    key=lambda p: _tier0_yaml_updates[p].get("last_apply_at", ""),
                                )
                                self._apply_auto_select(_most_recent)
                        try:
                            _write_unit_state(_tier0_yaml_updates)
                        except Exception as _exc:
                            _gui_log(f"[local-state-watcher] exit-status unit-state write error: {_exc}")

                    # ── Tier 0b: read maas-status YAMLs (NOT consumed — re-read each cycle) ──
                    # Written by commission-and-wait.sh / wait-for-ready.sh / wait-for-deployed.sh
                    # every poll iteration (~10-30s). Provides live phase + message during the
                    # long-running commission (~5 min) and deploy (~10 min) phases.
                    # Files stay on disk until write-exit-status/write-exit-status deletes them on apply completion.
                    _maas_status_updates: dict[str, dict] = {}
                    try:
                        for _mf in _unit_status_dir.glob("maas-*.yaml"):
                            try:
                                _mf_data = yaml.safe_load(_mf.read_text()) or {}
                                _m_unit_path = _mf_data.get("unit_path", "")
                                _m_phase = _mf_data.get("phase", "")
                                _m_message = _mf_data.get("message", "")
                                _m_updated_at = _mf_data.get("updated_at", "")
                                if _m_unit_path and _m_phase:
                                    _maas_status_updates[_m_unit_path] = {
                                        "maas_phase": _m_phase,
                                        "maas_message": _m_message,
                                        "last_apply_at": _m_updated_at or _datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    }
                            except Exception:
                                pass
                    except Exception:
                        pass  # unit-status dir not yet created; ignore

                    if _maas_status_updates:
                        async with self:
                            # Update statuses: mark in-progress units as "unknown" only if
                            # they don't already have a definitive status from Tier 0.
                            _maas_ui: dict[str, str] = {
                                p: self.unit_build_statuses.get(p, "unknown")
                                for p in _maas_status_updates
                                if p not in tier0_resolved
                            }
                            if _maas_ui:
                                self.unit_build_statuses = {**self.unit_build_statuses, **_maas_ui}
                            if self.auto_select_recent_unit:
                                _maas_recent = max(
                                    _maas_status_updates,
                                    key=lambda p: _maas_status_updates[p].get("last_apply_at", ""),
                                )
                                self._apply_auto_select(_maas_recent)
                        try:
                            _write_unit_state(_maas_status_updates)
                        except Exception as _exc:
                            _gui_log(f"[local-state-watcher] maas-status unit-state write error: {_exc}")

                # Tier 3: scan for apply exit-code files written by apply_unit.
                # File names: $_GUI_DIR/apply-<path-with-+-separators>.exit
                # Content: the shell exit code (0 = success, non-0 = failure).
                # Files are removed after reading so each result is processed once.
                _gui_dir = Path(os.environ.get("_GUI_DIR") or "/tmp")
                exit_files = _glob.glob(str(_gui_dir / "homelab_gui_apply_*.exit"))
                exit_updates: dict[str, str] = {}
                for ef in exit_files:
                    try:
                        ef_path = Path(ef)
                        exit_code_str = ef_path.read_text().strip()
                        exit_code = int(exit_code_str)
                        # Recover unit path: strip prefix/suffix, unescape + → /
                        stem = ef_path.stem  # "homelab_gui_apply_<safe_path>"
                        safe = stem[len("homelab_gui_apply_"):]
                        unit_path = safe.replace("+", "/")
                        if exit_code != 0:
                            # Definitive failure: apply exited non-zero.
                            exit_updates[unit_path] = "fail"
                            _gui_log(f"[local-state-watcher] apply_unit FAILED (exit {exit_code}): {unit_path}")
                        else:
                            # Exit 0: trust the tfstate content already picked up by Tier 1.
                            # Only set ok if we don't already have a more specific status.
                            _gui_log(f"[local-state-watcher] apply_unit OK (exit 0): {unit_path}")
                        ef_path.unlink(missing_ok=True)
                    except Exception:
                        try:
                            Path(ef).unlink(missing_ok=True)
                        except Exception:
                            pass

                if exit_updates:
                    async with self:
                        self.unit_build_statuses = {**self.unit_build_statuses, **exit_updates}
                        if self.auto_select_recent_unit:
                            most_recent = next(iter(exit_updates))
                            self._apply_auto_select(most_recent)
                    # Persist fail statuses to unit-state.yaml.
                    now_iso = _datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                    exit_yaml_updates: dict[str, dict] = {
                        unit_path: {"status": status, "last_apply_at": now_iso, "last_apply_exit_code": (0 if status != "fail" else 1)}
                        for unit_path, status in exit_updates.items()
                    }
                    try:
                        _write_unit_state(exit_yaml_updates)
                    except Exception as exc:
                        _gui_log(f"[local-state-watcher] unit-state.yaml exit write error: {exc}")

        except Exception as exc:
            _gui_log(f"[local-state-watcher] fatal: {exc}")
        finally:
            _LOCAL_STATE_WATCHER_RUNNING = False
            async with self:
                self.local_state_watcher_active = False

    @rx.event(background=True)
    async def sync_unit_status_from_gcs(self):
        """Pull unit_status/ objects from GCS and merge into unit_build_statuses.

        On first call (unit_status_sync_after is empty) fetches all objects.
        Subsequent calls fetch only objects newer than the cursor.
        Objects are JSON written by write-exit-status/write-exit-status via gcs-status.sh.
        """
        import subprocess as _sp
        import json as _json
        import re as _re

        stack  = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
        bucket = stack.get("backend", {}).get("config", {}).get("bucket", "")
        if not bucket:
            return
        if _sp.run(["which", "gsutil"], capture_output=True).returncode != 0:
            return

        async with self:
            self.gcs_unit_sync_running = True
            cursor = self.unit_status_sync_after

        try:
            now_iso = _datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            # Timestamp in GCS key uses hyphens (YYYY-MM-DDTHH-MM-SSZ); convert cursor.
            cursor_key = cursor.replace(":", "-") if cursor else ""

            try:
                ls = _sp.run(
                    ["gsutil", "ls", "-r", f"gs://{bucket}/unit_status/"],
                    capture_output=True, text=True, timeout=30,
                )
                if ls.returncode != 0:
                    _gui_log(f"[gcs-unit-sync] gsutil ls failed: {ls.stderr.strip()[:200]}")
                    return
            except Exception as exc:
                _gui_log(f"[gcs-unit-sync] error: {exc}")
                return

            uris = [
                line.strip() for line in ls.stdout.splitlines()
                if line.strip().endswith(".json")
            ]
            if cursor_key:
                # Object names end with /<ts>.json; filter by ts > cursor_key.
                def _ts_from_uri(u: str) -> str:
                    return u.rsplit("/", 1)[-1].replace(".json", "")
                uris = [u for u in uris if _ts_from_uri(u) > cursor_key]

            if not uris:
                async with self:
                    self.unit_status_sync_after = now_iso
                return

            unit_updates:  dict[str, str]  = {}
            yaml_updates:  dict[str, dict] = {}

            for uri in uris:
                try:
                    cat = _sp.run(
                        ["gsutil", "cat", uri],
                        capture_output=True, text=True, timeout=10,
                    )
                    if cat.returncode != 0:
                        continue
                    data = _json.loads(cat.stdout)
                    unit_path = data.get("unit_path", "")
                    status    = data.get("status", "")
                    finished  = data.get("finished_at", now_iso)
                    exit_code = data.get("last_apply_exit_code", 0)
                    if unit_path and status in ("ok", "fail"):
                        unit_updates[unit_path] = status
                        yaml_updates[unit_path] = {
                            "status": status,
                            "last_apply_at": finished,
                            "last_apply_exit_code": exit_code,
                        }
                except Exception:
                    continue

            if unit_updates:
                async with self:
                    self.unit_build_statuses  = {**self.unit_build_statuses, **unit_updates}
                    self.unit_status_sync_after = now_iso
                try:
                    _write_unit_state(yaml_updates)
                except Exception as exc:
                    _gui_log(f"[gcs-unit-sync] unit-state.yaml write error: {exc}")
                _gui_log(f"[gcs-unit-sync] merged {len(unit_updates)} unit status(es) from GCS")
            else:
                async with self:
                    self.unit_status_sync_after = now_iso
        finally:
            async with self:
                self.gcs_unit_sync_running = False

    @rx.event(background=True)
    async def sync_wave_status_from_gcs(self):
        """Pull wave_status/ objects from GCS and populate gcs_wave_statuses.

        Takes the newest status object per wave name.
        Called on load to recover wave history from before this session.
        run.log takes precedence in refresh_wave_log_statuses().
        """
        import subprocess as _sp
        import json as _json

        stack  = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
        bucket = stack.get("backend", {}).get("config", {}).get("bucket", "")
        if not bucket:
            return
        if _sp.run(["which", "gsutil"], capture_output=True).returncode != 0:
            return

        async with self:
            self.gcs_wave_sync_running = True
            cursor = self.wave_status_sync_after

        try:
            cursor_key = cursor.replace(":", "-") if cursor else ""

            try:
                ls = _sp.run(
                    ["gsutil", "ls", "-r", f"gs://{bucket}/wave_status/"],
                    capture_output=True, text=True, timeout=30,
                )
                if ls.returncode != 0:
                    _gui_log(f"[gcs-wave-sync] gsutil ls failed: {ls.stderr.strip()[:200]}")
                    return
            except Exception as exc:
                _gui_log(f"[gcs-wave-sync] error: {exc}")
                return

            # Group URIs by wave name; keep only the newest per wave.
            from collections import defaultdict as _dd
            wave_uris: dict[str, str] = {}
            for line in ls.stdout.splitlines():
                uri = line.strip()
                if not uri.endswith(".json"):
                    continue
                # URI: gs://bucket/wave_status/<wave_name>/<ts>.json
                parts = uri.split("/")
                if len(parts) < 2:
                    continue
                wave_name = parts[-2]
                ts_key    = parts[-1].replace(".json", "")
                if cursor_key and ts_key <= cursor_key:
                    continue
                existing = wave_uris.get(wave_name, "")
                if ts_key > existing.rsplit("/", 1)[-1].replace(".json", "") if existing else True:
                    wave_uris[wave_name] = uri

            if not wave_uris:
                return

            now_iso = _datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            new_gcs_statuses: dict[str, dict] = {}
            for wave_name, uri in wave_uris.items():
                try:
                    cat = _sp.run(
                        ["gsutil", "cat", uri],
                        capture_output=True, text=True, timeout=10,
                    )
                    if cat.returncode != 0:
                        continue
                    data = _json.loads(cat.stdout)
                    new_gcs_statuses[wave_name] = data
                except Exception:
                    continue

            if new_gcs_statuses:
                async with self:
                    self.gcs_wave_statuses    = {**self.gcs_wave_statuses, **new_gcs_statuses}
                    self.wave_status_sync_after = now_iso
                _gui_log(f"[gcs-wave-sync] loaded {len(new_gcs_statuses)} wave status(es) from GCS")
        finally:
            async with self:
                self.gcs_wave_sync_running = False

    def open_wave_log(self, log_path: str):
        """Open a wave run.log in the file viewer and search for STDERR."""
        if not log_path:
            return
        p = Path(log_path)
        if not p.exists():
            return
        self.hcl_content = p.read_text(errors="replace")
        self.hcl_file_path = str(p)
        self.unit_file_search_query = "STDERR"
        self.ansi_search_idx = 0
        self.file_search_match_count = self.ansi_match_total
        return rx.call_script(self._ansi_search_scroll_js())

    # ------------------------------------------------------------------
    # Wave floating popup — open/close/drag
    # ------------------------------------------------------------------

    _WAVE_POLL_STOP_JS = (
        "if(window._waveStatusPollId){"
        "  clearInterval(window._waveStatusPollId);"
        "  window._waveStatusPollId=null;"
        "}"
    )

    def set_object_viewer_mode(self, mode: str):
        """Switch the Object Viewer panel between 'params' and 'waves'."""
        self.object_viewer_mode = mode
        self._save_current_config()
        if mode == "waves":
            self.refresh_wave_log_statuses()
            return rx.call_script(self._WAVE_POLL_START_JS)
        else:
            return rx.call_script(self._WAVE_POLL_STOP_JS)

    # ------------------------------------------------------------------
    # Show inputs / outputs (read-only, opens terminal)
    # ------------------------------------------------------------------

    def show_inputs(self, path: str):
        """Run terragrunt render --all --json | jq '.inputs' in the action terminal."""
        config   = _load_config()
        unit_dir = _infra_path(config) / path
        self.shell_cwd         = str(unit_dir)
        self.shell_initial_cmd = (
            "source $(git rev-parse --show-toplevel)/set_env.sh"
            " && terragrunt render --all --json | jq '.inputs'"
        )

    def show_outputs(self, path: str):
        """Run terragrunt output -json | jq . in the action terminal."""
        config   = _load_config()
        unit_dir = _infra_path(config) / path
        self.shell_cwd         = str(unit_dir)
        self.shell_initial_cmd = (
            "source $(git rev-parse --show-toplevel)/set_env.sh"
            " && terragrunt output -json | jq ."
        )

    # ------------------------------------------------------------------
    # Apply unit (terragrunt apply / run-all apply)
    # ------------------------------------------------------------------

    def apply_unit(self, path: str):
        """Run terragrunt apply for a single unit (opens action terminal).

        Wraps the command to:
          1. Tee output to a per-unit log file at
             $WAVE_LOGS_DIR/unit-logs/<unit-path>/latest.log (+ timestamped copy).
          2. Write the apply exit code to $_GUI_DIR/apply-<safe>.exit so the
             local state watcher (Tier 3) can detect definitive success/failure.

        Uses PIPESTATUS[0] to capture terragrunt's exit code through the tee pipe.
        """
        config    = _load_config()
        unit_dir  = _infra_path(config) / path
        safe_path = path.replace("/", "+")
        _gui_dir = Path(os.environ.get("_GUI_DIR") or "/tmp")
        exit_file = str(_gui_dir / f"homelab_gui_apply_{safe_path}.exit")

        # Build the per-unit log directory path (mirrors wave log structure).
        log_base  = _wave_logs_dir()
        # Unit log dir: $WAVE_LOGS_DIR/unit-logs/<pkg>/_stack/<rest...>
        log_dir   = log_base / "unit-logs" / path
        log_dir_str = str(log_dir)

        self.shell_cwd = str(unit_dir)
        # Shell command breakdown:
        #   mkdir -p                 — create the log directory
        #   _TS=$(date …)            — timestamp for the per-run log filename
        #   _LOG=…/$_TS.log          — full log path for this run
        #   ln -sf …/latest.log      — always points at the most recent log
        #   terragrunt apply … 2>&1 | tee "$_LOG"
        #                            — tee to file; both stdout+stderr captured
        #   echo ${PIPESTATUS[0]}    — capture terragrunt exit code (not tee's)
        self.shell_initial_cmd = (
            f'mkdir -p "{log_dir_str}"'
            f' && _TS="$(date +%Y%m%d-%H%M%S)"'
            f' && _LOG="{log_dir_str}/$_TS.log"'
            f' && ln -sf "$_LOG" "{log_dir_str}/latest.log"'
            f" && source $(git rev-parse --show-toplevel)/set_env.sh"
            f" && terragrunt apply -- -auto-approve 2>&1 | tee \"$_LOG\""
            f"; echo ${{PIPESTATUS[0]}} > {exit_file}"
        )
        # Accelerate the local state watcher for 60 s so status updates appear quickly.
        global _LOCAL_STATE_WATCHER_ACCELERATE_UNTIL, _LOCAL_STATE_WATCHER_FOCUS_PATHS
        import time as _t
        _LOCAL_STATE_WATCHER_ACCELERATE_UNTIL = _t.time() + 60.0
        _LOCAL_STATE_WATCHER_FOCUS_PATHS = [path]

    def apply_recursive(self, path: str):
        """Run terragrunt run --all apply from the unit directory (opens action terminal).

        Tier 3 exit-code tracking is not used for recursive applies — individual unit
        states are picked up by the Tier 1 local cache watcher as each unit completes.
        """
        config   = _load_config()
        unit_dir = _infra_path(config) / path
        self.shell_cwd         = str(unit_dir)
        self.shell_initial_cmd = (
            "source $(git rev-parse --show-toplevel)/set_env.sh"
            " && terragrunt run --all apply --non-interactive --"
        )
        # Accelerate the local state watcher for 60 s so status updates appear quickly.
        global _LOCAL_STATE_WATCHER_ACCELERATE_UNTIL, _LOCAL_STATE_WATCHER_FOCUS_PATHS
        import time as _t
        _LOCAL_STATE_WATCHER_ACCELERATE_UNTIL = _t.time() + 60.0
        _LOCAL_STATE_WATCHER_FOCUS_PATHS = [path]

    def confirm_delete(self):
        """Remove the unit directory and config block from the stack YAML.

        No terragrunt is run.  Use confirm_destroy for infrastructure teardown.
        """
        import subprocess as _subprocess
        import shlex as _shlex

        mode = self.delete_pending_mode
        self.delete_dialog_open = False
        path = self.delete_pending_path
        if not path:
            return

        config   = _load_config()
        unit_dir = _infra_path(config) / path
        if not unit_dir.exists():
            self.clipboard_message = f"Remove failed: directory not found for '{path}'"
            self.clipboard_message_is_error = True
            return

        # ── Remove config block from stack YAML ───────────────────────
        try:
            if _delete_pkg_config_param(path):
                _load_stack_config()
        except Exception as exc:
            self.clipboard_message = f"Remove: config block cleanup failed: {exc}"
            self.clipboard_message_is_error = True
            return

        # ── rm -rf the unit directory ─────────────────────────────────
        result = _subprocess.run(["rm", "-rf", str(unit_dir)], capture_output=True, text=True)
        if result.returncode != 0:
            self.clipboard_message = f"Remove failed: {result.stderr.strip()}"
            self.clipboard_message_is_error = True
            return

        # ── Reload infra cache ────────────────────────────────────────
        try:
            _init_nodes_cache()
            _init_path_param_maps()
            flat   = list(_ALL_NODES_CACHE)
            merged = _build_merged_nodes(flat)
        except Exception as exc:
            self.clipboard_message = f"Removed but reload failed: {exc}"
            self.clipboard_message_is_error = True
            return

        unit_label = path.split("/")[-1]
        self.all_nodes         = flat
        self.merged_nodes_base = merged
        self.package_filters  = {n["name"]: True for n in flat if n.get("depth", -1) == 0}
        self.region_filters    = {"_none": True, **{v: True for v in set(_PATH_TO_REGION_CACHE.values())}}
        self.env_filters       = {"_none": True, **{v: True for v in set(_PATH_TO_ENV_CACHE.values())}}
        self.wave_filters      = _build_initial_wave_filters()
        dlim = self.depth_limit
        if dlim == 0:
            self.expanded_paths        = [n["path"] for n in flat]
            self.merged_expanded_paths = [n["path"] for n in merged]
        else:
            self.expanded_paths        = [n["path"] for n in flat   if n["depth"] < dlim]
            self.merged_expanded_paths = [n["path"] for n in merged if n["depth"] < dlim]
        if self.selected_node_path == path or self.selected_node_path.startswith(path + "/"):
            self.selected_node_path = ""
            self.hcl_content = ""
            self.hcl_file_path = ""
            self.unit_hcl_path = ""
        elif self.hcl_file_path and Path(self.hcl_file_path).exists():
            self.hcl_content = Path(self.hcl_file_path).read_text()
        self.shell_cwd         = str(unit_dir.parent)
        self.shell_initial_cmd = f"echo {_shlex.quote('Removed: ' + str(unit_dir))}"
        self.clipboard_message = f"Removed: {unit_label}"
        self.clipboard_message_is_error = False
        self.config_data_search_query = ""
        self._save_current_config()

    def toggle_role(self, tag: str):
        if tag in self.selected_roles:
            self.selected_roles = [r for r in self.selected_roles if r != tag]
        else:
            self.selected_roles = [*self.selected_roles, tag]
        self._save_current_config()

    def clear_role_filter(self):
        self.selected_roles = []
        self._save_current_config()

    def toggle_all_roles(self):
        """Toggle between all roles selected (including _none) and none selected."""
        if self.selected_roles:
            self.selected_roles = []
        else:
            self.selected_roles = [*self.available_roles, "_none"]
        self._save_current_config()

    def solo_role(self, tag: str):
        """Double-click handler: toggle solo for this role filter.

        First double-click: select only this role (show only nodes with this role).
        Second double-click (already soloed): invert — select all other roles except
        this one.
        """
        already_soloed = self.selected_roles == [tag]
        if already_soloed:
            others = [r for r in self.available_roles if r != tag]
            self.selected_roles = [*others, "_none"]
        else:
            self.selected_roles = [tag]
        self._save_current_config()

    def set_explorer_search(self, text: str):
        self.explorer_search = text
        # Auto-expand ancestors of matching nodes so that search results are
        # visible regardless of the current depth_limit / collapsed state.
        # This pairs with the visible_nodes change that always respects
        # expanded_paths: without auto-expansion, collapsed parents would hide
        # search results.
        if text:
            s = text.lower().strip()
            exps = set(self.expanded_paths)
            mexps = set(self.merged_expanded_paths)
            for node in self.all_nodes:
                name = node.get("name", "").lower()
                path = node.get("path", "")
                if s in name or s in path.lower():
                    parts = path.split("/")
                    for i in range(1, len(parts)):
                        exps.add("/".join(parts[:i]))
            for node in self.merged_nodes_base:
                name = node.get("name", "").lower()
                path = node.get("path", "")
                if s in name or s in path.lower():
                    parts = path.split("/")
                    for i in range(1, len(parts)):
                        mexps.add("/".join(parts[:i]))
            self.expanded_paths = list(exps)
            self.merged_expanded_paths = list(mexps)
        self._save_current_config()

    def clear_explorer_search(self):
        self.explorer_search = ""
        self._save_current_config()

    def set_unit_params_search(self, text: str):
        self.unit_params_search = text
        self._save_current_config()

    def clear_unit_params_search(self):
        self.unit_params_search = ""
        self._save_current_config()

    # ------------------------------------------------------------------
    # Inline param editing
    # ------------------------------------------------------------------

    def begin_edit_param(self, provider: str, config_key: str,
                         param_key: str, current_value: str):
        """Open the param-edit dialog for a single key/value pair."""
        self.param_edit_provider   = provider
        self.param_edit_config_key = config_key
        self.param_edit_param_key  = param_key
        self.param_edit_draft      = current_value
        self.param_edit_error      = ""
        # Determine if this param is inherited from an ancestor or defined at
        # the exact current node.  source_path (config_key) is always
        # provider-inclusive; reconstruct lookup_path the same way.
        if self.tree_mode == "merged":
            # Merged paths strip "_stack" + provider; full path = <pkg>/_stack/<provider>/<rest>
            parts = self.selected_node_path.split("/")
            lookup = "/".join([parts[0], "_stack", provider] + parts[1:]) if parts else self.selected_node_path
        else:
            lookup = self.selected_node_path
        self.param_edit_is_inherited = (config_key != lookup)
        self.param_edit_dialog_open  = True

    def set_param_edit_draft(self, value: str):
        self.param_edit_draft = value

    def cancel_edit_param(self):
        self.param_edit_dialog_open = False
        self.param_edit_error = ""

    def param_edit_keydown(self, key: str):
        if key == "Enter":
            return AppState.confirm_edit_param

    def confirm_edit_param(self):
        """Parse the draft, write it to the stack YAML, reload caches."""
        provider  = self.param_edit_provider
        cfg_key   = self.param_edit_config_key
        param_key = self.param_edit_param_key
        raw       = self.param_edit_draft.strip()

        # Parse draft as YAML so numbers/bools/dicts round-trip correctly
        try:
            new_value = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            self.param_edit_error = f"Invalid YAML: {exc}"
            return

        # Determine where to write:
        # • inherited → create an override at the exact current node path
        # • exact     → update in-place at the existing config_params key
        if self.param_edit_is_inherited:
            if self.tree_mode == "merged":
                # Merged paths strip "_stack" + provider; full path = <pkg>/_stack/<provider>/<rest>
                parts = self.selected_node_path.split("/")
                write_key = "/".join([parts[0], "_stack", provider] + parts[1:]) if parts else self.selected_node_path
            else:
                write_key = self.selected_node_path
        else:
            write_key = cfg_key

        try:
            yaml_path = _pkg_config_yaml_for_path(write_key)
            if not yaml_path:
                self.param_edit_error = "Package config file not found for this node"
                return
            pkg = write_key.split("/")[0]
            doc = yaml.safe_load(yaml_path.read_text()) or {}
            (doc.setdefault(pkg, {}).setdefault("config_params", {}).setdefault(write_key, {}))[param_key] = new_value
            yaml_path.write_text(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
            _load_stack_config()
            _init_path_param_maps()
        except Exception as exc:
            self.param_edit_error = f"Save failed: {exc}"
            return

        # Refresh filter caches in case env/region/wave was edited
        self.region_filters = {"_none": True, **{v: True for v in set(_PATH_TO_REGION_CACHE.values())}}
        self.env_filters    = {"_none": True, **{v: True for v in set(_PATH_TO_ENV_CACHE.values())}}
        self.wave_filters   = _build_initial_wave_filters()
        self.param_edit_dialog_open = False

    def toggle_merge(self):
        """Button handler: flip between merged and separated tree mode."""
        self.tree_mode = "separated" if self.tree_mode == "merged" else "merged"
        self.selected_node_path = ""
        self.active_provider_tab = ""
        self._save_current_config()

    def set_explorer_root(self, root: str):
        """Switch the explorer panel root: 'infra' | 'modules' | 'packages' | 'ansible_inventory' | 'framework_repos'."""
        self.explorer_root = root
        self.selected_node_path = ""
        self.active_provider_tab = ""
        if root == "ansible_inventory":
            content, path = _read_inventory_file()
            self.hcl_content = content
            self.hcl_file_path = path if path else "(ansible inventory not configured)"
        self._save_current_config()

    # ── Framework Repos event handlers ──────────────────────────────────────

    @rx.event(background=True)
    async def refresh_fw_repos_data(self):
        async with self:
            self.fw_repos_refreshing = True
        if _FW_REPOS_VIZ_BIN.exists():
            subprocess.run([str(_FW_REPOS_VIZ_BIN), "--refresh", "--list"], capture_output=True)
        async with self:
            self.fw_repos_refreshing = False
        yield rx.call_script(
            "var f=document.querySelector('iframe[src*=\"fw_repos\"]');"
            "if(f && f.contentWindow && f.contentWindow.load) f.contentWindow.load();"
        )

    def navigate_to_module(self, module_path: str):
        """Switch to Modules view and navigate to a specific module path.

        Expects a full modules-tree path (e.g. "gcp/buckets-pkg/google_storage_bucket")
        as stored in node["module_tree_path"] by _populate_module_tree_paths().
        Expands all ancestor paths so the target node is visible, selects it,
        and loads its content.
        """
        if not module_path:
            return
        self.explorer_root = "modules"
        # Ensure every ancestor and the target itself are expanded
        parts = module_path.split("/")
        expanded = set(self.modules_expanded_paths)
        for i in range(1, len(parts)):
            expanded.add("/".join(parts[:i]))
        expanded.add(module_path)
        self.modules_expanded_paths = list(expanded)
        # Select and load the module file
        self._reset_file_editor()
        self.selected_node_path = module_path
        self.active_provider_tab = ""
        self.unit_file_search_query = ""
        self.config_data_search_query = ""
        self.hcl_content, self.hcl_file_path = _read_module_file(module_path)
        self.file_viewer_status_msg = "" if self.hcl_content else f"No file found for: {module_path}"
        self._save_current_config()
        return self._search_reapply_script()

    def click_modules_node(self, path: str):
        """Click a modules tree row: select, load TF file, toggle expand/collapse."""
        self._reset_file_editor()
        self.selected_node_path = path
        self.active_provider_tab = ""
        self.unit_file_search_query = ""
        self.config_data_search_query = ""
        self.hcl_content, self.hcl_file_path = _read_module_file(path)
        self.file_viewer_status_msg = "" if self.hcl_content else f"No file found for: {path}"
        if path in self.modules_expanded_paths:
            self.modules_expanded_paths = [
                p for p in self.modules_expanded_paths
                if p != path and not p.startswith(path + "/")
            ]
        else:
            self.modules_expanded_paths = self.modules_expanded_paths + [path]
        return self._search_reapply_script()

    def open_abs_file_in_viewer(self, abs_path: str):
        """Open an absolute file path in the file viewer."""
        if not abs_path:
            return
        try:
            content = Path(abs_path).read_text()
        except Exception as exc:
            content = f"# Error reading file: {exc}"
        self._reset_file_editor()
        self.hcl_content = content
        self.hcl_file_path = abs_path
        # Clear node-path search queries — they're only relevant in infra views
        self.unit_file_search_query = ""
        self.config_data_search_query = ""
        self.file_viewer_status_msg = ""
        if abs_path.endswith((".yaml", ".yml")):
            self.file_viewer_mode = "config_data"
        else:
            self.file_viewer_mode = "unit_file"
        return self._search_reapply_script()

    def open_markdown_link(self, path: str):
        """Open a relative link clicked inside the markdown file viewer.

        Called by the JS click interceptor with the resolved absolute path.
        Only opens the file if it actually exists on disk.
        """
        if not path:
            return
        try:
            p = Path(path).resolve()
        except Exception:
            return
        if not p.is_file():
            return
        return self.open_abs_file_in_viewer(str(p))

    def open_wave_definition(self, name: str):
        """Open the stack config in the file viewer and search for this wave's definition."""
        if not name or name == "_none":
            return
        content, path = _read_stack_config_file()
        if not content:
            return
        self._reset_file_editor()
        self.hcl_content = content
        self.hcl_file_path = path
        self.file_viewer_mode = "config_data"
        self.config_data_search_query = name
        self.file_viewer_status_msg = ""
        return self._search_reapply_script()

    def open_context_menu(self, path: str):
        """Populate ctx_menu_rows when a tree node is right-clicked."""
        self.ctx_menu_path = path
        node = next((n for n in self.all_nodes if n["path"] == path), None)
        if node is None:
            self.ctx_menu_rows = []
            return
        actions = _get_node_actions(
            path,
            node.get("type", ""),
            node.get("provider", ""),
            node.get("has_terragrunt", False),
        )
        # Inject built-in "Open local shell" and "SSH to host" under the Shell group.
        injected: list[dict] = []
        shell_dir = ""
        if node.get("has_terragrunt", False):
            _, hcl_abs = _read_hcl_file(path)
            if hcl_abs:
                shell_dir = str(Path(hcl_abs).parent)
                injected.append({"group": "shell", "id": "open_local_shell",
                                  "label": "Open local shell", "action_type": "shell",
                                  "value": shell_dir})
        # "SSH to host" — opens terminal and auto-runs the SSH command
        ssh_cmd = _get_ssh_command(path)
        if ssh_cmd:
            import json as _json_local
            ssh_cwd = shell_dir if shell_dir else str(Path.home())
            injected.append({"group": "shell", "id": "ssh_to_host",
                              "label": "SSH to host", "action_type": "ssh",
                              "value": _json_local.dumps({"cwd": ssh_cwd, "cmd": ssh_cmd})})
        # "Open Kube Shell" — for kubeconfig nodes: sets KUBECONFIG and runs kubectl get nodes
        _path_parts = path.split("/")
        if _path_parts and _path_parts[-1] == "kubeconfig" and len(_path_parts) >= 2:
            import json as _json_local
            _cluster_name = _path_parts[-2]
            _kube_cmd = _build_kube_shell_cmd(_cluster_name)
            _kube_cwd = shell_dir if shell_dir else str(_infra_path(_load_config()) / path)
            injected.append({"group": "shell", "id": "open_kube_shell",
                              "label": "Open Kube Shell", "action_type": "ssh",
                              "value": _json_local.dumps({"cwd": _kube_cwd, "cmd": _kube_cmd})})
        has_tg = node.get("has_terragrunt", False)
        extra_actions: list[dict] = []
        # ── Group "build": Apply ───────────────────────────────────────
        if has_tg:
            extra_actions.append({
                "group": "build", "id": "apply_unit",
                "label": "Apply unit", "action_type": "apply_unit", "value": path,
            })
        extra_actions.append({
            "group": "build", "id": "apply_unit_recursive",
            "label": "Apply unit (recursive)", "action_type": "apply_recursive", "value": path,
        })
        # ── Group "edit": Move / Copy / Delete ────────────────────────
        extra_actions.append({
            "group": "edit", "id": "refactor_move",
            "label": "Move", "action_type": "begin_refactor_move", "value": path,
        })
        extra_actions.append({
            "group": "edit", "id": "refactor_copy",
            "label": "Copy", "action_type": "begin_refactor_copy", "value": path,
        })
        extra_actions.append({
            "group": "edit", "id": "refactor_delete",
            "label": "Delete", "action_type": "begin_refactor_delete", "value": path,
        })
        # ── Group "status": Show inputs/outputs + build-status refresh ─
        if has_tg:
            extra_actions.append({
                "group": "status", "id": "show_inputs",
                "label": "Show inputs", "action_type": "show_inputs", "value": path,
            })
            extra_actions.append({
                "group": "status", "id": "show_outputs",
                "label": "Show outputs", "action_type": "show_outputs", "value": path,
            })
        if self.show_unit_build_status:
            extra_actions.append({
                "group": "status", "id": "refresh_subtree_status",
                "label": "Refresh build status (recursive)",
                "action_type": "refresh_subtree_status", "value": path,
            })
        # ── Group "debug": State lock file removal ─────────────────────
        if has_tg:
            extra_actions.append({
                "group": "debug", "id": "remove_state_lock_file",
                "label": "Remove state lock file…", "action_type": "begin_unlock_file", "value": path,
            })
        # recursive lock-file delete is available for any node (may cover sub-units)
        extra_actions.append({
            "group": "debug", "id": "remove_state_lock_file_recursive",
            "label": "Remove state lock files (recursive)…",
            "action_type": "begin_unlock_file_recursive", "value": path,
        })
        # ── Group "destroy": Destroy + Taint + Remove unit ────────────
        if has_tg:
            extra_actions.append({
                "group": "destroy", "id": "destroy_unit",
                "label": "Destroy unit", "action_type": "begin_destroy_unit", "value": path,
            })
        extra_actions.append({
            "group": "destroy", "id": "destroy_unit_recursive",
            "label": "Destroy unit (recursive)", "action_type": "begin_destroy_recursive", "value": path,
        })
        if has_tg:
            extra_actions.append({
                "group": "destroy", "id": "taint_unit",
                "label": "Taint unit…", "action_type": "begin_taint_unit", "value": path,
            })
        extra_actions.append({
            "group": "destroy", "id": "taint_unit_recursive",
            "label": "Taint unit (recursive)…", "action_type": "begin_taint_recursive", "value": path,
        })
        actions = extra_actions + injected + actions
        group_labels = {
            "build":     "Build",
            "edit":      "Refactor",
            "status":    "Status",
            "debug":     "Debug",
            "destroy":   "Destroy",
            "shell":     "Shell",
            "provider":  "Provider UI",
            "unit":      "Terragrunt Unit",
            "misc":      "Misc",
        }
        rows: list[dict] = []
        seen_groups: list[str] = []
        for action in actions:
            g = action["group"]
            if g not in seen_groups:
                seen_groups.append(g)
                if rows:
                    rows.append({"row_type": "separator", "group": g,
                                 "label": "", "id": "", "action_type": "", "value": ""})
                rows.append({"row_type": "group_label", "group": g,
                             "label": group_labels.get(g, g.title()),
                             "id": "", "action_type": "", "value": ""})
            rows.append({"row_type": "item", "group": g,
                         "id": action["id"], "label": action["label"],
                         "action_type": action["action_type"], "value": action["value"]})
        self.ctx_menu_rows = rows

    def _open_url_in_profile(self, url: str, auth: dict | None, profile_id: str):
        """Internal: launch a URL in the given browser profile.

        Handles playwright, pycharm, default, named Chrome profile, and
        "none"/"" (falls back to xdg-open / webbrowser).
        """
        import subprocess as _sp
        if profile_id == "playwright":
            _launcher = str(Path(__file__).parent / "playwright_launcher.py")
            _env = {**os.environ, "PL_URL": url}
            if auth:
                _env["PL_SCHEME"]   = auth.get("scheme", "digest")
                _env["PL_USERNAME"] = auth["username"]
                _env["PL_PASSWORD"] = auth["password"]
                if auth.get("username_selector"):
                    _env["PL_USERNAME_SELECTOR"] = auth["username_selector"]
                if auth.get("password_selector"):
                    _env["PL_PASSWORD_SELECTOR"] = auth["password_selector"]
                if auth.get("submit_selector"):
                    _env["PL_SUBMIT_SELECTOR"]   = auth["submit_selector"]
                if auth.get("success_url_contains"):
                    _env["PL_SUCCESS_URL"]        = auth["success_url_contains"]
            _sp.Popen([sys.executable, _launcher], env=_env, start_new_session=True)
        elif profile_id == "pycharm":
            try:
                _sp.Popen(["pycharm", url], start_new_session=True)
            except Exception:
                _sp.Popen(["xdg-open", url], start_new_session=True)
        elif profile_id in ("default", "none", ""):
            try:
                _sp.Popen(["xdg-open", url], start_new_session=True)
            except Exception:
                import webbrowser as _wb
                _wb.open(url)
        else:
            # Named Chrome profile directory
            try:
                _sp.Popen(
                    ["google-chrome", f"--profile-directory={profile_id}", url],
                    start_new_session=True,
                )
            except Exception:
                import webbrowser as _wb
                _wb.open(url)

    def dispatch_url_with_profile(self, value: str, profile_id: str):
        """Open a URL action value in the explicitly chosen browser profile.

        Called from the per-action browser-picker dropdown. Ignores self.browser_profile.
        """
        import json as _json
        _url = value
        _auth = None
        try:
            _payload = _json.loads(value)
            if isinstance(_payload, dict) and "url" in _payload and "auth" in _payload:
                _url = _payload["url"]
                _auth = _payload["auth"]
        except (ValueError, TypeError):
            pass
        self._open_url_in_profile(_url, _auth, profile_id)

    def dispatch_action(self, action_type: str, value: str):
        """Execute a node action: open URL in external browser, shell, SSH, clipboard."""
        import json as _json
        if action_type == "url":
            # Decode auth payload produced by _get_node_actions for actions with auth blocks
            _url = value
            _auth = None
            try:
                _payload = _json.loads(value)
                if isinstance(_payload, dict) and "url" in _payload and "auth" in _payload:
                    _url = _payload["url"]
                    _auth = _payload["auth"]
            except (ValueError, TypeError):
                pass
            self._open_url_in_profile(_url, _auth, self.browser_profile)
        elif action_type == "clipboard":
            yield rx.call_script(
                f"navigator.clipboard.writeText({_json.dumps(value)})"
            )
        elif action_type == "expand_collapse":
            yield from self.click_node(self.ctx_menu_path)
        elif action_type == "shell":
            yield from self.open_shell(value)
        elif action_type == "ssh":
            data = _json.loads(value)
            yield from self.open_ssh_terminal(data["cwd"], data["cmd"])
        elif action_type == "begin_refactor":
            return self.begin_refactor(value)
        elif action_type == "begin_refactor_move":
            return self.begin_refactor(value, operation="move")
        elif action_type == "begin_refactor_copy":
            return self.begin_refactor(value, operation="copy")
        elif action_type == "begin_refactor_delete":
            return self.begin_refactor(value, operation="delete")
        elif action_type == "apply_unit":
            self.apply_unit(value)
        elif action_type == "apply_recursive":
            self.apply_recursive(value)
        elif action_type == "begin_destroy_unit":
            self.begin_destroy_unit(value)
        elif action_type == "begin_destroy_recursive":
            self.begin_destroy_recursive(value)
        elif action_type == "begin_taint_unit":
            self.begin_taint_unit(value)
        elif action_type == "begin_taint_recursive":
            self.begin_taint_recursive(value)
        elif action_type == "show_inputs":
            self.show_inputs(value)
        elif action_type == "show_outputs":
            self.show_outputs(value)
        elif action_type == "begin_unlock_file":
            self.begin_unlock_file(value)
        elif action_type == "begin_unlock_file_recursive":
            self.begin_unlock_file_recursive(value)
        elif action_type == "begin_rename":
            self.begin_rename(value)
        elif action_type == "refresh_subtree_status":
            return self.refresh_subtree_status(value)

    def open_app_in_browser(self, profile_id: str):
        """Open the GUI app itself in a Chrome profile, PyCharm preview, or the default browser."""
        import subprocess as _subprocess
        vm_ip = _get_vm_ip()
        app_url = f"http://{vm_ip}:{_FRONTEND_PORT}"
        if profile_id == "pycharm":
            # Write a redirect HTML and open it in PyCharm — its built-in preview bar
            # will appear automatically for HTML files, letting the user click "Preview".
            html = (
                "<!doctype html><html><head><title>GUI Preview</title></head><body>"
                f'<script>window.location.replace("{app_url}");</script>'
                f'<p>Loading <a href="{app_url}">{app_url}</a>…</p>'
                "</body></html>"
            )
            preview_path = str(Path(os.environ.get("_GUI_DIR", "/tmp")) / "gui_preview.html")
            Path(preview_path).write_text(html)
            try:
                _subprocess.Popen(["pycharm", preview_path], start_new_session=True)
            except Exception:
                _subprocess.Popen(["xdg-open", app_url], start_new_session=True)
        elif profile_id == "default":
            try:
                _subprocess.Popen(["xdg-open", app_url], start_new_session=True)
            except Exception:
                import webbrowser as _wb
                _wb.open(app_url)
        else:
            try:
                _subprocess.Popen(
                    ["google-chrome", f"--profile-directory={profile_id}", app_url],
                    start_new_session=True,
                )
            except Exception:
                import webbrowser as _wb
                _wb.open(app_url)

    # ------------------------------------------------------------------
    # Help menu
    # ------------------------------------------------------------------

    def open_help_about(self):
        self.help_dialog_title = f"About {_APP_TITLE}"
        self.help_dialog_body  = (
            f"{_APP_TITLE}\n\n"
            "A Terragrunt lab-stack GUI built with Reflex.\n\n"
            "Manages infrastructure units, waves, config params,\n"
            "and run operations for the de3 lab stack."
        )
        self.help_dialog_open = True

    def open_help_license(self):
        self.help_dialog_title = "License"
        self.help_dialog_body  = (
            "Author: Phil.Young@Insight.com for Insight Enterprises.\n"
            "All rights reserved."
        )
        self.help_dialog_open = True

    def close_help_dialog(self):
        self.help_dialog_open = False

    def open_docs(self):
        """Load the GUI project README into the file viewer."""
        readme = Path(__file__).parent.parent / "README.md"
        if readme.exists():
            self.hcl_content   = readme.read_text(errors="replace")
            self.hcl_file_path = str(readme)
        else:
            self.hcl_content   = "No README found."
            self.hcl_file_path = ""

    def open_docs_engine(self):
        """Load the engine (lab stack runner) README into the file viewer."""
        readme = _STACK_DIR / "README.md"
        if readme.exists():
            self.hcl_content   = readme.read_text(errors="replace")
            self.hcl_file_path = str(readme)
        else:
            self.hcl_content   = "No engine README found."
            self.hcl_file_path = ""

    def open_docs_topics(self):
        """Load the engine docs/README.md (topics index) into the file viewer."""
        readme = _STACK_DIR / "docs" / "README.md"
        if readme.exists():
            self.hcl_content   = readme.read_text(errors="replace")
            self.hcl_file_path = str(readme)
        else:
            self.hcl_content   = "No topics README found."
            self.hcl_file_path = ""

    def open_docs_scripts(self):
        """Load the engine scripts/README.md into the file viewer."""
        readme = _STACK_DIR / "scripts" / "README.md"
        if readme.exists():
            self.hcl_content   = readme.read_text(errors="replace")
            self.hcl_file_path = str(readme)
        else:
            self.hcl_content   = "No scripts README found."
            self.hcl_file_path = ""



# ---------------------------------------------------------------------------
# HCL file reader — called from select_node event handler
# ---------------------------------------------------------------------------

def _build_yaml_line_paths(content: str) -> list[str]:
    """Parse YAML content and return a per-line parent-path list (dot-separated).

    For the line containing key K inside a mapping at path P, the entry is P
    (not P.K) — so searching for a key shows WHERE that key lives.
    Lines inside the key's value block get path P.K.
    Block scalars (| and >) whose content is itself valid YAML are parsed
    recursively so that nested keys (e.g. inside a cloud-init config block)
    also show their true path.
    Blank/comment/continuation lines inherit the previous key's path.
    Returns all-empty list if content is not valid YAML (e.g. HCL files).
    """
    n_lines = max(1, content.count("\n") + 1)
    events: dict[int, str] = {}  # absolute line_no → path string

    def visit(node, parent_path: str, offset: int = 0) -> None:
        if node is None:
            return
        line = node.start_mark.line + offset
        if line not in events:
            events[line] = parent_path
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode):
                    k_line = key_node.start_mark.line + offset
                    # Key line shows its containing mapping's path (the parent)
                    events[k_line] = parent_path
                    key = key_node.value
                    child = f"{parent_path}.{key}" if parent_path else key
                    visit(value_node, child, offset)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                visit(item, parent_path, offset)
        elif isinstance(node, yaml.ScalarNode):
            # For block scalars (| or >) try to recursively parse the embedded
            # content as YAML.  This handles cloud-init / heredoc patterns where
            # a multi-line YAML document is stored as a block literal.
            # content_start is the absolute line number of the first content line.
            content_start = line + 1
            if node.style in ('|', '>') and node.value and '\n' in node.value:
                try:
                    sub_root = yaml.compose(node.value)
                    if sub_root is not None and not isinstance(sub_root, yaml.ScalarNode):
                        visit(sub_root, parent_path, content_start)
                        return
                except Exception:
                    pass
            # Fallback: mark all content lines with parent_path (the scalar's
            # own path) so they don't fall back to the grandparent via fill.
            end_line = node.end_mark.line + offset
            for l in range(line + 1, end_line):
                if l not in events:
                    events[l] = parent_path

    try:
        root = yaml.compose(content)
        if root is not None:
            visit(root, "")
    except Exception:
        return [""] * n_lines

    # Forward-fill: blank lines, comments, value continuation inherit previous path
    result: list[str] = [""] * n_lines
    current = ""
    for i in range(n_lines):
        if i in events:
            current = events[i]
        result[i] = current
    return result


def _read_hcl_file(node_path: str) -> tuple[str, str]:
    """Read the unit HCL file under infra/{node_path}/; return (content, absolute_path) or ('', '').

    Uses a two-level cache:
      _hcl_path_cache    — avoids repeated _find_unit_hcl() / directory scans per node
      _hcl_content_cache — avoids re-reading the file when mtime is unchanged
    Both caches are cleared on _init_nodes_cache() (infra rescan).
    """
    if not node_path:
        return "", ""
    try:
        # Level 1: resolve abs path (cached per node_path)
        abs_path = _hcl_path_cache.get(node_path)
        if abs_path is None:
            config = _load_config()
            hcl = _find_unit_hcl(_infra_path(config) / node_path)
            abs_path = str(hcl.resolve()) if hcl else ""
            _hcl_path_cache[node_path] = abs_path
        if not abs_path:
            return "", ""
        # Level 2: return content if mtime unchanged
        p = Path(abs_path)
        try:
            mtime = p.stat().st_mtime
        except FileNotFoundError:
            # File was deleted — clear path cache entry so we re-probe next call
            _hcl_path_cache.pop(node_path, None)
            _hcl_content_cache.pop(abs_path, None)
            return "", ""
        cached = _hcl_content_cache.get(abs_path)
        if cached and cached["mtime"] == mtime:
            return cached["content"], abs_path
        content = p.read_text()
        _hcl_content_cache[abs_path] = {"mtime": mtime, "content": content}
        return content, abs_path
    except Exception:
        return "", ""


def _collect_subtree_units(folder_path: str) -> list[dict]:
    """Walk _ALL_NODES_CACHE for nodes under folder_path that have a unit HCL file.

    Returns a list of dicts with keys:
      path, relative_path, hcl_filename, hcl_content, config_block, config_provider
    """
    results: list[dict] = []
    prefix = folder_path + "/"
    for node in _ALL_NODES_CACHE:
        node_path_check = node["path"]
        # Include the root node itself (exact match) and all descendants
        if node_path_check != folder_path and not node_path_check.startswith(prefix):
            continue
        if not node.get("has_terragrunt", False):
            continue
        node_path = node["path"]
        hcl_content, hcl_abs = _read_hcl_file(node_path)
        hcl_filename = Path(hcl_abs).name if hcl_abs else "terragrunt.hcl"
        # Look up config block in _STACK_CONFIG
        cfg_block: dict = {}
        cfg_provider: str = ""
        if _STACK_CONFIG:
            cfg = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
            for prov_name, prov_data in (cfg.get("providers") or {}).items():
                if not isinstance(prov_data, dict):
                    continue
                cp = prov_data.get("config_params") or {}
                if node_path in cp and isinstance(cp[node_path], dict):
                    cfg_block = dict(cp[node_path])
                    cfg_provider = prov_name
                    break
        relative_path = node_path[len(folder_path):]
        results.append({
            "path": node_path,
            "relative_path": relative_path,
            "hcl_filename": hcl_filename,
            "hcl_content": hcl_content,
            "config_block": cfg_block,
            "config_provider": cfg_provider,
        })
    return results


def _find_unit_mgr_run() -> str | None:
    """Return the absolute path to framework/unit-mgr/run, or None if not found."""
    import subprocess as _sp
    try:
        repo_root = _sp.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return None
    candidate = Path(os.environ.get('_UNIT_MGR', ''))
    return str(candidate) if candidate and candidate.exists() else None


def _parse_unit_mgr_json(stdout: str) -> dict:
    """Extract and parse the JSON report from unit-mgr stdout (after ---JSON--- sentinel)."""
    import json as _json_mod
    sentinel = "---JSON---"
    idx = stdout.find(sentinel)
    if idx == -1:
        return {}
    try:
        return _json_mod.loads(stdout[idx + len(sentinel):].strip()) or {}
    except Exception:
        return {}


def _read_hcl_file_for_merged(merged_path: str, provider: str) -> tuple[str, str]:
    """Read terragrunt.hcl for a merged-mode node + provider.

    Reconstructs the full provider-inclusive path:
      example-pkg/example-lab  +  proxmox  →  example-pkg/_stack/proxmox/example-lab
    """
    if not merged_path or not provider:
        return "", ""
    parts = merged_path.split("/")
    full_path = "/".join([parts[0], "_stack", provider] + parts[1:])
    return _read_hcl_file(full_path)


def _get_hcl_providers_for_merged(merged_path: str) -> list[str]:
    """Return provider names that have a terragrunt.hcl under infra/<pkg>/_stack/<provider>/<rel-path>/.

    Scans the provider sub-directories of the _stack directory rather than
    relying on config_params, so the list reflects what is actually on disk.
    """
    if not merged_path:
        return []
    try:
        config = _load_config()
        infra = _infra_path(config)
        parts = merged_path.split("/")
        pkg = parts[0]
        rel = parts[1:]
        stack_dir = infra / pkg / "_stack"
        if not stack_dir.is_dir():
            return []
        result = []
        for provider_dir in sorted(stack_dir.iterdir()):
            if not provider_dir.is_dir() or provider_dir.name.startswith("."):
                continue
            candidate_dir = provider_dir.joinpath(*rel) if rel else provider_dir
            if _find_unit_hcl(candidate_dir):
                result.append(provider_dir.name)
        return result
    except Exception:
        return []

_INVENTORY_HOSTS_CACHE: dict[str, dict] | None = None
_INVENTORY_REFRESH_DONE: bool = False      # run at most once per process lifetime
_INVENTORY_REFRESH_COMPLETE: bool = False  # set True after the refresh script exits

# Local state watcher — polls .terragrunt-cache for recently-changed terraform.tfstate files.
_LOCAL_STATE_WATCHER_RUNNING: bool = False          # process-level singleton guard
_LOCAL_STATE_WATCHER_ACCELERATE_UNTIL: float = 0.0 # time.time() deadline for fast-poll mode
_LOCAL_STATE_WATCHER_FOCUS_PATHS: list[str] = []   # unit paths targeted by the most recent apply
_UNIT_STATE_YAML_MTIME: float = 0.0                # mtime of unit-state.yaml at last auto-refresh read
_UNIT_STATE_LAST_AUTO_REFRESH: float = 0.0         # time.time() of the last interval-based auto-refresh


def _run_inventory_refresh(*, background: bool = True) -> Optional[str]:
    """Run the configured inventory-refresh script, then bust the hosts cache.

    When background=True the script is launched as a detached subprocess and
    control returns immediately; the cache is invalidated only after it exits.
    When background=False the call blocks until the script finishes and returns
    None on success or an error string on failure.
    """
    global _INVENTORY_HOSTS_CACHE, _INVENTORY_REFRESH_DONE, _INVENTORY_REFRESH_COMPLETE
    try:
        config = _load_config()
        refresh_cfg = config.get("config", {}).get("ansible_inventory_refresh", {})
        if not refresh_cfg.get("enabled", False):
            _INVENTORY_REFRESH_COMPLETE = True  # no refresh configured; unblock signal_inventory_ready
            return None
        script_rel = refresh_cfg.get("script", "").strip()
        if not script_rel:
            _INVENTORY_REFRESH_COMPLETE = True
            return None
        candidate = Path(script_rel)
        if not candidate.is_absolute():
            candidate = (_STACK_DIR / script_rel).resolve()
        if not candidate.exists():
            msg = f"script not found: {candidate}"
            _gui_log(f"[inventory_refresh] {msg}")
            _INVENTORY_REFRESH_COMPLETE = True
            return msg
        extra_args = refresh_cfg.get("args", [])
        if isinstance(extra_args, str):
            extra_args = extra_args.split()
        cmd = [str(candidate)] + list(extra_args)
        _gui_log(f"[inventory_refresh] running {' '.join(cmd)}")

        error_holder: list[str] = []

        def _run() -> None:
            global _INVENTORY_HOSTS_CACHE, _INVENTORY_REFRESH_COMPLETE
            try:
                result = subprocess.run(
                    cmd,
                    cwd=str(candidate.parent),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    _gui_log("[inventory_refresh] completed successfully")
                else:
                    msg = f"exit {result.returncode}: {result.stderr[:200]}"
                    _gui_log(f"[inventory_refresh] {msg}")
                    error_holder.append(msg)
            except Exception as exc:
                msg = str(exc)
                _gui_log(f"[inventory_refresh] error: {msg}")
                error_holder.append(msg)
            finally:
                global _INVENTORY_REFRESH_COMPLETE
                _INVENTORY_HOSTS_CACHE = None   # bust cache so next use re-reads the file
                _INVENTORY_REFRESH_COMPLETE = True

        if background:
            import threading as _threading
            _threading.Thread(target=_run, daemon=True).start()
            return None
        else:
            _run()
            return error_holder[0] if error_holder else None
    except Exception as exc:
        msg = str(exc)
        _gui_log(f"[inventory_refresh] unexpected error: {msg}")
        return msg


def _print_ready() -> None:
    """Print startup summary, then run inventory refresh in the background.

    Prints a second 'Ready' line when the inventory refresh completes (or is
    skipped/disabled) — that second line is the signal that the app is fully
    initialised and safe to open in the browser.
    """
    import threading as _threading

    n_infra     = len(_ALL_NODES_CACHE)
    n_modules   = len(_MODULES_NODES_CACHE)
    n_packages  = len(_PACKAGES_CACHE)
    _gui_log(
        f"[homelab_gui] Infra loaded — {n_infra} nodes, "
        f"{n_modules} modules, {n_packages} packages. "
        f"Running inventory refresh…"
    )

    def _bg() -> None:
        global _INVENTORY_REFRESH_DONE
        _INVENTORY_REFRESH_DONE = True          # prevent on_load from re-running it
        _run_inventory_refresh(background=False)  # blocks until script exits
        _gui_log("[homelab_gui] Ready — open the app in your browser.")

    _threading.Thread(target=_bg, daemon=True).start()


_print_ready()


def _flatten_inventory_group(node: dict, out: dict[str, dict]) -> None:
    """Recursively collect all hosts from an Ansible inventory group node."""
    if not isinstance(node, dict):
        return
    for host, hvars in (node.get("hosts") or {}).items():
        out[host] = hvars or {}
    for key, child in node.items():
        if key != "hosts":
            _flatten_inventory_group(child, out)


def _load_inventory_hosts() -> dict[str, dict]:
    """Load and cache the Ansible inventory, returning a flat {hostname: vars} dict.

    Only caches on success; leaves _INVENTORY_HOSTS_CACHE as None on failure so
    that subsequent calls retry (e.g. after the inventory file is generated).
    """
    global _INVENTORY_HOSTS_CACHE
    if _INVENTORY_HOSTS_CACHE is not None:
        return _INVENTORY_HOSTS_CACHE
    try:
        content, _ = _read_inventory_file()
        if not content:
            return {}  # don't cache — file may not exist yet
        raw = yaml.safe_load(content) or {}
        hosts: dict[str, dict] = {}
        _flatten_inventory_group(raw.get("all", {}), hosts)
        _INVENTORY_HOSTS_CACHE = hosts
    except Exception:
        return {}  # don't cache — transient error
    return _INVENTORY_HOSTS_CACHE or {}


def _build_role_maps() -> tuple[list[str], dict]:
    """Build (sorted_role_tags, {node_path: [role_tags]}) from the stack config.

    Primary source: _PATH_TO_ROLES_CACHE built from config_params additional_tags.
    This covers all nodes regardless of whether they have been Ansible-provisioned.
    Supplement: Ansible inventory additional_tags (for hosts present in inventory
    but not yet in the stack config), keyed by last path-segment name as fallback.
    """
    path_roles: dict[str, list[str]] = dict(_PATH_TO_ROLES_CACHE)
    role_set: set[str] = set()
    for roles in path_roles.values():
        role_set.update(roles)

    # Supplement with Ansible inventory roles (for any host not already covered).
    # Inventory is keyed by hostname; match against node last-segment names.
    hosts = _load_inventory_hosts()
    path_names = {p.split("/")[-1]: p for p in {n["path"] for n in _ALL_NODES_CACHE}}
    for hostname, hvars in hosts.items():
        if not isinstance(hvars, dict):
            continue
        tags = hvars.get("additional_tags") or []
        inv_roles = [t for t in tags if isinstance(t, str) and t.startswith("role_")]
        if not inv_roles:
            continue
        role_set.update(inv_roles)
        full_path = path_names.get(hostname)
        if full_path and full_path not in path_roles:
            path_roles[full_path] = inv_roles

    return sorted(role_set), path_roles


def _build_kube_shell_cmd(cluster_name: str) -> str:
    """Return the initial_cmd string for opening a kube shell for the given cluster.

    Sources the repo-level set_env.sh to ensure $_DYNAMIC_DIR is set,
    then exports KUBECONFIG and runs `kubectl get nodes`.
    """
    set_env = "$(git rev-parse --show-toplevel)/set_env.sh"
    kubeconfig = f"$_DYNAMIC_DIR/kubeconfig/{cluster_name}_kubeconfig.yaml"
    return (
        f"source {set_env}"
        f" && export KUBECONFIG={kubeconfig}"
        f" && kubectl get nodes"
    )


def _get_ssh_command(node_path: str) -> str:
    """Return an SSH command for the node using the Ansible inventory, or '' if not found.

    Matching strategy:
      1. Exact match on last path segment (e.g. pve-1 → pve-1).
      2. Prefix match — inventory host name starts with the node name
         (e.g. test-ubuntu-vm-1 → test-ubuntu-vm-1-pve, test-ubuntu-vm-1-pve-2).
      3. When multiple prefix matches exist, use node_name from each host's vars
         to pick the one whose node_name appears in the tree path segments.

    SSH command includes ansible_ssh_common_args, ansible_port,
    and ansible_ssh_private_key_file when present in the inventory.
    """
    hosts = _load_inventory_hosts()
    if not hosts:
        return ""

    node_name = node_path.split("/")[-1]

    # 1. Exact match
    host_vars: dict | None = hosts.get(node_name)

    # 2. Prefix matches
    if host_vars is None:
        matches = {n: v for n, v in hosts.items() if n.startswith(node_name)}
        if len(matches) == 1:
            host_vars = next(iter(matches.values()))
        elif len(matches) > 1:
            # Disambiguate: prefer the host whose node_name var appears in the path
            path_parts = set(node_path.split("/"))
            for h_vars in matches.values():
                nv = str(h_vars.get("node_name", ""))
                if nv and nv in path_parts:
                    host_vars = h_vars
                    break
            # Best effort fallback — take first match
            if host_vars is None:
                host_vars = next(iter(matches.values()))

    if not host_vars:
        return ""

    ansible_host = host_vars.get("ansible_host", "")
    if not ansible_host:
        return ""

    ansible_user  = str(host_vars.get("ansible_user", "")).strip()
    ansible_port  = host_vars.get("ansible_port")
    ssh_args      = str(host_vars.get("ansible_ssh_common_args", "")).strip()
    key_file      = str(host_vars.get("ansible_ssh_private_key_file", "")).strip()

    parts = ["ssh", "-t",   # -t: force remote PTY so interactive apps (emacs, vim, …) work
             "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null",
             "-o", "LogLevel=ERROR"]   # suppress known-hosts warnings (e.g. "key not known by any other names")
    if ssh_args:
        parts.append(ssh_args)
    if ansible_port and str(ansible_port) not in ("", "22"):
        parts += ["-p", str(ansible_port)]
    if key_file:
        parts += ["-i", key_file]
    target = f"{ansible_user}@{ansible_host}" if ansible_user else ansible_host
    parts.append(target)

    return " ".join(parts)


def _get_browser_url_for_node(node_path: str, is_merged: bool = False) -> str:
    """Return the most-specific _browser_url config param for node_path, or ''.

    Walks config_params across all providers, collects all ancestor matches,
    and returns the value from the most-specific (longest) matching key.

    Supports inventory-var tokens in the URL using Python .format() syntax,
    e.g. ``_browser_url: "https://{ansible_host}"`` resolves {ansible_host}
    from the Ansible inventory (same matching logic as _get_ssh_command).
    Other inventory vars such as {ansible_port} or {proxmox_api_port} also work.
    """
    if not node_path or not _STACK_CONFIG:
        return ""
    cfg = _STACK_CONFIG.get(_STACK_CONFIG_KEY, {})
    providers = cfg.get("providers", {}) or {}
    best_key_len = -1
    best_url = ""
    for provider_name, provider_data in providers.items():
        if not isinstance(provider_data, dict):
            continue
        config_params = provider_data.get("config_params") or {}
        if is_merged:
            parts = node_path.split("/")
            # Merged paths strip "_stack" + provider; full path = <pkg>/_stack/<provider>/<rest>
            lookup_path = "/".join([parts[0], "_stack", provider_name] + parts[1:]) if parts else node_path
        else:
            lookup_path = node_path
        for key, params in config_params.items():
            if not isinstance(params, dict):
                continue
            if lookup_path != key and not lookup_path.startswith(key + "/"):
                continue
            url = params.get("_browser_url", "")
            if url and len(key) > best_key_len:
                best_key_len = len(key)
                best_url = str(url).strip()

    # Resolve inventory-var tokens, e.g. {ansible_host}
    if best_url and "{" in best_url:
        node_name = node_path.split("/")[-1]
        hosts = _load_inventory_hosts()
        inv_vars: dict = hosts.get(node_name) or {}
        if not inv_vars:
            matches = {n: v for n, v in hosts.items() if n.startswith(node_name)}
            if len(matches) == 1:
                inv_vars = next(iter(matches.values()))
        if inv_vars:
            try:
                best_url = best_url.format(**inv_vars)
            except (KeyError, ValueError):
                pass

    return best_url


def _read_inventory_file() -> tuple[str, str]:
    """Read the ansible inventory file.

    Resolution order:
    1. Explicit override: ``ansible_inventory_path`` in de3-gui-pkg.yaml
       (relative paths resolved against ``_STACK_DIR``).
    2. Framework default: ``framework.ansible_inventory.output_file`` from
       ``config/framework.yaml``.  Relative paths are anchored to
       ``$_DYNAMIC_DIR`` (same logic as ``generate_ansible_inventory.py``);
       falls back to ``_STACK_DIR`` when ``_DYNAMIC_DIR`` is unset.

    Returns (content, absolute_path) or ('', '') if not found.
    """
    try:
        config = _load_config()
        explicit = (config.get("config") or {}).get("ansible_inventory_path") or ""
        if explicit:
            candidate = Path(explicit)
            if not candidate.is_absolute():
                candidate = (_STACK_DIR / explicit).resolve()
        else:
            # Fall back to framework.yaml: framework.ansible_inventory.output_file
            ansible_inv = (
                (_STACK_CONFIG.get(_STACK_CONFIG_KEY) or {}).get("ansible_inventory") or {}
            )
            output_file = ansible_inv.get("output_file") or ""
            if not output_file:
                return "", ""
            candidate = Path(output_file)
            if not candidate.is_absolute():
                dynamic_dir = os.environ.get("_DYNAMIC_DIR", "")
                base = Path(dynamic_dir) if dynamic_dir else _STACK_DIR
                candidate = (base / output_file).resolve()
        if candidate.exists():
            return candidate.read_text(), str(candidate)
        return "", ""
    except Exception:
        return "", ""


_stack_config_file_cache: dict = {
    "path": None,    # resolved Path (cached after first successful find)
    "mtime": 0.0,    # mtime of last read
    "content": "",   # file text
    "str_path": "",  # str(path) for the return value
}


def _read_stack_config_file() -> tuple[str, str]:
    """Read the stack config file, returning cached content when mtime is unchanged.

    Caches the resolved path after the first find (avoids repeated git subprocess
    calls on every node click).  Re-reads from disk only when the file's mtime changes.
    Returns (content, absolute_path) or ('', '') if not found.
    """
    global _stack_config_file_cache
    try:
        path: "Path | None" = _stack_config_file_cache["path"]
        if path is None:
            path = _find_stack_config()
            _stack_config_file_cache["path"] = path
        if not path or not path.exists():
            _stack_config_file_cache["path"] = None  # re-probe on next call
            return "", ""
        mtime = path.stat().st_mtime
        if mtime == _stack_config_file_cache["mtime"]:
            return _stack_config_file_cache["content"], _stack_config_file_cache["str_path"]
        content = path.read_text()
        _stack_config_file_cache.update(mtime=mtime, content=content, str_path=str(path))
        return content, str(path)
    except Exception:
        return "", ""


def _find_config_scroll_line(content: str, node_path: str) -> int:
    """Return the 0-based line number of the best match for node_path in content.

    Tries the full path first, then progressively shorter prefixes (parent dirs),
    so a node with no exact entry still scrolls to its nearest ancestor block.
    Returns -1 if nothing matches.
    """
    if not content or not node_path:
        return -1
    parts = node_path.split("/")
    lines = content.splitlines()
    for depth in range(len(parts), 0, -1):
        prefix = "/".join(parts[:depth])
        for i, line in enumerate(lines):
            if prefix in line:
                return i
    return -1


def _apply_color_mode_js(theme: str) -> str:
    """Return JS that applies a color mode ('light'|'dark') via next-themes + DOM."""
    radix_mode = "light" if theme == "light" else "dark"
    return (
        f"(function(){{"
        f"var t={repr(theme)};"
        f"var rm={repr(radix_mode)};"
        f"localStorage.setItem('theme',rm);"
        f"document.documentElement.classList.remove('light','dark');"
        f"document.documentElement.classList.add(t);"
        f"var r=document.querySelector('.radix-themes[data-is-root-theme=\"true\"]');"
        f"if(r){{r.classList.remove('light','dark');r.classList.add(rm);}}"
        f"}})()"
    )


_CLEAR_CRUMB_JS = "var _c=document.getElementById('yaml-breadcrumb');if(_c)_c.textContent='';"


def _markdown_link_interceptor_js() -> str:
    """Install a document-level click handler for links inside #file-viewer-markdown.

    - Relative/local paths  → prevented from navigating the page; resolved against the
      directory of the currently-viewed file (read from #hcl-file-path-src) and sent
      to Reflex via the hidden #markdown-link-input element.
    - http/https URLs       → prevented from navigating the main page; opened in a new tab.
    - #anchor / mailto: etc → default browser behaviour (scroll / mail client).

    Safe to call multiple times (removes the previous listener first).
    """
    return r"""(function(){
if(window._mdLinkHandler){
  document.removeEventListener('click',window._mdLinkHandler,true);
}
window._mdLinkHandler=function(e){
  var a=e.target.closest('a');
  if(!a)return;
  var md=document.getElementById('file-viewer-markdown');
  if(!md||!md.contains(a))return;
  var href=a.getAttribute('href');
  if(!href)return;
  // Anchor-only links (#section): let the browser scroll within the page
  if(href.charAt(0)==='#')return;
  // mailto: and other non-http schemes: leave alone
  if(/^[a-zA-Z][a-zA-Z0-9+\-.]*:/.test(href)&&!/^https?:/.test(href))return;
  e.preventDefault();
  e.stopPropagation();
  // External http/https: open in new tab
  if(/^https?:/.test(href)){window.open(href,'_blank');return;}
  // Relative path: resolve against directory of the currently-viewed file
  var basePath=(document.getElementById('hcl-file-path-src')||{}).textContent||'';
  if(!basePath)return;
  var dir=basePath.substring(0,basePath.lastIndexOf('/')+1);
  var resolved;
  try{resolved=new URL(href,'file://'+dir).pathname;}catch(ex){return;}
  // Send resolved path to Reflex via hidden input (React native-setter trick)
  var inp=document.getElementById('markdown-link-input');
  if(!inp)return;
  var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  setter.call(inp,resolved);
  inp.dispatchEvent(new Event('input',{bubbles:true}));
};
document.addEventListener('click',window._mdLinkHandler,true);
})();"""


def _yaml_breadcrumb_install_js() -> str:
    """Install selection listener on the file-viewer-pre container.

    Breadcrumb shows the YAML path when:
      - the user selects text inside the file viewer (mouseup), OR
      - search navigation calls window._yamlCrumbUpdateFromMark(markEl).

    Once set, the path STAYS until explicitly replaced — it does NOT clear on
    selectionchange/empty-selection (avoids flicker when search-mark DOM mutations
    fire selectionchange with no active selection).

    Style matches the filename bar: var(--gui-text-muted) on var(--gui-panel-bg).
    No dynamic colour changes — the bar always looks the same as the path bar above.

    Safe to call multiple times.
    """
    return r"""(function(){
// All DOM lookups are lazy (called at event time) so this installs correctly
// even when #file-viewer-pre does not yet exist (e.g. hcl_content still empty).

// --- clean up previous listener ---
if(window._yamlCrumbMouseupFn){
  document.removeEventListener('mouseup',window._yamlCrumbMouseupFn);
}

function lineSpanOf(node,pre){
  if(!node||!pre)return null;
  var cur=(node.nodeType===3)?node.parentElement:node;
  while(cur&&cur.parentElement!==pre)cur=cur.parentElement;
  return (cur&&cur.parentElement===pre)?cur:null;
}

function setCrumb(path){
  var crumb=document.getElementById('yaml-breadcrumb');
  if(crumb)crumb.textContent=path||'';
}

// Called by search JS after navigation — pins the path for the active match.
window._yamlCrumbUpdateFromMark=function(mark){
  if(!mark)return;
  var pre=document.getElementById('file-viewer-pre');
  var span=lineSpanOf(mark,pre);
  setCrumb(span?(span.dataset.yamlPath||''):'');
};

function getSelectionPath(){
  var pre=document.getElementById('file-viewer-pre');
  if(!pre)return null;
  var sel=window.getSelection();
  if(!sel||sel.isCollapsed||!sel.rangeCount)return null;
  var range=sel.getRangeAt(0);
  if(!pre.contains(range.commonAncestorContainer))return null;
  var span=lineSpanOf(range.startContainer,pre)||lineSpanOf(range.endContainer,pre);
  return span?(span.dataset.yamlPath||null):null;
}

// mouseup: only update breadcrumb when user finishes a selection inside pre.
// Never clears the path — stays until next selection or search navigation.
var mouseupFn=function(){
  setTimeout(function(){
    var path=getSelectionPath();
    if(path!==null)setCrumb(path);
  },80);
};
window._yamlCrumbMouseupFn=mouseupFn;
document.addEventListener('mouseup',mouseupFn);
})();"""


def _file_viewer_scroll_js(line_idx: int) -> str:
    """Return JS that scrolls the file-viewer-pre container to line_idx (0-based)."""
    if line_idx < 0:
        return ""
    return (
        f"(function(){{"
        f"var pre=document.getElementById('file-viewer-pre');"
        f"if(!pre)return;"
        f"var spans=pre.children;"
        f"var idx={line_idx};"
        f"if(idx>=0&&idx<spans.length){{"
        f"var el=spans[idx];"
        f"var c=pre.parentElement;"
        f"while(c&&c.scrollHeight<=c.clientHeight)c=c.parentElement;"
        f"if(c)c.scrollTop=Math.max(0,el.offsetTop-60);"
        f"}}}})();"
    )


def _pre_search_js(query: str, direction: str, smooth: bool = False,
                   element_id: str = "file-viewer-pre",
                   case_sensitive: bool = False) -> str:
    """JS to highlight and navigate text matches in a read-only file viewer element.

    direction: 'init' (first match), 'next', or 'prev'.
    Marks are injected as <mark data-fs> elements; current match gets a brighter colour.
    All marks are cleared and rebuilt whenever the query or case_sensitive flag changes.
    element_id: DOM id of the container to search ('file-viewer-pre' or 'file-viewer-ansi').
    case_sensitive: when True comparison is exact; when False both sides are lowercased.
    """
    q_esc = query.replace("\\", "\\\\").replace("'", "\\'")
    scroll_behavior = "smooth" if smooth else "instant"
    cs_flag = "true" if case_sensitive else "false"
    return f"""(function(q,dir,cs){{
var pre=document.getElementById('{element_id}');
if(!pre)return;
var qn=cs?q:(q?q.toLowerCase():'');
var cacheKey=qn+'\\x00'+(cs?'1':'0');
if(pre.dataset.searchQ!==cacheKey){{
  pre.dataset.searchQ=cacheKey;
  pre.querySelectorAll('mark[data-fs]').forEach(function(m){{m.replaceWith(document.createTextNode(m.textContent));}});
  pre.normalize();
  if(!qn){{pre._fsIdx=-1;return;}}
  var walker=document.createTreeWalker(pre,NodeFilter.SHOW_TEXT,null,false);
  var nodes=[];var n;
  while(n=walker.nextNode())nodes.push(n);
  nodes.forEach(function(tn){{
    var txt=tn.textContent;var tl=cs?txt:txt.toLowerCase();
    if(tl.indexOf(qn)<0)return;
    var frag=document.createDocumentFragment();var last=0,idx;
    while((idx=tl.indexOf(qn,last))>=0){{
      if(idx>last)frag.appendChild(document.createTextNode(txt.slice(last,idx)));
      var m=document.createElement('mark');
      m.setAttribute('data-fs','');
      m.style.cssText='background:#ffd54f;color:#000;border-radius:2px;';
      m.textContent=txt.slice(idx,idx+q.length);
      frag.appendChild(m);last=idx+qn.length;
    }}
    if(last<txt.length)frag.appendChild(document.createTextNode(txt.slice(last)));
    tn.replaceWith(frag);
  }});
  pre._fsIdx=-1;
}}
var marks=Array.from(pre.querySelectorAll('mark[data-fs]'));
if(!marks.length)return;
marks.forEach(function(m){{m.style.background='#ffd54f';m.style.color='#000';}});
var idx=(typeof pre._fsIdx==='number'?pre._fsIdx:-1);
if(dir==='last')idx=marks.length-1;
else if(dir==='next'||dir==='init')idx=(idx+1)%marks.length;
else if(dir==='prev')idx=(idx-1+marks.length)%marks.length;
pre._fsIdx=idx;
marks[idx].style.background='#e65100';marks[idx].style.color='#fff';
marks[idx].scrollIntoView({{block:'center',behavior:'{scroll_behavior}'}});
if(window._yamlCrumbUpdateFromMark)window._yamlCrumbUpdateFromMark(marks[idx]);
return marks.length;
}})('{q_esc}','{direction}',{cs_flag});"""


def _pre_search_clear_js(element_id: str = "file-viewer-pre") -> str:
    """JS to remove all search highlights from a read-only file viewer element. Returns 0."""
    return (f"(function(){{var pre=document.getElementById('{element_id}');"
            "if(!pre)return 0;"
            "pre.querySelectorAll('mark[data-fs]').forEach(function(m){"
            "m.replaceWith(document.createTextNode(m.textContent));});"
            "pre.normalize();pre.dataset.searchQ='';pre._fsIdx=-1;return 0;})();")


def _read_pre_top_line_js() -> str:
    """Return JS that reads the 1-based index of the first visible line in #file-viewer-pre.
    Uses getBoundingClientRect() so measurements are in viewport coordinates, avoiding the
    offsetTop-vs-scrollTop origin mismatch when intermediate positioned elements exist."""
    return r"""(function(){
var pre=document.getElementById('file-viewer-pre');
if(!pre)return 1;
var cont=pre.parentElement;
while(cont&&getComputedStyle(cont).overflowY==='visible')cont=cont.parentElement;
if(!cont)return 1;
var contTop=cont.getBoundingClientRect().top;
var spans=pre.children;
for(var i=0;i<spans.length;i++){
  if(spans[i].getBoundingClientRect().bottom>contTop)return i+1;
}
return 1;
})()"""


def _monaco_reveal_line_js(line: int) -> str:
    """Return JS that reveals the given 1-based line in the Monaco editor.
    Retries every 60ms until Monaco is mounted and ready."""
    return (
        f"(function(ln){{"
        f"function r(){{"
        f"if(typeof monaco==='undefined'||!monaco.editor.getEditors().length)"
        f"{{setTimeout(r,60);return;}}"
        f"var e=monaco.editor.getEditors()[0];"
        f"e.setScrollPosition({{scrollTop:e.getTopForLineNumber(ln)}},1);"
        f"}}r();"
        f"}})({line})"
    )


def _monaco_search_js(query: str, direction: str, smooth: bool = False, case_sensitive: bool = False) -> str:
    """JS to search/navigate in the active Monaco editor instance.

    Uses model.findMatches() + setSelection/revealRangeInCenter for reliable navigation
    without requiring the find widget to be open.
    direction: 'init' or 'next' → first match after cursor; 'prev' → last match before cursor.
    Monaco ScrollType: 0=Smooth, 1=Immediate.
    """
    q_esc = query.replace("\\", "\\\\").replace("'", "\\'")
    scroll_type = "0" if smooth else "1"
    cs_js = "true" if case_sensitive else "false"
    return f"""(function(q,dir){{
if(typeof monaco==='undefined')return;
var editors=monaco.editor.getEditors();
if(!editors||!editors.length)return;
var editor=editors[0];
var model=editor.getModel();
if(!model||!q)return;
var matches=model.findMatches(q,true,false,{cs_js},null,false);
if(!matches.length)return;
var pos=editor.getPosition();
var idx=-1,i,r;
if(dir==='last'){{
  idx=matches.length-1;
}}else if(dir==='prev'){{
  for(i=matches.length-1;i>=0;i--){{
    r=matches[i].range;
    if(r.startLineNumber<pos.lineNumber||(r.startLineNumber===pos.lineNumber&&r.startColumn<pos.column)){{idx=i;break;}}
  }}
  if(idx<0)idx=matches.length-1;
}}else{{
  for(i=0;i<matches.length;i++){{
    r=matches[i].range;
    if(r.startLineNumber>pos.lineNumber||(r.startLineNumber===pos.lineNumber&&r.startColumn>pos.column)){{idx=i;break;}}
  }}
  if(idx<0)idx=0;
}}
editor.setSelection(matches[idx].range);
editor.revealRangeInCenter(matches[idx].range,{scroll_type});
return matches.length;
}})('{q_esc}','{direction}');"""


def _config_data_node_search_js(raw_path: str, provider: str, quoted: bool, smooth: bool = False) -> str:
    """JS to search config-data pre for a node path, anchored to the provider section.

    Builds marks for the search string (optionally double-quoted to match YAML key syntax),
    then finds the providers/<provider> anchor in the DOM and navigates to the first
    mark that appears after that anchor using Range.compareBoundaryPoints.
    """
    path_esc = raw_path.replace("\\", "\\\\").replace("'", "\\'")
    prov_esc = provider.replace("\\", "\\\\").replace("'", "\\'")
    quoted_js = "true" if quoted else "false"
    scroll_behavior = "smooth" if smooth else "instant"
    return f"""(function(rawPath,provider,quoted){{
var pre=document.getElementById('file-viewer-pre');
if(!pre)return;
var q=quoted?('"'+rawPath+'"'):rawPath;
if(!q)return;
var ql=q.toLowerCase();
// --- rebuild marks unconditionally (called once per navigation; cache check skipped
//     because React re-renders destroy marks while preserving pre.dataset.searchQ) ---
pre.dataset.searchQ='';
pre.querySelectorAll('mark[data-fs]').forEach(function(m){{m.replaceWith(document.createTextNode(m.textContent));}});
pre.normalize();
var walker=document.createTreeWalker(pre,NodeFilter.SHOW_TEXT,null,false);
var nodes=[];var n;
while(n=walker.nextNode())nodes.push(n);
nodes.forEach(function(tn){{
  var txt=tn.textContent;var tl=txt.toLowerCase();
  if(tl.indexOf(ql)<0)return;
  var frag=document.createDocumentFragment();var last=0,idx;
  while((idx=tl.indexOf(ql,last))>=0){{
    if(idx>last)frag.appendChild(document.createTextNode(txt.slice(last,idx)));
    var m=document.createElement('mark');
    m.setAttribute('data-fs','');
    m.style.cssText='background:#ffd54f;color:#000;border-radius:2px;';
    m.textContent=txt.slice(idx,idx+q.length);
    frag.appendChild(m);last=idx+ql.length;
  }}
  if(last<txt.length)frag.appendChild(document.createTextNode(txt.slice(last)));
  tn.replaceWith(frag);
}});
pre._fsIdx=-1;
var marks=Array.from(pre.querySelectorAll('mark[data-fs]'));
if(!marks.length)return;
// reset all mark colours
marks.forEach(function(m){{m.style.background='#ffd54f';m.style.color='#000';}});
// --- find provider anchor ---
var anchorRange=null;
var anchorText='providers/'+provider;
var walker2=document.createTreeWalker(pre,NodeFilter.SHOW_TEXT,null,false);
var tn2;
while((tn2=walker2.nextNode())){{
  var aPos=tn2.nodeValue.toLowerCase().indexOf(anchorText.toLowerCase());
  if(aPos!==-1){{
    anchorRange=document.createRange();
    anchorRange.setStart(tn2,aPos+anchorText.length);
    anchorRange.setEnd(tn2,aPos+anchorText.length);
    break;
  }}
}}
// --- find first mark after anchor ---
var target=null;
if(anchorRange){{
  for(var i=0;i<marks.length;i++){{
    var mRange=document.createRange();
    mRange.setStart(marks[i],0);
    mRange.setEnd(marks[i],0);
    try{{
      // START_TO_START: anchorRange.start vs mRange.start; <=0 means anchor is before or at mark
      if(anchorRange.compareBoundaryPoints(Range.START_TO_START,mRange)<=0){{
        target=marks[i];
        pre._fsIdx=i;
        break;
      }}
    }}catch(e){{}}
  }}
}}
if(!target){{target=marks[0];pre._fsIdx=0;}}
// highlight active mark
target.style.background='#e65100';target.style.color='#fff';
target.scrollIntoView({{block:'center',behavior:'{scroll_behavior}'}});
if(window._yamlCrumbUpdateFromMark)window._yamlCrumbUpdateFromMark(target);
return marks.length;
}})( '{path_esc}', '{prov_esc}', {quoted_js});"""


# ---------------------------------------------------------------------------
# UI: unit params panel (right panel content)
# ---------------------------------------------------------------------------

def _provider_header_row(item: dict) -> rx.Component:
    """Bold coloured bar for a provider section."""
    return rx.box(
        rx.hstack(
            rx.box(
                width="3px",
                height="18px",
                background=item["accent"],
                border_radius="2px",
                flex_shrink="0",
            ),
            rx.text(
                item["provider"],
                font_size="12px",
                font_weight="700",
                color=item["accent"],
                text_transform="uppercase",
                letter_spacing="0.08em",
            ),
            align="center",
            spacing="2",
        ),
        padding_x="12px",
        padding_y="10px",
        margin_top="8px",
        border_top="1px solid var(--gui-border)",
        background="var(--gui-panel-bg)",
        width="100%",
    )


def _source_header_row(item: dict) -> rx.Component:
    """Shows which ancestor path injected the following params."""
    label_content = rx.cond(
        item["source_path"] != "",
        rx.hstack(
            rx.text(
                item["source_label"],
                font_size="10px",
                color="var(--gui-text-dim)",
                white_space="nowrap",
                font_family="monospace",
            ),
            rx.text(
                item["source_display"],
                font_size="10px",
                color="#3b82f6",
                white_space="nowrap",
                font_family="monospace",
                text_decoration="underline",
                cursor="pointer",
                on_click=AppState.navigate_to_source(item["source_path"]),
                title="Click to select this ancestor node in the tree",
            ),
            spacing="1",
            align="center",
            padding_x="8px",
        ),
        rx.text(
            item["source_label"],
            font_size="10px",
            color="var(--gui-text-dim)",
            white_space="nowrap",
            font_family="monospace",
            padding_x="8px",
        ),
    )
    return rx.hstack(
        rx.box(height="1px", background="var(--gui-border)", flex="1"),
        label_content,
        rx.box(height="1px", background="var(--gui-border)", flex="1"),
        align="center",
        width="100%",
        padding_x="12px",
        padding_y="6px",
    )


def _param_kv_row(item: dict) -> rx.Component:
    """Key → value param row; overrides shown in progressively lighter green."""
    # Shade of green that fades with each successive override level:
    #   0 → normal (#1f2937)   1 → dark green   2 → medium   3+ → pale
    value_color = rx.match(
        item["override_level"],
        (0, "var(--gui-param-value)"),
        (1, "var(--gui-param-override-1)"),
        (2, "var(--gui-param-override-2)"),
        "var(--gui-param-override-3)",
    )
    # Code block background also tinted green on overrides
    block_bg = rx.match(
        item["override_level"],
        (0, "var(--gui-content-bg)"),
        (1, "var(--gui-param-block-bg-1)"),
        (2, "var(--gui-param-block-bg-2)"),
        "var(--gui-param-block-bg-3)",
    )
    block_border = rx.match(
        item["override_level"],
        (0, "1px solid var(--gui-border)"),
        (1, "1px solid #86efac"),
        (2, "1px solid #bbf7d0"),
        "1px solid #d1fae5",
    )
    return rx.hstack(
        rx.text(
            item["key"],
            font_size="12px",
            color=item["key_color"],
            font_weight=rx.cond(item["key_color"] == _REGULAR_KEY_COLOR, "400", "600"),
            min_width="160px",
            max_width="160px",
            font_family="monospace",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
            flex_shrink="0",
        ),
        rx.cond(
            item["is_multiline"],
            rx.box(
                rx.text(
                    item["value"],
                    font_size="11px",
                    color=value_color,
                    font_family="monospace",
                    white_space=rx.cond(AppState.param_wrap_values, "pre-wrap", "pre"),
                    word_break=rx.cond(AppState.param_wrap_values, "break-all", "normal"),
                ),
                background=block_bg,
                border=block_border,
                border_radius="4px",
                padding="6px 10px",
                overflow_x=rx.cond(AppState.param_wrap_values, "visible", "auto"),
                width="100%",
            ),
            rx.text(
                item["value"],
                font_size="12px",
                color=value_color,
                font_family="monospace",
                font_weight=rx.cond(item["is_override"], "500", "400"),
                flex="1",
                overflow=rx.cond(AppState.param_wrap_values, "visible", "hidden"),
                text_overflow=rx.cond(AppState.param_wrap_values, "clip", "ellipsis"),
                white_space=rx.cond(AppState.param_wrap_values, "normal", "nowrap"),
                word_break=rx.cond(AppState.param_wrap_values, "break-all", "normal"),
            ),
        ),
        align="start",
        spacing="3",
        padding_x="16px",
        padding_y="3px",
        width="100%",
        cursor="pointer",
        border_radius="4px",
        _hover={"background": "var(--gui-hover-soft)", "outline": "1px solid var(--gui-border)"},
        on_click=AppState.begin_edit_param(
            item["provider"],
            item["source_path"],
            item["key"],
            item["value"],
        ),
        title="Click to edit",
    )


def param_row(item: dict) -> rx.Component:
    """Dispatch to the correct row renderer based on row_type."""
    return rx.match(
        item["row_type"],
        ("provider_header", _provider_header_row(item)),
        ("source_header",   _source_header_row(item)),
        ("param",           _param_kv_row(item)),
        rx.box(),
    )


def _provider_tab(provider: str) -> rx.Component:
    """One tab button in the provider tab bar."""
    is_active = provider == AppState.active_provider_tab
    accent = rx.match(
        provider,
        ("gcp",     "#4285F4"),
        ("aws",     "#FF9900"),
        ("azure",   "#0078D4"),
        ("proxmox", "#E07000"),
        ("maas",    "#7C3AED"),
        ("unifi",   "#4338CA"),
        "#6B7280",
    )
    return rx.box(
        rx.text(
            provider,
            font_size="11px",
            font_weight=rx.cond(is_active, "600", "400"),
            color=rx.cond(is_active, accent, "var(--gui-text-muted)"),
            text_transform="capitalize",
        ),
        padding_x="10px",
        padding_y="5px",
        cursor="pointer",
        border_radius="6px",
        border=rx.cond(is_active, "1px solid var(--gui-border)", "1px solid transparent"),
        background=rx.cond(is_active, "var(--gui-tab-active-bg)", "transparent"),
        box_shadow=rx.cond(is_active, "0 1px 3px rgba(0,0,0,0.08)", "none"),
        _hover={"background": "var(--gui-content-bg)"},
        on_click=AppState.set_active_provider_tab(provider),
        flex_shrink="0",
        title="Filter params to show only the " + provider + " provider · click again to show all",
    )


def _provider_tab_bar() -> rx.Component:
    """Tab bar shown when the selected node has params from multiple providers."""
    return rx.cond(
        AppState.has_unit_params,
        rx.box(
            rx.hstack(
                # "All" tab
                rx.box(
                    rx.text(
                        "All",
                        font_size="11px",
                        font_weight=rx.cond(AppState.active_provider_tab == "", "600", "400"),
                        color=rx.cond(AppState.active_provider_tab == "", "var(--gui-text-primary)", "var(--gui-text-muted)"),
                    ),
                    padding_x="10px",
                    padding_y="5px",
                    cursor="pointer",
                    border_radius="6px",
                    border=rx.cond(
                        AppState.active_provider_tab == "",
                        "1px solid var(--gui-border)",
                        "1px solid transparent",
                    ),
                    background=rx.cond(AppState.active_provider_tab == "", "var(--gui-tab-active-bg)", "transparent"),
                    box_shadow=rx.cond(
                        AppState.active_provider_tab == "",
                        "0 1px 3px rgba(0,0,0,0.08)",
                        "none",
                    ),
                    _hover={"background": "var(--gui-content-bg)"},
                    on_click=AppState.set_active_provider_tab(""),
                    flex_shrink="0",
                    title="Show params from all providers",
                ),
                rx.foreach(AppState.available_provider_tabs, _provider_tab),
                spacing="1",
                align="center",
                overflow_x="auto",
                padding_x="12px",
                padding_y="6px",
            ),
            background="var(--gui-panel-bg)",
            border_bottom="1px solid var(--gui-border)",
            width="100%",
        ),
        rx.box(),
    )


def unit_params_panel() -> rx.Component:
    """Right panel: unit params for the currently selected tree node."""
    return rx.vstack(
        rx.cond(
            AppState.selected_node_path != "",
            rx.cond(
                AppState.has_unit_params,
                rx.vstack(
                    _provider_tab_bar(),
                    rx.vstack(
                        rx.foreach(AppState.selected_node_params_display, param_row),
                        spacing="0",
                        align="start",
                        width="100%",
                    ),
                    spacing="0",
                    align="start",
                    width="100%",
                ),
                rx.center(
                    rx.vstack(
                        rx.text("No config_params found for this path.", color="var(--gui-text-dim)", font_size="13px"),
                        rx.cond(
                            AppState.is_merged,
                            rx.text(
                                "In merged mode params are looked up by inserting each provider name into the path.",
                                color="#c4c9d4",
                                font_size="11px",
                                text_align="center",
                                max_width="280px",
                            ),
                            rx.box(),
                        ),
                        align="center",
                        spacing="2",
                    ),
                    padding_top="40px",
                    width="100%",
                ),
            ),
            rx.center(
                rx.text(
                    "Select a node in the tree to view its unit params.",
                    color="#c4c9d4",
                    font_size="13px",
                ),
                padding_top="40px",
                width="100%",
            ),
        ),
        spacing="0",
        align="start",
        width="100%",
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# UI: iframe-based framework views
# Each pluggable framework is an asset HTML page loaded inside an iframe.
# Data is fetched by the viewer from the /api/infra-graph endpoint.
# ---------------------------------------------------------------------------

def _iframe_view(src: str) -> rx.Component:
    """Generic full-bleed iframe wrapper for external framework viewers."""
    return rx.el.iframe(
        src=src,
        width="100%",
        height="100%",
        style={"border": "none", "display": "block"},
    )


# JavaScript callback passed to the react-cytoscapejs `cy` prop.
# Runs once after the cy instance is created.
# - Tapping a compound (parent) node collapses/expands its descendants.
# - Tapping any node signals the Reflex state via the hidden trigger div
#   (same mechanism the panel resizer uses).
_CYTOSCAPE_INIT_JS = r"""(cy) => {
  cy.on('tap', 'node', function(evt) {
    var node = evt.target;

    // ── Signal Reflex with the tapped node path ──────────────────────────
    window._cySelectedPath = node.id();
    var trigger = document.getElementById('cy-node-trigger');
    if (trigger) trigger.click();

    // ── Collapse / expand compound nodes ────────────────────────────────
    if (!node.isParent()) return;
    var desc = node.descendants();
    var anyVisible = false;
    desc.each(function(n) { if (n.visible()) anyVisible = true; });
    if (anyVisible) {
      desc.hide();
      node.addClass('cy-collapsed');
    } else {
      desc.show();
      node.removeClass('cy-collapsed');
    }
  });
}"""


def cytoscape_view() -> rx.Component:
    """Compound (nested) network graph rendered via react-cytoscapejs.

    - Real infra data from AppState.cytoscape_elements (populated in on_load).
    - Falls back to synthetic demo data when infra is unavailable.
    - Click any compound node to collapse/expand its contents.
    """
    return rx.box(
        _CytoscapeGraph.create(
            elements=AppState.cytoscape_elements,
            stylesheet=_CYTOSCAPE_STYLESHEET,
            layout={
                "name":    "preset",
                "fit":     True,
                "padding": 60,
            },
            cy_style={"width": "100%", "height": "100%", "background": "#0f172a"},
            cy_cb=Var(_js_expr=_CYTOSCAPE_INIT_JS),
            wheel_sensitivity=AppState.cy_wheel_sensitivity,
        ),
        width="100%",
        height="100%",
        overflow="hidden",
        background="#0f172a",
    )


# JS callback passed as onNodeClick prop to the ReactFlow component.
# Sets window._rfSelectedPath then clicks the hidden rf-node-trigger div
# so the Reflex event handler can read the value back via rx.call_script.
_REACTFLOW_NODE_CLICK_JS = r"""(event, node) => {
  window._rfSelectedPath = node.id;
  var trigger = document.getElementById('rf-node-trigger');
  if (trigger) trigger.click();
}"""

_ARCH_DIAGRAM_NODE_CLICK_JS = r"""(event, node) => {
  if (!node.id || node.id.startsWith('__zone__')) return;
  window._rfSelectedPath = node.id;
  var trigger = document.getElementById('rf-node-trigger');
  if (trigger) trigger.click();
}"""


def _arch_export_menu_item(fmt: dict) -> rx.Component:
    """One row in the Export section: Save button + optional Open-in-browser link."""
    return rx.vstack(
        rx.button(
            rx.text("Save  ", fmt["label"], font_size="12px",
                    color="var(--gui-text-primary)"),
            variant="ghost", size="1", color_scheme="gray",
            cursor="pointer", width="100%", text_align="left",
            padding="6px 12px",
            on_click=AppState.export_arch_diagram(fmt["id"]),
            _hover={"background": "var(--gray-3)"}, border_radius="4px",
        ),
        rx.cond(
            fmt["open_url"] != "",
            rx.link(
                rx.hstack(
                    rx.text(fmt["label"], "  ↗ open in browser",
                            font_size="11px", color="var(--gui-text-dim)"),
                    padding="4px 12px", width="100%",
                    _hover={"background": "var(--gray-3)"}, border_radius="4px",
                ),
                href=fmt["open_url"],
                is_external=True, text_decoration="none",
            ),
            rx.box(),
        ),
        spacing="0", width="100%",
    )


def _arch_diagram_toolbar() -> rx.Component:
    def _depth_popover(label: str, value_var, on_change, min_v: int, max_v: int):
        return rx.popover.root(
            rx.popover.trigger(
                rx.button(
                    label, value_var,
                    variant="outline", size="1", color_scheme="gray",
                    cursor="pointer", padding="2px 8px", font_size="11px",
                ),
            ),
            rx.popover.content(
                rx.vstack(
                    rx.hstack(
                        rx.text(label, font_size="12px", font_weight="600"),
                        rx.spacer(),
                        rx.text(value_var, font_size="12px", color="#3b82f6",
                                font_weight="600", min_width="20px", text_align="right"),
                        width="160px", align="center",
                    ),
                    rx.slider(
                        min=min_v, max=max_v, step=1,
                        value=[value_var],
                        on_change=on_change,
                        width="160px",
                    ),
                    rx.hstack(
                        rx.text(str(min_v), font_size="10px", color="var(--gui-text-dim)"),
                        rx.spacer(),
                        rx.text(str(max_v), font_size="10px", color="var(--gui-text-dim)"),
                        width="160px",
                    ),
                    spacing="2", padding="10px", width="180px",
                ),
                side="bottom", align="start",
            ),
        )

    dir_picker = rx.popover.root(
        rx.popover.trigger(
            rx.button(
                rx.hstack(
                    rx.text("📁", font_size="10px"),
                    rx.text(AppState.arch_export_dir_label, font_size="10px",
                            max_width="100px", overflow="hidden",
                            text_overflow="ellipsis", white_space="nowrap"),
                    spacing="1",
                ),
                variant="outline", size="1", color_scheme="gray",
                cursor="pointer", padding="2px 6px",
                title=AppState.arch_export_dir,
            ),
        ),
        rx.popover.content(
            rx.vstack(
                rx.text("Export Directory", font_size="12px", font_weight="600"),
                rx.input(
                    default_value=AppState.arch_export_dir,
                    on_blur=AppState.set_arch_export_dir,
                    placeholder="/path/to/save",
                    font_size="11px", width="320px",
                ),
                rx.text("Files are written to this path on the server.",
                        font_size="10px", color="var(--gui-text-dim)"),
                spacing="2", padding="10px",
            ),
            side="bottom", align="start",
        ),
    )

    return rx.hstack(
        rx.popover.root(
            rx.popover.trigger(
                rx.button(
                    rx.hstack(rx.text("File", font_size="12px"),
                              rx.text("▾", font_size="10px"), spacing="1"),
                    variant="ghost", size="1", color_scheme="gray",
                    cursor="pointer", padding="4px 8px",
                ),
            ),
            rx.popover.content(
                rx.vstack(
                    rx.text("Export", font_size="10px", font_weight="700",
                            color="var(--gui-text-dim)", text_transform="uppercase",
                            letter_spacing="0.07em", padding="4px 8px 2px"),
                    rx.foreach(AppState.arch_export_urls, _arch_export_menu_item),
                    spacing="0", padding="4px", min_width="280px",
                ),
                padding="4px",
            ),
        ),

        dir_picker,

        rx.divider(orientation="vertical", height="16px", color="var(--gray-5)"),

        rx.hstack(
            rx.text("Dir:", font_size="11px", color="var(--gui-text-dim)"),
            rx.button("→ LR", size="1",
                      variant=rx.cond(AppState.arch_direction == "LR", "solid", "outline"),
                      color_scheme="blue", cursor="pointer",
                      on_click=AppState.set_arch_direction("LR"),
                      padding="2px 6px", font_size="11px"),
            rx.button("↓ TB", size="1",
                      variant=rx.cond(AppState.arch_direction == "TB", "solid", "outline"),
                      color_scheme="blue", cursor="pointer",
                      on_click=AppState.set_arch_direction("TB"),
                      padding="2px 6px", font_size="11px"),
            spacing="1", align="center",
        ),

        rx.divider(orientation="vertical", height="16px", color="var(--gray-5)"),

        _depth_popover("Min:", AppState.arch_min_depth, AppState.set_arch_min_depth, 1, 5),
        _depth_popover("Max:", AppState.arch_max_depth, AppState.set_arch_max_depth, 1, 6),

        rx.divider(orientation="vertical", height="16px", color="var(--gray-5)"),

        rx.button(
            rx.cond(AppState.arch_show_connections,
                    rx.text("⊶ Conn", font_size="11px"),
                    rx.text("⊶ Conn", font_size="11px", opacity="0.4")),
            size="1",
            variant=rx.cond(AppState.arch_show_connections, "soft", "outline"),
            color_scheme="gray", cursor="pointer",
            on_click=AppState.toggle_arch_connections,
            padding="2px 8px",
            title="Toggle dependency connection edges",
        ),

        rx.spacer(),

        rx.cond(
            AppState.arch_export_status != "",
            rx.text(
                AppState.arch_export_status,
                font_size="10px",
                color=rx.cond(
                    AppState.arch_export_status.contains("Error"),
                    "var(--red-9)", "var(--green-9)",
                ),
                max_width="220px", overflow="hidden",
                text_overflow="ellipsis", white_space="nowrap",
                padding_right="6px",
            ),
            rx.box(),
        ),

        rx.text("Arch Diagram", font_size="10px",
                color="var(--gui-text-dim)", padding_right="8px"),

        width="100%", height="36px", align="center", spacing="2",
        padding="0 8px",
        background="var(--gray-2)",
        border_bottom="1px solid var(--gray-5)",
        flex_shrink="0",
    )


def arch_diagram_view() -> rx.Component:
    """Architectural diagram rendered via React Flow.

    Components are auto-derived from _ALL_NODES_CACHE at component_depth.
    Layers are defined in arch_diagram_config.yaml by path prefix rules.
    Connections come from _DEPENDENCIES_CACHE filtered to component pairs.
    A toolbar above the canvas provides File → Export → draw.io.
    """
    return rx.vstack(
        _arch_diagram_toolbar(),
        rx.box(
            _ReactFlowGraph.create(
                nodes=AppState.arch_diagram_nodes,
                edges=AppState.arch_diagram_edges,
                fit_view=True,
                nodes_draggable=False,
                nodes_connectable=False,
                rf_style={"width": "100%", "height": "100%", "background": "#F8FAFC"},
                on_node_click_cb=Var(_js_expr=_ARCH_DIAGRAM_NODE_CLICK_JS),
            ),
            width="100%",
            flex="1",
            overflow="hidden",
        ),
        width="100%",
        height="100%",
        spacing="0",
        overflow="hidden",
    )


def reactflow_view() -> rx.Component:
    """Top-down hierarchical tree rendered via React Flow.

    - Positions are pre-computed in Python (no client-side layout pass).
    - Real infra data from AppState.reactflow_nodes/edges; synthetic fallback
      when infra is unavailable.
    - Clicking a node selects it and shows its params in the right panel.
    """
    return rx.box(
        _ReactFlowGraph.create(
            nodes=AppState.reactflow_nodes,
            edges=AppState.reactflow_edges,
            fit_view=True,
            nodes_draggable=False,
            nodes_connectable=False,
            rf_style={"width": "100%", "height": "100%", "background": "#0f172a"},
            on_node_click_cb=Var(_js_expr=_REACTFLOW_NODE_CLICK_JS),
        ),
        width="100%",
        height="100%",
        overflow="hidden",
        background="#0f172a",
    )


def modules_node_component(node: dict) -> rx.Component:
    """Tree row for a module node (no context menu, no provider pills)."""
    is_selected = node["path"] == AppState.selected_node_path
    return rx.box(
        rx.hstack(
            rx.box(min_width=node["indent_px"], flex_shrink="0"),
            rx.cond(
                node["has_children"],
                rx.cond(
                    node["is_expanded"],
                    rx.text("▼", color="var(--gui-text-dim)", font_size="10px", width="12px"),
                    rx.text("▶", color="var(--gui-text-dim)", font_size="10px", width="12px"),
                ),
                rx.box(width="12px"),
            ),
            rx.cond(
                node["has_terragrunt"],
                rx.text("📄", font_size="12px"),
                rx.cond(
                    node["has_children"],
                    rx.text("📁", font_size="12px"),
                    rx.text("", width="14px"),
                ),
            ),
            rx.text(
                node["name"],
                font_size="13px",
                font_weight=rx.cond(node["is_bold"], "600", "400"),
                color=rx.cond(node["has_terragrunt"], "var(--gui-text-primary)", "var(--gui-text-muted)"),
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
                flex="1",
                min_width="0",
            ),
            rx.cond(
                node["show_badge"],
                rx.badge(node["type"], size="1", variant="soft"),
                rx.box(),
            ),
            align="center",
            spacing="1",
            width="100%",
            overflow="hidden",
        ),
        padding_x="8px",
        padding_y="3px",
        cursor="pointer",
        border_radius="4px",
        width="100%",
        background=rx.cond(is_selected, "var(--gui-tree-select-bg)", "transparent"),
        _hover={"background_color": rx.cond(is_selected, "var(--gui-tree-select-bg)", "var(--gui-tree-hover-bg)")},
        on_click=AppState.click_modules_node(node["path"]),
    )


def _pkg_module_row(mod: PackageModule) -> rx.Component:
    """Single module row inside a package card."""
    return rx.hstack(
        rx.text(
            mod.provider,
            font_size="11px",
            color="var(--gui-text-dim)",
            width="80px",
            flex_shrink="0",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.cond(
            mod.tf_path,
            rx.button(
                mod.name,
                variant="ghost",
                size="1",
                font_size="11px",
                padding="0",
                height="auto",
                cursor="pointer",
                color="var(--accent-9)",
                on_click=AppState.open_abs_file_in_viewer(mod.tf_path),
                title=mod.tf_path,
            ),
            rx.text(mod.name, font_size="11px"),
        ),
        rx.cond(
            mod.tg_scripts_readme,
            rx.button(
                "tg-scripts",
                variant="outline",
                size="1",
                font_size="10px",
                padding_x="4px",
                height="auto",
                cursor="pointer",
                color="var(--gui-text-dim)",
                on_click=AppState.open_abs_file_in_viewer(mod.tg_scripts_readme),
                title=mod.tg_scripts_readme,
            ),
            rx.box(),
        ),
        spacing="2",
        align="center",
        width="100%",
        padding_y="1px",
    )


def _pkg_script_link(label: str, path: str) -> rx.Component:
    """Clickable script-file link pill."""
    return rx.cond(
        path,
        rx.button(
            label,
            variant="outline",
            size="1",
            font_size="10px",
            cursor="pointer",
            color="var(--gui-text-dim)",
            on_click=AppState.open_abs_file_in_viewer(path),
            title=path,
        ),
        rx.box(),
    )


def _pkg_template_pill(path: str) -> rx.Component:
    """Pill for a provider template path (list[str] foreach — path is the item var directly)."""
    return rx.button(
        path.split("/")[-1],
        variant="outline",
        size="1",
        font_size="10px",
        cursor="pointer",
        color="var(--gui-text-dim)",
        on_click=AppState.open_abs_file_in_viewer(path),
        title=path,
    )


def _pkg_file_link_pill(lnk: PackageFileLink) -> rx.Component:
    """Single pill in a list of PackageFileLink items."""
    return rx.cond(
        lnk.path,
        rx.button(
            lnk.label,
            variant="outline",
            size="1",
            font_size="10px",
            cursor="pointer",
            color="var(--gui-text-dim)",
            on_click=AppState.open_abs_file_in_viewer(lnk.path),
            title=lnk.path,
        ),
        rx.text(lnk.label, font_size="10px", color="var(--gui-text-dim)",
                padding_x="3px", padding_y="1px",
                border="1px solid var(--gray-4)", border_radius="3px"),
    )


def _pkg_section_label(text: str) -> rx.Component:
    return rx.text(text, font_size="11px", font_weight="600",
                   color="var(--gui-text-dim)", padding_bottom="2px")


def _pkg_card(pkg: PackageInfo) -> rx.Component:
    """Collapsible package row: compact list row when collapsed, full card when expanded."""
    is_expanded = AppState.packages_expanded_names.contains(pkg.name)
    chevron = rx.cond(is_expanded, "▼", "▶")

    # ── Collapsed row ────────────────────────────────────────────────────────
    collapsed_row = rx.hstack(
        rx.text(chevron, font_size="10px", color="var(--gui-text-dim)",
                width="14px", flex_shrink="0"),
        rx.text("📦", font_size="13px"),
        rx.text(pkg.name, font_size="13px", font_weight="600", color="var(--gui-text)"),
        rx.cond(
            pkg.providers_str,
            rx.text(pkg.providers_str, font_size="11px", color="var(--gui-text-dim)"),
            rx.box(),
        ),
        rx.cond(
            pkg.source_repo,
            rx.badge(pkg.source_repo, variant="soft", color_scheme="cyan",
                     font_size="10px", padding_x="5px"),
            rx.box(),
        ),
        rx.spacer(),
        align="center",
        spacing="2",
        width="100%",
        cursor="pointer",
        on_click=AppState.toggle_package_expanded(pkg.name),
        padding="6px 10px",
        border_radius="4px",
        _hover={"background": "var(--gray-3)"},
    )

    # ── Expanded card (full detail) ──────────────────────────────────────────
    expanded_card = rx.box(
        rx.vstack(
            # Header row with collapse button
            rx.hstack(
                rx.text("▼", font_size="10px", color="var(--gui-text-dim)",
                        width="14px", flex_shrink="0", cursor="pointer",
                        on_click=AppState.toggle_package_expanded(pkg.name)),
                rx.text("📦", font_size="14px"),
                rx.text(pkg.name, font_size="14px", font_weight="700",
                        color="var(--gui-text)"),
                rx.cond(
                    pkg.source_repo,
                    rx.badge(pkg.source_repo, variant="soft", color_scheme="cyan",
                             font_size="10px", padding_x="5px"),
                    rx.box(),
                ),
                rx.spacer(),
                rx.cond(
                    pkg.config_yaml_path,
                    rx.button(
                        "config YAML", variant="ghost", size="1", font_size="11px",
                        cursor="pointer", color="var(--accent-9)",
                        on_click=AppState.open_abs_file_in_viewer(pkg.config_yaml_path),
                        title=pkg.config_yaml_path,
                    ),
                    rx.box(),
                ),
                rx.cond(
                    pkg.secrets_yaml_path,
                    rx.button(
                        "secrets", variant="ghost", size="1", font_size="11px",
                        cursor="pointer", color="var(--orange-9)",
                        on_click=AppState.open_abs_file_in_viewer(pkg.secrets_yaml_path),
                        title=pkg.secrets_yaml_path,
                    ),
                    rx.box(),
                ),
                rx.button(
                    "✎ Rename", variant="ghost", size="1", font_size="11px",
                    cursor="pointer", color="var(--blue-9)",
                    on_click=AppState.begin_pkg_rename(pkg.name),
                    title="Rename this package",
                ),
                rx.button(
                    "⧉ Copy", variant="ghost", size="1", font_size="11px",
                    cursor="pointer", color="var(--blue-9)",
                    on_click=AppState.begin_pkg_copy(pkg.name),
                    title="Copy this package to a new name",
                ),
                align="center",
                width="100%",
                spacing="2",
                cursor="pointer",
                on_click=AppState.toggle_package_expanded(pkg.name),
            ),
            # ── Providers ────────────────────────────────────────────────────
            rx.cond(
                pkg.providers_str,
                rx.hstack(
                    rx.tooltip(
                        rx.text("Providers:", font_size="11px", color="var(--gui-text-dim)",
                                width="80px", flex_shrink="0"),
                        content="Terraform providers used by the modules in this package",
                    ),
                    rx.text(pkg.providers_str, font_size="11px",
                            color="var(--gui-text-muted)"),
                    spacing="2", align="center",
                ),
                rx.box(),
            ),
            # ── Provider templates ────────────────────────────────────────────
            rx.cond(
                pkg.provider_templates,
                rx.vstack(
                    _pkg_section_label("Provider Templates"),
                    rx.hstack(
                        rx.foreach(pkg.provider_templates, _pkg_template_pill),
                        spacing="1", flex_wrap="wrap",
                    ),
                    spacing="0", align="start", width="100%",
                ),
                rx.box(),
            ),
            # ── Modules ──────────────────────────────────────────────────────
            rx.cond(
                pkg.modules,
                rx.vstack(
                    rx.tooltip(
                        _pkg_section_label("Modules"),
                        content="Terraform modules included in this package",
                    ),
                    rx.box(
                        rx.foreach(pkg.modules, _pkg_module_row),
                        border_left="2px solid var(--gray-4)",
                        padding_left="8px",
                        width="100%",
                    ),
                    spacing="0", align="start", width="100%",
                ),
                rx.box(),
            ),
            # ── TG Scripts ───────────────────────────────────────────────────
            rx.cond(
                pkg.tg_scripts_env_path | pkg.tg_scripts_readme_path | pkg.tg_scripts_sub_dirs,
                rx.vstack(
                    rx.tooltip(
                        _pkg_section_label("TG Scripts"),
                        content="Scripts called by the Terragrunt units in this package",
                    ),
                    rx.hstack(
                        rx.text("Files:", font_size="11px", color="var(--gui-text-dim)",
                                width="40px", flex_shrink="0"),
                        _pkg_script_link("pkg_env.sh", pkg.tg_scripts_env_path),
                        _pkg_script_link("README.md", pkg.tg_scripts_readme_path),
                        spacing="2", align="center", flex_wrap="wrap",
                    ),
                    rx.cond(
                        pkg.tg_scripts_sub_dirs,
                        rx.hstack(
                            rx.text("Dirs:", font_size="11px", color="var(--gui-text-dim)",
                                    width="40px", flex_shrink="0"),
                            rx.hstack(
                                rx.foreach(pkg.tg_scripts_sub_dirs, _pkg_file_link_pill),
                                spacing="1", flex_wrap="wrap",
                            ),
                            spacing="2", align="start", width="100%",
                        ),
                        rx.box(),
                    ),
                    spacing="1", align="start", width="100%",
                ),
                rx.box(),
            ),
            # ── Wave Scripts ──────────────────────────────────────────────────
            rx.cond(
                pkg.wave_scripts_env_path | pkg.wave_scripts_readme_path | pkg.wave_test_playbooks,
                rx.vstack(
                    rx.tooltip(
                        _pkg_section_label("Wave Scripts"),
                        content="Scripts available to be called by the wave(s) in this package",
                    ),
                    rx.hstack(
                        rx.text("Files:", font_size="11px", color="var(--gui-text-dim)",
                                width="40px", flex_shrink="0"),
                        _pkg_script_link("pkg_env.sh", pkg.wave_scripts_env_path),
                        _pkg_script_link("README.md", pkg.wave_scripts_readme_path),
                        spacing="2", align="center", flex_wrap="wrap",
                    ),
                    rx.cond(
                        pkg.wave_test_playbooks,
                        rx.hstack(
                            rx.text("Tests:", font_size="11px", color="var(--gui-text-dim)",
                                    width="40px", flex_shrink="0"),
                            rx.hstack(
                                rx.foreach(pkg.wave_test_playbooks, _pkg_file_link_pill),
                                spacing="1", flex_wrap="wrap",
                            ),
                            spacing="2", align="start", width="100%",
                        ),
                        rx.box(),
                    ),
                    spacing="1", align="start", width="100%",
                ),
                rx.box(),
            ),
            spacing="2",
            align="start",
            width="100%",
        ),
        padding="10px",
        border="1px solid var(--gray-5)",
        border_radius="6px",
        width="100%",
    )

    return rx.cond(is_expanded, expanded_card, collapsed_row)


def modules_tree_view() -> rx.Component:
    """Scrollable tree for the _modules directory."""
    return rx.scroll_area(
        rx.cond(
            AppState.is_loading,
            rx.center(
                rx.vstack(
                    rx.spinner(size="3"),
                    rx.text("Loading modules…", color="#888", font_size="13px"),
                    align="center",
                    spacing="2",
                ),
                height="200px",
            ),
            rx.cond(
                AppState.modules_nodes_empty,
                rx.center(
                    rx.text("No modules found in infra/*/  _modules/", color="#aaa", font_size="13px"),
                    height="120px",
                ),
                rx.vstack(
                    rx.text(
                        "MODULES",
                        font_size="10px",
                        font_weight="700",
                        color="var(--gui-text-dim)",
                        text_transform="uppercase",
                        letter_spacing="0.1em",
                        padding_x="8px",
                        padding_top="10px",
                        padding_bottom="4px",
                    ),
                    rx.foreach(AppState.visible_modules_nodes, modules_node_component),
                    spacing="0",
                    align="start",
                    width="100%",
                ),
            ),
        ),
        padding_x="0",
        padding_y="0",
        width="100%",
        height="100%",
    )


def _pkg_sync_strip() -> rx.Component:
    """Output strip shown after pkg-mgr sync runs."""
    return rx.cond(
        AppState.pkg_sync_output != "",
        rx.vstack(
            rx.hstack(
                rx.text(
                    "pkg-mgr sync",
                    font_size="11px",
                    font_weight="600",
                    color=rx.cond(AppState.pkg_sync_ok, "var(--green-9)", "var(--red-9)"),
                ),
                rx.spacer(),
                rx.button(
                    "✕",
                    on_click=AppState.clear_pkg_sync_output,
                    size="1",
                    variant="ghost",
                    cursor="pointer",
                ),
                width="100%",
                align="center",
            ),
            rx.code_block(
                AppState.pkg_sync_output,
                font_size="10px",
                max_height="120px",
                overflow_y="auto",
                width="100%",
            ),
            padding="6px 8px",
            background=rx.cond(AppState.pkg_sync_ok, "var(--green-2)", "var(--red-2)"),
            border_radius="4px",
            width="100%",
        ),
        rx.box(),
    )


def _ext_repo_chip(repo: dict) -> rx.Component:
    """Inline chip for one external repo with a remove button."""
    return rx.hstack(
        rx.text(repo["name"], font_size="11px", color="var(--gui-text)"),
        rx.tooltip(
            rx.button(
                "✕", variant="ghost", size="1", font_size="10px",
                cursor="pointer", color="var(--red-9)", padding="0 3px",
                on_click=AppState.remove_pkg_repo(repo["name"]),
            ),
            content="Remove repo and delete clone",
        ),
        align="center",
        spacing="1",
        border="1px solid var(--cyan-6)",
        border_radius="12px",
        padding="2px 6px",
        background="var(--cyan-2)",
    )


def packages_view() -> rx.Component:
    """Scrollable list/card view of all packages discovered in _modules/."""
    return rx.fragment(
        rx.scroll_area(
            rx.vstack(
                # ── Top bar: heading + config buttons + sync ────────────────────
                rx.hstack(
                    rx.text(
                        "PACKAGES",
                        font_size="10px",
                        font_weight="700",
                        color="var(--gui-text-dim)",
                        text_transform="uppercase",
                        letter_spacing="0.1em",
                    ),
                    rx.spacer(),
                    rx.cond(
                        AppState.packages_all_expanded,
                        rx.button(
                            "⊟ Collapse all",
                            size="1",
                            variant="ghost",
                            font_size="11px",
                            cursor="pointer",
                            on_click=AppState.collapse_all_packages,
                        ),
                        rx.button(
                            "⊞ Expand all",
                            size="1",
                            variant="ghost",
                            font_size="11px",
                            cursor="pointer",
                            on_click=AppState.expand_all_packages,
                        ),
                    ),
                    rx.button(
                        "📄 framework_packages.yaml",
                        size="1",
                        variant="ghost",
                        font_size="11px",
                        cursor="pointer",
                        on_click=AppState.open_framework_pkgs_in_viewer,
                    ),
                    rx.button(
                        "📄 pkg-repos.yaml",
                        size="1",
                        variant="ghost",
                        font_size="11px",
                        cursor="pointer",
                        on_click=AppState.open_pkg_repos_config_in_viewer,
                    ),
                    rx.button(
                        rx.cond(
                            AppState.pkg_sync_running,
                            rx.hstack(rx.spinner(size="1"), rx.text("Syncing…"), spacing="1"),
                            "↻ Sync",
                        ),
                        size="1",
                        variant="soft",
                        font_size="11px",
                        cursor="pointer",
                        on_click=AppState.sync_packages,
                        disabled=AppState.pkg_sync_running,
                    ),
                    align="center",
                    width="100%",
                    padding_x="8px",
                    padding_top="10px",
                    padding_bottom="4px",
                ),
                # ── Sync output strip ────────────────────────────────────────────
                rx.box(
                    _pkg_sync_strip(),
                    padding_x="8px",
                    width="100%",
                ),
                # ── External repos row (if any) ─────────────────────────────────
                rx.cond(
                    AppState.ext_package_repos,
                    rx.hstack(
                        rx.text("Ext repos:", font_size="11px",
                                color="var(--gui-text-dim)", flex_shrink="0"),
                        rx.hstack(
                            rx.foreach(AppState.ext_package_repos, _ext_repo_chip),
                            spacing="2",
                            flex_wrap="wrap",
                        ),
                        spacing="2",
                        align="center",
                        width="100%",
                        padding_x="8px",
                        padding_bottom="6px",
                    ),
                    rx.box(),
                ),
                # ── Package list ────────────────────────────────────────────────
                rx.cond(
                    AppState.packages_data_empty,
                    rx.center(
                        rx.text("No packages found in infra/*/  _modules/",
                                color="#aaa", font_size="13px"),
                        height="80px",
                    ),
                    rx.vstack(
                        rx.foreach(AppState.packages_data, _pkg_card),
                        spacing="1",
                        align="start",
                        width="100%",
                        padding_x="8px",
                        padding_bottom="10px",
                    ),
                ),
                spacing="0",
                align="start",
                width="100%",
            ),
            padding_x="0",
            padding_y="0",
            width="100%",
            height="100%",
        ),
    )


def ansible_inventory_view() -> rx.Component:
    """Left-panel placeholder shown when the Ansible Inventory root is active."""
    return rx.center(
        rx.vstack(
            rx.text("📋", font_size="32px"),
            rx.text(
                "Ansible Inventory",
                font_size="14px",
                font_weight="600",
                color="var(--gui-text-primary)",
            ),
            rx.cond(
                AppState.hcl_file_path != "",
                rx.text(
                    AppState.hcl_file_path,
                    font_size="11px",
                    color="var(--gui-text-muted)",
                    font_family="monospace",
                    text_align="center",
                    max_width="260px",
                    word_break="break-all",
                ),
                rx.text(
                    "No inventory file configured.\nSet ansible_inventory_path in _config/de3-gui-pkg.yaml.",
                    font_size="12px",
                    color="var(--gui-text-dim)",
                    text_align="center",
                    white_space="pre-line",
                ),
            ),
            rx.vstack(
                rx.button(
                    rx.cond(
                        AppState.dag_refresh_status == "running",
                        "↺ Updating…",
                        "↺ Update Inventory (and DAG)",
                    ),
                    on_click=AppState.update_inventory_and_dag,
                    size="2",
                    variant="soft",
                    color_scheme=rx.cond(
                        AppState.dag_refresh_status == "error",
                        "red",
                        rx.cond(AppState.dag_refresh_status == "running", "yellow", "blue"),
                    ),
                    disabled=AppState.dag_refresh_status == "running",
                    title="Re-scan infra directory, rebuild all node caches, and refresh the Ansible inventory — equivalent to restarting the app",
                ),
                rx.cond(
                    AppState.dag_refresh_status == "error",
                    rx.text(
                        AppState.dag_refresh_error,
                        color="red",
                        font_size="11px",
                        max_width="280px",
                        text_align="center",
                        white_space="pre-wrap",
                    ),
                    rx.fragment(),
                ),
                align="center",
                spacing="1",
            ),
            align="center",
            spacing="3",
        ),
        width="100%",
        height="100%",
    )


# ---------------------------------------------------------------------------
# UI: Framework Repos view
# ---------------------------------------------------------------------------

def fw_repos_mermaid_view() -> rx.Component:
    """Framework Repos view — Mermaid class diagram rendered in an iframe asset."""
    return rx.el.iframe(
        src=AppState.fw_repos_iframe_src,
        width="100%",
        height="100%",
        style={"border": "none", "display": "block"},
    )


def render_left_panel_content() -> rx.Component:
    """Dispatch to explorer_root first, then visualization framework."""
    return rx.match(
        AppState.explorer_root,
        ("modules",           modules_tree_view()),
        ("packages",          packages_view()),
        ("ansible_inventory", ansible_inventory_view()),
        ("framework_repos",   fw_repos_mermaid_view()),
        # default: "infra"
        rx.match(
            AppState.viz_framework,
            ("reflex",      render_view(AppState.left_view)),
            ("cytoscape",   cytoscape_view()),
            ("reactflow",   reactflow_view()),
            ("archdiagram", arch_diagram_view()),
            rx.center(rx.text("Unknown framework", color="#888"), height="100%"),
        ),
    )


# ---------------------------------------------------------------------------
# UI: providers menu
# ---------------------------------------------------------------------------

def provider_toggle_item(p: dict) -> rx.Component:
    return rx.hstack(
        rx.cond(
            p["is_visible"],
            rx.text("☑", color="#3b82f6", font_size="16px", width="18px"),
            rx.text("☐", color="#aaa", font_size="16px", width="18px"),
        ),
        rx.text(p["provider-name"], font_size="13px"),
        align="center",
        spacing="2",
        cursor="pointer",
        padding_y="4px",
        padding_x="6px",
        border_radius="4px",
        width="100%",
        _hover={"background": "var(--gui-hover-soft)"},
        on_click=AppState.toggle_provider(p["provider-name"]),
        on_double_click=AppState.solo_provider(p["provider-name"]),
    )


# ---------------------------------------------------------------------------
# UI: tree view components
# ---------------------------------------------------------------------------

def _ctx_menu_row(row: dict) -> rx.Component:
    """Render one row in the dynamic context menu (driven by AppState.ctx_menu_rows).

    URL-type items expand into a browser-picker sub-menu so the user can choose
    which browser to open without a separate global profile selector.
    """
    url_item = rx.context_menu.sub(
        rx.context_menu.sub_trigger(row["label"], id=row["id"]),
        rx.context_menu.sub_content(
            rx.foreach(
                AppState.chrome_profiles,
                lambda p: rx.context_menu.item(
                    p["label"],
                    on_select=AppState.dispatch_url_with_profile(row["value"], p["id"]),
                ),
            ),
        ),
    )
    plain_item = rx.context_menu.item(
        row["label"],
        on_select=AppState.dispatch_action(row["action_type"], row["value"]),
        id=row["id"],
    )
    return rx.match(
        row["row_type"],
        ("separator",   rx.context_menu.separator()),
        ("group_label", rx.context_menu.label(
            row["label"],
            font_size="10px",
            color="var(--gui-text-dim)",
            text_transform="uppercase",
            letter_spacing="0.06em",
        )),
        ("item", rx.cond(row["action_type"] == "url", url_item, plain_item)),
        rx.box(),
    )


# Ansible icon: official red circle with white "A" wordmark (simplified SVG)
def _host_icon() -> rx.Component:
    """Server/physical-host icon: rack unit with drive bays and a status LED."""
    return rx.html(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14" width="14" height="14">'
        # chassis body
        '<rect x="0" y="3" width="14" height="8" rx="1" fill="#555"/>'
        # front bezel highlight
        '<rect x="0" y="3" width="14" height="2" rx="1" fill="#777"/>'
        # three drive bays
        '<rect x="1" y="6" width="3" height="4" rx="0.5" fill="#333"/>'
        '<rect x="5" y="6" width="3" height="4" rx="0.5" fill="#333"/>'
        '<rect x="9" y="6" width="3" height="4" rx="0.5" fill="#333"/>'
        # status LED (green)
        '<circle cx="12.5" cy="4.5" r="0.8" fill="#22cc44"/>'
        "</svg>",
        style={"display": "inline-flex", "flex_shrink": "0"},
    )


def tree_node_component(node: dict) -> rx.Component:
    """Tree row — in merged mode shows provider pills; right-click opens context menu."""
    is_selected = node["path"] == AppState.selected_node_path

    # Provider pills shown in merged mode (comma-separated providers_str)
    provider_pills = rx.cond(
        AppState.is_merged & (node["providers_str"] != ""),
        rx.text(
            node["providers_str"],
            font_size="10px",
            color="var(--gui-text-dim)",
            font_family="monospace",
            white_space="nowrap",
            padding_x="4px",
            padding_y="1px",
            background="var(--gui-hover-soft)",
            border_radius="3px",
            border="1px solid var(--gui-border)",
            flex_shrink="0",
        ),
        rx.box(),
    )

    # Module name pill — click to open the module file directly in the file viewer
    module_pill = rx.cond(
        node["module_source"] != "",
        rx.text(
            rx.cond(
                AppState.show_full_module_name,
                node["module_tree_path"],
                node["module_source_short"],
            ),
            font_size="10px",
            color="var(--gui-text-dim)",
            font_family="monospace",
            white_space="nowrap",
            padding_x="4px",
            padding_y="1px",
            background="var(--gui-hover-soft)",
            border_radius="3px",
            border="1px solid var(--gui-border)",
            flex_shrink="0",
            cursor="pointer",
            title=node["module_tree_path"],
            on_click=AppState.navigate_to_module(node["module_tree_path"]),
            _hover={"border_color": "var(--gui-text-dim)"},
        ),
        rx.box(),
    )

    row = rx.box(
        rx.hstack(
            rx.box(min_width=node["indent_px"], flex_shrink="0"),
            rx.cond(
                node["has_children"],
                rx.cond(
                    node["is_expanded"],
                    rx.text("▼", color="var(--gui-text-dim)", font_size="10px", width="12px"),
                    rx.text("▶", color="var(--gui-text-dim)", font_size="10px", width="12px"),
                ),
                rx.box(width="12px"),
            ),
            rx.cond(
                node["is_host"],
                _host_icon(),
                rx.cond(
                    node["has_terragrunt"],
                    rx.text("📦", font_size="12px"),
                    rx.cond(
                        node["has_children"],
                        rx.text("📁", font_size="12px"),
                        rx.box(width="14px"),
                    ),
                ),
            ),
            rx.hstack(
                rx.cond(
                    AppState.show_unit_build_status & node["has_terragrunt"],
                    rx.box(
                        width="7px",
                        height="7px",
                        border_radius="50%",
                        flex_shrink="0",
                        background=rx.cond(
                            AppState.is_refreshing_build_statuses,
                            "var(--accent-9)",
                            rx.match(
                                node["build_status"],
                                ("ok",        "var(--green-9)"),
                                ("fail",      "var(--red-9)"),
                                ("unknown",   "var(--amber-9)"),
                                ("destroyed", "var(--purple-9)"),
                                "var(--gray-6)",
                            ),
                        ),
                        title=rx.cond(
                            AppState.is_refreshing_build_statuses,
                            "Updating status…",
                            rx.match(
                                node["build_status"],
                                ("ok",        "Built — resources exist in state"),
                                ("fail",      "Build failed (in queue, no state)"),
                                ("unknown",   "Unknown state"),
                                ("destroyed", "Destroyed — state is empty"),
                                "Not yet built",
                            ),
                        ),
                    ),
                    rx.box(),
                ),
                rx.text(
                    node["name"],
                    font_size="13px",
                    font_weight=rx.cond(node["is_bold"], "600", "400"),
                    color=rx.cond(node["has_terragrunt"], "var(--gui-text-primary)", "var(--gui-text-muted)"),
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.cond(
                    AppState.show_wave_numbers & (node["wave_num_str"] != ""),
                    rx.text(
                        "(", node["wave_num_str"], ")",
                        font_size="11px",
                        color="var(--gui-text-dim)",
                        font_family="monospace",
                        white_space="nowrap",
                        flex_shrink="0",
                    ),
                    rx.box(),
                ),
                spacing="1",
                align="center",
                overflow="hidden",
                flex="1",
                min_width="0",
            ),
            rx.cond(
                node["package"] != "",
                rx.text(
                    node["package"],
                    font_size="9px",
                    color="var(--gui-text-dim)",
                    font_family="monospace",
                    white_space="nowrap",
                    padding_x="3px",
                    padding_y="1px",
                    background="var(--gui-hover-soft)",
                    border_radius="3px",
                    border="1px solid var(--gui-border)",
                    flex_shrink="0",
                ),
                rx.box(),
            ),
            rx.cond(
                node["show_badge"],
                rx.badge(node["type"], size="1", variant="soft"),
                rx.box(),
            ),
            provider_pills,
            module_pill,
            align="center",
            spacing="1",
            width="100%",
            overflow="hidden",
        ),
        padding_x="8px",
        padding_y="3px",
        cursor="pointer",
        border_radius="4px",
        width="100%",
        background=rx.cond(is_selected, "var(--gui-tree-select-bg)", "transparent"),
        _hover={"background_color": rx.cond(is_selected, "var(--gui-tree-select-bg)", "var(--gui-tree-hover-bg)")},
        on_click=AppState.click_node(node["path"]),
        on_context_menu=AppState.open_context_menu(node["path"]),
        id=rx.cond(is_selected, "tree-selected-node", ""),
    )

    return rx.context_menu.root(
        rx.context_menu.trigger(row),
        rx.context_menu.content(
            rx.foreach(AppState.ctx_menu_rows, _ctx_menu_row),
        ),
    )


# ---------------------------------------------------------------------------
# UI: C4 provider card (shared by static + component diagram views)
# ---------------------------------------------------------------------------

def c4_provider_card(p: ProviderCard) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(p.name, size="4"),
                rx.badge(p.count, size="1", variant="solid"),
                rx.spacer(),
                rx.link(
                    rx.text("docs ↗", font_size="11px", color="#888"),
                    href=p.doc_url,
                    target="_blank",
                ),
                align="center",
                width="100%",
            ),
            rx.separator(width="100%"),
            rx.scroll_area(
                rx.vstack(
                    rx.foreach(
                        p.resources,
                        lambda r: rx.hstack(
                            rx.text("📦", font_size="11px"),
                            rx.text(r, font_size="12px", color="#333"),
                            spacing="1",
                            align="center",
                        ),
                    ),
                    spacing="1",
                    align="start",
                ),
                max_height="220px",
                width="100%",
            ),
            spacing="2",
            align="start",
            width="100%",
        ),
        width="260px",
        min_height="140px",
    )


# ---------------------------------------------------------------------------
# UI: canvas views
# ---------------------------------------------------------------------------

def tree_view() -> rx.Component:
    return rx.scroll_area(
        rx.cond(
            AppState.is_loading,
            rx.center(
                rx.vstack(
                    rx.spinner(size="3"),
                    rx.text("Scanning infra…", color="#888", font_size="13px"),
                    align="center",
                    spacing="2",
                ),
                height="200px",
            ),
            rx.vstack(
                rx.text(
                    "EXPLORER",
                    font_size="10px",
                    font_weight="700",
                    color="var(--gui-text-dim)",
                    text_transform="uppercase",
                    letter_spacing="0.1em",
                    padding_x="8px",
                    padding_top="10px",
                    padding_bottom="4px",
                ),
                rx.foreach(AppState.effective_nodes, tree_node_component),
                spacing="0",
                align="start",
                width="100%",
            ),
        ),
        padding_x="0",
        padding_y="0",
        width="100%",
        height="100%",
    )


def c4_view() -> rx.Component:
    return rx.scroll_area(
        rx.flex(
            rx.foreach(AppState.providers_c4, c4_provider_card),
            flex_wrap="wrap",
            gap="12px",
            padding="12px",
            align="start",
        ),
        width="100%",
        height="100%",
    )


def _diagram_layer(title: str, cards_var) -> rx.Component:
    """One horizontal layer in the component diagram."""
    return rx.box(
        rx.hstack(
            rx.text(
                title,
                font_size="11px",
                font_weight="700",
                color="var(--gui-text-muted)",
                text_transform="uppercase",
                letter_spacing="0.06em",
                white_space="nowrap",
            ),
            rx.separator(flex="1"),
            align="center",
            spacing="3",
            width="100%",
            margin_bottom="10px",
        ),
        rx.flex(
            rx.foreach(cards_var, c4_provider_card),
            flex_wrap="wrap",
            gap="12px",
        ),
        padding="14px",
        border="1px solid var(--gui-divider)",
        border_radius="8px",
        background="var(--gui-content-bg)",
        width="100%",
    )


def _arrow() -> rx.Component:
    return rx.text("↓", font_size="22px", color="var(--gui-text-dim)", text_align="center", width="100%")


def component_diagram_view() -> rx.Component:
    return rx.scroll_area(
        rx.vstack(
            _diagram_layer("On-Premise Infrastructure", AppState.layer_onprem),
            _arrow(),
            _diagram_layer("Provisioning", AppState.layer_provisioning),
            _arrow(),
            _diagram_layer("Cloud", AppState.layer_cloud),
            spacing="0",
            align="start",
            width="100%",
            padding="12px",
        ),
        width="100%",
        height="100%",
    )


def render_view(view_var) -> rx.Component:
    return rx.match(
        view_var,
        ("tree", tree_view()),
        ("c4-static-structure", c4_view()),
        ("c4-component-diagram", component_diagram_view()),
        rx.center(rx.text("Select a view", color="#888"), height="200px"),
    )


# ---------------------------------------------------------------------------
# UI: View menu
# ---------------------------------------------------------------------------

def _view_menu_providers_content() -> rx.Component:
    """Provider checklist rendered inside the View > Filters > Providers submenu.
    Uses plain hstack rows (not dropdown_menu.item) so clicking a provider
    toggles it without closing the menu."""
    return rx.vstack(
        rx.hstack(
            rx.text("Providers", font_weight="600", font_size="13px"),
            rx.spacer(),
            rx.button("All/None", size="1", variant="ghost",
                      on_click=AppState.toggle_all_providers,
                      title="Show all providers; click again to hide all"),
            align="center",
            width="100%",
        ),
        rx.separator(width="100%"),
        rx.foreach(AppState.providers_with_visibility, provider_toggle_item),
        spacing="1",
        min_width="180px",
        padding="4px",
    )


def _panel_view_selector() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(
            size="1",
            title="Switch between tree and graph visualisation modes",
        ),
        rx.select.content(
            rx.select.item("Folder",          value="tree"),
            rx.select.item("Tree",            value="reactflow"),
            rx.select.item("Nested Networks", value="cytoscape"),
            rx.select.item("Arch Diagram",    value="archdiagram"),
        ),
        value=AppState.view_mode,
        on_change=AppState.set_view_mode,
        size="1",
    )


def _panel_merged_checkbox() -> rx.Component:
    return rx.cond(
        AppState.viz_framework == "reflex",
        rx.checkbox(
            "Show merged",
            checked=AppState.is_merged,
            on_change=AppState.toggle_tree_mode,
            size="1",
            title="Merge all providers into a single tree view (hide provider layer)",
        ),
        rx.box(),
    )


def _package_toggle_item(item: dict) -> rx.Component:
    return rx.hstack(
        rx.cond(
            item["is_visible"],
            rx.text("☑", color="#3b82f6", font_size="16px", width="18px"),
            rx.text("☐", color="#aaa", font_size="16px", width="18px"),
        ),
        rx.cond(
            item["name"] == "_none",
            rx.text("(none)", font_size="13px", color="var(--gui-text-dim)", font_style="italic"),
            rx.text(item["name"], font_size="13px"),
        ),
        align="center",
        spacing="2",
        cursor="pointer",
        padding_y="4px",
        padding_x="6px",
        border_radius="4px",
        width="100%",
        on_click=AppState.toggle_package(item["name"]),
        on_double_click=AppState.solo_package(item["name"]),
        _hover={"background": "var(--gui-hover)"},
    )


def _region_toggle_item(item: dict) -> rx.Component:
    return rx.hstack(
        rx.cond(
            item["is_visible"],
            rx.text("☑", color="#3b82f6", font_size="16px", width="18px"),
            rx.text("☐", color="#aaa", font_size="16px", width="18px"),
        ),
        rx.cond(
            item["name"] == "_none",
            rx.text("(none)", font_size="13px", color="var(--gui-text-dim)", font_style="italic"),
            rx.text(item["name"], font_size="13px"),
        ),
        align="center",
        spacing="2",
        cursor="pointer",
        padding_y="4px",
        padding_x="6px",
        border_radius="4px",
        width="100%",
        on_click=AppState.toggle_region(item["name"]),
        on_double_click=AppState.solo_region(item["name"]),
        _hover={"background": "var(--gui-hover)"},
    )


def _role_toggle_item(item: dict) -> rx.Component:
    return rx.hstack(
        rx.cond(
            item["selected"],
            rx.text("☑", color="#3b82f6", font_size="16px", width="18px"),
            rx.text("☐", color="#aaa", font_size="16px", width="18px"),
        ),
        rx.text(item["label"], font_size="13px"),
        align="center",
        spacing="2",
        cursor="pointer",
        padding_y="4px",
        padding_x="6px",
        border_radius="4px",
        width="100%",
        on_click=AppState.toggle_role(item["tag"]),
        on_double_click=AppState.solo_role(item["tag"]),
        _hover={"background": "var(--gui-hover)"},
    )


def _panel_roles() -> rx.Component:
    """Roles dropdown — filter infra tree to nodes matching selected Ansible roles."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                AppState.roles_button_label,
                variant="outline",
                size="1",
                color_scheme=rx.cond(AppState.role_filter_active, "orange", "gray"),
                title="Filter the tree to nodes matching selected Ansible roles (sourced from additional_tags in the inventory). Turns orange when a role filter is active.",
            ),
        ),
        rx.dropdown_menu.content(
            rx.vstack(
                rx.hstack(
                    rx.text("Roles", font_weight="600", font_size="13px"),
                    rx.spacer(),
                    rx.button(
                        "All/None",
                        size="1",
                        variant="ghost",
                        on_click=AppState.toggle_all_roles,
                        title="Toggle between all roles selected and none selected",
                    ),
                    align="center",
                    width="100%",
                ),
                rx.separator(width="100%"),
                rx.cond(
                    AppState.roles_with_selection,
                    rx.foreach(AppState.roles_with_selection, _role_toggle_item),
                    rx.text(
                        "No roles found in inventory",
                        font_size="12px",
                        color="var(--gui-text-dim)",
                        padding="4px",
                    ),
                ),
                spacing="1",
                min_width="180px",
                padding="4px",
            ),
            padding="6px",
            align="start",
        ),
    )


def _panel_packages() -> rx.Component:
    """Packages dropdown — toggle package visibility."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                "Packages ▾",
                variant="outline",
                size="1",
                color_scheme=rx.cond(AppState.package_filter_active, "orange", "gray"),
                title="Show or hide infra packages in the tree. Turns orange when one or more packages are hidden.",
            ),
        ),
        rx.dropdown_menu.content(
            rx.vstack(
                rx.hstack(
                    rx.text("Packages", font_weight="600", font_size="13px"),
                    rx.spacer(),
                    rx.button("All/None", size="1", variant="ghost",
                              on_click=AppState.toggle_all_packages,
                              title="Show all packages; click again to hide all"),
                    align="center",
                    width="100%",
                ),
                rx.separator(width="100%"),
                rx.foreach(AppState.packages_with_visibility, _package_toggle_item),
                spacing="1",
                min_width="180px",
                padding="4px",
            ),
            padding="6px",
            align="start",
        ),
    )


def _panel_regions() -> rx.Component:
    """Regions dropdown — toggle region/environment visibility."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                "Regions ▾",
                variant="outline",
                size="1",
                color_scheme=rx.cond(AppState.region_filter_active, "orange", "gray"),
                title="Show or hide deployment regions in the tree. Turns orange when one or more regions are hidden.",
            ),
        ),
        rx.dropdown_menu.content(
            rx.vstack(
                rx.hstack(
                    rx.text("Regions", font_weight="600", font_size="13px"),
                    rx.spacer(),
                    rx.button("All/None", size="1", variant="ghost",
                              on_click=AppState.toggle_all_regions,
                              title="Show all regions; click again to hide all"),
                    align="center",
                    width="100%",
                ),
                rx.separator(width="100%"),
                rx.foreach(AppState.regions_with_visibility, _region_toggle_item),
                spacing="1",
                min_width="180px",
                padding="4px",
            ),
            padding="6px",
            align="start",
        ),
    )


def _env_toggle_item(item: dict) -> rx.Component:
    return rx.hstack(
        rx.cond(
            item["is_visible"],
            rx.text("☑", color="#3b82f6", font_size="16px", width="18px"),
            rx.text("☐", color="#aaa", font_size="16px", width="18px"),
        ),
        rx.cond(
            item["name"] == "_none",
            rx.text("(none)", font_size="13px", color="var(--gui-text-dim)", font_style="italic"),
            rx.text(item["name"], font_size="13px"),
        ),
        align="center",
        spacing="2",
        cursor="pointer",
        padding_y="4px",
        padding_x="6px",
        border_radius="4px",
        width="100%",
        on_click=AppState.toggle_env(item["name"]),
        on_double_click=AppState.solo_env(item["name"]),
        _hover={"background": "var(--gui-hover)"},
    )


def _panel_envs() -> rx.Component:
    """Environments dropdown — toggle environment visibility."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                "Envs ▾",
                variant="outline",
                size="1",
                color_scheme=rx.cond(AppState.env_filter_active, "orange", "gray"),
                title="Show or hide deployment environments in the tree. Turns orange when one or more envs are hidden.",
            ),
        ),
        rx.dropdown_menu.content(
            rx.vstack(
                rx.hstack(
                    rx.text("Environments", font_weight="600", font_size="13px"),
                    rx.spacer(),
                    rx.button("All/None", size="1", variant="ghost",
                              on_click=AppState.toggle_all_envs,
                              title="Show all environments; click again to hide all"),
                    align="center",
                    width="100%",
                ),
                rx.separator(width="100%"),
                rx.foreach(AppState.envs_with_visibility, _env_toggle_item),
                spacing="1",
                min_width="180px",
                padding="4px",
            ),
            padding="6px",
            align="start",
        ),
    )


def _wave_hover_card(item: dict, trigger: rx.Component) -> rx.Component:
    """Wrap trigger in a hover card showing wave attributes from the config."""
    def _attr_row(label: str, value) -> rx.Component:
        return rx.hstack(
            rx.text(label, font_size="12px", color="var(--gui-text-dim)",
                    white_space="nowrap", min_width="160px"),
            rx.text(value, font_size="12px", font_family="monospace"),
            spacing="2", align="start",
        )
    return rx.hover_card.root(
        rx.hover_card.trigger(trigger),
        rx.hover_card.content(
            rx.vstack(
                _attr_row("name:", item["name"]),
                rx.cond(item["description"] != "",
                        _attr_row("description:", item["description"]), rx.box()),
                rx.cond(item["pre_ansible_playbook"] != "",
                        _attr_row("pre_ansible_playbook:", item["pre_ansible_playbook"]), rx.box()),
                rx.cond(item["test_ansible_playbook"] != "",
                        _attr_row("test_ansible_playbook:", item["test_ansible_playbook"]), rx.box()),
                rx.cond(item["test_action"] != "",
                        _attr_row("test_action:", item["test_action"]), rx.box()),
                rx.cond(item["update_inventory"] != "",
                        _attr_row("update_inventory:", item["update_inventory"]), rx.box()),
                rx.cond(item["skip_on_wave_run"] != "",
                        _attr_row("skip on wave run:", item["skip_on_wave_run"]), rx.box()),
                spacing="1", align="start", padding="2px",
            ),
            side="right",
            max_width="520px",
        ),
    )


def _wave_status_icon_card(item: dict) -> rx.Component:
    """Status icon button: ✓ (green), ✗ (red), or – (grey/inactive). Preceded by a gap."""
    icon = rx.cond(
        item["log_status"] == "none",
        rx.text("–", font_size="16px", color="var(--gui-text-dim)",
                width="36px", text_align="center", flex_shrink="0"),
        rx.button(
            rx.cond(item["log_status"] == "ok", "✓", "✗"),
            size="3",
            variant="ghost",
            color_scheme=rx.cond(item["log_status"] == "ok", "green", "red"),
            title=rx.cond(
                item["log_status"] == "ok",
                "Last run succeeded — click to open log",
                "Last run failed — click to open log",
            ),
            on_click=AppState.open_wave_log(item["log_path"]),
            flex_shrink="0",
        ),
    )
    return rx.hstack(
        rx.box(width="36px", flex_shrink="0"),  # gap before status icon
        icon,
        spacing="0",
        align="center",
        flex_shrink="0",
    )


def _wave_time_cols(item: dict) -> rx.Component:
    """Optional timing columns appended after the status icon in each wave row."""
    col_style = {"font_size": "11px", "font_family": "monospace",
                 "color": "var(--gui-text-dim)", "white_space": "nowrap",
                 "flex_shrink": "0"}
    return rx.hstack(
        rx.cond(AppState.wave_show_start_time,
                rx.text(rx.cond(item["start_time"] != "", item["start_time"], "–"),
                        width="135px", **col_style), rx.box()),
        rx.cond(AppState.wave_show_end_time,
                rx.text(rx.cond(item["end_time"] != "", item["end_time"], "–"),
                        width="135px", **col_style), rx.box()),
        rx.cond(AppState.wave_show_duration,
                rx.text(rx.cond(item["duration"] != "", item["duration"], "–"),
                        width="85px", **col_style), rx.box()),
        rx.cond(AppState.wave_show_age,
                rx.text(rx.cond(item["age"] != "", item["age"], "–"),
                        width="85px", **col_style), rx.box()),
        rx.cond(AppState.wave_show_log_update,
                rx.text(rx.cond(item["log_update_age"] != "", item["log_update_age"], "–"),
                        width="85px", **col_style), rx.box()),
        spacing="2", align="center", flex_shrink="0",
    )


def _wave_status_icon(status_key: str, log_path_key: str, item: dict,
                      ok_title: str, fail_title: str) -> rx.Component:
    """Reusable status icon cell content (✓/✗/⟳/–) that opens a log file on click."""
    return rx.cond(
        item[status_key] == "none",
        rx.text("–", font_size="14px", color="var(--gui-text-dim)"),
        rx.cond(
            item[status_key] == "running",
            rx.text("⟳", font_size="16px", color="var(--amber-9)", title="In progress…"),
            rx.button(
                rx.cond(item[status_key] == "ok", "✓", "✗"),
                size="2", variant="ghost",
                color_scheme=rx.cond(item[status_key] == "ok", "green", "red"),
                title=rx.cond(item[status_key] == "ok", ok_title, fail_title),
                on_click=AppState.open_wave_log(item[log_path_key]),
            ),
        ),
    )


def _wave_toggle_item(item: dict) -> rx.Component:
    """One data row in the wave list table."""
    td = {"padding": "3px 6px", "vertical_align": "middle"}
    mono_dim = {"font_size": "11px", "font_family": "monospace",
                "color": "var(--gui-text-dim)", "white_space": "nowrap"}

    _checkbox_title = (
        "Click: toggle wave visibility\n"
        "Double-click: solo (show only this wave)\n"
        "Double-double-click: invert (show all except this wave)"
    )
    checkbox = rx.box(
        rx.cond(
            item["is_visible"],
            rx.text("☑", color="#3b82f6", font_size="16px"),
            rx.text("☐", color="#aaa", font_size="16px"),
        ),
        title=_checkbox_title,
        on_click=AppState.toggle_wave(item["name"]),
        on_double_click=AppState.solo_wave(item["name"]),
        cursor="pointer",
        flex_shrink="0",
    )
    name_label = rx.cond(
        item["name"] == "_none",
        rx.hstack(checkbox,
                  rx.text("(none)", font_size="13px", color="var(--gui-text-dim)",
                          font_style="italic"),
                  spacing="2", align="center"),
        rx.hstack(
            checkbox,
            _wave_hover_card(
                item,
                rx.text(item["name"], font_size="13px", font_family="monospace",
                        text_decoration="underline", text_decoration_style="dotted",
                        text_underline_offset="3px",
                        title="Click to open wave definition in file viewer",
                        on_click=AppState.open_wave_definition(item["name"]),
                        cursor="pointer"),
            ),
            spacing="2", align="center",
        ),
    )
    _btn_slot = {"width": "28px", "display": "flex",
                 "align_items": "center", "justify_content": "center",
                 "flex_shrink": "0"}
    action_cell = rx.cond(
        item["name"] != "_none",
        rx.hstack(
            rx.box(rx.button("▶", size="2", variant="ghost", color_scheme="grass",
                             title="Apply wave (skip tests): ./run -a -w <wave> --skip-test",
                             on_click=AppState.begin_wave_run(item["name"], "apply")),
                   **_btn_slot),
            rx.box(rx.button("🗑", size="2", variant="ghost", color_scheme="red",
                             title="Destroy wave: ./run --clean -w <wave>",
                             on_click=AppState.begin_wave_run(item["name"], "destroy")),
                   **_btn_slot),
            rx.box(
                rx.button(
                    "⊘",
                    size="2",
                    variant=rx.cond(item["skip_on_wave_run"] != "", "soft", "ghost"),
                    color_scheme=rx.cond(item["skip_on_wave_run"] != "", "blue", "gray"),
                    title=rx.cond(
                        item["skip_on_wave_run"] != "",
                        "Skip on wave run: ON — click to disable",
                        "Skip on wave run: OFF — click to enable",
                    ),
                    on_click=AppState.toggle_wave_skip_on_wave_run(item["name"]),
                ),
                **_btn_slot,
            ),
            spacing="0", align="center",
        ),
        rx.hstack(rx.box(**_btn_slot), rx.box(**_btn_slot), rx.box(**_btn_slot),
                  spacing="0"),
    )
    return rx.table.row(
        rx.table.cell(
            rx.text(item["wave_num"], **mono_dim, text_align="right"),
            **td, width="28px",
        ),
        rx.table.cell(
            name_label,
            **td,
        ),
        rx.table.cell(action_cell, **td),
        rx.table.cell(
            _wave_status_icon("pre_log_status", "pre_log_path", item,
                              "Pre-run playbook succeeded — click to open log",
                              "Pre-run playbook failed — click to open log"),
            **td, text_align="center",
        ),
        rx.table.cell(
            _wave_status_icon("log_status", "log_path", item,
                              "Last run succeeded — click to open log",
                              "Last run failed — click to open log"),
            **td, text_align="center",
        ),
        rx.table.cell(
            _wave_status_icon("test_log_status", "test_log_path", item,
                              "Test playbook succeeded — click to open log",
                              "Test playbook failed — click to open log"),
            **td, text_align="center",
        ),
        rx.table.cell(
            rx.text(rx.cond(item["start_time"] != "", item["start_time"], "–"), **mono_dim),
            display=rx.cond(AppState.wave_show_start_time, "table-cell", "none"),
            **td,
        ),
        rx.table.cell(
            rx.text(rx.cond(item["end_time"] != "", item["end_time"], "–"), **mono_dim),
            display=rx.cond(AppState.wave_show_end_time, "table-cell", "none"),
            **td,
        ),
        rx.table.cell(
            rx.text(rx.cond(item["duration"] != "", item["duration"], "–"), **mono_dim),
            display=rx.cond(AppState.wave_show_duration, "table-cell", "none"),
            **td,
        ),
        rx.table.cell(
            rx.text(rx.cond(item["age"] != "", item["age"], "–"), **mono_dim),
            display=rx.cond(AppState.wave_show_age, "table-cell", "none"),
            **td,
        ),
        rx.table.cell(
            rx.text(rx.cond(item["log_update_age"] != "", item["log_update_age"], "–"), **mono_dim),
            display=rx.cond(AppState.wave_show_log_update, "table-cell", "none"),
            **td,
        ),
        rx.table.cell(
            rx.cond(
                item["wave_num"] != "",
                rx.hstack(
                    rx.box(rx.button("↑", size="2", variant="ghost",
                              color_scheme=rx.cond(item["is_first"], "gray", "blue"),
                              disabled=item["is_first"],
                              on_click=AppState.move_wave_up(item["name"])),
                           **_btn_slot),
                    rx.box(rx.button("↓", size="2", variant="ghost",
                              color_scheme=rx.cond(item["is_last"], "gray", "blue"),
                              disabled=item["is_last"],
                              on_click=AppState.move_wave_down(item["name"])),
                           **_btn_slot),
                    spacing="0", align="center",
                ),
                rx.box(),
            ),
            **td, text_align="center", width="56px",
        ),
        background=rx.cond(item["is_recent"], "var(--blue-3)", "transparent"),
        _hover={"background": rx.cond(item["is_recent"], "var(--blue-4)", "var(--gui-hover)")},
        id=item["row_id"],
    )


def _wave_table_header() -> rx.Component:
    """Shared sticky header row for both list and folder wave tables."""
    th_bg = "var(--gui-panel-bg, var(--color-background))"
    th = {
        "font_size": "11px", "font_weight": "600",
        "color": "var(--gui-text-muted)", "white_space": "nowrap",
        "padding": "4px 6px",
        "position": "sticky", "top": "0", "z_index": "1",
        "background": th_bg,
        "border_bottom": "1px solid var(--gui-border)",
    }
    return rx.table.header(
        rx.table.row(
            rx.table.column_header_cell("#",       **th, width="28px", text_align="right",
                title="Wave sequence number"),
            rx.table.column_header_cell("Wave",    **th,
                title="Wave name — click a row to toggle it on/off in the filter"),
            rx.table.column_header_cell("Actions", **th, text_align="center",
                title="▶ Apply wave  |  🗑 Destroy wave  |  ⊘ Skip on clean"),
            rx.table.column_header_cell("Pre",     **th, text_align="center",
                title="Pre-run ansible playbook status — ✓ succeeded, ✗ failed, – not run. Click to open log."),
            rx.table.column_header_cell("Run",     **th, text_align="center",
                title="Terragrunt apply/destroy status — ✓ succeeded, ✗ failed, – not run. Click to open log."),
            rx.table.column_header_cell("Test",    **th, text_align="center",
                title="Test ansible playbook status — ✓ succeeded, ✗ failed, – not run. Click to open log."),
            rx.table.column_header_cell(
                "Start Time", **th,
                title="Timestamp when the wave run started",
                display=rx.cond(AppState.wave_show_start_time, "table-cell", "none"),
            ),
            rx.table.column_header_cell(
                "End Time", **th,
                title="Timestamp when the wave run finished",
                display=rx.cond(AppState.wave_show_end_time, "table-cell", "none"),
            ),
            rx.table.column_header_cell(
                "Duration", **th,
                title="How long the wave run took (end time − start time)",
                display=rx.cond(AppState.wave_show_duration, "table-cell", "none"),
            ),
            rx.table.column_header_cell(
                "Age", **th,
                title="Time elapsed since the wave run finished",
                display=rx.cond(AppState.wave_show_age, "table-cell", "none"),
            ),
            rx.table.column_header_cell(
                "Last Update", **th,
                title="Time since the last write to the wave's apply/destroy log",
                display=rx.cond(AppState.wave_show_log_update, "table-cell", "none"),
            ),
            rx.table.column_header_cell("Order", **th, text_align="center", width="56px",
                title="Re-order waves — ↑ move earlier, ↓ move later"),
        )
    )


def _wave_list_table() -> rx.Component:
    """Full table for the list view: sticky header + foreach body rows."""
    no_waves_row = rx.table.row(
        rx.table.cell(
            rx.text("No waves found in stack config",
                    font_size="12px", color="var(--gui-text-dim)"),
            col_span=9, padding="8px 6px",
        )
    )
    return rx.table.root(
        _wave_table_header(),
        rx.table.body(
            rx.cond(
                AppState.waves_with_visibility,
                rx.foreach(AppState.waves_with_visibility, _wave_toggle_item),
                no_waves_row,
            )
        ),
        size="1",
        width="100%",
        # flex:1 + min_height:0 make rt-TableRoot a flex item that fills waves_content
        # (which is display:flex flex-direction:column).  flex:1 as inline style also
        # overrides Radix's class-level flex-shrink:0, allowing the table to shrink.
        # overflow_y:auto on a flex item with a bounded flex height = the scroll container
        # that CSS position:sticky in <thead> anchors to.
        flex="1",
        min_height="0",
        overflow_y="auto",
    )


def _wave_folder_item(item: dict) -> rx.Component:
    """One row in the waves folder table.

    wave_node   — checkbox + label + actions + status + timing cells
    folder_node — folder icon + label spanning the name cell; other cells empty
    """
    td = {"padding": "3px 6px", "vertical_align": "middle"}
    mono_dim = {"font_size": "11px", "font_family": "monospace",
                "color": "var(--gui-text-dim)", "white_space": "nowrap"}

    # Indent via padding-left on the name cell (16px per depth level)
    indent_pl = rx.match(
        item["indent"],
        (0, "6px"), (1, "22px"), (2, "38px"), (3, "54px"), (4, "70px"),
        "86px",
    )

    _checkbox_title = (
        "Click: toggle wave visibility\n"
        "Double-click: solo (show only this wave)\n"
        "Double-double-click: invert (show all except this wave)"
    )
    # Wave node name content
    wave_name = rx.hstack(
        rx.box(
            rx.cond(item["is_visible"],
                    rx.text("☑", color="#3b82f6", font_size="16px"),
                    rx.text("☐", color="#aaa", font_size="16px")),
            title=_checkbox_title,
            on_click=AppState.toggle_wave(item["wave"]),
            on_double_click=AppState.solo_wave(item["wave"]),
            cursor="pointer",
            flex_shrink="0",
        ),
        _wave_hover_card(
            item,
            rx.text(item["label"], font_size="13px", font_family="monospace",
                    text_decoration="underline", text_decoration_style="dotted",
                    text_underline_offset="3px",
                    title="Click to open wave definition in file viewer",
                    on_click=AppState.open_wave_definition(item["wave"]),
                    cursor="pointer"),
        ),
        spacing="2", align="center",
    )
    # Folder node name content — chevron toggles collapse/expand
    folder_name = rx.hstack(
        rx.text(
            rx.cond(item["is_expanded"], "▼", "▶"),
            font_size="10px",
            color="var(--gui-text-dim)",
            width="12px",
            flex_shrink="0",
        ),
        rx.text("📁", font_size="12px", flex_shrink="0"),
        rx.text(item["label"], font_size="13px", font_family="monospace",
                color="var(--gui-text-dim)"),
        spacing="1",
        align="center",
        cursor="pointer",
        on_click=AppState.toggle_wave_folder(item["folder_path"]),
        title="Click to collapse / expand",
        _hover={"color": "var(--gui-text)"},
    )

    is_wave = item["row_type"] == "wave_node"

    action_cell = rx.hstack(
        rx.button("▶", size="2", variant="ghost", color_scheme="grass",
                  title="Apply wave (skip tests)",
                  on_click=AppState.begin_wave_run(item["wave"], "apply")),
        rx.box(width="32px"),
        rx.button("🗑", size="2", variant="ghost", color_scheme="red",
                  title="Destroy wave",
                  on_click=AppState.begin_wave_run(item["wave"], "destroy")),
        spacing="0", align="center",
    )
    folder_action_cell = rx.hstack(
        rx.button("▶", size="2", variant="ghost", color_scheme="grass",
                  title="Apply all waves in this folder (skip tests)",
                  on_click=AppState.begin_wave_folder_run(item["folder_path"], "apply")),
        rx.box(width="32px"),
        rx.button("🗑", size="2", variant="ghost", color_scheme="red",
                  title="Destroy all waves in this folder",
                  on_click=AppState.begin_wave_folder_run(item["folder_path"], "destroy")),
        spacing="0", align="center",
    )
    return rx.table.row(
        rx.table.cell(
            rx.cond(is_wave, rx.text(item["wave_num"], **mono_dim, text_align="right"), rx.box()),
            **td, width="28px",
        ),
        rx.table.cell(
            rx.cond(is_wave, wave_name, folder_name),
            padding_top="3px", padding_right="6px", padding_bottom="3px",
            padding_left=indent_pl,
            vertical_align="middle",
        ),
        rx.table.cell(rx.cond(is_wave, action_cell, folder_action_cell), **td),
        rx.table.cell(
            rx.cond(is_wave,
                    _wave_status_icon("pre_log_status", "pre_log_path", item,
                                      "Pre-run playbook succeeded — click to open log",
                                      "Pre-run playbook failed — click to open log"),
                    rx.box()),
            **td, text_align="center",
        ),
        rx.table.cell(
            rx.cond(is_wave,
                    _wave_status_icon("log_status", "log_path", item,
                                      "Last run succeeded — click to open log",
                                      "Last run failed — click to open log"),
                    rx.box()),
            **td, text_align="center",
        ),
        rx.table.cell(
            rx.cond(is_wave,
                    _wave_status_icon("test_log_status", "test_log_path", item,
                                      "Test playbook succeeded — click to open log",
                                      "Test playbook failed — click to open log"),
                    rx.box()),
            **td, text_align="center",
        ),
        rx.table.cell(
            rx.cond(is_wave,
                    rx.text(rx.cond(item["start_time"] != "", item["start_time"], "–"), **mono_dim),
                    rx.box()),
            display=rx.cond(AppState.wave_show_start_time, "table-cell", "none"), **td,
        ),
        rx.table.cell(
            rx.cond(is_wave,
                    rx.text(rx.cond(item["end_time"] != "", item["end_time"], "–"), **mono_dim),
                    rx.box()),
            display=rx.cond(AppState.wave_show_end_time, "table-cell", "none"), **td,
        ),
        rx.table.cell(
            rx.cond(is_wave,
                    rx.text(rx.cond(item["duration"] != "", item["duration"], "–"), **mono_dim),
                    rx.box()),
            display=rx.cond(AppState.wave_show_duration, "table-cell", "none"), **td,
        ),
        rx.table.cell(
            rx.cond(is_wave,
                    rx.text(rx.cond(item["age"] != "", item["age"], "–"), **mono_dim),
                    rx.box()),
            display=rx.cond(AppState.wave_show_age, "table-cell", "none"), **td,
        ),
        rx.table.cell(
            rx.cond(is_wave,
                    rx.text(rx.cond(item["log_update_age"] != "", item["log_update_age"], "–"), **mono_dim),
                    rx.box()),
            display=rx.cond(AppState.wave_show_log_update, "table-cell", "none"), **td,
        ),
        rx.table.cell(
            rx.cond(
                is_wave & (item["wave_num"] != ""),
                rx.hstack(
                    rx.box(rx.button("↑", size="2", variant="ghost",
                              color_scheme=rx.cond(item["is_first"], "gray", "blue"),
                              disabled=item["is_first"],
                              on_click=AppState.move_wave_up(item["wave"])),
                           width="28px", display="flex",
                           align_items="center", justify_content="center", flex_shrink="0"),
                    rx.box(rx.button("↓", size="2", variant="ghost",
                              color_scheme=rx.cond(item["is_last"], "gray", "blue"),
                              disabled=item["is_last"],
                              on_click=AppState.move_wave_down(item["wave"])),
                           width="28px", display="flex",
                           align_items="center", justify_content="center", flex_shrink="0"),
                    spacing="0", align="center",
                ),
                rx.box(),
            ),
            **td, text_align="center", width="56px",
        ),
        background=rx.cond(item["is_recent"], "var(--blue-3)", "transparent"),
        _hover={"background": rx.cond(item["is_recent"], "var(--blue-4)", "var(--gui-hover)")},
        id=item["row_id"],
    )


def _wave_folder_table() -> rx.Component:
    """Full table for the folder view: sticky header + foreach body rows."""
    no_waves_row = rx.table.row(
        rx.table.cell(
            rx.text("No waves found in stack config",
                    font_size="12px", color="var(--gui-text-dim)"),
            col_span=9, padding="8px 6px",
        )
    )
    return rx.table.root(
        _wave_table_header(),
        rx.table.body(
            rx.cond(
                AppState.waves_with_visibility,
                rx.foreach(AppState.waves_folder_rows, _wave_folder_item),
                no_waves_row,
            )
        ),
        size="1",
        width="100%",
        # Same flex pattern as _wave_list_table — see comment there.
        flex="1",
        min_height="0",
        overflow_y="auto",
    )




def _panel_merge_btn() -> rx.Component:
    """Button: shows 'Merge' when separated, 'Unmerge' when merged."""
    return rx.cond(
        AppState.viz_framework == "reflex",
        rx.button(
            rx.cond(AppState.is_merged, "Unmerge", "Merge"),
            on_click=AppState.toggle_merge,
            variant="outline",
            size="1",
            title="Merge all providers into a single tree view, or restore separate provider subtrees",
        ),
        rx.box(),
    )


def _panel_auto_select_btn() -> rx.Component:
    """Toggle button: auto-select the most recently applied unit in the tree."""
    return rx.button(
        "Follow",
        on_click=AppState.flip_auto_select_recent_unit,
        variant=rx.cond(AppState.auto_select_recent_unit, "solid", "outline"),
        size="1",
        title="Follow (auto-select) the most recently applied unit in the tree",
    )


def _panel_providers() -> rx.Component:
    """Providers dropdown — toggle provider visibility."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                "Providers ▾",
                variant="outline",
                size="1",
                color_scheme=rx.cond(AppState.provider_filter_active, "orange", "gray"),
                title="Show or hide infrastructure providers in the tree. Turns orange when one or more providers are hidden.",
            ),
        ),
        rx.dropdown_menu.content(
            _view_menu_providers_content(),
            padding="6px",
            align="start",
        ),
    )


def _panel_depth_slider() -> rx.Component:
    """Popover depth control: slider from 'All' (0) to _MAX_DEPTH."""
    return rx.popover.root(
        rx.popover.trigger(
            rx.button(
                "Depth: ",
                AppState.depth_button_label,
                variant="outline",
                size="1",
                title="Limit how many levels deep the tree expands (0 = show all)",
            ),
        ),
        rx.popover.content(
            rx.vstack(
                rx.hstack(
                    rx.text("Depth", font_size="12px", font_weight="600"),
                    rx.spacer(),
                    rx.text(
                        rx.cond(AppState.depth_limit == 0, "All", AppState.depth_button_label),
                        font_size="12px",
                        color="#3b82f6",
                        font_weight="600",
                        min_width="20px",
                        text_align="right",
                    ),
                    width="180px",
                    align="center",
                ),
                rx.slider(
                    min=0,
                    max=AppState.max_depth,
                    step=1,
                    value=AppState.depth_slider_value,
                    on_change=AppState.set_depth_limit,
                    width="180px",
                ),
                rx.hstack(
                    rx.text("All", font_size="10px", color="var(--gui-text-dim)"),
                    rx.spacer(),
                    rx.text(AppState.max_depth, font_size="10px", color="var(--gui-text-dim)"),
                    width="180px",
                ),
                spacing="2",
                padding="10px",
                width="200px",
            ),
            side="bottom",
            align="start",
        ),
    )


def _appearance_menu_item(label: str, checked: rx.Var, on_change, on_row_click, tooltip: str = "") -> rx.Component:
    """One row in the Appearance menu — checkbox + label, stays open on click.

    on_change is wired to the checkbox only (receives the new bool value).
    on_row_click is wired to the label text only (flip, no argument).
    Keeping them separate prevents the double-fire that occurs when a single
    click propagates to both the checkbox on_change and a parent on_click.
    """
    return rx.hstack(
        rx.checkbox(checked=checked, on_change=on_change, size="1"),
        rx.text(label, font_size="13px", on_click=on_row_click,
                cursor="pointer", flex="1"),
        align="center",
        spacing="2",
        padding_y="4px",
        padding_x="6px",
        border_radius="4px",
        width="100%",
        _hover={"background": "var(--gui-hover-soft)"},
        **({"title": tooltip} if tooltip else {}),
    )


def panels_menu() -> rx.Component:
    """Panels dropdown — controls which floating panels are visible."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button("Panels ▾", variant="ghost", size="2",
                      title="Show/hide floating panels and unit detail popup"),
        ),
        rx.dropdown_menu.content(
            rx.vstack(
                # Unit detail popup — works in both normal and floating mode
                _appearance_menu_item(
                    "Unit detail popup",
                    AppState.show_unit_popup,
                    AppState.toggle_show_unit_popup,
                    AppState.flip_show_unit_popup,
                    tooltip="Show a detail panel when clicking a unit — works in both layout modes",
                ),
                rx.separator(width="100%"),
                # Floating mode panels — require floating panels mode to be active
                _appearance_menu_item(
                    "File viewer",
                    AppState.float_file_viewer_open,
                    AppState.toggle_float_file_viewer,
                    AppState.flip_float_file_viewer,
                    tooltip="Open a floating file viewer panel (requires Floating panels mode)",
                ),
                _appearance_menu_item(
                    "Terminal",
                    AppState.float_terminal_open,
                    AppState.toggle_float_terminal,
                    AppState.flip_float_terminal,
                    tooltip="Open a floating terminal panel (requires Floating panels mode)",
                ),
                _appearance_menu_item(
                    "Object viewer",
                    AppState.float_object_viewer_open,
                    AppState.toggle_float_object_viewer,
                    AppState.flip_float_object_viewer,
                    tooltip="Open a floating object/JSON viewer panel (requires Floating panels mode)",
                ),
                spacing="0",
                padding="4px",
            ),
            rx.cond(
                AppState.panel_mode != "floating",
                rx.text(
                    "Enable Floating Panels mode\n(Appearance → Layout → Mode)\nfor file viewer, terminal,\nand object viewer",
                    font_size="11px",
                    color="var(--gui-text-dim)",
                    padding_x="8px",
                    padding_y="4px",
                    max_width="200px",
                    white_space="pre-wrap",
                ),
                rx.fragment(),
            ),
            min_width="220px",
        ),
    )


def help_menu() -> rx.Component:
    """Help dropdown in the explorer title bar."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                "Help ▾",
                variant="ghost",
                size="2",
                title="Help and information",
            ),
        ),
        rx.dropdown_menu.content(
            rx.dropdown_menu.item(
                rx.hstack(rx.icon("book-open", size=14), rx.text("Docs (GUI)"),
                          spacing="2", align="center"),
                on_click=AppState.open_docs,
                title="Open the GUI user documentation in a new browser tab",
            ),
            rx.dropdown_menu.item(
                rx.hstack(rx.icon("book-open", size=14), rx.text("Docs (Engine)"),
                          spacing="2", align="center"),
                on_click=AppState.open_docs_engine,
                title="Open the infrastructure engine documentation in a new browser tab",
            ),
            rx.dropdown_menu.item(
                rx.hstack(rx.icon("book-open", size=14), rx.text("Topics"),
                          spacing="2", align="center"),
                on_click=AppState.open_docs_topics,
                title="Browse documentation topics for the infrastructure framework",
            ),
            rx.dropdown_menu.item(
                rx.hstack(rx.icon("book-open", size=14), rx.text("Scripts"),
                          spacing="2", align="center"),
                on_click=AppState.open_docs_scripts,
                title="Browse available scripts: wave scripts, Terragrunt hooks, and ai-only utilities",
            ),
            rx.dropdown_menu.separator(),
            rx.dropdown_menu.item(
                rx.hstack(rx.icon("info", size=14), rx.text("About"),
                          spacing="2", align="center"),
                on_click=AppState.open_help_about,
                title="Show app version, Python/Reflex versions, and current configuration",
            ),
            rx.dropdown_menu.item(
                rx.hstack(rx.icon("scroll-text", size=14), rx.text("License"),
                          spacing="2", align="center"),
                on_click=AppState.open_help_license,
                title="View the software license",
            ),
        ),
    )


def _appearance_section(
    title: str,
    is_open: rx.Var,
    on_toggle,
    *children,
) -> rx.Component:
    """Collapsible titled section for the appearance menu accordion."""
    return rx.vstack(
        rx.hstack(
            rx.text(
                rx.cond(is_open, "▾", "▸"),
                " ",
                title,
                font_size="11px",
                font_weight="600",
                color="var(--gui-text-muted)",
                text_transform="uppercase",
                letter_spacing="0.06em",
            ),
            on_click=on_toggle,
            cursor="pointer",
            padding_x="6px",
            padding_y="6px",
            width="100%",
            _hover={"background": "var(--gui-hover-soft)"},
            border_radius="4px",
        ),
        rx.cond(
            is_open,
            rx.vstack(*children, spacing="0", padding_x="4px", padding_bottom="4px"),
            rx.fragment(),
        ),
        rx.separator(width="100%"),
        spacing="0",
        width="100%",
    )


def appearance_menu() -> rx.Component:
    """Appearance dropdown — controls which widgets are shown in the controls bar."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                "Appearance ▾",
                variant="ghost",
                size="2",
                title="Customise which controls appear in the bar and panel layout options",
            ),
        ),
        rx.dropdown_menu.content(
            rx.vstack(
                # ── Show in controls bar ───────────────────────────────────
                _appearance_section(
                    "Show in controls bar",
                    AppState.appear_s_controls,
                    AppState.flip_appear_s_controls,
                    _appearance_menu_item(
                        "View selector",
                        AppState.panel_show_view_selector,
                        AppState.toggle_panel_view_selector,
                        AppState.flip_panel_view_selector,
                        tooltip="Show the Infra/Modules/Packages/Ansible Inventory switcher in the top bar",
                    ),
                    _appearance_menu_item(
                        "Show merged",
                        AppState.panel_show_merged,
                        AppState.toggle_panel_merged,
                        AppState.flip_panel_merged,
                        tooltip="Show the merged-view toggle in the top bar (combines applied + to-apply units)",
                    ),
                    _appearance_menu_item(
                        "Depth",
                        AppState.panel_show_depth,
                        AppState.toggle_panel_depth,
                        AppState.flip_panel_depth,
                        tooltip="Show the tree depth limit slider in the top bar",
                    ),
                ),
                # ── Infra tree ─────────────────────────────────────────────
                _appearance_section(
                    "Infra tree",
                    AppState.appear_s_infra,
                    AppState.flip_appear_s_infra,
                    _appearance_menu_item(
                        "Show full module name",
                        AppState.show_full_module_name,
                        AppState.toggle_show_full_module_name,
                        AppState.flip_show_full_module_name,
                        tooltip="Show the full Terraform module path on each tree node instead of the short display name",
                    ),
                    _appearance_menu_item(
                        "Show wave numbers",
                        AppState.show_wave_numbers,
                        AppState.toggle_show_wave_numbers,
                        AppState.flip_show_wave_numbers,
                        tooltip="Prefix each tree node with its wave number (e.g. [12] machine-name)",
                    ),
                    _appearance_menu_item(
                        "Show build status",
                        AppState.show_unit_build_status,
                        AppState.toggle_show_unit_build_status,
                        AppState.flip_show_unit_build_status,
                        tooltip="Colour tree nodes by their last known build state (applied / destroyed / unknown)",
                    ),
                    rx.cond(
                        AppState.show_unit_build_status,
                        rx.vstack(
                            rx.hstack(
                                rx.button(
                                    rx.cond(
                                        AppState.is_refreshing_build_statuses,
                                        "⟳ Updating…",
                                        "⟳ Refresh",
                                    ),
                                    size="1",
                                    variant="soft",
                                    color_scheme=rx.cond(
                                        AppState.is_refreshing_build_statuses,
                                        "yellow",
                                        "gray",
                                    ),
                                    disabled=AppState.is_refreshing_build_statuses,
                                    on_click=AppState.refresh_unit_build_statuses,
                                    font_size="11px",
                                    title="Read unit-state.yaml (fast, no GCS)",
                                ),
                                rx.button(
                                    "Validate (GCS)",
                                    size="1",
                                    variant="soft",
                                    color_scheme="blue",
                                    disabled=AppState.is_refreshing_build_statuses,
                                    on_click=AppState.validate_unit_build_statuses,
                                    font_size="11px",
                                    title="Full GCS scan — authoritative but slower",
                                ),
                                spacing="2",
                                padding_y="3px",
                                padding_x="22px",
                            ),
                            rx.hstack(
                                rx.checkbox(
                                    checked=AppState.unit_status_auto_refresh,
                                    on_change=AppState.toggle_unit_status_auto_refresh,
                                    size="1",
                                    title="Automatically re-read build status when unit-state.yaml changes or the interval elapses",
                                ),
                                rx.text(
                                    "Auto-refresh",
                                    font_size="12px",
                                    cursor="pointer",
                                    on_click=AppState.flip_unit_status_auto_refresh,
                                    flex="1",
                                    title="Automatically re-read build status when unit-state.yaml changes or the interval elapses",
                                ),
                                rx.cond(
                                    AppState.unit_status_auto_refresh,
                                    rx.hstack(
                                        rx.select(
                                            ["0", "10", "15", "30", "60", "120", "300"],
                                            value=AppState.unit_status_auto_refresh_secs.to_string(),
                                            on_change=lambda v: AppState.set_unit_status_auto_refresh_secs(v.to(int)),
                                            size="1",
                                            width="68px",
                                            title="Interval in seconds (0 = on file-change only)",
                                        ),
                                        rx.text("s", font_size="11px", color="var(--gui-text-dim)"),
                                        spacing="1",
                                        align="center",
                                    ),
                                    rx.fragment(),
                                ),
                                align="center",
                                spacing="2",
                                padding_y="4px",
                                padding_x="22px",
                                width="100%",
                            ),
                            rx.cond(
                                AppState.build_status_error != "",
                                rx.text(
                                    AppState.build_status_error,
                                    color="var(--red-11)",
                                    font_size="11px",
                                    padding_x="22px",
                                    padding_bottom="4px",
                                    white_space="pre-wrap",
                                    max_width="260px",
                                ),
                                rx.fragment(),
                            ),
                            spacing="0",
                            width="100%",
                        ),
                        rx.box(),
                    ),
                ),
                # ── Wave panel ─────────────────────────────────────────────
                _appearance_section(
                    "Wave panel",
                    AppState.appear_s_wave,
                    AppState.flip_appear_s_wave,
                    _appearance_menu_item(
                        "Start time",
                        AppState.wave_show_start_time,
                        AppState.toggle_wave_show_start_time,
                        AppState.flip_wave_show_start_time,
                        tooltip="Show the wave start time column in the wave panel",
                    ),
                    _appearance_menu_item(
                        "End time",
                        AppState.wave_show_end_time,
                        AppState.toggle_wave_show_end_time,
                        AppState.flip_wave_show_end_time,
                        tooltip="Show the wave end time column in the wave panel",
                    ),
                    _appearance_menu_item(
                        "Duration",
                        AppState.wave_show_duration,
                        AppState.toggle_wave_show_duration,
                        AppState.flip_wave_show_duration,
                        tooltip="Show the wave run duration column in the wave panel",
                    ),
                    _appearance_menu_item(
                        "Age",
                        AppState.wave_show_age,
                        AppState.toggle_wave_show_age,
                        AppState.flip_wave_show_age,
                        tooltip="Show how long ago the wave last ran in the wave panel",
                    ),
                    _appearance_menu_item(
                        "Last Update",
                        AppState.wave_show_log_update,
                        AppState.toggle_wave_show_log_update,
                        AppState.flip_wave_show_log_update,
                        tooltip="Show the time of the most recent log-file write for each wave",
                    ),
                    _appearance_menu_item(
                        "Highlight recent wave",
                        AppState.wave_highlight_recent,
                        AppState.toggle_wave_highlight_recent,
                        AppState.flip_wave_highlight_recent,
                        tooltip="Highlight the most-recently-run wave with a coloured border",
                    ),
                ),
                # ── File viewer ────────────────────────────────────────────
                _appearance_section(
                    "File viewer",
                    AppState.appear_s_file,
                    AppState.flip_appear_s_file,
                    _appearance_menu_item(
                        "Render markdown files",
                        AppState.file_viewer_render_markdown,
                        AppState.toggle_file_viewer_render_markdown,
                        AppState.flip_file_viewer_render_markdown,
                        tooltip="Render .md files as formatted HTML instead of showing raw text",
                    ),
                    _appearance_menu_item(
                        "Show line numbers",
                        AppState.file_viewer_show_line_numbers,
                        AppState.toggle_file_viewer_show_line_numbers,
                        AppState.flip_file_viewer_show_line_numbers,
                        tooltip="Show line numbers in the file viewer code pane",
                    ),
                ),
                # ── Terminal ───────────────────────────────────────────────
                _appearance_section(
                    "Terminal",
                    AppState.appear_s_terminal,
                    AppState.flip_appear_s_terminal,
                    _appearance_menu_item(
                        "Hide auto-run commands",
                        AppState.terminal_hide_initial_cmd,
                        AppState.toggle_terminal_hide_initial_cmd,
                        AppState.flip_terminal_hide_initial_cmd,
                        tooltip="Hide the initial auto-run command from the terminal display (the command still runs)",
                    ),
                    rx.hstack(
                        rx.text("Backend", font_size="12px", color="var(--gui-text-primary)", flex="1",
                                title="xterm.js: built-in, no install required. ttyd: native shell with full PTY support, requires a separate install."),
                        rx.select.root(
                            rx.select.trigger(size="1",
                                              title="xterm.js: built-in, no install required. ttyd: native shell with full PTY support, requires a separate install."),
                            rx.select.content(
                                *[
                                    rx.select.item(b["label"], value=b["id"])
                                    for b in _TERMINAL_BACKENDS
                                ],
                            ),
                            value=AppState.terminal_backend,
                            on_change=AppState.set_terminal_backend,
                            size="1",
                        ),
                        align="center",
                        padding_x="6px",
                        padding_y="4px",
                    ),
                    *(
                        [rx.cond(
                            AppState.terminal_backend == "ttyd",
                            rx.hstack(
                                rx.icon("triangle-alert", size=12, color="var(--amber-9)"),
                                rx.text(
                                    f"Install: {_TTYD_INSTALL_CMD}",
                                    font_size="11px",
                                    color="var(--amber-9)",
                                    flex="1",
                                ),
                                rx.button(
                                    "Install",
                                    on_click=AppState.install_ttyd,
                                    size="1",
                                    variant="soft",
                                    color_scheme="amber",
                                ),
                                align="center",
                                padding_x="6px",
                                padding_y="4px",
                                gap="6px",
                            ),
                        )]
                        if not _TTYD_AVAILABLE else []
                    ),
                ),
                # ── Params panel ───────────────────────────────────────────
                _appearance_section(
                    "Params panel",
                    AppState.appear_s_params,
                    AppState.flip_appear_s_params,
                    _appearance_menu_item(
                        "Wrap long values",
                        AppState.param_wrap_values,
                        AppState.toggle_param_wrap_values,
                        AppState.flip_param_wrap_values,
                        tooltip="Wrap long parameter values to multiple lines instead of truncating with ellipsis",
                    ),
                ),
                # ── Nested networks ────────────────────────────────────────
                _appearance_section(
                    "Nested networks",
                    AppState.appear_s_networks,
                    AppState.flip_appear_s_networks,
                    _appearance_menu_item(
                        "Show dependency arrows",
                        AppState.cy_show_dependencies,
                        AppState.toggle_cy_show_dependencies,
                        AppState.flip_cy_show_dependencies,
                        tooltip="Draw directed arrows between nodes to show Terraform dependencies",
                    ),
                    _appearance_menu_item(
                        "Color nodes by wave",
                        AppState.cy_color_by_wave,
                        AppState.toggle_cy_color_by_wave,
                        AppState.flip_cy_color_by_wave,
                        tooltip="Colour each node in the dependency graph by its wave number",
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text(
                                "Zoom Speed",
                                font_size="13px",
                                title=(
                                    "Controls how fast the Nested Networks view zooms "
                                    "when scrolling. Lower = slower/finer zoom."
                                ),
                            ),
                            rx.spacer(),
                            rx.text(
                                AppState.cy_wheel_sensitivity_label,
                                font_size="12px",
                                color="var(--gui-text-muted)",
                                font_weight="600",
                                min_width="32px",
                                text_align="right",
                            ),
                            width="100%",
                            align="center",
                        ),
                        rx.slider(
                            min=0.05,
                            max=1.0,
                            step=0.05,
                            value=AppState.cy_wheel_sensitivity_list,
                            on_change=AppState.set_cy_wheel_sensitivity,
                            width="100%",
                        ),
                        spacing="1",
                        padding_x="6px",
                        padding_y="6px",
                        width="100%",
                    ),
                ),
                # ── Framework Repos diagram ────────────────────────────────
                _appearance_section(
                    "Framework Repos diagram",
                    AppState.appear_s_fw_repos,
                    AppState.flip_appear_s_fw_repos,
                    rx.hstack(
                        rx.button(
                            rx.cond(
                                AppState.fw_repos_refreshing,
                                rx.hstack(rx.spinner(size="1"), rx.text("Refreshing…"), spacing="1"),
                                "⟳ Refresh",
                            ),
                            size="1",
                            variant="soft",
                            on_click=AppState.refresh_fw_repos_data,
                            disabled=AppState.fw_repos_refreshing,
                            title="Re-run fw-repos-diagram-exporter and reload diagram",
                        ),
                        width="100%",
                        padding_x="4",
                        padding_y="2",
                        align="center",
                    ),
                    rx.hstack(
                        rx.text("Git", size="2",
                                title="Show or hide the Git section (url: ...) in each repo class box"),
                        rx.spacer(),
                        rx.select.root(
                            rx.select.trigger(size="1"),
                            rx.select.content(
                                rx.select.item("Hide", value="hide"),
                                rx.select.item("Show", value="show"),
                            ),
                            value=AppState.fw_repos_git,
                            on_change=AppState.set_fw_repos_git,
                            size="1",
                        ),
                        width="100%",
                        padding_x="4",
                        padding_y="2",
                        align="center",
                    ),
                    rx.hstack(
                        rx.text("Main Package", size="2",
                                title="Show or hide the Main Package section in each repo class box"),
                        rx.spacer(),
                        rx.select.root(
                            rx.select.trigger(size="1"),
                            rx.select.content(
                                rx.select.item("Hide", value="hide"),
                                rx.select.item("Show", value="show"),
                            ),
                            value=AppState.fw_repos_config_pkg,
                            on_change=AppState.set_fw_repos_config_pkg,
                            size="1",
                        ),
                        width="100%",
                        padding_x="4",
                        padding_y="2",
                        align="center",
                    ),
                    rx.hstack(
                        rx.text("Labels", size="2",
                                title="Show or hide the Labels section (_purpose, _docs, etc.) in each repo class box"),
                        rx.spacer(),
                        rx.select.root(
                            rx.select.trigger(size="1"),
                            rx.select.content(
                                rx.select.item("Hide", value="hide"),
                                rx.select.item("Show", value="show"),
                            ),
                            value=AppState.fw_repos_labels,
                            on_change=AppState.set_fw_repos_labels,
                            size="1",
                        ),
                        width="100%",
                        padding_x="4",
                        padding_y="2",
                        align="center",
                    ),
                    rx.hstack(
                        rx.text("Backend", size="2",
                                title="Controls how much of the framework_backend config is shown in each repo box"),
                        rx.spacer(),
                        rx.select.root(
                            rx.select.trigger(size="1"),
                            rx.select.content(
                                rx.select.item("Hide",     value="hide"),
                                rx.select.item("Summary",  value="summary"),
                                rx.select.item("Show all", value="all"),
                            ),
                            value=AppState.fw_repos_backend,
                            on_change=AppState.set_fw_repos_backend,
                            size="1",
                        ),
                        width="100%",
                        padding_x="4",
                        padding_y="2",
                        align="center",
                    ),
                    rx.hstack(
                        rx.text("Packages", size="2",
                                title="Show packages and control their sort order in each repo class box"),
                        rx.spacer(),
                        rx.select.root(
                            rx.select.trigger(size="1"),
                            rx.select.content(
                                rx.select.item("Hide",      value="hide"),
                                rx.select.item("A-Z",       value="a-z"),
                                rx.select.item("From-code", value="from-code"),
                            ),
                            value=AppState.fw_repos_packages,
                            on_change=AppState.set_fw_repos_packages,
                            size="1",
                        ),
                        width="100%",
                        padding_x="4",
                        padding_y="2",
                        align="center",
                    ),
                    rx.hstack(
                        rx.text("Inaccessible repos", size="2",
                                title="Requires check_accessibility: true in framework_repos_visualizer.yaml and a --refresh scan"),
                        rx.spacer(),
                        rx.select.root(
                            rx.select.trigger(size="1"),
                            rx.select.content(
                                rx.select.item("Show (normal)", value="normal"),
                                rx.select.item("Show (red)",    value="red"),
                                rx.select.item("Show (black)",  value="black"),
                                rx.select.item("Hide",          value="hide"),
                            ),
                            value=AppState.fw_repos_inaccessible,
                            on_change=AppState.set_fw_repos_inaccessible,
                            size="1",
                        ),
                        width="100%",
                        padding_x="4",
                        padding_y="2",
                        align="center",
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text("Zoom", font_size="13px"),
                            rx.spacer(),
                            rx.text(
                                AppState.fw_repos_zoom_label,
                                font_size="12px",
                                color="var(--gui-text-muted)",
                                font_weight="600",
                                min_width="36px",
                                text_align="right",
                            ),
                            width="100%",
                            align="center",
                        ),
                        rx.slider(
                            min=10,
                            max=_FW_REPOS_ZOOM_MAX,
                            step=5,
                            value=AppState.fw_repos_zoom_list,
                            on_change=AppState.set_fw_repos_zoom,
                            width="100%",
                        ),
                        spacing="1",
                        padding_x="6px",
                        padding_y="6px",
                        width="100%",
                    ),
                ),
                # ── Layout ─────────────────────────────────────────────────
                _appearance_section(
                    "Layout",
                    AppState.appear_s_layout,
                    AppState.flip_appear_s_layout,
                    _appearance_menu_item(
                        "Status bar",
                        AppState.show_status_bar,
                        AppState.toggle_show_status_bar,
                        AppState.flip_show_status_bar,
                        tooltip="Show the status bar at the bottom of the app with build state and GCS sync info",
                    ),
                    rx.hstack(
                        rx.text(
                            "Mode:",
                            font_size="13px",
                            title="Switch between 4-panel grid, draggable floating panels, or tabbed panels",
                        ),
                        rx.spacer(),
                        rx.select.root(
                            rx.select.trigger(size="1"),
                            rx.select.content(
                                rx.select.item("4-panels",        value="4-panels"),
                                rx.select.item("Floating Panels", value="floating"),
                                rx.select.item("Tabbed Panels",   value="tabbed"),
                            ),
                            value=AppState.panel_mode,
                            on_change=AppState.set_panel_mode,
                            size="1",
                        ),
                        width="100%",
                        align="center",
                        padding_x="6px",
                        padding_y="6px",
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text(
                                "Drag Width",
                                font_size="13px",
                                title=(
                                    "Pixel thickness of the draggable dividers between panels. "
                                    "Increase if they are hard to catch with the mouse."
                                ),
                            ),
                            rx.spacer(),
                            rx.text(
                                AppState.resizer_drag_width_px,
                                font_size="12px",
                                color="var(--gui-text-muted)",
                                font_weight="600",
                                min_width="28px",
                                text_align="right",
                            ),
                            width="100%",
                            align="center",
                        ),
                        rx.slider(
                            min=4,
                            max=24,
                            step=1,
                            value=AppState.resizer_drag_width_list,
                            on_change=AppState.set_resizer_drag_width,
                            width="100%",
                        ),
                        spacing="1",
                        padding_x="6px",
                        padding_y="6px",
                        width="100%",
                    ),
                ),
                # ── Theme & App ────────────────────────────────────────────
                _appearance_section(
                    "Theme & App",
                    AppState.appear_s_theme,
                    AppState.flip_appear_s_theme,
                    rx.hstack(
                        rx.cond(
                            AppState.ui_theme == "light",
                            rx.button("☀ Light", on_click=[AppState.set_ui_theme("light"), _set_color_mode("light"), rx.call_script(_apply_color_mode_js("light"))], size="1", variant="solid", color_scheme="gray", flex="1", title="Switch to light colour theme (currently active)"),
                            rx.button("☀ Light", on_click=[AppState.set_ui_theme("light"), _set_color_mode("light"), rx.call_script(_apply_color_mode_js("light"))], size="1", variant="soft", color_scheme="gray", flex="1", title="Switch to light colour theme"),
                        ),
                        rx.cond(
                            AppState.ui_theme == "dark",
                            rx.button("☾ Dark", on_click=[AppState.set_ui_theme("dark"), _set_color_mode("dark"), rx.call_script(_apply_color_mode_js("dark"))], size="1", variant="solid", color_scheme="gray", flex="1", title="Switch to dark colour theme (currently active)"),
                            rx.button("☾ Dark", on_click=[AppState.set_ui_theme("dark"), _set_color_mode("dark"), rx.call_script(_apply_color_mode_js("dark"))], size="1", variant="soft", color_scheme="gray", flex="1", title="Switch to dark colour theme"),
                        ),
                        spacing="2",
                        padding_x="6px",
                        padding_bottom="4px",
                        width="100%",
                    ),
                    rx.hstack(
                        rx.button(
                            "↺ Refresh",
                            on_click=rx.call_script("window.location.reload()"),
                            size="2",
                            variant="soft",
                            color_scheme="gray",
                            title="Reload the GUI app page",
                            flex="1",
                        ),
                        rx.dropdown_menu.root(
                            rx.dropdown_menu.trigger(
                                rx.button(
                                    "Open in ▾",
                                    size="2",
                                    variant="soft",
                                    color_scheme="blue",
                                    title="Open the GUI app in a browser window",
                                ),
                            ),
                            rx.dropdown_menu.content(
                                rx.dropdown_menu.item(
                                    "PyCharm Preview",
                                    on_select=AppState.open_app_in_browser("pycharm"),
                                ),
                                rx.dropdown_menu.item(
                                    "Default browser",
                                    on_select=AppState.open_app_in_browser("default"),
                                ),
                                rx.dropdown_menu.separator(),
                                rx.foreach(
                                    AppState.chrome_profiles,
                                    lambda p: rx.cond(
                                        p["id"] != "playwright",
                                        rx.dropdown_menu.item(
                                            p["label"],
                                            on_select=AppState.open_app_in_browser(p["id"]),
                                        ),
                                        rx.box(),
                                    ),
                                ),
                                align="end",
                            ),
                        ),
                        spacing="2",
                        padding_x="6px",
                        padding_bottom="6px",
                        width="100%",
                    ),
                ),
                spacing="0",
                width="100%",
            ),
            align="start",
            min_width="240px",
            max_height="80vh",
            overflow_y="auto",
        ),
    )


# ---------------------------------------------------------------------------
# UI: navbar + panels
# ---------------------------------------------------------------------------

def _panel_header(label: str, extra: rx.Component | None = None) -> rx.Component:
    return rx.hstack(
        rx.text(label, font_size="11px", font_weight="600", color="var(--gui-text-dim)",
                text_transform="uppercase", letter_spacing="0.05em"),
        rx.spacer(),
        extra or rx.box(),
        align="center",
        padding_x="12px",
        padding_y="6px",
        border_bottom="1px solid var(--gui-border)",
        background="var(--gui-panel-bg)",
        width="100%",
        height="36px",
    )




def _panel_maximize_btn(panel_id: str) -> rx.Component:
    """Window-manager maximize / restore button for a panel header corner."""
    is_this = AppState.maximized_panel == panel_id
    return rx.cond(
        is_this,
        # Restore button — shown in the maximized panel
        rx.button(
            "⤡",
            on_click=AppState.set_maximized_panel(""),
            size="1",
            variant="ghost",
            color="var(--gui-text-dim)",
            _hover={"color": "var(--gui-text-primary)", "background": "var(--gui-hover)"},
            flex_shrink="0",
            title="Restore 4-panel layout",
        ),
        # Maximize button — shown in normal mode (hidden automatically when another
        # panel is maximized because the whole panel is unmounted)
        rx.button(
            "⤢",
            on_click=AppState.set_maximized_panel(panel_id),
            size="1",
            variant="ghost",
            color="var(--gui-text-dim)",
            _hover={"color": "var(--gui-text-primary)", "background": "var(--gui-hover)"},
            flex_shrink="0",
            title="Maximize this panel",
        ),
    )


def panel_resizer() -> rx.Component:
    """Thin draggable bar between the left and right panels.

    on_mount installs the resizer JS once this component is in the DOM.
    Using on_mount here (inner component) rather than on the page root avoids
    triggering a second on_load cycle through Reflex's root-level event handling.
    """
    return rx.box(
        width=AppState.resizer_drag_width_px,
        height="100%",
        cursor="col-resize",
        background="var(--gui-border)",
        flex_shrink="0",
        _hover={"background": "#c7d2fe"},
        id="panel-resizer",
        title="Drag to resize panels · adjust width in Appearance → Drag Width",
    )


def _explorer_root_selector() -> rx.Component:
    """Dropdown to switch the explorer root: Infra / Modules / Packages / Ansible Inventory / Framework Repos."""
    label = rx.match(
        AppState.explorer_root,
        ("modules",           "Modules ▾"),
        ("packages",          "Packages ▾"),
        ("ansible_inventory", "Ansible Inventory ▾"),
        ("framework_repos",   "Framework Repos ▾"),
        "Infra ▾",
    )
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                label,
                variant="solid",
                size="1",
                color_scheme="blue",
                title="Switch the explorer between Infra, Modules, Packages, and Ansible Inventory views",
            ),
        ),
        rx.dropdown_menu.content(
            rx.dropdown_menu.item(
                "Infra",
                on_click=AppState.set_explorer_root("infra"),
                title="Browse the infrastructure tree: Terragrunt units organised by package and wave",
            ),
            rx.dropdown_menu.item(
                "Modules",
                on_click=AppState.set_explorer_root("modules"),
                title="Browse Terraform module definitions: reusable building blocks shared across units",
            ),
            rx.dropdown_menu.item(
                "Packages",
                on_click=AppState.set_explorer_root("packages"),
                title="Browse packages: top-level groupings of infrastructure (e.g. maas-pkg, de3-gui-pkg)",
            ),
            rx.dropdown_menu.item(
                "Ansible Inventory",
                on_click=AppState.set_explorer_root("ansible_inventory"),
                title="Browse the dynamic Ansible inventory: hosts grouped by role and wave",
            ),
            rx.dropdown_menu.item(
                "Framework Repos",
                on_click=AppState.set_explorer_root("framework_repos"),
                title="Visualise framework package repositories and their lineage",
            ),
            align="start",
        ),
    )


def left_panel() -> rx.Component:
    """Top-left explorer panel content (controls bar + viz area)."""
    # Search input — shown for all explorer roots
    search_box = rx.hstack(
        rx.input(
            placeholder="Search…",
            value=AppState.explorer_search,
            on_change=AppState.set_explorer_search,
            size="1",
            width="280px",
            title="Filter nodes by name — shows matching nodes and their ancestor paths",
            color_scheme=rx.cond(AppState.explorer_search_active, "orange", "gray"),
            color=rx.cond(AppState.explorer_search_active, "var(--orange-11)", "inherit"),
        ),
        rx.cond(
            AppState.explorer_search_active,
            rx.button(
                "×",
                on_click=AppState.clear_explorer_search,
                size="2",
                variant="ghost",
                color_scheme="gray",
                title="Clear search filter",
                padding_x="10px",
                padding_y="6px",
                font_size="16px",
                cursor="pointer",
            ),
            rx.box(),
        ),
        spacing="0",
        align="center",
    )

    _divider = rx.box(width="1px", height="20px", background="var(--gui-divider)", flex_shrink="0", margin_x="4px")

    # Row 1: Filters — only shown for the "infra" explorer root.
    filter_bar = rx.hstack(
        _panel_packages(),
        _divider,
        _panel_providers(),
        _divider,
        rx.cond(AppState.has_stack_config, _panel_regions(), rx.box()),
        _divider,
        rx.cond(AppState.has_stack_config, _panel_envs(), rx.box()),
        _divider,
        _panel_roles(),
        _divider,
        search_box,
        align="center",
        spacing="2",
        padding_x="8px",
        padding_y="4px",
        border_bottom="1px solid var(--gui-border)",
        background="var(--gui-panel-bg)",
        width="100%",
        flex_shrink="0",
        height="36px",
    )

    # Row 2: View controls (root selector, view, depth, merge, appearance, maximize)
    control_bar = rx.hstack(
        rx.text(_APP_TITLE, font_size="14px", font_weight="600",
                color="var(--gui-text-primary)", white_space="nowrap", flex_shrink="0"),
        _divider,
        _explorer_root_selector(),
        _divider,
        rx.cond(
            AppState.explorer_root == "infra",
            rx.fragment(
                rx.cond(AppState.panel_show_view_selector, _panel_view_selector(), rx.box()),
                rx.cond(AppState.panel_show_depth, _panel_depth_slider(), rx.box()),
                _divider,
                rx.cond(AppState.panel_show_merged, _panel_merge_btn(), rx.box()),
                _panel_auto_select_btn(),
            ),
            rx.box(),
        ),
        rx.spacer(),
        appearance_menu(),
        rx.separator(orientation="vertical", height="16px"),
        panels_menu(),
        rx.separator(orientation="vertical", height="16px"),
        help_menu(),
        rx.separator(orientation="vertical", height="16px"),
        _panel_maximize_btn("top-left"),
        align="center",
        spacing="2",
        padding_x="8px",
        padding_y="4px",
        border_bottom="1px solid var(--gui-border)",
        background="var(--gui-panel-bg)",
        width="100%",
        flex_shrink="0",
        height="36px",
    )

    clipboard_banner = rx.cond(
        AppState.clipboard_message != "",
        rx.hstack(
            rx.text(
                AppState.clipboard_message,
                font_size="12px",
                color=rx.cond(AppState.clipboard_message_is_error, "#ef4444", "#22c55e"),
                flex="1",
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
            ),
            rx.button(
                "×",
                size="1",
                variant="ghost",
                color_scheme="gray",
                on_click=AppState.clear_clipboard_message,
                padding="0 4px",
                min_width="0",
                font_size="14px",
                line_height="1",
            ),
            align="center",
            spacing="1",
            padding_x="8px",
            padding_y="2px",
            background="var(--gui-panel-bg)",
            border_bottom="1px solid var(--gui-border)",
            width="100%",
            flex_shrink="0",
        ),
        rx.box(),
    )

    return rx.box(
        control_bar,
        rx.cond(AppState.explorer_root == "infra", filter_bar, rx.box()),
        clipboard_banner,
        rx.box(
            render_left_panel_content(),
            flex="1",
            overflow="hidden",
        ),
        display="flex",
        flex_direction="column",
        width="100%",
        height="100%",
        overflow="hidden",
    )


def _refactor_unit_row(unit: dict) -> rx.Component:
    """Row for a single unit in the refactor preview list."""
    return rx.text(
        "• ", unit["dst_rel"],
        font_size="11px", font_family="monospace",
        color="var(--gui-text-dim)",
        padding_left="8px",
        white_space="nowrap",
        overflow="hidden",
        text_overflow="ellipsis",
    )


def _refactor_dep_row(dep: dict) -> rx.Component:
    """Row for an external dependency warning."""
    return rx.vstack(
        rx.text(
            dep["hcl_file"], ":", dep["line"],
            font_size="11px", font_family="monospace",
            color="#f59e0b",
        ),
        rx.text(
            "  refs: ", dep["old_ref"],
            font_size="11px", font_family="monospace",
            color="var(--gui-text-dim)",
        ),
        spacing="0",
        padding_left="8px",
        align_items="start",
    )


def _refactor_preview_section() -> rx.Component:
    """Preview dry-run results -- units, state files, config keys."""
    _fs = "12px"
    _dim = "var(--gui-text-dim)"
    return rx.cond(
        AppState.refactor_preview_result != {},
        rx.vstack(
            rx.text(
                "Units to process: ",
                AppState.refactor_preview_result.get("units_found", 0),
                font_size=_fs, color=_dim, font_weight="600",
            ),
            rx.cond(
                AppState.refactor_preview_external_deps.length() > 0,
                rx.vstack(
                    rx.text(
                        "\u26a0 External dependencies \u2014 update manually:",
                        font_size=_fs, color="#f59e0b", font_weight="600",
                    ),
                    rx.foreach(
                        AppState.refactor_preview_external_deps,
                        _refactor_dep_row,
                    ),
                    spacing="1", align_items="start", width="100%",
                ),
                rx.box(),
            ),
            rx.text(
                "State files: ",
                AppState.refactor_preview_result.get("state_files_migrated", 0),
                " to migrate, ",
                AppState.refactor_preview_result.get("state_files_skipped", 0),
                " skipped (not yet applied)",
                font_size=_fs, color=_dim,
            ),
            rx.text(
                "Config keys: ",
                AppState.refactor_preview_result.get("config_keys_migrated", 0),
                " public, ",
                AppState.refactor_preview_result.get("secret_keys_migrated", 0),
                " secrets",
                font_size=_fs, color=_dim,
            ),
            spacing="1", align_items="start", width="100%",
        ),
        rx.box(),
    )


def _refactor_panel() -> rx.Component:
    """Refactor panel — move/copy a unit tree via the unit-mgr CLI."""
    _dim = "var(--gui-text-dim)"
    _mono = "monospace"
    _fs = "12px"

    preview_units_section = _refactor_preview_section()

    _detail_text_style = {"font_size": "11px", "color": _dim, "line_height": "1.5"}
    _detail_heading_style = {"font_size": "11px", "color": "var(--gui-text-primary)",
                             "font_weight": "600"}

    details_block = rx.cond(
        AppState.refactor_show_details,
        rx.vstack(
            rx.text("What the unit manager refactors:", **_detail_heading_style),
            rx.text("• Unit directories — the Terragrunt tree (terragrunt.hcl and all files beneath it)", **_detail_text_style),
            rx.text("• Config YAML keys — config_params entries in infra/<pkg>/_config/<pkg>.yaml", **_detail_text_style),
            rx.text("• SOPS secrets — matching entries in secrets.sops.yaml (decrypted, migrated, re-encrypted atomically)", **_detail_text_style),
            rx.text("• GCS Terraform state — .tfstate blobs and lock files at gs://bucket/<path>/…", **_detail_text_style),
            rx.text("• Internal dependency refs — dependencies { paths = [...] } entries inside the moved tree are patched", **_detail_text_style),
            rx.text("External dependency references (from outside the tree pointing in) are flagged for manual update, not auto-patched.",
                    font_size="11px", color="#f59e0b", font_style="italic", margin_top="4px"),
            spacing="1",
            align_items="start",
            width="100%",
            padding="8px 10px",
            background="var(--gui-hover)",
            border_radius="6px",
            border="1px solid var(--gui-border)",
        ),
        rx.box(),
    )

    _sep = rx.box(width="100%", height="1px", background="var(--gui-border)", flex_shrink="0")

    return rx.scroll_area(
        rx.vstack(
            details_block,
            _sep,
            # ── Operation ────────────────────────────────────────────────
            rx.vstack(
                rx.text("Operation", font_size=_fs, color=_dim, font_weight="600"),
                rx.hstack(
                    rx.button(
                        "Move",
                        size="1",
                        variant=rx.cond(AppState.refactor_operation == "move", "solid", "soft"),
                        color_scheme="blue",
                        on_click=AppState.set_refactor_operation("move"),
                        title="Move units, config, and state, recursively to a new path",
                    ),
                    rx.button(
                        "Copy",
                        size="1",
                        variant=rx.cond(AppState.refactor_operation == "copy", "solid", "soft"),
                        color_scheme="blue",
                        on_click=AppState.set_refactor_operation("copy"),
                        title="Copy units, config, and state, recursively to a new path",
                    ),
                    rx.button(
                        "Delete",
                        size="1",
                        variant=rx.cond(AppState.refactor_operation == "delete", "solid", "soft"),
                        color_scheme="red",
                        on_click=AppState.set_refactor_operation("delete"),
                        title="Delete units, config, and state, recursively",
                    ),
                    spacing="2", align="center",
                ),
                spacing="1", align_items="start", width="100%",
            ),
            _sep,
            # ── Source ───────────────────────────────────────────────────
            rx.vstack(
                rx.text("Source", font_size=_fs, color=_dim, font_weight="600",
                        title="The unit path being refactored"),
                rx.text(
                    AppState.refactor_src_path,
                    font_size="11px", font_family=_mono,
                    color="var(--gui-text-primary)",
                    padding="4px 6px",
                    background="var(--gui-hover)",
                    border_radius="4px",
                    width="100%",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                    title="Source path (read-only)",
                ),
                spacing="1", align_items="start", width="100%",
            ),
            # ── Destination (hidden when Delete) ─────────────────────────
            rx.cond(
                AppState.refactor_operation != "delete",
                rx.fragment(
                    _sep,
                    rx.vstack(
                        rx.text("Destination", font_size=_fs, color=_dim, font_weight="600",
                                title="Enter or click on a destination path"),
                        rx.input(
                            placeholder="<pkg>/_stack/…",
                            value=AppState.refactor_dst_path,
                            on_change=AppState.set_refactor_dst_path,
                            font_size="11px",
                            font_family=_mono,
                            width="100%",
                            title="Enter or click on a destination path",
                        ),
                        spacing="1", align_items="start", width="100%",
                    ),
                ),
                rx.box(),
            ),
            _sep,
            # ── Run ──────────────────────────────────────────────────────
            rx.vstack(
                rx.text("Run", font_size=_fs, color=_dim, font_weight="600"),
                rx.hstack(
                    rx.button(
                        rx.cond(AppState.refactor_running, "Running…", "Preview"),
                        size="1",
                        variant="soft",
                        color_scheme="gray",
                        on_click=AppState.run_refactor_preview,
                        disabled=AppState.refactor_running,
                        title="Dry-run: show what will change without making any modifications",
                    ),
                    rx.button(
                        rx.cond(AppState.refactor_running, "Running…", "Execute"),
                        size="1",
                        color_scheme="blue",
                        on_click=AppState.run_refactor_execute,
                        disabled=rx.cond(
                            AppState.refactor_running,
                            True,
                            rx.cond(
                                AppState.refactor_operation == "delete",
                                False,
                                AppState.refactor_dst_path == "",
                            ),
                        ),
                        title="Apply the selected operation — this cannot be undone",
                    ),
                    rx.button(
                        "Clear",
                        size="1", variant="ghost", color_scheme="gray",
                        on_click=AppState.clear_refactor_result,
                        title="Clear the preview/result output",
                    ),
                    spacing="2", align="center",
                ),
                spacing="1", align_items="start", width="100%",
            ),
            # Hidden trigger button clicked by JS debounce for auto-preview
            rx.button(
                id="refactor-auto-preview-trigger",
                on_click=AppState.run_refactor_preview,
                display="none",
            ),
            spacing="3",
            align_items="start",
            width="100%",
            padding="12px",
        ),
        flex="1",
        width="100%",
        height="100%",
    )


def _right_panel_header() -> rx.Component:
    """Header for the Object Viewer panel: view dropdown + mode-specific controls."""
    view_dropdown = rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                rx.cond(AppState.object_viewer_mode == "waves", "Waves", "Unit Params"),
                " ▾",
                size="1", variant="ghost",
                color="var(--gui-text-primary)",
                _hover={"background": "var(--gui-hover)"},
                flex_shrink="0",
            ),
        ),
        rx.dropdown_menu.content(
            rx.dropdown_menu.item(
                "Unit Params",
                on_click=AppState.set_object_viewer_mode("params"),
            ),
            rx.dropdown_menu.item(
                "Waves",
                on_click=AppState.set_object_viewer_mode("waves"),
            ),
            align="start",
        ),
    )

    params_controls = rx.box(
        rx.input(
            placeholder="Search params…",
            value=AppState.unit_params_search,
            on_change=AppState.set_unit_params_search,
            size="1",
            font_size="12px",
            font_family="monospace",
            width="100%",
        ),
        rx.cond(
            AppState.unit_params_search != "",
            rx.button(
                "✕",
                on_click=AppState.clear_unit_params_search,
                size="1", variant="ghost", color_scheme="gray",
                position="absolute", right="4px", top="50%",
                transform="translateY(-50%)",
                padding="0", height="16px", min_width="16px",
            ),
            rx.box(),
        ),
        position="relative", flex="1", min_width="60px",
    )

    waves_controls = rx.hstack(
        rx.button(
            rx.cond(AppState.waves_view_mode == "list", "Table", "Folder"),
            size="1", variant="ghost", color_scheme="gray",
            on_click=AppState.flip_waves_view_mode,
            title="Toggle between table and folder tree view",
        ),
        rx.cond(
            AppState.waves_view_mode == "folder",
            rx.hstack(
                rx.separator(orientation="vertical", height="16px"),
                rx.button(
                    rx.cond(AppState.wave_folders_collapsed, "⊞ Expand", "⊟ Collapse"),
                    size="1", variant="ghost", color_scheme="gray",
                    on_click=AppState.toggle_wave_folder_all,
                    title=rx.cond(
                        AppState.wave_folders_collapsed,
                        "Expand all folders",
                        "Collapse to top-level folders only",
                    ),
                ),
                spacing="3", align="center",
            ),
            rx.box(),
        ),
        rx.separator(orientation="vertical", height="16px"),
        rx.button("All/None", size="1", variant="ghost",
                  on_click=AppState.toggle_all_waves),
        rx.separator(orientation="vertical", height="16px"),
        rx.button("↺", size="1", variant="ghost",
                  on_click=AppState.refresh_wave_log_statuses,
                  title="Refresh wave status"),
        rx.separator(orientation="vertical", height="16px"),
        rx.button(
            "▶ Run All",
            size="1", variant="ghost", color_scheme="green",
            on_click=AppState.begin_run_all_waves,
            title="Apply all waves: ./run -a",
        ),
        rx.cond(
            bool(_WAVE_TAIL_CMD),
            rx.hstack(
                rx.separator(orientation="vertical", height="16px"),
                rx.button(
                    "⏵ Tail",
                    size="1", variant="ghost", color_scheme="gray",
                    on_click=AppState.tail_wave_log,
                    title="Run wave_tail_cmd in the terminal to follow the latest run.log",
                ),
                spacing="3", align="center",
            ),
            rx.box(),
        ),
        spacing="3", align="center", flex_shrink="0",
    )

    return rx.hstack(
        view_dropdown,
        rx.separator(orientation="vertical", height="16px"),
        rx.cond(
            AppState.object_viewer_mode == "params",
            params_controls,
            rx.cond(AppState.object_viewer_mode == "waves", waves_controls, rx.box()),
        ),
        rx.spacer(),
        _panel_maximize_btn("bottom-right"),
        align="center",
        spacing="2",
        padding_x="8px",
        padding_y="6px",
        border_bottom="1px solid var(--gui-border)",
        background="var(--gui-panel-bg)",
        width="100%",
        height="36px",
        overflow="visible",
        flex_shrink="0",
    )


def top_right_panel() -> rx.Component:
    """Object Viewer panel — shows Unit Params or Waves."""
    # Poll trigger always in DOM so JS setInterval can click it after a wave run
    poll_trigger = rx.el.div(
        id="wave-status-poll-trigger",
        style={"display": "none"},
        on_click=AppState.refresh_wave_log_statuses,
    )
    waves_content = rx.box(
        rx.cond(
            AppState.waves_view_mode == "folder",
            _wave_folder_table(),
            _wave_list_table(),
        ),
        # display:flex flex-direction:column makes rt-TableRoot a flex item so that
        # flex:1 + min_height:0 on the table root give it a bounded height.
        # The table root is the scroll container; position:sticky on <thead> anchors to it.
        display="flex",
        flex_direction="column",
        width="100%",
        flex="1",
        min_height="0",
    )
    params_content = rx.scroll_area(
        rx.box(unit_params_panel(), padding_bottom="24px"),
        flex="1",
        width="100%",
    )
    return rx.box(
        poll_trigger,
        _right_panel_header(),
        rx.cond(
            AppState.object_viewer_mode == "waves",
            waves_content,
            params_content,
        ),
        display="flex",
        flex_direction="column",
        width="100%",
        height="100%",
        overflow="hidden",
        background="var(--gui-content-bg)",
    )


def h_panel_resizer() -> rx.Component:
    """Thin horizontal draggable bar between top and bottom rows."""
    return rx.box(
        height=AppState.resizer_drag_width_px,
        width="100%",
        cursor="row-resize",
        background="var(--gui-border)",
        flex_shrink="0",
        _hover={"background": "#c7d2fe"},
        id="panel-h-resizer",
        title="Drag to resize panels · adjust width in Appearance → Drag Width",
    )


def _ansi_to_html(text: str, search_query: str = "", current_match_idx: int = -1,
                  case_sensitive: bool = False) -> tuple[str, int]:
    """Convert ANSI SGR escape sequences to HTML <span style="..."> markup.

    Handles: reset (0), bold (1), dim (2), italic (3), underline (4),
    standard fg 30-37 / bright fg 90-97, and 256-color fg (38;5;N).
    Text is HTML-escaped before wrapping so the output is safe to inject via
    dangerouslySetInnerHTML / rx.html().

    When search_query is provided, occurrences are wrapped in <mark> elements:
      - current match (current_match_idx, 0-based): data-fs-current attribute + orange bg
      - other matches: yellow bg
    Returns (html_string, total_match_count).
    """
    import re as _re
    import html as _html_mod

    _STD_FG: dict[str, str] = {
        '30': '#6c7086', '31': '#ff5555', '32': '#50fa7b', '33': '#f1fa8c',
        '34': '#6272a4', '35': '#ff79c6', '36': '#8be9fd', '37': '#c0c0c0',
        '90': '#888888', '91': '#ff6e6e', '92': '#69ff94', '93': '#ffffa5',
        '94': '#d6acff', '95': '#ff92df', '96': '#a4ffff', '97': '#ffffff',
    }

    def _256_to_hex(n: int) -> str:
        if n < 16:
            key = str(n + 30) if n < 8 else str(n + 82)
            return _STD_FG.get(key, '#ffffff')
        if n >= 232:                      # grayscale ramp
            v = 8 + (n - 232) * 10
            return f'#{v:02x}{v:02x}{v:02x}'
        n -= 16                           # 6×6×6 color cube
        _RAMP = (0, 95, 135, 175, 215, 255)
        return f'#{_RAMP[n // 36]:02x}{_RAMP[(n // 6) % 6]:02x}{_RAMP[n % 6]:02x}'

    _ANSI_RE = _re.compile(r'\x1b\[([0-9;]*)m')

    def _apply_codes(code_str: str, fg: str, bold: bool, dim: bool, italic: bool, underline: bool):
        codes = code_str.split(';') if code_str else ['0']
        i = 0
        while i < len(codes):
            c = codes[i]
            if c in ('0', ''):
                fg = ''; bold = dim = italic = underline = False
            elif c == '1':  bold = True
            elif c == '2':  dim = True
            elif c == '3':  italic = True
            elif c == '4':  underline = True
            elif c in _STD_FG:
                fg = _STD_FG[c]
            elif c == '38' and i + 2 < len(codes) and codes[i + 1] == '5':
                try:
                    fg = _256_to_hex(int(codes[i + 2]))
                except ValueError:
                    pass
                i += 2
            i += 1
        return fg, bold, dim, italic, underline

    def _inject_marks(raw_html: str, sq: str, match_counter: list[int], cur_idx: int,
                      cs: bool = False) -> str:
        """Replace occurrences of sq in raw_html text nodes with <mark> elements.

        raw_html is already HTML-escaped plain text (no tags). Operates on text segments
        directly so we don't accidentally split inside HTML entities like &amp;.
        match_counter[0] is incremented for each occurrence found.
        cs: when True use exact match; when False compare lowercase.
        """
        if not sq:
            return raw_html
        needle = sq if cs else sq.lower()
        result: list[str] = []
        pos = 0
        haystack = raw_html if cs else raw_html.lower()
        while True:
            idx = haystack.find(needle, pos)
            if idx == -1:
                result.append(raw_html[pos:])
                break
            result.append(raw_html[pos:idx])
            m_num = match_counter[0]
            match_counter[0] += 1
            if m_num == cur_idx:
                result.append(
                    f'<mark data-fs data-fs-current style="background:#ff9900;color:#000;border-radius:2px">'
                    f'{raw_html[idx:idx+len(sq)]}</mark>'
                )
            else:
                result.append(
                    f'<mark data-fs style="background:#ffff00;color:#000;border-radius:2px">'
                    f'{raw_html[idx:idx+len(sq)]}</mark>'
                )
            pos = idx + len(sq)
        return ''.join(result)

    lines_out: list[str] = []
    match_counter = [0]  # mutable counter shared across all lines

    for line in text.split('\n'):
        parts: list[tuple[str, str, bool, bool, bool, bool]] = []
        pos = 0
        fg = ''
        bold = dim = italic = underline = False

        for m in _ANSI_RE.finditer(line):
            if m.start() > pos:
                parts.append((_html_mod.escape(line[pos:m.start()]), fg, bold, dim, italic, underline))
            fg, bold, dim, italic, underline = _apply_codes(m.group(1), fg, bold, dim, italic, underline)
            pos = m.end()
        if pos < len(line):
            parts.append((_html_mod.escape(line[pos:]), fg, bold, dim, italic, underline))

        line_html: list[str] = []
        for chunk, f, bo, di, it, un in parts:
            if not chunk:
                continue
            if search_query:
                chunk = _inject_marks(chunk, search_query, match_counter, current_match_idx, case_sensitive)
            css = ''
            if f:   css += f'color:{f};'
            if bo:  css += 'font-weight:bold;'
            if di:  css += 'opacity:0.55;'
            if it:  css += 'font-style:italic;'
            if un:  css += 'text-decoration:underline;'
            line_html.append(f'<span style="{css}">{chunk}</span>' if css else chunk)
        lines_out.append(''.join(line_html))

    return '\n'.join(lines_out), match_counter[0]


_HCL_FONT: dict = {
    "fontFamily": "monospace",
    "fontSize":   "12px",
    "color":      "var(--gui-code-text)",
    "whiteSpace": "pre",
    "lineHeight": "1.5",
}
# display:block turns each span into a line — used for the outer wrapper only
_HCL_LINE_STYLE:   dict = {**_HCL_FONT, "display": "block"}
# display:inline for sub-spans inside a source line so they flow on one row
_HCL_INLINE_STYLE: dict = {**_HCL_FONT, "display": "inline"}


_HCL_LINE_NUM_STYLE: dict = {
    **_HCL_FONT,
    "display":        "inline-block",
    "width":          "4ch",
    "minWidth":       "4ch",
    "textAlign":      "right",
    "paddingRight":   "8px",
    "marginRight":    "4px",
    "borderRight":    "1px solid var(--gui-divider)",
    "color":          "var(--gui-text-muted)",
    "userSelect":     "none",
    "flexShrink":     "0",
}


def _render_hcl_line(line: dict) -> rx.Component:
    """Render one line of HCL; source lines get a clickable link for the path."""
    line_num_el = rx.cond(
        AppState.file_viewer_show_line_numbers,
        rx.el.span(line["line_num"], style=_HCL_LINE_NUM_STYLE),
        rx.el.span(),
    )
    return rx.cond(
        line["is_source"],
        rx.el.span(
            line_num_el,
            rx.el.span(line["prefix"], style=_HCL_INLINE_STYLE),
            rx.el.a(
                line["source_val"],
                on_click=AppState.open_source_link(line["source_val"]),
                style={
                    **_HCL_INLINE_STYLE,
                    "color":          "#2563eb",
                    "textDecoration": "underline",
                    "cursor":         "pointer",
                },
                title="Click to open this module in the File Viewer",
                id="hcl-source-link",
            ),
            rx.el.span(line["suffix"], style=_HCL_INLINE_STYLE),
            data_yaml_path=line["yaml_path"],
            style=_HCL_LINE_STYLE,
        ),
        rx.el.span(
            line_num_el,
            line["text"],
            data_yaml_path=line["yaml_path"],
            style=_HCL_LINE_STYLE,
        ),
    )


def _fv_divider() -> rx.Component:
    """Thin vertical divider for the file viewer menu bar."""
    return rx.box(width="1px", height="16px", background="var(--gui-divider)",
                  flex_shrink="0", margin_x="2px")


def _fv_type_selector() -> rx.Component:
    """Type dropdown: Unit File / Config Data (Wave Log is auto-detected, read-only)."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                AppState.file_viewer_type_label, " ▾",
                variant="ghost", size="1",
                color="var(--gui-text-primary)",
                _hover={"background": "var(--gui-hover)"},
                title="Switch between Unit File and Config Data views",
            ),
        ),
        rx.dropdown_menu.content(
            rx.dropdown_menu.item("Unit File",   on_click=AppState.set_file_viewer_mode("unit_file")),
            rx.dropdown_menu.item("Config Data", on_click=AppState.set_file_viewer_mode("config_data")),
            align="start",
        ),
    )


def _fv_editor_selector() -> rx.Component:
    """Editor dropdown: selecting an item sets the editor and opens the file immediately."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                rx.cond(AppState.selected_editor_label != "", AppState.selected_editor_label, "—"),
                " ▾",
                variant="ghost", size="1",
                color="var(--gui-text-primary)",
                _hover={"background": "var(--gui-hover)"},
                disabled=AppState.hcl_file_path == "",
                title="Select editor and open file",
            ),
        ),
        rx.dropdown_menu.content(
            *[
                rx.dropdown_menu.item(
                    editor["label"],
                    on_click=AppState.select_and_launch_in_editor(editor["id"]),
                )
                for editor in _FILE_VIEWER_EDITORS
            ],
            align="start",
        ),
    )


def _fv_open_in_chrome_item(p: dict) -> rx.Component:
    return rx.dropdown_menu.item(
        p["label"],
        on_select=AppState.open_file_in_chrome(p["id"]),
    )


def _fv_open_in_chrome() -> rx.Component:
    """Dropdown to open the current file as a file:// URL in a Chrome profile."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                rx.icon("chrome", size=13),
                " ▾",
                variant="ghost",
                size="1",
                color="var(--gui-text-primary)",
                _hover={"background": "var(--gui-hover)"},
                disabled=AppState.hcl_file_path == "",
                title="Open file in Chrome profile",
                flex_shrink="0",
            ),
        ),
        rx.dropdown_menu.content(
            rx.foreach(AppState.chrome_file_profiles, _fv_open_in_chrome_item),
            align="end",
        ),
    )


def _file_viewer_edit_menu() -> rx.Component:
    """Legacy shim — no longer used directly; kept to avoid rename churn."""
    return rx.box()


def _file_viewer_export_menu() -> rx.Component:
    """Copy-to-clipboard / Save-as dropdown for the file viewer menu bar."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                "⬇ ▾",
                variant="ghost",
                size="1",
                color="var(--gui-text-primary)",
                _hover={"background": "var(--gui-hover)"},
                disabled=AppState.hcl_content == "",
                title="Copy or save the viewed file",
            ),
        ),
        rx.dropdown_menu.content(
            rx.dropdown_menu.item(
                "📋  Copy content to clipboard",
                on_click=AppState.copy_file_content_to_clipboard,
                disabled=AppState.hcl_content == "",
            ),
            rx.dropdown_menu.separator(),
            rx.dropdown_menu.item(
                "💾  Save file as…",
                on_click=AppState.download_current_file,
                disabled=AppState.hcl_content == "",
            ),
            align="end",
        ),
    )


def _file_viewer_mode_selector() -> rx.Component:
    """Unit File / Config Data toggle for the file viewer menu bar."""
    return rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                rx.cond(
                    AppState.file_viewer_mode == "config_data",
                    "Config Data ▾",
                    "Unit File ▾",
                ),
                variant="ghost",
                size="1",
                color="var(--gui-text-primary)",
                _hover={"background": "var(--gui-hover)"},
                title="Switch between the unit's terragrunt.hcl and the stack config YAML",
            ),
        ),
        rx.dropdown_menu.content(
            rx.dropdown_menu.item(
                "Unit File",
                on_click=AppState.set_file_viewer_mode("unit_file"),
            ),
            rx.dropdown_menu.item(
                "Config Data",
                on_click=AppState.set_file_viewer_mode("config_data"),
            ),
            align="start",
        ),
    )


def _file_viewer_provider_selector() -> rx.Component:
    """Provider dropdown in the File Viewer menu bar.

    Visible only when in merged mode with a node selected that has at least one
    provider with a terragrunt.hcl on disk (show_file_viewer_provider_selector).
    """
    return rx.cond(
        AppState.show_file_viewer_provider_selector,
        rx.dropdown_menu.root(
            rx.dropdown_menu.trigger(
                rx.button(
                    rx.cond(
                        AppState.file_viewer_provider_full_path != "",
                        AppState.file_viewer_provider_full_path + " ▾",
                        "Provider ▾",
                    ),
                    variant="ghost",
                    size="1",
                    color="var(--gui-text-primary)",
                    font_family="monospace",
                    font_size="11px",
                    _hover={"background": "var(--gui-hover)"},
                    title="Select which provider's terragrunt.hcl to show",
                ),
            ),
            rx.dropdown_menu.content(
                rx.foreach(
                    AppState.file_viewer_provider_options,
                    lambda opt: rx.dropdown_menu.item(
                        opt["full_path"],
                        on_click=AppState.set_file_viewer_provider(opt["provider"]),
                        font_family="monospace",
                        font_size="12px",
                        font_weight=rx.cond(
                            AppState.file_viewer_provider == opt["provider"], "700", "400"
                        ),
                    ),
                ),
                align="start",
            ),
        ),
        rx.box(),
    )


def _file_viewer_monaco_editor() -> rx.Component:
    """Monaco editor shown when file_editor_active is True."""
    return rx.box(
        _monaco(
            value=AppState.file_editor_draft,
            language=AppState.file_editor_language,
            theme=AppState.file_editor_monaco_theme,
            on_change=AppState.set_editor_draft,
            width="100%",
            height="100%",
        ),
        flex="1",
        min_height="0",
        width="100%",
        overflow="hidden",
    )


def bottom_left_panel() -> rx.Component:
    """Bottom-left panel: displays the terragrunt.hcl for the selected node."""
    return rx.box(
        # Menu bar
        rx.hstack(
            # Brand
            rx.text(
                "FILE VIEWER",
                font_size="11px",
                font_weight="600",
                color="var(--gui-text-dim)",
                text_transform="uppercase",
                letter_spacing="0.05em",
                flex_shrink="0",
                white_space="nowrap",
            ),
            _fv_divider(),
            # Type: [label + selector]
            rx.text("Type:", font_size="11px", color="var(--gui-text-dim)",
                    flex_shrink="0", white_space="nowrap"),
            _fv_type_selector(),
            _file_viewer_provider_selector(),
            # Dynamic right section: edit controls OR view controls
            rx.cond(
                AppState.file_editor_active,
                # ── Edit mode: error + Save + Cancel ─────────────────────────
                rx.hstack(
                    rx.spacer(),
                    rx.cond(
                        AppState.file_editor_save_error != "",
                        rx.text(AppState.file_editor_save_error, color="red",
                                font_size="11px", flex_shrink="0"),
                        rx.box(),
                    ),
                    rx.button("Save", on_click=AppState.save_file_edit,
                              size="1", variant="solid", color_scheme="green", flex_shrink="0"),
                    rx.button("Cancel", on_click=AppState.cancel_file_edit,
                              size="1", variant="soft", color_scheme="gray", flex_shrink="0"),
                    flex="1", spacing="2", align="center", overflow="hidden",
                ),
                # ── View mode: Editor selector | Copy | Save ─────────────────
                rx.hstack(
                    _fv_divider(),
                    rx.text("Editor:", font_size="11px", color="var(--gui-text-dim)",
                            flex_shrink="0", white_space="nowrap"),
                    _fv_editor_selector(),
                    _fv_divider(),
                    rx.button(
                        "Copy",
                        on_click=AppState.copy_file_content_to_clipboard,
                        size="1", variant="ghost",
                        color="var(--gui-text-primary)",
                        _hover={"background": "var(--gui-hover)"},
                        disabled=AppState.hcl_content == "",
                        title="Copy file content to clipboard",
                        flex_shrink="0",
                    ),
                    _fv_divider(),
                    rx.button(
                        "Download",
                        on_click=AppState.download_current_file,
                        size="1", variant="ghost",
                        color="var(--gui-text-primary)",
                        _hover={"background": "var(--gui-hover)"},
                        disabled=AppState.hcl_content == "",
                        title="Download / save file as…",
                        flex_shrink="0",
                    ),
                    _fv_divider(),
                    rx.button(
                        "Tail",
                        on_click=AppState.tail_current_file,
                        size="1", variant="ghost",
                        color="var(--gui-text-primary)",
                        _hover={"background": "var(--gui-hover)"},
                        disabled=AppState.hcl_file_path == "",
                        title="Run: tail -99f <file> in terminal",
                        flex_shrink="0",
                    ),
                    _fv_divider(),
                    rx.cond(
                        AppState.chrome_file_profiles.length() > 0,
                        _fv_open_in_chrome(),
                        rx.box(),
                    ),
                    rx.spacer(),
                    spacing="2", align="center", flex="1", overflow="hidden",
                ),
            ),
            _panel_maximize_btn("top-right"),
            align="center",
            spacing="1",
            padding_x="8px",
            padding_y="4px",
            border_top="1px solid var(--gui-border)",
            border_bottom="1px solid var(--gui-border)",
            background="var(--gui-panel-bg)",
            width="100%",
            flex_shrink="0",
            height="32px",
            overflow="visible",
        ),
        # Search bar (always visible) — binds to the mode-specific query var
        rx.hstack(
            rx.cond(
                AppState.file_viewer_mode == "config_data",
                rx.input(
                    id="file-search-input",
                    placeholder="Search…",
                    value=AppState.config_data_search_query,
                    on_change=AppState.set_active_search_query,
                    on_key_down=AppState.file_search_key_down,
                    size="1",
                    font_size="12px",
                    font_family="monospace",
                    flex="1",
                    min_width="0",
                ),
                rx.input(
                    id="file-search-input",
                    placeholder="Search…",
                    value=AppState.unit_file_search_query,
                    on_change=AppState.set_active_search_query,
                    on_key_down=AppState.file_search_key_down,
                    size="1",
                    font_size="12px",
                    font_family="monospace",
                    flex="1",
                    min_width="0",
                ),
            ),
            rx.cond(
                AppState.file_search_not_found,
                rx.badge(
                    "Not found",
                    color_scheme="red",
                    variant="soft",
                    font_size="11px",
                    flex_shrink="0",
                ),
                rx.box(),
            ),
            rx.button(
                rx.icon("case-sensitive", size=13),
                on_click=AppState.flip_file_search_case_sensitive,
                size="1",
                variant=rx.cond(AppState.file_search_case_sensitive, "solid", "soft"),
                color_scheme=rx.cond(AppState.file_search_case_sensitive, "blue", "gray"),
                title="Case-sensitive search (currently on)" if False else
                      rx.cond(AppState.file_search_case_sensitive,
                               "Case-sensitive search (on — click to disable)",
                               "Case-insensitive search (off — click to enable)"),
                flex_shrink="0",
            ),
            rx.button(
                "↑",
                on_click=AppState.file_search_prev,
                size="1",
                variant="soft",
                color_scheme=rx.cond(AppState.file_search_match_count > 1, "blue", "gray"),
                title="Previous match",
                flex_shrink="0",
            ),
            rx.button(
                "↓",
                on_click=AppState.file_search_next,
                size="1",
                variant="soft",
                color_scheme=rx.cond(AppState.file_search_match_count > 1, "blue", "gray"),
                title="Next match",
                flex_shrink="0",
            ),
            rx.cond(
                AppState.file_viewer_mode == "config_data",
                rx.button(
                    '""',
                    on_click=AppState.flip_config_data_quote_path,
                    size="1",
                    variant=rx.cond(AppState.config_data_quote_path, "solid", "soft"),
                    color_scheme=rx.cond(AppState.config_data_quote_path, "blue", "gray"),
                    title="Wrap path in double quotes when searching",
                    font_family="monospace",
                    flex_shrink="0",
                ),
                rx.box(),
            ),
            rx.button(
                "~",
                on_click=AppState.flip_file_search_smooth_scroll,
                size="1",
                variant=rx.cond(AppState.file_search_smooth_scroll, "solid", "soft"),
                color_scheme=rx.cond(AppState.file_search_smooth_scroll, "blue", "gray"),
                title="Smooth scroll animation when navigating matches",
                flex_shrink="0",
            ),
            padding_x="8px",
            padding_y="4px",
            spacing="2",
            align="center",
            border_bottom="1px solid var(--gui-border)",
            background="var(--gui-panel-bg)",
            width="100%",
            flex_shrink="0",
        ),
        # Path bar
        rx.cond(
            AppState.hcl_file_path != "",
            rx.hstack(
                rx.text(
                    AppState.hcl_file_path,
                    font_size="11px",
                    color="var(--gui-text-muted)",
                    font_family="monospace",
                    word_break="break-all",
                    flex="1",
                    min_width="0",
                ),
                rx.button(
                    rx.icon("clipboard", size=12),
                    on_click=AppState.copy_file_path_to_clipboard,
                    size="1",
                    variant="ghost",
                    color="var(--gui-text-dim)",
                    _hover={"background": "var(--gui-hover)"},
                    title="Copy file path to clipboard",
                    flex_shrink="0",
                ),
                padding_x="8px",
                padding_y="4px",
                align="start",
                spacing="2",
                border_bottom="1px solid var(--gui-border)",
                background="var(--gui-panel-bg)",
                width="100%",
                flex_shrink="0",
            ),
            rx.box(),
        ),
        # YAML breadcrumb bar — shows YAML path of selected/navigated text.
        # Text set directly by JS; style matches the filename bar above.
        # Always in DOM so JS can find it; hidden when no file is loaded.
        rx.box(
            id="yaml-breadcrumb",
            padding_x="12px",
            padding_y="4px",
            border_bottom="1px solid var(--gui-border)",
            background="var(--gui-panel-bg)",
            width="100%",
            flex_shrink="0",
            min_height="22px",
            font_family="monospace",
            font_size="11px",
            color="var(--gui-text-muted)",
            overflow="hidden",
            white_space="nowrap",
            text_overflow="ellipsis",
            display=rx.cond(
                (AppState.hcl_content != "") & (AppState.file_viewer_mode == "config_data"),
                "block",
                "none",
            ),
        ),
        # Content
        rx.cond(
            AppState.hcl_content != "",
            rx.cond(
                AppState.file_editor_active,
                # Edit mode: Monaco editor
                _file_viewer_monaco_editor(),
                # Read-only mode: ANSI log, markdown, or syntax-highlighted pre
                rx.cond(
                    AppState.hcl_is_ansi_log,
                    # ANSI-colored log rendering (dark terminal background)
                    rx.box(
                        rx.html(
                            AppState.hcl_content_html,
                            id="file-viewer-ansi",
                            style={
                                "fontFamily": "monospace",
                                "fontSize": "12px",
                                "whiteSpace": "pre",
                                "lineHeight": "1.5",
                                "padding": "12px",
                                "margin": "0",
                                "color": "#f8f8f2",
                                "minHeight": "100%",
                            },
                        ),
                        flex="1",
                        min_height="0",
                        width="100%",
                        overflow_y="auto",
                        overflow_x="auto",
                        background="#1e1e2e",
                    ),
                    rx.cond(
                        AppState.hcl_is_markdown,
                        # Markdown rendering
                        rx.box(
                            rx.markdown(
                                AppState.hcl_content,
                                style={
                                    "fontSize": "14px",
                                    "lineHeight": "1.7",
                                    "color": "var(--gui-text)",
                                    "maxWidth": "800px",
                                },
                            ),
                            flex="1",
                            min_height="0",
                            width="100%",
                            overflow_y="auto",
                            overflow_x="auto",
                            padding="16px 20px",
                            id="file-viewer-markdown",
                        ),
                        # Regular HCL/YAML/plaintext rendering
                        rx.box(
                            rx.el.pre(
                                rx.foreach(AppState.hcl_parsed_lines, _render_hcl_line),
                                id="file-viewer-pre",
                                style={
                                    "fontFamily": "monospace",
                                    "fontSize": "12px",
                                    "color": "var(--gui-code-text)",
                                    "whiteSpace": "pre",
                                    "padding": "12px",
                                    "margin": "0",
                                    "background": "transparent",
                                },
                            ),
                            flex="1",
                            min_height="0",
                            width="100%",
                            overflow_y="auto",
                            overflow_x="auto",
                        ),
                    ),
                ),
            ),
            rx.center(
                rx.text(AppState.file_viewer_status_msg,
                        color="var(--gui-text-dim)", font_size="13px",
                        text_align="center"),
                flex="1",
                width="100%",
            ),
        ),
        # Hidden helpers for the markdown relative-link interceptor.
        # hcl-file-path-src: Reflex keeps this span's text in sync with hcl_file_path
        #   so the JS click handler can read the current file's directory without any
        #   additional round-trips.
        # markdown-link-input: hidden input whose on_change fires open_markdown_link
        #   when the JS interceptor triggers it with a resolved absolute path.
        rx.box(AppState.hcl_file_path, id="hcl-file-path-src", display="none"),
        rx.input(
            id="markdown-link-input",
            on_change=AppState.open_markdown_link,
            display="none",
        ),
        display="flex",
        flex_direction="column",
        width="100%",
        height="100%",
        overflow="hidden",
        background="var(--gui-content-bg)",
    )


_ACTION_COLOR: dict[str, str] = {
    "shell": "gray",
    "ssh":   "indigo",
    "url":   "blue",
    "clipboard": "gray",
}

_ACTION_ICON: dict[str, str] = {
    "shell": "⬛ ",
    "ssh":   "🔒 ",
    "url":   "",
    "clipboard": "📋 ",
}


def _node_action_btn(action: dict) -> rx.Component:
    """One action button shown in the browser panel header for the selected node.

    URL-type actions render as a browser-picker dropdown (pick browser + open in one
    click).  All other action types render as a plain button.
    """
    atype = action["action_type"]

    # URL actions: dropdown listing all available browser profiles; pick one to open
    url_btn = rx.dropdown_menu.root(
        rx.dropdown_menu.trigger(
            rx.button(
                action["label"], " ▾",
                size="1", variant="soft", color_scheme="blue",
                flex_shrink="0",
                title=action["value"],
            ),
        ),
        rx.dropdown_menu.content(
            rx.foreach(
                AppState.chrome_profiles,
                lambda p: rx.dropdown_menu.item(
                    p["label"],
                    on_select=AppState.dispatch_url_with_profile(action["value"], p["id"]),
                ),
            ),
            align="end",
        ),
    )

    plain_btn = rx.button(
        rx.match(
            atype,
            ("shell",     "⬛ "),
            ("ssh",       "🔒 "),
            ("clipboard", "📋 "),
            "",
        ),
        action["label"],
        on_click=AppState.dispatch_action(atype, action["value"]),
        size="1",
        variant="soft",
        color_scheme=rx.match(
            atype,
            ("shell",     "gray"),
            ("ssh",       "green"),
            ("clipboard", "orange"),
            "gray",
        ),
        flex_shrink="0",
        title=action["value"],
    )

    return rx.cond(atype == "url", url_btn, plain_btn)



def bottom_right_panel() -> rx.Component:
    """Bottom-right panel: local shell terminal or placeholder."""
    return rx.box(
        # Header: [action buttons] | [info text — flex=1] | [✕] | [maximize]
        rx.hstack(
            # Action buttons for the selected node (Shell, SSH, provider URLs, …)
            rx.foreach(AppState.selected_node_browser_actions, _node_action_btn),
            rx.separator(orientation="vertical", height="16px"),
            # Info text: label (when tailing) or cwd (when terminal open) or node path / placeholder
            rx.cond(
                AppState.shell_cwd != "",
                rx.cond(
                    AppState.shell_label != "",
                    rx.text(AppState.shell_label, font_size="11px", color="var(--gui-text-muted)",
                            font_family="monospace", overflow="hidden",
                            text_overflow="ellipsis", white_space="nowrap", flex="1"),
                    rx.text(AppState.shell_cwd_display, font_size="11px", color="var(--gui-text-muted)",
                            font_family="monospace", overflow="hidden",
                            text_overflow="ellipsis", white_space="nowrap", flex="1"),
                ),
                rx.cond(
                    AppState.selected_node_path != "",
                    rx.text(AppState.selected_node_path, font_size="11px",
                            color="var(--gui-text-muted)", font_family="monospace",
                            overflow="hidden", text_overflow="ellipsis",
                            white_space="nowrap", flex="1"),
                    rx.text("Select a node to see available actions",
                            font_size="11px", color="#c4c9d4", flex="1"),
                ),
            ),
            # Close button (terminal only)
            rx.cond(
                AppState.shell_cwd != "",
                rx.hstack(
                    rx.separator(orientation="vertical", height="16px"),
                    rx.button("✕", on_click=AppState.open_shell(""), size="1",
                              variant="ghost", color_scheme="gray", title="Close terminal"),
                    spacing="3", align="center",
                ),
                rx.box(),
            ),
            rx.separator(orientation="vertical", height="16px"),
            _panel_maximize_btn("bottom-left"),
            align="center",
            spacing="3",
            padding_x="8px",
            padding_y="4px",
            border_bottom="1px solid var(--gui-border)",
            border_top="1px solid var(--gui-border)",
            border_left="1px solid var(--gui-border)",
            background="var(--gui-panel-bg)",
            width="100%",
            flex_shrink="0",
            height="36px",
            overflow="hidden",
        ),
        # Content: terminal iframe or placeholder
        rx.cond(
            AppState.shell_cwd != "",
            rx.el.iframe(
                src=AppState.terminal_iframe_url,
                style={
                    "width": "100%",
                    "height": "100%",
                    "border": "none",
                    "flex": "1",
                    "background": "#1e1e2e",
                },
            ),
            rx.center(
                rx.vstack(
                    rx.cond(
                        AppState.selected_node_path == "",
                        rx.text(
                            "Select a node to open a shell or URL.",
                            color="#c4c9d4",
                            font_size="11px",
                            text_align="center",
                            max_width="280px",
                        ),
                        rx.box(),
                    ),
                    align="center",
                    spacing="2",
                ),
                flex="1",
                width="100%",
            ),
        ),
        display="flex",
        flex_direction="column",
        height="100%",
        min_width="0",
        overflow="hidden",
        background="var(--gui-content-bg)",
        border_left="1px solid var(--gui-border)",
    )


def backend_error_banner() -> rx.Component:
    """Fixed red banner shown whenever the WebSocket connection to the backend is lost."""
    return rx.cond(
        has_connection_errors,
        rx.box(
            rx.hstack(
                rx.el.span(
                    "⚠",
                    style={"fontSize": "16px", "lineHeight": "1"},
                ),
                rx.text(
                    "Backend not responding — ",
                    connection_error,
                    font_size="13px",
                    font_weight="500",
                    color="white",
                ),
                align="center",
                spacing="2",
            ),
            position="fixed",
            top="0",
            left="0",
            right="0",
            z_index="9999",
            background="#dc2626",
            padding_x="16px",
            padding_y="8px",
            box_shadow="0 2px 8px rgba(220,38,38,0.4)",
            display="flex",
            align_items="center",
            justify_content="center",
        ),
        rx.box(),
    )


_STATUS_BAR_HEIGHT = "26px"


def static_status_bar() -> rx.Component:
    """Permanent bottom strip — always occupies space; highlighted when active.

    Used when AppState.show_status_bar is True. Caller gates on show_status_bar via rx.cond.
    """
    return rx.box(
        rx.cond(
            AppState.app_activity_active,
            rx.hstack(
                rx.spinner(size="1", color="white"),
                rx.text(
                    AppState.app_status_message,
                    font_size="12px",
                    font_weight="500",
                    color="white",
                ),
                align="center",
                spacing="2",
                height="100%",
            ),
            rx.box(),
        ),
        width="100%",
        height=_STATUS_BAR_HEIGHT,
        flex_shrink="0",
        border_top="1px solid var(--gui-border)",
        background=rx.cond(
            AppState.app_activity_active,
            "var(--accent-9)",
            "var(--gui-surface)",
        ),
        padding_x="16px",
        display="flex",
        align_items="center",
        justify_content="center",
        transition="background 0.2s ease",
    )


def startup_status_banner() -> rx.Component:
    """Fixed bottom bar shown while the app is initialising or refreshing inventory."""
    return rx.cond(
        AppState.app_status_message != "",
        rx.box(
            rx.hstack(
                rx.spinner(size="1", color="white"),
                rx.text(
                    AppState.app_status_message,
                    font_size="12px",
                    font_weight="500",
                    color="white",
                ),
                align="center",
                spacing="2",
            ),
            position="fixed",
            bottom="0",
            left="0",
            right="0",
            z_index="9998",
            background="var(--accent-9)",
            padding_x="16px",
            padding_y="6px",
            display="flex",
            align_items="center",
            justify_content="center",
            box_shadow="0 -2px 8px rgba(0,0,0,0.2)",
        ),
        rx.box(),
    )


def navbar() -> rx.Component:
    return rx.box()


_GUI_THEME_CSS = """
:root, html.light {
  --gui-panel-bg:           #f9fafb;
  --gui-content-bg:         #ffffff;
  --gui-border:             #e5e7eb;
  --gui-divider:            #d1d5db;
  --gui-text-dim:           #9ca3af;
  --gui-text-muted:         #6b7280;
  --gui-text-primary:       #374151;
  --gui-code-text:          #1e293b;
  --gui-hover:              #e5e7eb;
  --gui-hover-soft:         #f0f0f0;
  --gui-tree-select-bg:     #e0e7ff;
  --gui-tree-hover-bg:      #f0f5ff;
  --gui-param-value:        #1f2937;
  --gui-param-override-1:   #15803d;
  --gui-param-override-2:   #22c55e;
  --gui-param-override-3:   #86efac;
  --gui-param-block-bg-1:   #dcfce7;
  --gui-param-block-bg-2:   #f0fdf4;
  --gui-param-block-bg-3:   #f7fef9;
  --gui-tab-active-bg:      #ffffff;
}
html.dark {
  --gui-panel-bg:           #2d2d2d;
  --gui-content-bg:         #222222;
  --gui-border:             #4a4a4a;
  --gui-divider:            #5a5a5a;
  --gui-text-dim:           #999999;
  --gui-text-muted:         #c0c0c0;
  --gui-text-primary:       #e8e8e8;
  --gui-code-text:          #f0f0f0;
  --gui-hover:              #3a3a3a;
  --gui-hover-soft:         #333333;
  --gui-tree-select-bg:     #1e3a5c;
  --gui-tree-hover-bg:      #2a3a4a;
  --gui-param-value:        #e2e8f0;
  --gui-param-override-1:   #4ade80;
  --gui-param-override-2:   #86efac;
  --gui-param-override-3:   #bbf7d0;
  --gui-param-block-bg-1:   #14532d;
  --gui-param-block-bg-2:   #166534;
  --gui-param-block-bg-3:   #15803d;
  --gui-tab-active-bg:      #3a3a3a;
}
"""


def _hover_state_row(item: dict) -> rx.Component:
    """One key-value row in the unit-state section of the hover popup."""
    return rx.hstack(
        rx.text(
            item["key"],
            font_size="11px",
            color="var(--gui-text-dim)",
            font_family="monospace",
            min_width="160px",
            flex_shrink="0",
        ),
        rx.text(
            item["value"],
            font_size="11px",
            color="var(--gui-text-primary)",
            font_family="monospace",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        padding_x="12px",
        padding_y="2px",
        width="100%",
        spacing="2",
        align="center",
    )


def float_file_viewer_panel() -> rx.Component:
    """Floating file viewer window — shown only in floating panels mode."""
    return rx.cond(
        (AppState.panel_mode == "floating") & AppState.float_file_viewer_open,
        rx.box(
            rx.hstack(
                rx.text("File Viewer", font_size="12px", font_weight="600",
                        color="var(--gui-text-primary)", flex="1"),
                rx.button("✕", on_click=AppState.close_float_file_viewer,
                          variant="ghost", size="1", cursor="pointer",
                          flex_shrink="0", title="Close"),
                align="center",
                spacing="2",
                padding_x="12px",
                padding_y="8px",
                cursor="grab",
                id="float-fv-header",
                background="var(--gui-panel-bg)",
                border_bottom="1px solid var(--gui-border)",
                border_radius="8px 8px 0 0",
                user_select="none",
                width="100%",
                flex_shrink="0",
            ),
            rx.box(
                bottom_left_panel(),
                flex="1",
                overflow="hidden",
                min_height="0",
                width="100%",
            ),
            id="float-fv-window",
            display="flex",
            flex_direction="column",
            position="fixed",
            style={
                "left": "var(--fv-x, 100px)",
                "top": "var(--fv-y, 100px)",
                "width": "600px",
                "min_width": "280px",
                "min_height": "200px",
                "max_height": "95vh",
                "resize": "both",
                "overflow": "hidden",
                "z_index": "9990",
                "border": "1px solid var(--gui-border)",
                "border_radius": "8px",
                "box_shadow": "0 8px 32px rgba(0,0,0,0.28)",
                "background": "var(--gui-content-bg)",
            },
        ),
        rx.box(),
    )


def float_terminal_panel() -> rx.Component:
    """Floating terminal window — shown only in floating panels mode."""
    return rx.cond(
        (AppState.panel_mode == "floating") & AppState.float_terminal_open,
        rx.box(
            rx.hstack(
                rx.text("Terminal", font_size="12px", font_weight="600",
                        color="var(--gui-text-primary)", flex="1"),
                rx.button("✕", on_click=AppState.close_float_terminal,
                          variant="ghost", size="1", cursor="pointer",
                          flex_shrink="0", title="Close"),
                align="center",
                spacing="2",
                padding_x="12px",
                padding_y="8px",
                cursor="grab",
                id="float-term-header",
                background="var(--gui-panel-bg)",
                border_bottom="1px solid var(--gui-border)",
                border_radius="8px 8px 0 0",
                user_select="none",
                width="100%",
                flex_shrink="0",
            ),
            rx.box(
                bottom_right_panel(),
                flex="1",
                overflow="hidden",
                min_height="0",
                width="100%",
            ),
            id="float-term-window",
            display="flex",
            flex_direction="column",
            position="fixed",
            style={
                "left": "var(--term-x, 130px)",
                "top": "var(--term-y, 130px)",
                "width": "600px",
                "min_width": "280px",
                "min_height": "200px",
                "max_height": "95vh",
                "resize": "both",
                "overflow": "hidden",
                "z_index": "9990",
                "border": "1px solid var(--gui-border)",
                "border_radius": "8px",
                "box_shadow": "0 8px 32px rgba(0,0,0,0.28)",
                "background": "var(--gui-content-bg)",
            },
        ),
        rx.box(),
    )


def float_object_viewer_panel() -> rx.Component:
    """Floating object viewer window — shown only in floating panels mode."""
    return rx.cond(
        (AppState.panel_mode == "floating") & AppState.float_object_viewer_open,
        rx.box(
            rx.hstack(
                rx.text("Object Viewer", font_size="12px", font_weight="600",
                        color="var(--gui-text-primary)", flex="1"),
                rx.button("✕", on_click=AppState.close_float_object_viewer,
                          variant="ghost", size="1", cursor="pointer",
                          flex_shrink="0", title="Close"),
                align="center",
                spacing="2",
                padding_x="12px",
                padding_y="8px",
                cursor="grab",
                id="float-ov-header",
                background="var(--gui-panel-bg)",
                border_bottom="1px solid var(--gui-border)",
                border_radius="8px 8px 0 0",
                user_select="none",
                width="100%",
                flex_shrink="0",
            ),
            rx.box(
                top_right_panel(),
                flex="1",
                overflow="hidden",
                min_height="0",
                width="100%",
            ),
            id="float-ov-window",
            display="flex",
            flex_direction="column",
            position="fixed",
            style={
                "left": "var(--ov-x, 160px)",
                "top": "var(--ov-y, 160px)",
                "width": "600px",
                "min_width": "280px",
                "min_height": "200px",
                "max_height": "95vh",
                "resize": "both",
                "overflow": "hidden",
                "z_index": "9990",
                "border": "1px solid var(--gui-border)",
                "border_radius": "8px",
                "box_shadow": "0 8px 32px rgba(0,0,0,0.28)",
                "background": "var(--gui-content-bg)",
            },
        ),
        rx.box(),
    )


def float_refactor_panel() -> rx.Component:
    """Floating refactor window — opened via right-click → Refactor on a tree node."""
    return rx.cond(
        AppState.float_refactor_open,
        rx.box(
            rx.hstack(
                rx.text("Refactor", font_size="12px", font_weight="600",
                        color="var(--gui-text-primary)", flex="1"),
                rx.button(
                    rx.cond(AppState.refactor_show_details, "Hide Details", "Show Details"),
                    on_click=AppState.toggle_refactor_details,
                    variant="ghost", size="1", cursor="pointer",
                    flex_shrink="0", font_size="11px",
                    title="Show what the unit manager refactors",
                ),
                rx.button("✕", on_click=AppState.close_float_refactor,
                          variant="ghost", size="1", cursor="pointer",
                          flex_shrink="0", title="Close"),
                align="center",
                spacing="2",
                padding_x="12px",
                padding_y="8px",
                cursor="grab",
                id="float-refactor-header",
                background="var(--gui-panel-bg)",
                border_bottom="1px solid var(--gui-border)",
                border_radius="8px 8px 0 0",
                user_select="none",
                width="100%",
                flex_shrink="0",
            ),
            rx.box(
                _refactor_panel(),
                flex="1",
                overflow_y="auto",
                min_height="0",
                width="100%",
            ),
            # ── Status footer (always visible) ────────────────────────────
            rx.box(width="100%", height="1px", background="var(--gui-border)", flex_shrink="0"),
            rx.vstack(
                rx.hstack(
                    rx.text("Status", font_size="12px", color="var(--gui-text-dim)",
                            font_weight="600"),
                    rx.cond(
                        AppState.refactor_status_exit != "",
                        rx.text(
                            rx.cond(
                                AppState.refactor_status_exit.startswith("✓"),
                                "✓", "✗",
                            ),
                            font_size="14px",
                            font_weight="700",
                            color=rx.cond(
                                AppState.refactor_status_exit.startswith("✓"),
                                "#22c55e", "#ef4444",
                            ),
                        ),
                        rx.box(),
                    ),
                    spacing="2", align="center",
                ),
                rx.hstack(
                    rx.cond(
                        AppState.refactor_running,
                        rx.spinner(size="1"),
                        rx.box(width="14px", height="14px"),
                    ),
                    rx.text(AppState.refactor_status_op, font_size="12px",
                            color="var(--gui-text-primary)"),
                    spacing="2", align="center",
                ),
                rx.text(
                    AppState.refactor_status_detail,
                    font_size="10px", color="var(--gui-text-dim)",
                    font_family="monospace",
                    white_space="nowrap", overflow="hidden",
                    text_overflow="ellipsis", width="100%",
                ),
                rx.cond(
                    AppState.refactor_status_exit != "",
                    rx.text(
                        AppState.refactor_status_exit,
                        font_size="12px", font_weight="600",
                        color=rx.cond(
                            AppState.refactor_status_exit.startswith("✓"),
                            "#22c55e", "#ef4444",
                        ),
                    ),
                    rx.box(),
                ),
                rx.cond(
                    AppState.refactor_status_summary != "",
                    rx.text(
                        AppState.refactor_status_summary,
                        font_size="10px", color="var(--gui-text-dim)",
                        font_family="monospace",
                        white_space="nowrap", overflow="hidden",
                        text_overflow="ellipsis", width="100%",
                    ),
                    rx.box(),
                ),
                # Error display
                rx.cond(
                    AppState.refactor_error != "",
                    rx.text(
                        "✗ ", AppState.refactor_error,
                        font_size="12px", color="#ef4444",
                        white_space="pre-wrap",
                    ),
                    rx.box(),
                ),
                # Preview results (scrollable if long)
                _refactor_preview_section(),
                spacing="1",
                align_items="start",
                width="100%",
                padding="8px 12px",
                background="var(--gui-panel-bg)",
                flex_shrink="0",
                max_height="40vh",
                overflow_y="auto",
            ),
            id="float-refactor-window",
            display="flex",
            flex_direction="column",
            position="fixed",
            style={
                "left": "var(--refactor-x, 45vw)",
                "top": "var(--refactor-y, 10vh)",
                "width": "480px",
                "min_width": "320px",
                "min_height": "200px",
                "max_height": "85vh",
                "resize": "both",
                "overflow": "hidden",
                "z_index": "9990",
                "border": "1px solid var(--gui-border)",
                "border_radius": "8px",
                "box_shadow": "0 8px 32px rgba(0,0,0,0.28)",
                "background": "var(--gui-content-bg)",
            },
        ),
        rx.box(),
    )


def _float_pkg_op_dialog() -> rx.Component:
    """Floating dialog for pkg-mgr rename / copy."""
    return rx.cond(
        AppState.pkg_op_open,
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text(
                        rx.cond(AppState.pkg_op_mode == "rename", "Rename Package", "Copy Package"),
                        font_size="14px", font_weight="700", color="var(--gui-text)",
                    ),
                    rx.spacer(),
                    rx.button("✕", size="1", variant="ghost", cursor="pointer",
                              on_click=AppState.close_pkg_op),
                    align="center", width="100%",
                ),
                rx.hstack(
                    rx.text("Source:", font_size="12px", color="var(--gui-text-dim)",
                            width="80px", flex_shrink="0"),
                    rx.text(AppState.pkg_op_src, font_size="12px",
                            color="var(--gui-text)", font_family="monospace"),
                    align="center", width="100%",
                ),
                rx.hstack(
                    rx.text("New name:", font_size="12px", color="var(--gui-text-dim)",
                            width="80px", flex_shrink="0"),
                    rx.input(
                        placeholder="new-pkg-name",
                        value=AppState.pkg_op_dst,
                        on_change=AppState.set_pkg_op_dst,
                        size="1", font_size="12px", width="100%",
                        font_family="monospace",
                    ),
                    align="center", width="100%",
                ),
                rx.cond(
                    AppState.pkg_op_mode == "copy",
                    rx.hstack(
                        rx.text("State:", font_size="12px", color="var(--gui-text-dim)",
                                width="80px", flex_shrink="0"),
                        rx.radio.root(
                            rx.hstack(
                                rx.radio.item(value="skip"),
                                rx.text("--skip-state", font_size="11px"),
                                spacing="1", align="center",
                            ),
                            rx.hstack(
                                rx.radio.item(value="with"),
                                rx.text("--with-state", font_size="11px"),
                                spacing="1", align="center",
                            ),
                            value=AppState.pkg_op_state_flag,
                            on_change=AppState.set_pkg_op_state_flag,
                            direction="row",
                            spacing="4",
                        ),
                        align="center", width="100%",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    AppState.pkg_op_error != "",
                    rx.text(AppState.pkg_op_error, font_size="11px",
                            color="var(--red-9)", white_space="pre-wrap"),
                    rx.box(),
                ),
                rx.cond(
                    (AppState.pkg_op_output != "") & (AppState.pkg_op_error == ""),
                    rx.text(AppState.pkg_op_output, font_size="11px",
                            color="var(--green-9)", white_space="pre-wrap"),
                    rx.box(),
                ),
                rx.hstack(
                    rx.button(
                        rx.cond(
                            AppState.pkg_op_running,
                            rx.hstack(rx.spinner(size="1"), rx.text("Running…"), spacing="1"),
                            rx.cond(AppState.pkg_op_mode == "rename", "Rename", "Copy"),
                        ),
                        size="1", variant="solid", color_scheme="blue",
                        disabled=AppState.pkg_op_running | (AppState.pkg_op_dst == ""),
                        on_click=AppState.run_pkg_op,
                        cursor="pointer",
                    ),
                    rx.button(
                        "Cancel", size="1", variant="ghost", cursor="pointer",
                        on_click=AppState.close_pkg_op,
                        disabled=AppState.pkg_op_running,
                    ),
                    spacing="2", align="center",
                ),
                spacing="3", align="start", width="100%", padding="16px",
            ),
            position="fixed",
            top="50%",
            left="50%",
            transform="translate(-50%, -50%)",
            width="420px",
            background="var(--gray-1)",
            border="1px solid var(--gray-6)",
            border_radius="8px",
            box_shadow="0 4px 24px rgba(0,0,0,0.35)",
            z_index="200",
            id="float-pkg-op-dialog",
        ),
        rx.box(),
    )


def hover_popup_window() -> rx.Component:
    """Floating popup shown after 5-second hover on a tree node.
    Top section: unit-state.yaml data.  Bottom section: config_params.
    Draggable via pointer-capture on the header; resizable via CSS resize handle."""
    return rx.cond(
        AppState.hover_popup_open,
        rx.box(
            # ── Header / drag handle ──────────────────────────────────────────
            rx.hstack(
                rx.vstack(
                    rx.text(
                        "Node Details",
                        font_size="12px",
                        font_weight="600",
                        color="var(--gui-text-primary)",
                    ),
                    rx.text(
                        AppState.hover_popup_node_path,
                        font_size="10px",
                        color="var(--gui-text-dim)",
                        font_family="monospace",
                        overflow="hidden",
                        text_overflow="ellipsis",
                        white_space="nowrap",
                        max_width="340px",
                    ),
                    spacing="0",
                    align="start",
                    overflow="hidden",
                    flex="1",
                ),
                rx.button(
                    "✕",
                    on_click=AppState.close_hover_popup,
                    variant="ghost",
                    size="1",
                    cursor="pointer",
                    flex_shrink="0",
                    title="Close",
                ),
                align="center",
                spacing="2",
                width="100%",
                padding_x="12px",
                padding_y="8px",
                cursor="grab",
                id="hover-popup-header",
                background="var(--gui-panel-bg)",
                border_bottom="1px solid var(--gui-border)",
                border_radius="8px 8px 0 0",
                user_select="none",
                flex_shrink="0",
            ),
            # ── Scrollable content area ───────────────────────────────────────
            rx.box(
                # Unit state section
                rx.vstack(
                    rx.text(
                        "Unit State",
                        font_size="10px",
                        font_weight="600",
                        color="var(--gui-text-dim)",
                        text_transform="uppercase",
                        letter_spacing="0.06em",
                        padding_x="12px",
                        padding_top="10px",
                        padding_bottom="4px",
                    ),
                    rx.cond(
                        AppState.hover_popup_has_unit_state,
                        rx.vstack(
                            rx.foreach(AppState.hover_popup_unit_state_rows, _hover_state_row),
                            spacing="0",
                            width="100%",
                            padding_bottom="8px",
                        ),
                        rx.text(
                            "No unit-state data for this node.",
                            font_size="12px",
                            color="var(--gui-text-dim)",
                            padding_x="12px",
                            padding_y="6px",
                        ),
                    ),
                    spacing="0",
                    width="100%",
                    align="start",
                ),
                # Divider between sections
                rx.divider(margin_y="0", opacity="0.5"),
                # Unit params section
                rx.vstack(
                    rx.text(
                        "Unit Params",
                        font_size="10px",
                        font_weight="600",
                        color="var(--gui-text-dim)",
                        text_transform="uppercase",
                        letter_spacing="0.06em",
                        padding_x="12px",
                        padding_top="10px",
                        padding_bottom="4px",
                    ),
                    rx.cond(
                        AppState.hover_popup_has_params,
                        rx.vstack(
                            rx.foreach(AppState.hover_popup_params, param_row),
                            spacing="0",
                            width="100%",
                            padding_bottom="8px",
                        ),
                        rx.text(
                            "No config_params found for this node.",
                            font_size="12px",
                            color="var(--gui-text-dim)",
                            padding_x="12px",
                            padding_y="6px",
                        ),
                    ),
                    spacing="0",
                    width="100%",
                    align="start",
                ),
                overflow_y="auto",
                flex="1",
                min_height="0",
                width="100%",
            ),
            # Outer popup box — position comes from CSS vars set by JS so that
            # React re-renders don't reset the drag position.
            id="hover-popup-window",
            display="flex",
            flex_direction="column",
            position="fixed",
            style={
                "left": "var(--popup-x, 300px)",
                "top": "var(--popup-y, 200px)",
                "resize": "both",
                "overflow": "hidden",
                "width": "480px",
                "min_width": "300px",
                "min_height": "260px",
                "max_height": "95vh",
                "z_index": "9999",
                "border": "1px solid var(--gui-border)",
                "border_radius": "8px",
                "box_shadow": "0 8px 32px rgba(0,0,0,0.28)",
                "background": "var(--gui-content-bg)",
            },
        ),
        rx.box(),
    )


def tabbed_panels_layout() -> rx.Component:
    """Tabbed mode: infra tree sidebar + all content panels as tabs to the right."""
    return rx.hstack(
        rx.box(
            left_panel(),
            id="left-column",
            overflow_y="auto",
            overflow_x="hidden",
            height="100%",
            border_right="1px solid var(--gui-border)",
            style={
                "min_width": AppState.left_panel_width_style,
                "width": "max-content",
                "height": "100%",
            },
        ),
        panel_resizer(),
        rx.tabs.root(
            rx.tabs.list(
                rx.tabs.trigger("Object Viewer", value="object-viewer", size="1"),
                rx.tabs.trigger("File Viewer",   value="file-viewer",   size="1"),
                rx.tabs.trigger("Terminal",      value="terminal",      size="1"),
            ),
            rx.tabs.content(
                rx.box(top_right_panel(), width="100%", height="100%", overflow="hidden"),
                value="object-viewer",
                flex="1",
                min_height="0",
                overflow="hidden",
                display="flex",
                flex_direction="column",
            ),
            rx.tabs.content(
                rx.box(bottom_left_panel(), width="100%", height="100%", overflow="hidden"),
                value="file-viewer",
                flex="1",
                min_height="0",
                overflow="hidden",
                display="flex",
                flex_direction="column",
            ),
            rx.tabs.content(
                rx.box(bottom_right_panel(), width="100%", height="100%", overflow="hidden"),
                value="terminal",
                flex="1",
                min_height="0",
                overflow="hidden",
                display="flex",
                flex_direction="column",
            ),
            value=AppState.tabbed_panel_active,
            on_change=AppState.set_tabbed_panel_active,
            flex="1",
            min_width="0",
            height="100%",
            overflow="hidden",
            display="flex",
            flex_direction="column",
        ),
        spacing="0",
        width="100%",
        height="100%",
        overflow="hidden",
        align="start",
    )


def index() -> rx.Component:
    return rx.box(
        rx.el.style(_GUI_THEME_CSS),
        backend_error_banner(),                           # fixed, no flow impact
        # Floating overlay banner — only when status bar is disabled
        rx.cond(
            ~AppState.show_status_bar,
            startup_status_banner(),
            rx.fragment(),
        ),
        navbar(),
        # ── Main area: floating / 4-panel / maximized ─────────────────────
        rx.box(
            rx.match(
                AppState.panel_mode,
                # ── Floating mode: infra tree sidebar only ─────────────────
                ("floating",
                    rx.box(
                        left_panel(),
                        id="left-column",
                        overflow_y="auto",
                        overflow_x="hidden",
                        height="100%",
                        border_right="1px solid var(--gui-border)",
                        style={
                            "min_width": AppState.left_panel_width_style,
                            "width": "max-content",
                            "height": "100%",
                        },
                    ),
                ),
                # ── Tabbed mode: infra tree + content tabs ─────────────────
                ("tabbed", tabbed_panels_layout()),
                # ── Default: 4-panels / maximized ──────────────────────────
                rx.cond(
                    AppState.maximized_panel == "",
                    # ── Normal 4-panel layout ──────────────────────────────
                    rx.box(
                        # Top row: left viz panel + right file viewer
                        rx.hstack(
                            rx.box(
                                left_panel(),
                                id="left-column",
                                overflow="hidden",
                                height="100%",
                                min_width="200px",
                                border_right="1px solid var(--gui-border)",
                                style={"width": AppState.left_panel_width_style, "flex": "none"},
                            ),
                            panel_resizer(),
                            rx.box(
                                bottom_left_panel(),
                                id="top-right-panel",
                                width="100%",
                                height="100%",
                                overflow="hidden",
                                flex="1",
                                min_width="0",
                            ),
                            id="top-left-panel",
                            spacing="0",
                            align="start",
                            width="100%",
                            flex_shrink="0",
                            overflow="hidden",
                            style={"height": AppState.top_row_height_style},
                        ),
                        # Full-width horizontal resizer
                        h_panel_resizer(),
                        # Bottom row: left terminal/browser + right unit params
                        rx.hstack(
                            rx.box(
                                bottom_right_panel(),
                                id="left-column-bottom",
                                overflow="hidden",
                                height="100%",
                                min_width="200px",
                                border_right="1px solid var(--gui-border)",
                                style={"width": AppState.left_panel_width_style, "flex": "none"},
                            ),
                            rx.box(
                                width=AppState.resizer_drag_width_px,
                                height="100%",
                                background="var(--gui-border)",
                                flex_shrink="0",
                            ),
                            rx.box(
                                top_right_panel(),
                                flex="1",
                                min_width="0",
                                height="100%",
                                overflow="hidden",
                            ),
                            spacing="0",
                            align="start",
                            width="100%",
                            flex="1",
                            min_height="0",
                            overflow="hidden",
                        ),
                        display="flex",
                        flex_direction="column",
                        margin_top="0",
                        height="100%",
                        width="100%",
                        overflow="hidden",
                        id="main-panels",
                    ),
                    # ── Maximized single-panel layout ──────────────────────
                    rx.box(
                        rx.match(
                            AppState.maximized_panel,
                            ("top-left",     left_panel()),
                            ("bottom-left",  bottom_right_panel()),
                            ("top-right",    bottom_left_panel()),
                            ("bottom-right", top_right_panel()),
                            rx.box(),
                        ),
                        margin_top="0",
                        height="100%",
                        width="100%",
                        overflow="hidden",
                        display="flex",
                        flex_direction="column",
                    ),
                ),
            ),
            flex="1",
            min_height="0",
            overflow="hidden",
            width="100%",
        ),
        # Permanent status bar — only when enabled
        rx.cond(
            AppState.show_status_bar,
            static_status_bar(),
            rx.fragment(),
        ),
        # Floating panel windows — always in DOM; gate internally via rx.cond
        float_file_viewer_panel(),
        float_terminal_panel(),
        float_object_viewer_panel(),
        float_refactor_panel(),
        _float_pkg_op_dialog(),
        # Paste-rename dialog
        # Remove unit + config block — confirmation dialog (no terragrunt)
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title(
                    rx.cond(
                        AppState.delete_pending_mode == "recursive",
                        "Remove unit and config block (recursive) — are you sure?",
                        "Remove unit and config block — are you sure?",
                    )
                ),
                rx.dialog.description(
                    rx.hstack(
                        rx.text("Path:", color="var(--gui-text-dim)", font_size="13px", white_space="nowrap"),
                        rx.text(AppState.delete_pending_path, font_size="13px", font_family="monospace"),
                        spacing="2", align="center",
                    ),
                    margin_bottom="12px",
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.cancel_delete),
                    ),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button(
                            rx.cond(AppState.delete_pending_mode == "recursive",
                                    "Remove (recursive)", "Remove unit"),
                            size="2",
                            color_scheme=rx.cond(AppState.delete_pending_mode == "recursive", "red", "orange"),
                            variant=rx.cond(AppState.delete_pending_mode == "recursive", "solid", "outline"),
                            on_click=AppState.confirm_delete,
                        ),
                    ),
                    spacing="2",
                ),
                style={"max_width": "500px"},
            ),
            open=AppState.delete_dialog_open,
            on_open_change=AppState.cancel_delete,
        ),
        # Rename node dialog
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("Rename node"),
                rx.dialog.description(
                    rx.vstack(
                        rx.hstack(
                            rx.text("Path:", color="var(--gui-text-dim)", font_size="13px", white_space="nowrap"),
                            rx.text(AppState.rename_pending_path, font_size="13px", font_family="monospace"),
                            spacing="2", align="center",
                        ),
                        rx.text(
                            "Renames the directory and updates all matching config_params keys "
                            "in every package YAML and SOPS secrets file.",
                            font_size="12px", color="var(--gui-text-dim)",
                        ),
                        spacing="1",
                    ),
                    margin_bottom="12px",
                ),
                rx.text("New name:", font_size="13px", color="var(--gui-text-dim)", margin_bottom="6px"),
                rx.input(
                    value=AppState.rename_pending_name,
                    on_change=AppState.set_rename_name,
                    on_key_down=AppState.rename_name_keydown,
                    auto_focus=True,
                    placeholder="new-name",
                    font_family="monospace",
                    font_size="13px",
                    width="100%",
                ),
                rx.cond(
                    AppState.rename_error != "",
                    rx.text(
                        AppState.rename_error,
                        font_size="12px",
                        color="var(--red-9)",
                        margin_top="6px",
                    ),
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.cancel_rename),
                    ),
                    rx.spacer(),
                    rx.button(
                        "Rename",
                        size="2",
                        color_scheme="orange",
                        on_click=AppState.confirm_rename,
                        disabled=AppState.rename_pending_name == "",
                    ),
                    spacing="2",
                    margin_top="16px",
                ),
                style={"max_width": "480px"},
            ),
            open=AppState.rename_dialog_open,
            on_open_change=AppState.cancel_rename,
        ),
        # Destroy — confirmation dialog (runs terragrunt destroy in terminal, no file changes)
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title(
                    rx.cond(
                        AppState.destroy_pending_mode == "recursive",
                        "Destroy unit (recursive) — are you sure?",
                        "Destroy unit — are you sure?",
                    )
                ),
                rx.dialog.description(
                    rx.vstack(
                        rx.hstack(
                            rx.text("Path:", color="var(--gui-text-dim)", font_size="13px", white_space="nowrap"),
                            rx.text(AppState.destroy_pending_path, font_size="13px", font_family="monospace"),
                            spacing="2", align="center",
                        ),
                        rx.text(
                            rx.cond(
                                AppState.destroy_pending_mode == "recursive",
                                "Runs: terragrunt run --all destroy --non-interactive -- -lock=false -lock-timeout=0s",
                                "Runs: terragrunt destroy --non-interactive -- -lock=false -lock-timeout=0s",
                            ),
                            font_size="12px", font_family="monospace", color="var(--gui-text-dim)",
                        ),
                        spacing="2",
                    ),
                    margin_bottom="12px",
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.cancel_destroy),
                    ),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button(
                            rx.cond(AppState.destroy_pending_mode == "recursive",
                                    "Destroy (recursive)", "Destroy unit"),
                            size="2", color_scheme="red",
                            on_click=AppState.confirm_destroy,
                        ),
                    ),
                    spacing="2",
                ),
                style={"max_width": "520px"},
            ),
            open=AppState.destroy_dialog_open,
            on_open_change=AppState.cancel_destroy,
        ),
        # Taint — confirmation dialog (runs terragrunt taint via state list | xargs)
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title(
                    rx.cond(
                        AppState.taint_pending_mode == "recursive",
                        "Taint unit (recursive) — are you sure?",
                        "Taint unit — are you sure?",
                    )
                ),
                rx.dialog.description(
                    rx.vstack(
                        rx.hstack(
                            rx.text("Path:", color="var(--gui-text-dim)", font_size="13px", white_space="nowrap"),
                            rx.text(AppState.taint_pending_path, font_size="13px", font_family="monospace"),
                            spacing="2", align="center",
                        ),
                        rx.text(
                            rx.cond(
                                AppState.taint_pending_mode == "recursive",
                                "Runs: terragrunt run --all -- state list | xargs -r -I{} terragrunt run -- taint {}",
                                "Runs: terragrunt state list | xargs -r -I{} terragrunt run -- taint {}",
                            ),
                            font_size="12px", font_family="monospace", color="var(--gui-text-dim)",
                        ),
                        rx.text(
                            "Marks every resource in the unit(s) for forced recreation on next apply.",
                            font_size="12px", color="var(--gui-text-dim)",
                        ),
                        spacing="2",
                    ),
                    margin_bottom="12px",
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.cancel_taint),
                    ),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button(
                            rx.cond(AppState.taint_pending_mode == "recursive",
                                    "Taint (recursive)", "Taint unit"),
                            size="2", color_scheme="orange",
                            on_click=AppState.confirm_taint,
                        ),
                    ),
                    spacing="2",
                ),
                style={"max_width": "560px"},
            ),
            open=AppState.taint_dialog_open,
            on_open_change=AppState.cancel_taint,
        ),
        # Run all waves — confirmation dialog
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("Run all waves — are you sure?"),
                rx.dialog.description(
                    rx.vstack(
                        rx.text(
                            "Runs: ./run -a",
                            font_size="12px", font_family="monospace",
                            color="var(--gui-text-dim)",
                        ),
                        rx.text(
                            "This will apply all waves in sequence.",
                            font_size="13px", color="var(--gui-text-dim)",
                        ),
                        spacing="2",
                    ),
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.cancel_run_all_waves),
                    ),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button("Run all waves", size="2", color_scheme="green",
                                  on_click=AppState.confirm_run_all_waves),
                    ),
                    spacing="2",
                ),
                style={"max_width": "480px"},
            ),
            open=AppState.run_all_waves_dialog_open,
            on_open_change=AppState.cancel_run_all_waves,
        ),
        # Wave destroy — confirmation dialog
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("Destroy wave — are you sure?"),
                rx.dialog.description(
                    rx.vstack(
                        rx.hstack(
                            rx.text("Wave:", color="var(--gui-text-dim)", font_size="13px", white_space="nowrap"),
                            rx.text(AppState.wave_run_pending_name, font_size="13px", font_family="monospace"),
                            spacing="2", align="center",
                        ),
                        rx.text(
                            "Runs: ./run --clean -w <wave>",
                            font_size="12px", font_family="monospace",
                            color="var(--gui-text-dim)",
                        ),
                        rx.text(
                            "This will run terragrunt destroy for all units in the wave.",
                            font_size="13px", color="var(--gui-text-dim)",
                        ),
                        spacing="2",
                    ),
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.cancel_wave_run),
                    ),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button("Destroy wave", size="2", color_scheme="red",
                                  on_click=AppState.confirm_wave_run),
                    ),
                    spacing="2",
                ),
                style={"max_width": "480px"},
            ),
            open=AppState.wave_run_dialog_open,
            on_open_change=AppState.cancel_wave_run,
        ),
        # Wave folder destroy — confirmation dialog
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("Destroy folder waves — are you sure?"),
                rx.dialog.description(
                    rx.vstack(
                        rx.hstack(
                            rx.text("Folder:", color="var(--gui-text-dim)", font_size="13px", white_space="nowrap"),
                            rx.text(AppState.wave_folder_run_pending_path, font_size="13px", font_family="monospace"),
                            spacing="2", align="center",
                        ),
                        rx.text(
                            "./run --clean -w '" + AppState.wave_folder_run_pending_path + ".*'",
                            font_size="12px", font_family="monospace",
                            color="var(--gui-text-dim)",
                        ),
                        rx.text(
                            "This will run terragrunt destroy for all waves matching this folder prefix.",
                            font_size="13px", color="var(--gui-text-dim)",
                        ),
                        spacing="2",
                    ),
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.cancel_wave_folder_run),
                    ),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button("Destroy folder waves", size="2", color_scheme="red",
                                  on_click=AppState.confirm_wave_folder_run),
                    ),
                    spacing="2",
                ),
                style={"max_width": "480px"},
            ),
            open=AppState.wave_folder_run_dialog_open,
            on_open_change=AppState.cancel_wave_folder_run,
        ),
        # State lock file removal — direct backend delete confirmation dialog (unit + recursive)
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title(
                    rx.cond(
                        AppState.unlock_file_pending_mode == "recursive",
                        "Remove state lock files (recursive) — are you sure?",
                        "Remove state lock file — are you sure?",
                    ),
                ),
                rx.dialog.description(
                    rx.vstack(
                        rx.hstack(
                            rx.cond(
                                AppState.unlock_file_pending_mode == "recursive",
                                rx.text("Path:", color="var(--gui-text-dim)", font_size="13px",
                                        white_space="nowrap"),
                                rx.text("Unit:", color="var(--gui-text-dim)", font_size="13px",
                                        white_space="nowrap"),
                            ),
                            rx.text(AppState.unlock_file_pending_path, font_size="13px",
                                    font_family="monospace",
                                    overflow="hidden", text_overflow="ellipsis",
                                    white_space="nowrap"),
                            spacing="2", align="center",
                        ),
                        rx.hstack(
                            rx.cond(
                                AppState.unlock_file_pending_mode == "recursive",
                                rx.text("Pattern:", color="var(--gui-text-dim)", font_size="13px",
                                        white_space="nowrap"),
                                rx.text("Lock file:", color="var(--gui-text-dim)", font_size="13px",
                                        white_space="nowrap"),
                            ),
                            rx.text(AppState.unlock_file_lock_uri, font_size="12px",
                                    font_family="monospace", color="var(--gui-text-primary)",
                                    overflow="hidden", text_overflow="ellipsis",
                                    white_space="nowrap"),
                            spacing="2", align="center",
                        ),
                        rx.callout.root(
                            rx.callout.icon(rx.icon("triangle-alert", size=16)),
                            rx.callout.text(
                                rx.cond(
                                    AppState.unlock_file_pending_mode == "recursive",
                                    "Only do this if you are certain no Terraform/Terragrunt "
                                    "process is holding any lock under this path. Deleting active "
                                    "locks can corrupt state files.",
                                    "Only do this if you are certain no Terraform/Terragrunt process "
                                    "is currently holding this lock. Deleting an active lock can "
                                    "corrupt the state file.",
                                ),
                                font_size="13px",
                            ),
                            color="red",
                            size="1",
                        ),
                        rx.text(
                            "This directly deletes lock object(s) from backend storage "
                            "(GCS/S3/local). No terragrunt commands are run.",
                            font_size="12px", color="var(--gui-text-dim)",
                        ),
                        spacing="3",
                    ),
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.cancel_unlock_file),
                    ),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button(
                            rx.cond(
                                AppState.unlock_file_pending_mode == "recursive",
                                "Delete all lock files",
                                "Delete lock file",
                            ),
                            size="2", color_scheme="red",
                            on_click=AppState.confirm_unlock_file,
                        ),
                    ),
                    spacing="2",
                ),
                style={"max_width": "560px"},
            ),
            open=AppState.unlock_file_dialog_open,
            on_open_change=AppState.cancel_unlock_file,
        ),
        # Help — About / License dialog
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title(AppState.help_dialog_title),
                rx.dialog.description(
                    rx.el.pre(
                        AppState.help_dialog_body,
                        style={
                            "fontFamily": "inherit",
                            "fontSize": "13px",
                            "whiteSpace": "pre-wrap",
                            "color": "var(--gui-text-primary)",
                            "lineHeight": "1.6",
                            "margin": "0",
                        },
                    ),
                ),
                rx.hstack(
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button("Close", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.close_help_dialog),
                    ),
                    spacing="2",
                    margin_top="16px",
                ),
                style={"max_width": "420px"},
            ),
            open=AppState.help_dialog_open,
            on_open_change=AppState.close_help_dialog,
        ),
        # Param edit — inline edit dialog for a single config_params key/value
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title(
                    rx.hstack(
                        rx.text("Edit param:"),
                        rx.text(
                            AppState.param_edit_param_key,
                            font_family="monospace",
                            color="var(--gui-text-primary)",
                        ),
                        spacing="2",
                        align="center",
                    ),
                ),
                rx.dialog.description(
                    rx.vstack(
                        rx.hstack(
                            rx.text("Provider:", color="var(--gui-text-dim)",
                                    font_size="13px", white_space="nowrap"),
                            rx.text(AppState.param_edit_provider,
                                    font_size="13px", font_family="monospace"),
                            spacing="2", align="center",
                        ),
                        rx.hstack(
                            rx.text("Config key:", color="var(--gui-text-dim)",
                                    font_size="13px", white_space="nowrap"),
                            rx.text(AppState.param_edit_config_key,
                                    font_size="13px", font_family="monospace",
                                    overflow="hidden", text_overflow="ellipsis",
                                    white_space="nowrap"),
                            spacing="2", align="center",
                        ),
                        rx.cond(
                            AppState.param_edit_is_inherited,
                            rx.callout.root(
                                rx.callout.text(
                                    "This param is inherited from an ancestor path. "
                                    "Saving will create a new override entry at the current node.",
                                ),
                                color="orange",
                                variant="soft",
                                size="1",
                            ),
                            rx.box(),
                        ),
                        spacing="2",
                    ),
                    margin_bottom="12px",
                ),
                rx.text("Value (YAML):", font_size="13px",
                        color="var(--gui-text-dim)", margin_bottom="4px"),
                rx.text_area(
                    value=AppState.param_edit_draft,
                    on_change=AppState.set_param_edit_draft,
                    on_key_down=AppState.param_edit_keydown,
                    auto_focus=True,
                    font_family="monospace",
                    font_size="12px",
                    width="100%",
                    min_height="60px",
                    placeholder="YAML value",
                ),
                rx.cond(
                    AppState.param_edit_error != "",
                    rx.text(AppState.param_edit_error,
                            color="red", font_size="12px", margin_top="6px"),
                    rx.box(),
                ),
                rx.hstack(
                    rx.dialog.close(
                        rx.button("Cancel", variant="soft", color_scheme="gray", size="2",
                                  on_click=AppState.cancel_edit_param),
                    ),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button("Save", size="2", color_scheme="blue",
                                  on_click=AppState.confirm_edit_param),
                    ),
                    spacing="2",
                    margin_top="16px",
                ),
                style={"max_width": "480px"},
            ),
            open=AppState.param_edit_dialog_open,
            on_open_change=AppState.cancel_edit_param,
        ),
        # Hover popup — floats over the UI after 5s of cursor rest on a tree node
        hover_popup_window(),
        # Hidden divs for JS → Reflex event bridging
        rx.el.div(
            id="resize-complete-trigger",
            style={"display": "none"},
            on_click=AppState.on_resize_complete,
        ),
        rx.el.div(
            id="hresize-complete-trigger",
            style={"display": "none"},
            on_click=AppState.on_hresize_complete,
        ),
        rx.el.div(
            id="cy-node-trigger",
            style={"display": "none"},
            on_click=AppState.on_cy_node_click,
        ),
        rx.el.div(
            id="rf-node-trigger",
            style={"display": "none"},
            on_click=AppState.on_rf_node_click,
        ),
        display="flex",
        flex_direction="column",
        height="100vh",
        overflow="hidden",
        background="var(--gui-panel-bg)",
        max_width="100vw",
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = rx.App(
    theme=rx.theme(appearance="light", accent_color="blue", radius="medium"),
    style={"html, body": {"overflow": "hidden", "height": "100%", "maxWidth": "100vw"}},
)
app.add_page(index, route="/", on_load=AppState.on_load)


# ---------------------------------------------------------------------------
# API endpoints — served by the Reflex FastAPI backend.
# Iframe-based framework viewers fetch from these to get the infra graph data.
# ---------------------------------------------------------------------------

from starlette.requests import Request   # noqa: E402
from starlette.responses import JSONResponse as _JSONResponse  # noqa: E402


async def _api_infra_graph(request: Request) -> _JSONResponse:
    """Cytoscape.js element list (nodes + edges) with provider accent colours."""
    return _JSONResponse({
        "elements":  _build_cytoscape_elements(),
        "providers": list(PROVIDER_ACCENT.keys()),
        "accent":    PROVIDER_ACCENT,
    })


app._api.add_route("/api/infra-graph", _api_infra_graph, methods=["GET"])


async def _api_fw_repos_graph(request: Request) -> _JSONResponse:
    """Repos + packages data for the Mermaid class diagram viewer."""
    if not _FW_REPOS_YAML.exists():
        return _JSONResponse({"repos": {}})
    raw = yaml.safe_load(_FW_REPOS_YAML.read_text()) or {}
    return _JSONResponse({"repos": raw.get("data", {}).get("repos", {})})


app._api.add_route("/api/fw-repos-graph", _api_fw_repos_graph, methods=["GET"])


async def _api_arch_diagram_export(request: Request):
    """Serve an arch diagram export in the requested format.

    Query params:
      format           — required; must be a key in _ARCH_GENERATORS
      direction        — LR | TB  (default from config)
      min_depth        — int
      max_depth        — int
      show_connections — true | false
    """
    from starlette.responses import Response as _StarletteResponse
    params    = dict(request.query_params)
    fmt_id    = params.get("format", "drawio")
    generator = _ARCH_GENERATORS.get(fmt_id)
    if generator is None:
        return _StarletteResponse(
            content=f"Unknown format '{fmt_id}'. Available: {list(_ARCH_GENERATORS)}",
            status_code=400, media_type="text/plain",
        )

    fmt_meta = next((f for f in _ARCH_EXPORT_FORMATS if f["id"] == fmt_id), {})

    cfg = {**_ARCH_DIAGRAM_CONFIG}
    if "direction" in params and params["direction"] in ("LR", "TB"):
        cfg["direction"] = params["direction"]
    if "min_depth" in params:
        try: cfg["min_depth"] = int(params["min_depth"])
        except ValueError: pass
    if "max_depth" in params:
        try: cfg["max_depth"] = int(params["max_depth"])
        except ValueError: pass
    if "show_connections" in params:
        cfg["show_connections"] = params["show_connections"].lower() == "true"

    content  = generator(_ALL_NODES_CACHE, _DEPENDENCIES_CACHE, cfg)
    filename = fmt_meta.get("filename", f"arch-diagram.{fmt_id}")
    mime     = fmt_meta.get("mime", "text/plain")
    return _StarletteResponse(
        content=content, media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


app._api.add_route("/api/arch-diagram-export", _api_arch_diagram_export, methods=["GET"])


# ---------------------------------------------------------------------------
# Test support API — used by the Ansible test framework to pre-load GUI state.
# The test runner POSTs a state dict; on_load applies it when the page loads.
# ---------------------------------------------------------------------------

async def _api_test_set_state(request: Request) -> _JSONResponse:
    """Write a GUI state dict to .test_state.yml for the next on_load to consume."""
    try:
        body = await request.json()
    except Exception:
        return _JSONResponse({"ok": False, "error": "invalid JSON body"}, status_code=400)
    state = body.get("state", {})
    _TEST_STATE_FILE.write_text(yaml.dump({"gui_state": state}, allow_unicode=True))
    return _JSONResponse({"ok": True})


async def _api_test_clear_state(request: Request) -> _JSONResponse:
    """Remove .test_state.yml so the next on_load uses default state."""
    _TEST_STATE_FILE.unlink(missing_ok=True)
    return _JSONResponse({"ok": True})


app._api.add_route("/api/test/set-state",   _api_test_set_state,   methods=["POST"])
app._api.add_route("/api/test/clear-state", _api_test_clear_state, methods=["POST"])


# ---------------------------------------------------------------------------
# Terminal: HTML page + WebSocket PTY bridge
# ---------------------------------------------------------------------------

from starlette.responses import HTMLResponse as _HTMLResponse   # noqa: E402
from starlette.routing import Route as _Route, WebSocketRoute as _WebSocketRoute  # noqa: E402
from starlette.websockets import WebSocket as _WebSocket        # noqa: E402
from starlette.websockets import WebSocketDisconnect            # noqa: E402


async def _terminal_page_handler(request: Request) -> _HTMLResponse:
    """Serve the self-contained xterm.js terminal HTML page."""
    cwd = request.query_params.get("cwd", os.getcwd())
    initial_cmd = request.query_params.get("initial_cmd", "")
    if not os.path.isdir(cwd):
        cwd = os.getcwd()
    return _HTMLResponse(_terminal_html(cwd, initial_cmd))


async def _terminal_ws_handler(websocket: _WebSocket):
    """WebSocket endpoint: bridge browser xterm ↔ local PTY bash process."""
    await websocket.accept()
    cwd = websocket.query_params.get("cwd", os.getcwd())
    if not os.path.isdir(cwd):
        cwd = os.getcwd()

    master_fd, slave_fd = pty.openpty()
    env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}

    # Write a temp rcfile that sources ~/.bashrc then forces a two-line prompt.
    # Setting PS1 in env alone is not enough — ~/.bashrc runs later and overwrites it.
    import tempfile as _tempfile
    rc_fd, rc_path = _tempfile.mkstemp(suffix=".bashrc", prefix="homelab_term_")
    with os.fdopen(rc_fd, "w") as _f:
        _f.write("[ -f ~/.bashrc ] && source ~/.bashrc 2>/dev/null\n")
        # Two-line prompt: info line then a blank input line starting at column 0.
        _f.write(r'PS1="\u@\h:\w\n\$ "' + "\n")

    initial_cmd = websocket.query_params.get("initial_cmd", "").strip()
    hide_cmd    = websocket.query_params.get("hide_cmd", "") == "1"

    proc = await asyncio.create_subprocess_exec(
        os.environ.get("SHELL", "bash"),
        "--rcfile", rc_path,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=cwd,
        env=env,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    # Send the initial command (e.g. ssh login) once bash has had time to initialise.
    if initial_cmd:
        async def _send_initial():
            await asyncio.sleep(0.6)
            try:
                if hide_cmd:
                    # Suppress echo so the command text is not shown in the terminal.
                    import termios as _termios
                    attr = _termios.tcgetattr(master_fd)
                    orig_lflag = attr[3]
                    attr[3] &= ~_termios.ECHO
                    _termios.tcsetattr(master_fd, _termios.TCSANOW, attr)
                    os.write(master_fd, (initial_cmd + "\n").encode("utf-8"))
                    await asyncio.sleep(0.05)   # let the line discipline process before re-enabling
                    attr[3] = orig_lflag
                    _termios.tcsetattr(master_fd, _termios.TCSANOW, attr)
                else:
                    os.write(master_fd, (initial_cmd + "\n").encode("utf-8"))
            except OSError:
                pass
        asyncio.create_task(_send_initial())

    loop = asyncio.get_event_loop()

    async def pty_to_ws():
        """Read from PTY master and forward to WebSocket."""
        try:
            while True:
                ready = await loop.run_in_executor(
                    None, lambda: _select_mod.select([master_fd], [], [], 0.05)[0]
                )
                if ready:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            break
                        await websocket.send_bytes(data)
                    except OSError:
                        break
                if proc.returncode is not None:
                    break
        except Exception:
            pass

    async def ws_to_pty():
        """Receive from WebSocket and write to PTY master.

        Text frames are either JSON control messages (resize) or raw keyboard
        input from xterm.onData.  Only resize messages are JSON; everything
        else must be written verbatim to the PTY.  The previous implementation
        silently discarded non-JSON text, which blocked all keyboard input.
        """
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break

                raw_text = msg.get("text")
                raw_bytes = msg.get("bytes")

                if raw_text:
                    # Check if it's a JSON resize control message.
                    try:
                        payload = json.loads(raw_text)
                        if isinstance(payload, dict):
                            msg_type = payload.get("type")
                            if msg_type == "resize":
                                cols = int(payload.get("cols", 80))
                                rows = int(payload.get("rows", 24))
                                fcntl.ioctl(
                                    master_fd, termios.TIOCSWINSZ,
                                    struct.pack("HHHH", rows, cols, 0, 0),
                                )
                                continue  # handled — do NOT write to PTY
                            elif msg_type == "keyboard_layout":
                                layout = payload.get("layout", "?")
                                kmap = payload.get("map", {})
                                # Log a compact summary of keys relevant to the tilde/quote issue
                                relevant = {k: kmap[k] for k in ("Backquote", "Quote", "Digit2") if k in kmap}
                                _gui_log(f"[keyboard-layout] browser reports layout={layout!r} keys={relevant}")
                                continue  # informational only — do NOT write to PTY
                    except (json.JSONDecodeError, ValueError, KeyError, OSError):
                        pass
                    # Not a control message — regular keyboard input; write to PTY.
                    try:
                        os.write(master_fd, raw_text.encode("utf-8"))
                    except OSError:
                        break

                elif raw_bytes:
                    try:
                        os.write(master_fd, raw_bytes)
                    except OSError:
                        break

        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    # Run both directions concurrently; cancel the other when one exits.
    t1 = asyncio.create_task(pty_to_ws())
    t2 = asyncio.create_task(ws_to_pty())
    try:
        _done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            os.unlink(rc_path)
        except OSError:
            pass


app._api.router.routes.append(_Route("/terminal", _terminal_page_handler, methods=["GET"]))
app._api.router.routes.append(_WebSocketRoute("/ws/terminal", _terminal_ws_handler))

