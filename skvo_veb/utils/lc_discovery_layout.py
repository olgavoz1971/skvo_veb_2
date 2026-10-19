"""Layout arithmetic for the Discovery search results panel."""

import logging

logger = logging.getLogger(__name__)

# Frame of the grid that is not column width: borders plus the vertical scrollbar.
GRID_FRAME_ALLOWANCE_PX = 20


def catalog_grid_width_px(column_state: list[dict] | None) -> int | None:
    """Sums the widths of the visible AgGrid columns plus the grid frame.

    Args:
        column_state (list[dict], optional): ``columnState`` of the grid; each item has
            ``colId``, ``width`` and optionally ``hide``.

    Returns:
        int | None: Width in pixels the grid needs to show every visible column
        without blank space on the right, or None while the state is empty.

    Raises:
        ValueError: If a visible column has no numeric ``width``.
    """
    if not column_state:
        return None
    total = 0.0
    for column in column_state:
        if column.get('hide'):
            continue
        width = column.get('width')
        if not isinstance(width, (int, float)):
            raise ValueError(f"Column {column.get('colId')!r} has no numeric width in the column state.")
        total += width
    return int(round(total)) + GRID_FRAME_ALLOWANCE_PX
