"""Pytest setup: make the engine and working scripts importable.

Run from ``auxiliary/mikulasek_eb_2``::

    ../../.venv/bin/python -m pytest tests
"""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
for _sub in ("scripts", "working_scripts"):
    _path = str(PACKAGE_ROOT / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
