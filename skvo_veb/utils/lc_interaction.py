"""Shared lightcurve trim, selection, and export-window helpers.

Pure functions used by Dash pages to mutate ``CurveDash`` instances or derive
non-destructive export views. Plot axis coordinates are either MJD
(``jd - display_epoch``) or calendar dates from Plotly; both are converted to
absolute Julian Date before trim/export mutations.
"""

from __future__ import annotations

import logging

import numpy as np

from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    TIME_AXIS_DATE,
    TIME_AXIS_MJD,
    normalize_time_axis_mode,
)
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def infer_time_axis_mode_from_x(x_value, fallback: str = TIME_AXIS_MJD) -> str:
    """Guesses the plot time-axis mode from a single Plotly x coordinate.

    Args:
        x_value: Horizontal coordinate from ``selectedData`` or bounds store.
        fallback (str): Mode to use for ambiguous numeric values.

    Returns:
        str: ``TIME_AXIS_MJD`` or ``TIME_AXIS_DATE``.
    """
    if isinstance(x_value, str):
        return TIME_AXIS_DATE
    try:
        numeric = float(x_value)
    except (TypeError, ValueError):
        return normalize_time_axis_mode(fallback)
    if not np.isfinite(numeric):
        return normalize_time_axis_mode(fallback)
    if abs(numeric) > 1e9:
        return TIME_AXIS_DATE
    if numeric > 1_000_000:
        return TIME_AXIS_MJD
    return normalize_time_axis_mode(fallback)


def plot_x_to_jd(
    x_value,
    time_axis_mode: str = TIME_AXIS_MJD,
    display_epoch: float = DEFAULT_EPOCH_JD,
) -> float:
    """Converts a plot x-axis coordinate to absolute Julian Date.

    Args:
        x_value: MJD offset, Plotly calendar date string, or Unix epoch value.
        time_axis_mode (str): ``mjd`` or ``date`` for the active graph axis.
        display_epoch (float): Epoch subtracted for the MJD display.

    Returns:
        float: Absolute Julian Date.

    Raises:
        ValueError: If ``x_value`` cannot be parsed as a time coordinate.
    """
    from astropy.time import Time

    mode = normalize_time_axis_mode(time_axis_mode)
    if x_value is None:
        raise ValueError('missing plot x coordinate')

    if mode == TIME_AXIS_MJD:
        numeric = float(x_value)
        if not np.isfinite(numeric):
            raise ValueError('non-finite MJD plot coordinate')
        return numeric + float(display_epoch)

    if isinstance(x_value, str):
        text = x_value.strip()
        if not text:
            raise ValueError('empty calendar date string')
        return float(Time(text).jd)

    numeric = float(x_value)
    if not np.isfinite(numeric):
        raise ValueError('non-finite date-axis coordinate')
    if abs(numeric) > 1e10:
        return float(Time(numeric / 1000.0, format='unix').jd)
    if numeric > 2_400_000:
        return numeric
    if abs(numeric) > 1e8:
        return float(Time(numeric, format='unix').jd)
    return float(Time(numeric, format='unix').jd)


def display_x_to_jd(display_x: float, display_epoch: float = DEFAULT_EPOCH_JD) -> float:
    """Converts an MJD plot-axis coordinate to absolute Julian Date.

    Args:
        display_x (float): Relative time on the graph (e.g. ``jd - 2400000.5``).
        display_epoch (float): Epoch subtracted for display.

    Returns:
        float: Absolute Julian Date.
    """
    return plot_x_to_jd(display_x, TIME_AXIS_MJD, display_epoch)


def _resolve_bounds_time_axis_mode(
    selection_bounds: dict | None,
    fallback: str = TIME_AXIS_MJD,
) -> str:
    """Returns the time-axis mode recorded on selection bounds or inferred from x.

    Args:
        selection_bounds (dict): ``{xmin, xmax, time_axis_mode?}`` payload.
        fallback (str): Default mode when none is stored.

    Returns:
        str: ``TIME_AXIS_MJD`` or ``TIME_AXIS_DATE``.
    """
    if selection_bounds and selection_bounds.get('time_axis_mode'):
        return normalize_time_axis_mode(selection_bounds['time_axis_mode'])
    if selection_bounds and selection_bounds.get('xmin') is not None:
        return infer_time_axis_mode_from_x(selection_bounds['xmin'], fallback)
    return normalize_time_axis_mode(fallback)


