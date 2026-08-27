"""Prep-plot interval pick bands for GP O-C (unfolded lightcurve only)."""

from __future__ import annotations

from skvo_veb.utils.gp.working_window import interval_overlaps_jd_window

GP_INTERVAL_SHAPE_NAME_PREFIX = "gp-int-"


def interval_shape_name(index: int) -> str:
    """Returns the Plotly layout shape name for interval ``index``.

    Args:
        index (int): Row index in ``store-intervals-data``.

    Returns:
        str: Stable shape name for clientside mark styling.
    """
    return f"{GP_INTERVAL_SHAPE_NAME_PREFIX}{index}"


def prep_interval_band_shape_style(*, marked: bool) -> dict:
    """Plotly rectangle shape kwargs for one interval band on the prep plot.

    Args:
        marked (bool): Whether the interval is marked for removal.

    Returns:
        dict: ``fillcolor``, ``opacity``, and ``line`` kwargs for ``fig.add_shape``.
    """
    if marked:
        return {
            "fillcolor": "rgba(220, 53, 69, 0.35)",
            "opacity": 0.35,
            "line": {"color": "#dc3545", "width": 2},
            "editable": False,
        }
    return {
        "fillcolor": "green",
        "opacity": 0.15,
        "line": {"color": "green", "width": 1},
        "editable": False,
    }


def prep_interval_band_shape(
    x0,
    x1,
    *,
    name: str | None = None,
    marked: bool = False,
) -> dict:
    """Builds one Plotly rectangle shape dict for an interval band.

    Returned dicts are meant to be collected into a list and assigned in a single
    ``fig.update_layout(shapes=...)`` call. Adding bands one at a time with
    ``fig.add_shape`` or ``fig.add_vrect`` is quadratic in the band count, because
    each call re-validates the whole existing shapes tuple.

    Args:
        x0: Left edge in plot x coordinates (MJD offset, phase, or datetime).
        x1: Right edge in plot x coordinates.
        name (str, optional): Stable shape name for clientside styling; omitted
            when ``None`` so bands that are never marked stay anonymous.
        marked (bool): Whether the interval is marked for removal.

    Returns:
        dict: Shape kwargs spanning the full plot height (``yref="paper"``).
    """
    shape = {
        "type": "rect",
        "xref": "x",
        "yref": "paper",
        "x0": x0,
        "x1": x1,
        "y0": 0,
        "y1": 1,
        "layer": "below",
        **prep_interval_band_shape_style(marked=marked),
    }
    if name is not None:
        shape["name"] = name
    return shape


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
    jd_window: tuple[float, float] | None = None,
) -> dict:
    """Builds clientside hit-test metadata for unfolded interval bands.

    Args:
        intervals (list, optional): ``[[jd_start, jd_end], ...]`` in absolute JD.
        time_axis_mode (str): Active MJD or date axis mode.
        display_epoch (float): JD reference for MJD display.
        timescale (str, optional): ``TIMESYS/@timescale`` for date axis.
        jd_window (tuple, optional): When set, ``(jd_min, jd_max)``; bands outside
            the closed window are omitted (indices unchanged for survivors).

    Returns:
        dict: ``{enabled, axis, styles, bands: [{i, x0, x1}, ...]}`` for
            ``dcc.Store``. ``styles`` carries the plain and marked band
            appearance so the clientside recolour has a single source of truth.
    """
    from skvo_veb.utils.lc_figure import absolute_jd_to_plot_x

    styles = {
        "plain": prep_interval_band_shape_style(marked=False),
        "marked": prep_interval_band_shape_style(marked=True),
    }
    if not intervals:
        return {
            "enabled": True,
            "axis": time_axis_mode,
            "styles": styles,
            "bands": [],
        }

    bands = []
    for index, interval in enumerate(intervals):
        if jd_window is not None and not interval_overlaps_jd_window(
            interval, jd_window[0], jd_window[1]
        ):
            continue
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
    return {
        "enabled": True,
        "axis": time_axis_mode,
        "styles": styles,
        "bands": bands,
    }


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
