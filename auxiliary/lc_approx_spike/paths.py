"""Path bootstrap so the spike can import ``skvo_veb`` and template_timing I/O."""

from __future__ import annotations

import sys
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parent
AUX_ROOT = SPIKE_ROOT.parent
PROJECT_ROOT = AUX_ROOT.parent
TEMPLATE_TIMING = AUX_ROOT / "template_timing"
DATA_DIR = SPIKE_ROOT / "data"
VENDOR_DIR = SPIKE_ROOT / "vendor"


def ensure_import_paths() -> None:
    """Insert project and template_timing roots on ``sys.path`` (idempotent)."""
    for path in (PROJECT_ROOT, TEMPLATE_TIMING, SPIKE_ROOT, VENDOR_DIR):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
