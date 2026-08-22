"""Re-export ``template_timing.plot_style`` for IDE-resolvable spike imports.

``ensure_import_paths`` puts this folder ahead of ``template_timing`` on
``sys.path``, so ``from plot_style import …`` binds here. Definitions are
loaded from ``../template_timing/plot_style.py`` (not duplicated).
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SRC = Path(__file__).resolve().parent.parent / "template_timing" / "plot_style.py"


def _load() -> object:
    """Load the template_timing plot_style module by file path.

    Returns:
        module: The loaded ``plot_style`` module.

    Raises:
        ImportError: If the source file cannot be loaded.
    """
    if not _SRC.is_file():
        raise ImportError(f"template_timing plot_style not found: {_SRC}")
    spec = importlib.util.spec_from_file_location(
        "template_timing_plot_style", _SRC
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create import spec for {_SRC}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mod = _load()

FONT_SIZE = _mod.FONT_SIZE
FIGSIZE_TEMPLATE = _mod.FIGSIZE_TEMPLATE
FIGSIZE_INTERVAL = _mod.FIGSIZE_INTERVAL
FIGSIZE_SEGMENT_ANCHOR = _mod.FIGSIZE_SEGMENT_ANCHOR
FIGSIZE_OVERVIEW = _mod.FIGSIZE_OVERVIEW
apply_plot_style = _mod.apply_plot_style
apply_interval_plot_style = _mod.apply_interval_plot_style

__all__ = [
    "FONT_SIZE",
    "FIGSIZE_TEMPLATE",
    "FIGSIZE_INTERVAL",
    "FIGSIZE_SEGMENT_ANCHOR",
    "FIGSIZE_OVERVIEW",
    "apply_plot_style",
    "apply_interval_plot_style",
]
