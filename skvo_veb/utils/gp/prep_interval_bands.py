"""Prep-plot interval pick bands for GP O-C (unfolded lightcurve only)."""

from __future__ import annotations

GP_INTERVAL_SHAPE_NAME_PREFIX = "gp-int-"


def interval_shape_name(index: int) -> str:
    """Returns the Plotly layout shape name for interval ``index``.

    Args:
        index (int): Row index in ``store-intervals-data``.

    Returns:
        str: Stable shape name for clientside mark styling.
    """
    return f"{GP_INTERVAL_SHAPE_NAME_PREFIX}{index}"


def _plot_x_for_pick_store(value) -> float | str:
    """Serialises a plot x bound for JSON ``Store`` transport.

    Args:
        value: MJD offset (float) or calendar datetime from Astropy.

    Returns:
        float or str: JSON-safe coordinate.
    """
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return float(value)


def build_unfolded_interval_pick_payload(
    intervals: list | None,
    *,
    time_axis_mode: str,
    display_epoch: float,
    timescale: str | None,
) -> dict:
    """Builds clientside hit-test metadata for unfolded interval bands.

    Args:
        intervals (list, optional): ``[[jd_start, jd_end], ...]`` in absolute JD.
        time_axis_mode (str): Active MJD or date axis mode.
        display_epoch (float): JD reference for MJD display.
        timescale (str, optional): ``TIMESYS/@timescale`` for date axis.

    Returns:
        dict: ``{enabled, axis, bands: [{i, x0, x1}, ...]}`` for ``dcc.Store``.
    """
    from skvo_veb.utils.lc_figure import absolute_jd_to_plot_x

    if not intervals:
        return {"enabled": True, "axis": time_axis_mode, "bands": []}

    bands = []
    for index, interval in enumerate(intervals):
        x0, x1 = absolute_jd_to_plot_x(
            [interval[0], interval[1]],
            time_axis_mode,
            display_epoch,
            timescale=timescale,
        )
        bands.append(
            {
                "i": index,
                "x0": _plot_x_for_pick_store(x0),
                "x1": _plot_x_for_pick_store(x1),
            }
        )
    return {"enabled": True, "axis": time_axis_mode, "bands": bands}


def intervals_without_marked_indices(
    intervals: list,
    marked_indices: list | None,
) -> list:
    """Removes intervals whose indices appear in ``marked_indices``.

    Args:
        intervals (list): Full interval list.
        marked_indices (list, optional): Integer indices marked for removal.

    Returns:
        list: Filtered intervals (empty when all removed).
    """
    if not intervals or not marked_indices:
        return list(intervals) if intervals else []
    drop = {int(i) for i in marked_indices}
    return [row for idx, row in enumerate(intervals) if idx not in drop]
