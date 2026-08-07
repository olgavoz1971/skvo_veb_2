"""Live GP Processing View grid (paginated slots while fitting)."""

from __future__ import annotations

import plotly.graph_objects as go
from dash import dcc, html

from skvo_veb.utils.gp.config import GP_LIVE_PAGE_SIZE
from skvo_veb.utils.gp.review_page import _fail_card_content, badges_from_specs


def live_slot_waiting() -> html.Div:
    """Placeholder content for a grid cell before its fit has finished.

    Returns:
        html.Div: Centred grey ``Waiting`` label.
    """
    return html.Div("Waiting", className="gp-live-slot-waiting")


def live_visible_page_for_done_count(
    done_count: int,
    page_size: int = GP_LIVE_PAGE_SIZE,
) -> int:
    """Page index to show after ``done_count`` fits have completed.

    When the page fills (e.g. 6 done), the user stays on that page while the
    next fit runs. When fit 7 completes, this returns page 1 so extremum 7
    appears in the first cell.

    Args:
        done_count (int): Number of completed fits (success or failure).
        page_size (int): Live grid capacity per page.

    Returns:
        int: Zero-based page index.
    """
    if done_count <= 0:
        return 0
    return (done_count - 1) // page_size


def live_progress_label(done: int, total: int) -> str:
    """Formats the live fitting progress line.

    Args:
        done (int): Completed fits so far.
        total (int): Total fits scheduled this run.

    Returns:
        str: e.g. ``7 extrema from 150 ready``.
    """
    if total <= 0:
        return "No intervals to fit"
    return f"{done} extrema from {total} ready"


def live_slot_card(entry: dict) -> html.Div:
    """Builds one live grid cell (badges + graph or failure), without export checkbox.

    Args:
        entry (dict): Serialised review row.

    Returns:
        html.Div: Bordered card body for the slot.
    """
    is_fail = entry["is_fail"]
    badges = badges_from_specs(entry.get("badge_specs", []))
    badge_row = html.Div(badges, style={"textAlign": "center", "marginBottom": "2px"})

    if is_fail:
        content = _fail_card_content(entry)
    else:
        fig = go.Figure(entry["figure_json"])
        content = dcc.Graph(figure=fig, config={"displaylogo": False})  # type: ignore[arg-type]

    return html.Div(
        [badge_row, content],
        style={
            "border": "1px solid #eee",
            "padding": "10px",
            "borderRadius": "5px",
            "backgroundColor": "#fdfdfd" if is_fail else "white",
            "minHeight": "200px",
        },
    )


def build_live_page_slot_children(
    stored_entries: list[dict],
    visible_page: int,
    page_size: int = GP_LIVE_PAGE_SIZE,
) -> list:
    """Returns inner ``children`` for each fixed live slot on the visible page.

    Args:
        stored_entries (list[dict]): Completed fits in order.
        visible_page (int): Zero-based live page index.
        page_size (int): Number of slots (must match layout slot count).

    Returns:
        list: One element per slot index ``0 .. page_size - 1``.
    """
    slots = []
    for slot in range(page_size):
        global_idx = visible_page * page_size + slot
        if global_idx < len(stored_entries):
            slots.append(live_slot_card(stored_entries[global_idx]))
        else:
            slots.append(live_slot_waiting())
    return slots