def selection_bounds_to_jd_range(
    selection_bounds: dict | None,
    display_epoch: float = DEFAULT_EPOCH_JD,
    time_axis_mode: str | None = None,
) -> tuple[float, float]:
    """Converts stored box-selection bounds to absolute Julian Date limits.

    Args:
        selection_bounds (dict): ``{xmin, xmax, time_axis_mode?}`` from the UI store.
        display_epoch (float): Epoch subtracted for the MJD display.
        time_axis_mode (str, optional): Active graph mode when bounds omit it.

    Returns:
        tuple[float, float]: Sorted ``(left_jd, right_jd)``.

    Raises:
        PipeException: If bounds are missing or cannot be parsed.
    """
    if not selection_bounds:
        raise PipeException('Draw a box selection on the lightcurve first.')
    xmin = selection_bounds.get('xmin')
    xmax = selection_bounds.get('xmax')
    if xmin is None or xmax is None:
        raise PipeException('Draw a box selection on the lightcurve first.')
    mode = _resolve_bounds_time_axis_mode(selection_bounds, time_axis_mode or TIME_AXIS_MJD)
    try:
        left_jd = plot_x_to_jd(xmin, mode, display_epoch)
        right_jd = plot_x_to_jd(xmax, mode, display_epoch)
    except (TypeError, ValueError) as exc:
        raise PipeException('Could not interpret the selected time range.') from exc
    return tuple(sorted((left_jd, right_jd)))


def extract_display_x_range_from_bounds(selection_bounds: dict | None) -> tuple | None:
    """Reads horizontal trim/export bounds from the lightweight selection store.

    Args:
        selection_bounds (dict): ``{xmin, xmax}`` in plot coordinates.

    Returns:
        tuple or None: ``(x_min, x_max)`` without coercion when values are dates.
    """
    if not selection_bounds:
        return None
    xmin = selection_bounds.get('xmin')
    xmax = selection_bounds.get('xmax')
    if xmin is None or xmax is None:
        return None
    return xmin, xmax


def extract_display_x_range_from_selected_data(selected_data: dict | None) -> tuple | None:
    """Reads the horizontal bounds of a Plotly box or lasso selection.

    Args:
        selected_data (dict): Plotly ``selectedData`` payload.

    Returns:
        tuple or None: ``(x_min, x_max)`` in plot coordinates.
    """
    if not selected_data:
        return None
    range_block = selected_data.get('range') or {}
    x_range = range_block.get('x')
    if x_range is None or len(x_range) != 2:
        return None
    return x_range[0], x_range[1]


def extract_display_x_range_from_relayout(
    relayout_data: dict | None,
    lc_metadata: dict | None = None,
) -> tuple[float, float] | None:
    """Reads the current zoomed x-axis window from Plotly relayout or cached metadata.

    Args:
        relayout_data (dict): Plotly ``relayoutData`` from the graph.
        lc_metadata (dict): Optional persisted axis-range metadata from ``dcc.Store``.

    Returns:
        tuple[float, float] or None: ``(x_min, x_max)`` in display coordinates.
    """
    if relayout_data:
        if relayout_data.get('xaxis.autorange') is True:
            return None
        left = relayout_data.get('xaxis.range[0]')
        right = relayout_data.get('xaxis.range[1]')
        if left is not None and right is not None:
            return left, right

    if lc_metadata:
        left = lc_metadata.get('xrange_left')
        right = lc_metadata.get('xrange_right')
        if left is not None and right is not None:
            return left, right

    return None


