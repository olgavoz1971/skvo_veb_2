"""Path bootstrap so the detrend probe can import ``skvo_veb``."""

from __future__ import annotations

import sys
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parent
AUX_ROOT = SPIKE_ROOT.parent
PROJECT_ROOT = AUX_ROOT.parent
DATA_DIR = SPIKE_ROOT / "data"


def ensure_import_paths() -> None:
    """Insert the project root on ``sys.path`` and keep this folder first.

    Args:
        None.

    Returns:
        None.
    """
    for path in (PROJECT_ROOT, SPIKE_ROOT):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    spike = str(SPIKE_ROOT)
    if spike in sys.path:
        sys.path.remove(spike)
    sys.path.insert(0, spike)
