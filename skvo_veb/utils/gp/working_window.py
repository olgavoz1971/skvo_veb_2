"""GP transport-JSON working-window helpers.

JD-array window maths live in ``skvo_veb.utils.lc_working_window``.
"""

from __future__ import annotations

import json
import logging

import numpy as np

from skvo_veb.utils.lc_working_window import (
    build_working_window_store_from_times,
    normalize_working_window,
)
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def count_observations_in_jd_window(
    lc_json_string: str,
    jd_min: float,
    jd_max: float,
) -> int:
    """Counts transport rows whose absolute JD lies in the closed window.

    Args:
        lc_json_string: Serialised light curve transport JSON.
        jd_min (float): Window start (absolute JD).
        jd_max (float): Window end (absolute JD).

    Returns:
        int: Number of finite time samples inside the window.
    """
    packet = json.loads(lc_json_string)
    jd0 = float(packet.get("meta", {}).get("jd0") or 0.0)
    lo, hi = sorted((float(jd_min), float(jd_max)))
    rows = packet.get("data") or []
    if not rows:
        return 0
    times = np.asarray([row[0] for row in rows], dtype=float) + jd0
    finite = np.isfinite(times)
    return int(np.count_nonzero(finite & (times >= lo) & (times <= hi)))


def build_working_window_store(
    jd_min: float,
    jd_max: float,
    lc_json_string: str,
) -> dict:
    """Validates a working window against GP transport JSON.

    Args:
        jd_min (float): Window start (absolute JD).
        jd_max (float): Window end (absolute JD).
        lc_json_string: Full light curve transport (unchanged in store).

    Returns:
        dict: ``{enabled, jd_min, jd_max}``.

    Raises:
        PipeException: If the window is empty or contains no observations.
    """
    packet = json.loads(lc_json_string)
    jd0 = float(packet.get("meta", {}).get("jd0") or 0.0)
    rows = packet.get("data") or []
    times = np.asarray([row[0] for row in rows], dtype=float) + jd0
    return build_working_window_store_from_times(jd_min, jd_max, times)


def clip_transport_json_to_jd_window(
    lc_json_string: str,
    jd_min: float,
    jd_max: float,
) -> str:
    """Returns transport JSON containing only rows inside the JD window.

    Args:
        lc_json_string: Full serialised light curve transport.
        jd_min (float): Window start (absolute JD).
        jd_max (float): Window end (absolute JD).

    Returns:
        str: New transport JSON with filtered ``data`` rows.

    Raises:
        PipeException: If no finite rows remain in the window.
    """
    packet = json.loads(lc_json_string)
    jd0 = float(packet.get("meta", {}).get("jd0") or 0.0)
    lo, hi = sorted((float(jd_min), float(jd_max)))
    kept = []
    for row in packet.get("data") or []:
        t_raw = float(row[0])
        if not np.isfinite(t_raw):
            continue
        jd_abs = t_raw + jd0
        if lo <= jd_abs <= hi:
            kept.append(row)
    if not kept:
        raise PipeException(
            "Working time range contains no light curve points to export."
        )
    clipped = dict(packet)
    clipped["data"] = kept
    return json.dumps(clipped)


def transport_json_for_prep_export(
    lc_json_string: str,
    working_window_store: dict | None,
) -> str:
    """Selects full or clipped transport for prep light curve export.

    Args:
        lc_json_string: Canonical prep transport in ``store-lc-data``.
        working_window_store: ``store-gp-prep-working-window`` payload.

    Returns:
        str: Transport JSON to pass to ``curvedash_from_transport_json``.
    """
    window = normalize_working_window(working_window_store)
    if window is None:
        return lc_json_string
    return clip_transport_json_to_jd_window(
        lc_json_string,
        window["jd_min"],
        window["jd_max"],
    )
