"""Path bootstrap so the spike can import ``skvo_veb`` and template_timing I/O."""

from __future__ import annotations

import sys
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parent
AUX_ROOT = SPIKE_ROOT.parent
PROJECT_ROOT = AUX_ROOT.parent
TEMPLATE_TIMING = AUX_ROOT / "template_timing"
DATA_DIR = SPIKE_ROOT / "data"


def ensure_import_paths() -> None:
    """Insert project and template_timing roots on ``sys.path`` (idempotent).

    ``SPIKE_ROOT`` is forced to the front so local modules (e.g. ``plot_style``)
    are not shadowed by same-named files under ``template_timing``.

    Args:
        None.

    Returns:
        None.
    """
    for path in (PROJECT_ROOT, TEMPLATE_TIMING, SPIKE_ROOT):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    spike = str(SPIKE_ROOT)
    if spike in sys.path:
        sys.path.remove(spike)
    sys.path.insert(0, spike)