def resolve_export_jd_range(
    selection_bounds: dict | None = None,
    relayout_data: dict | None = None,
    lc_metadata: dict | None = None,
    selected_data: dict | None = None,
    display_epoch: float = DEFAULT_EPOCH_JD,
    time_axis_mode: str = TIME_AXIS_MJD,
) -> tuple[float, float] | None:
    """Chooses an export window in absolute Julian Date.

    Args:
        selection_bounds (dict): ``{xmin, xmax, time_axis_mode?}`` from the store.
        relayout_data (dict): Latest relayout event.
        lc_metadata (dict): Cached axis ranges from the metadata store.
        selected_data (dict): Optional Plotly ``selectedData`` fallback.
        display_epoch (float): Epoch subtracted for the MJD display.
        time_axis_mode (str): Active graph time-axis mode.

    Returns:
        tuple[float, float] or None: Sorted JD limits, or full-curve export.
    """
    if selection_bounds and selection_bounds.get('xmin') is not None:
        return selection_bounds_to_jd_range(
            selection_bounds,
            display_epoch=display_epoch,
            time_axis_mode=time_axis_mode,
        )

    x_range = extract_display_x_range_from_selected_data(selected_data)
    if x_range is not None:
        mode = infer_time_axis_mode_from_x(x_range[0], time_axis_mode)
        left_jd = plot_x_to_jd(x_range[0], mode, display_epoch)
        right_jd = plot_x_to_jd(x_range[1], mode, display_epoch)
        return tuple(sorted((left_jd, right_jd)))

    relayout_range = extract_display_x_range_from_relayout(relayout_data, lc_metadata)
    if relayout_range is not None:
        left_jd = plot_x_to_jd(relayout_range[0], time_axis_mode, display_epoch)
        right_jd = plot_x_to_jd(relayout_range[1], time_axis_mode, display_epoch)
        return tuple(sorted((left_jd, right_jd)))

    return None


def resolve_export_display_x_range(
    selection_bounds: dict | None = None,
    relayout_data: dict | None = None,
    lc_metadata: dict | None = None,
    selected_data: dict | None = None,
) -> tuple | None:
    """Chooses the export time window in raw plot coordinates.

    Prefer ``selection_bounds`` from ``store_*_selection_bounds``; ``selected_data``
    is a legacy fallback for pages that have not yet adopted the bounds store.

    Args:
        selection_bounds (dict): ``{xmin, xmax}`` from clientside box-select capture.
        relayout_data (dict): Latest relayout event.
        lc_metadata (dict): Cached axis ranges from the metadata store.
        selected_data (dict): Optional Plotly ``selectedData`` fallback.

    Returns:
        tuple or None: Export window in plot coordinates, or full curve.
    """
    selection_range = extract_display_x_range_from_bounds(selection_bounds)
    if selection_range is not None:
        return selection_range
    selection_range = extract_display_x_range_from_selected_data(selected_data)
    if selection_range is not None:
        return selection_range
    return extract_display_x_range_from_relayout(relayout_data, lc_metadata)


def require_time_view_for_trim(phase_view: bool) -> None:
    """Rejects trim when the plot x-axis is folded phase rather than time.

    Args:
        phase_view (bool): True when the UI shows phase on the x-axis.

    Raises:
        PipeException: If ``phase_view`` is true.
    """
    if phase_view:
        raise PipeException(
            'Trim is only available in time view. Switch off the folded view first'
        )


def trim_curvedash_display_range(
    lcd,
    left_display,
    right_display,
    display_epoch: float = DEFAULT_EPOCH_JD,
    time_axis_mode: str = TIME_AXIS_MJD,
):
    """Permanently removes observations inside a plot-axis time interval.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        left_display: Interval start in plot coordinates (MJD or calendar date).
        right_display: Interval end in plot coordinates.
        display_epoch (float): Epoch subtracted for the MJD display.
        time_axis_mode (str): ``mjd`` or ``date`` for the active graph axis.

    Returns:
        CurveDash: The same instance with the interior time range removed.
    """
    left_jd = plot_x_to_jd(left_display, time_axis_mode, display_epoch)
    right_jd = plot_x_to_jd(right_display, time_axis_mode, display_epoch)
    left_jd, right_jd = sorted((left_jd, right_jd))
    lcd.cut(left_jd, right_jd)
    return lcd


