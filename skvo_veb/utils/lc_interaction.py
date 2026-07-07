"""Shared lightcurve trim, selection, and export-window helpers.

Pure functions used by Dash pages to mutate ``CurveDash`` instances or derive
non-destructive export views. Plot axis coordinates are relative JD
(``jd - display_epoch``); absolute Julian dates are recovered by adding
``display_epoch``.
"""

from __future__ import annotations

import logging

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def display_x_to_jd(display_x: float, display_epoch: float = DEFAULT_EPOCH_JD) -> float:
    """Converts a plot-axis time coordinate to absolute Julian Date.

    Args:
        display_x (float): Relative time on the graph (e.g. ``jd - 2400000.5``).
        display_epoch (float): Epoch subtracted for display.

    Returns:
        float: Absolute Julian Date.
    """
    return float(display_x) + float(display_epoch)


def extract_display_x_range_from_bounds(selection_bounds: dict | None) -> tuple[float, float] | None:
    """Reads horizontal trim/export bounds from the lightweight selection store.

    Args:
        selection_bounds (dict): ``{xmin, xmax}`` in display coordinates.

    Returns:
        tuple[float, float] or None: ``(x_min, x_max)`` in display coordinates.
    """
    if not selection_bounds:
        return None
    xmin = selection_bounds.get('xmin')
    xmax = selection_bounds.get('xmax')
    if xmin is None or xmax is None:
        return None
    return float(xmin), float(xmax)


def extract_display_x_range_from_selected_data(selected_data: dict | None) -> tuple[float, float] | None:
    """Reads the horizontal bounds of a Plotly box or lasso selection.

    Args:
        selected_data (dict): Plotly ``selectedData`` payload.

    Returns:
        tuple[float, float] or None: ``(x_min, x_max)`` in display coordinates.
    """
    if not selected_data:
        return None
    range_block = selected_data.get('range') or {}
    x_range = range_block.get('x')
    if x_range is None or len(x_range) != 2:
        return None
    return float(x_range[0]), float(x_range[1])


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
            return float(left), float(right)

    if lc_metadata:
        left = lc_metadata.get('xrange_left')
        right = lc_metadata.get('xrange_right')
        if left is not None and right is not None:
            return float(left), float(right)

    return None


def resolve_export_display_x_range(
    selection_bounds: dict | None = None,
    relayout_data: dict | None = None,
    lc_metadata: dict | None = None,
    selected_data: dict | None = None,
) -> tuple[float, float] | None:
    """Chooses the export time window: selection bounds first, then visible zoom.

    Prefer ``selection_bounds`` from ``store_*_selection_bounds``; ``selected_data``
    is a legacy fallback for pages that have not yet adopted the bounds store.

    Args:
        selection_bounds (dict): ``{xmin, xmax}`` from clientside box-select capture.
        relayout_data (dict): Latest relayout event.
        lc_metadata (dict): Cached axis ranges from the metadata store.
        selected_data (dict): Optional Plotly ``selectedData`` fallback.

    Returns:
        tuple[float, float] or None: Export window in display coordinates, or full curve.
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


def trim_curvedash_display_range(lcd, left_display: float, right_display: float,
                                 display_epoch: float = DEFAULT_EPOCH_JD):
    """Permanently removes observations inside a display-axis time interval.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        left_display (float): Interval start in display coordinates.
        right_display (float): Interval end in display coordinates.
        display_epoch (float): Display epoch added to recover absolute JD.

    Returns:
        CurveDash: The same instance with the interior time range removed.
    """
    left_jd, right_jd = sorted((display_x_to_jd(left_display, display_epoch),
                                display_x_to_jd(right_display, display_epoch)))
    lcd.cut(left_jd, right_jd)
    return lcd


def trim_curvedash_from_plot_selection(lcd, selected_data: dict | None,
                                       display_epoch: float = DEFAULT_EPOCH_JD):
    """Permanently removes the time range enclosed by a Plotly box/lasso selection.

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        selected_data (dict): Plotly ``selectedData`` with ``range.x`` bounds.
        display_epoch (float): Display epoch for the graph x-axis.

    Returns:
        CurveDash: The mutated instance.

    Raises:
        PipeException: If no usable horizontal selection range is present.
    """
    x_range = extract_display_x_range_from_selected_data(selected_data)
    if x_range is None:
        raise PipeException('Draw a box or lasso selection on the lightcurve first.')
    return trim_curvedash_display_range(lcd, x_range[0], x_range[1], display_epoch)


def clip_curvedash_to_display_range(lcd, left_display: float, right_display: float,
                                    display_epoch: float = DEFAULT_EPOCH_JD):
    """Keeps only observations inside a display-axis interval (non-destructive).

    Args:
        lcd (CurveDash): Lightcurve to mutate in place.
        left_display (float): Interval start in display coordinates.
        right_display (float): Interval end in display coordinates.
        display_epoch (float): Display epoch added to recover absolute JD.

    Returns:
        CurveDash: The same instance restricted to the interval.
    """
    left_jd, right_jd = sorted((display_x_to_jd(left_display, display_epoch),
                                display_x_to_jd(right_display, display_epoch)))
    lcd.keep(left_jd, right_jd)
    return lcd


def prepare_lcd_for_export(lcd, selection_bounds: dict | None = None,
                           relayout_data: dict | None = None,
                           lc_metadata: dict | None = None,
                           selected_data: dict | None = None,
                           display_epoch: float = DEFAULT_EPOCH_JD):
    """Returns a copy of a lightcurve clipped to the export time window.

    The stored lightcurve is left unchanged. Clipping uses ``selection_bounds``
    when present; otherwise the visible zoom range from relayout or cached metadata.

    Args:
        lcd (CurveDash): Source lightcurve (may already have been trimmed).
        selection_bounds (dict): ``{xmin, xmax}`` from the selection bounds store.
        relayout_data (dict): Plotly ``relayoutData`` from the graph.
        lc_metadata (dict): Cached axis-range metadata.
        selected_data (dict): Optional Plotly ``selectedData`` fallback.
        display_epoch (float): Display epoch for the graph x-axis.

    Returns:
        CurveDash: Deserialised copy, optionally clipped to the resolved window.

    Raises:
        PipeException: If the source lightcurve is empty.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash) or lcd.lightcurve is None:
        raise PipeException('Cannot export an empty lightcurve.')

    export_lcd = CurveDash.from_serialized(lcd.serialize())
    x_range = resolve_export_display_x_range(
        selection_bounds, relayout_data, lc_metadata, selected_data
    )
    if x_range is not None:
        clip_curvedash_to_display_range(export_lcd, x_range[0], x_range[1], display_epoch)
        if export_lcd.lightcurve is None or export_lcd.lightcurve.empty:
            logger.warning(
                'Export clip window contains no observations (often stale selection after trim); '
                'exporting the full stored lightcurve instead.'
            )
            export_lcd = CurveDash.from_serialized(lcd.serialize())
    return export_lcd


def apply_plot_point_selection(lcd, event_data: dict | None):
    """Marks lightcurve rows selected using ``perm_index`` from a Plotly event.

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

    perm_to_row = {int(row['perm_index']): idx for idx, row in df.iterrows()}

    for point in event_data['points']:
        custom = point.get('customdata')
        if custom is None:
            continue
        perm_index = int(custom[0] if isinstance(custom, (list, tuple)) else custom)
        row_idx = perm_to_row.get(perm_index)
        if row_idx is not None:
            df.loc[row_idx, 'selected'] = 1

    return lcd