def trim_curvedash_from_selection_bounds(
    lcd,
    selection_bounds: dict | None,
    display_epoch: float = DEFAULT_EPOCH_JD,
    time_axis_mode: str | None = None,
):
    """Permanently removes the JD interval enclosed by stored box-selection bounds.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        selection_bounds (dict): ``{xmin, xmax, time_axis_mode?}`` from the UI store.
        display_epoch (float): Epoch subtracted for the MJD display.
        time_axis_mode (str, optional): Active graph mode when bounds omit it.

    Returns:
        CurveDash: The mutated instance.

    Raises:
        PipeException: If no usable horizontal selection range is present.
    """
    left_jd, right_jd = selection_bounds_to_jd_range(
        selection_bounds,
        display_epoch=display_epoch,
        time_axis_mode=time_axis_mode or TIME_AXIS_MJD,
    )
    lcd.cut(left_jd, right_jd)
    return lcd


def trim_curvedash_from_plot_selection(
    lcd,
    selected_data: dict | None,
    display_epoch: float = DEFAULT_EPOCH_JD,
    time_axis_mode: str = TIME_AXIS_MJD,
):
    """Permanently removes the time range enclosed by a Plotly box/lasso selection.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        selected_data (dict): Plotly ``selectedData`` with ``range.x`` bounds.
        display_epoch (float): Display epoch for the graph x-axis.
        time_axis_mode (str): Active graph time-axis mode.

    Returns:
        CurveDash: The mutated instance.

    Raises:
        PipeException: If no usable horizontal selection range is present.
    """
    x_range = extract_display_x_range_from_selected_data(selected_data)
    if x_range is None:
        raise PipeException('Draw a box or lasso selection on the lightcurve first.')
    mode = infer_time_axis_mode_from_x(x_range[0], time_axis_mode)
    return trim_curvedash_display_range(
        lcd,
        x_range[0],
        x_range[1],
        display_epoch=display_epoch,
        time_axis_mode=mode,
    )


def clip_curvedash_to_jd_range(lcd, left_jd: float, right_jd: float):
    """Keeps only observations inside an absolute Julian Date interval.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        left_jd (float): Interval start Julian Date.
        right_jd (float): Interval end Julian Date.

    Returns:
        CurveDash: The same instance restricted to the interval.
    """
    left_jd, right_jd = sorted((float(left_jd), float(right_jd)))
    lcd.keep(left_jd, right_jd)
    return lcd


def clip_curvedash_to_display_range(
    lcd,
    left_display,
    right_display,
    display_epoch: float = DEFAULT_EPOCH_JD,
    time_axis_mode: str = TIME_AXIS_MJD,
):
    """Keeps only observations inside a plot-axis interval (non-destructive).

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        left_display: Interval start in plot coordinates.
        right_display: Interval end in plot coordinates.
        display_epoch (float): Epoch subtracted for the MJD display.
        time_axis_mode (str): ``mjd`` or ``date`` for the active graph axis.

    Returns:
        CurveDash: The same instance restricted to the interval.
    """
    left_jd = plot_x_to_jd(left_display, time_axis_mode, display_epoch)
    right_jd = plot_x_to_jd(right_display, time_axis_mode, display_epoch)
    return clip_curvedash_to_jd_range(lcd, left_jd, right_jd)


def prepare_lcd_for_export(lcd, selection_bounds: dict | None = None,
                           relayout_data: dict | None = None,
                           lc_metadata: dict | None = None,
                           selected_data: dict | None = None,
                           display_epoch: float = DEFAULT_EPOCH_JD,
                           time_axis_mode: str = TIME_AXIS_MJD):
    """Returns a copy of a lightcurve clipped to the export time window.

    The stored lightcurve is left unchanged. Clipping uses ``selection_bounds``
    when present; otherwise the visible zoom range from relayout or cached metadata.

    Args:
        lcd (CurveDash): Source lightcurve (may already have been trimmed).
        selection_bounds (dict): ``{xmin, xmax, time_axis_mode?}`` from the store.
        relayout_data (dict): Plotly ``relayoutData`` from the graph.
        lc_metadata (dict): Cached axis-range metadata.
        selected_data (dict): Optional Plotly ``selectedData`` fallback.
        display_epoch (float): Display epoch for the graph x-axis.
        time_axis_mode (str): Active graph time-axis mode.

    Returns:
        CurveDash: Deserialised copy, optionally clipped to the resolved window.

    Raises:
        PipeException: If the source lightcurve is empty.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash) or lcd.lightcurve is None:
        raise PipeException('Cannot export an empty lightcurve.')

    export_lcd = CurveDash.from_serialized(lcd.serialize())
    jd_range = resolve_export_jd_range(
        selection_bounds,
        relayout_data,
        lc_metadata,
        selected_data,
        display_epoch=display_epoch,
        time_axis_mode=time_axis_mode,
    )
    if jd_range is not None:
        clip_curvedash_to_jd_range(export_lcd, jd_range[0], jd_range[1])
        if export_lcd.lightcurve is None or export_lcd.lightcurve.empty:
            logger.warning(
                'Export clip window contains no observations (often stale selection after trim); '
                'exporting the full stored lightcurve instead.'
            )
            export_lcd = CurveDash.from_serialized(lcd.serialize())
    return export_lcd


def normalize_selected_perm_store(store_data) -> list[int]:
    """Parses the lightweight selection store into integer ``perm_index`` values.

    Args:
        store_data: ``dcc.Store`` payload (list of ints or None).

    Returns:
        list[int]: Normalised permanent indices, possibly empty.
    """
    if not store_data:
        return []
    if isinstance(store_data, list):
        return [int(value) for value in store_data]
    return []


def perm_index_from_plot_point(point: dict, perm_index_by_row: list | None = None) -> int | None:
    """Extracts ``perm_index`` from a Plotly ``clickData`` / ``selectedData`` point.

    WebGL scatter traces often omit ``customdata`` in server callbacks; in that
    case the trace-local ``pointIndex`` / ``pointNumber`` is mapped through
    ``perm_index_by_row``.

    Args:
        point (dict): Single point entry from a Plotly interaction event.
        perm_index_by_row (list, optional): ``perm_index`` values in trace order.

    Returns:
        int or None: Permanent row index, or None when the point cannot be mapped.
    """
    custom = point.get('customdata')
    if custom is not None:
        raw = custom[0] if isinstance(custom, (list, tuple)) else custom
        return int(np.asarray(raw).item())

    point_index = point.get('pointIndex')
    if point_index is None:
        point_index = point.get('pointNumber')
    if point_index is not None and perm_index_by_row is not None:
        row_index = int(point_index)
        if 0 <= row_index < len(perm_index_by_row):
            return int(perm_index_by_row[row_index])
    return None


def row_index_from_plot_point(point: dict) -> int | None:
    """Returns the dataframe row index for a single-trace Plotly point event.

    Args:
        point (dict): Single point entry from a Plotly interaction event.

    Returns:
        int or None: Row index in the plotted trace order.
    """
    point_index = point.get('pointIndex')
    if point_index is None:
        point_index = point.get('pointNumber')
    if point_index is None:
        return None
    return int(point_index)


def trace_selected_indices_from_column(lcd) -> list[int]:
    """Returns Plotly ``selectedpoints`` indices from the ``selected`` column.

    Mirrors the legacy clientside ``plotLightcurveFromStore`` behaviour.

    Args:
        lcd (CurveDash): Lightcurve with a ``selected`` marker column.

    Returns:
        list[int]: Trace-local indices of rows marked ``selected=1``.
    """
    if lcd.lightcurve is None or 'selected' not in lcd.lightcurve.columns:
        return []
    return [
        index
        for index, value in enumerate(lcd.lightcurve['selected'].tolist())
        if int(value) == 1
    ]


def clear_plot_point_selection(lcd) -> None:
    """Clears all ``selected`` markers in the lightcurve table.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
    """
    if lcd.lightcurve is None or 'selected' not in lcd.lightcurve.columns:
        return
    lcd.lightcurve.loc[:, 'selected'] = 0


def delete_selected_rows(lcd) -> None:
    """Permanently removes rows marked ``selected=1``.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
    """
    if lcd.lightcurve is None or 'selected' not in lcd.lightcurve.columns:
        return
    lcd.lightcurve = lcd.lightcurve[lcd.lightcurve['selected'] != 1].reset_index(drop=True)


def merge_perm_indices_from_plot_event(current_perm, event_data: dict | None) -> list[int]:
    """Merges ``perm_index`` values from a Plotly selection event into the store list.

    Args:
        current_perm: Existing ``dcc.Store`` selection payload.
        event_data (dict): Plotly ``selectedData`` or ``clickData`` payload.

    Returns:
        list[int]: Sorted unique permanent indices.
    """
    selected = set(normalize_selected_perm_store(current_perm))
    if not event_data or 'points' not in event_data:
        return sorted(selected)
    for point in event_data['points']:
        perm_index = perm_index_from_plot_point(point)
        if perm_index is not None:
            selected.add(perm_index)
    return sorted(selected)


def trace_selected_indices(lcd, selected_perm_indices) -> list[int]:
    """Maps ``perm_index`` values to trace point indices for a single trace.

    Args:
        lcd (CurveDash): Lightcurve with ``perm_index`` column.
        selected_perm_indices: Iterable of selected permanent indices.

    Returns:
        list[int]: Indices suitable for Plotly ``selectedpoints`` on one trace.
    """
    if lcd.lightcurve is None or not selected_perm_indices:
        return []
    selected_set = {int(value) for value in selected_perm_indices}
    perm = lcd.perm_index
    return [index for index, perm_value in enumerate(perm) if int(perm_value) in selected_set]


def apply_selectedpoints_to_figure(fig, selected_perm_indices) -> None:
    """Highlights selected observations on every trace via ``selectedpoints``.

    Args:
        fig (plotly.graph_objects.Figure): Scatter figure with ``perm_index`` customdata.
        selected_perm_indices: Iterable of selected permanent indices.
    """
    selected_set = {int(value) for value in (selected_perm_indices or [])}
    for trace in fig.data:
        custom = trace.customdata
        if custom is None or not selected_set:
            trace.selectedpoints = []
            continue
        indices = []
        for point_index, custom_value in enumerate(custom):
            perm_raw = custom_value[0] if isinstance(custom_value, (list, tuple)) else custom_value
            perm = int(np.asarray(perm_raw).item())
            if perm in selected_set:
                indices.append(point_index)
        trace.selectedpoints = indices


def delete_rows_by_perm_indices(lcd, perm_indices) -> None:
    """Permanently removes rows whose ``perm_index`` is in ``perm_indices``.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        perm_indices: Iterable of permanent indices to drop.
    """
    if lcd.lightcurve is None or not perm_indices:
        return
    drop_set = {int(value) for value in perm_indices}
    mask = ~lcd.lightcurve['perm_index'].isin(drop_set)
    lcd.lightcurve = lcd.lightcurve.loc[mask].reset_index(drop=True)


def apply_plot_point_selection(lcd, event_data: dict | None):
    """Marks lightcurve rows selected using Plotly click or lasso/box events.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        event_data (dict): Plotly ``selectedData`` or ``clickData`` payload.

    Returns:
        CurveDash: The same instance with matching rows marked ``selected=1``.
    """
    if lcd.lightcurve is None or not event_data or 'points' not in event_data:
        return lcd

    df = lcd.lightcurve
    if 'selected' not in df.columns or 'perm_index' not in df.columns:
        return lcd

    perm_by_row = df['perm_index'].tolist()
    perm_to_row = {int(value): idx for idx, value in enumerate(perm_by_row)}

    for point in event_data['points']:
        row_idx = row_index_from_plot_point(point)
        if row_idx is not None and 0 <= row_idx < len(df):
            df.loc[row_idx, 'selected'] = 1
            continue

        perm_index = perm_index_from_plot_point(point, perm_by_row)
        if perm_index is None:
            continue
        mapped_row = perm_to_row.get(int(perm_index))
        if mapped_row is not None:
            df.loc[mapped_row, 'selected'] = 1

    return lcd
