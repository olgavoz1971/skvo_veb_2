"""Paginated Review and Export grid for the GP O-C page."""

from __future__ import annotations

import math

import dash_bootstrap_components as dbc
from dash import html

from skvo_veb.components.fail_fit_badge import failed_fit_badge, review_card_graph
from skvo_veb.components.extrema_modeller_appearance import CARD_COL_WIDTH, PAGE_SIZE

_FAIL_TITLE = "GP fit failed"
_FAIL_BADGE_TYPE = "gp-fail-badge"


def success_badge_specs(
    kernel_type: str,
    opt_l: float,
    l_color: str,
    opt_ampl: float,
    amp_color: str,
    sigma_t: float,
    *,
    window_capped: bool = False,
) -> list[dict]:
    """Builds serialisable badge metadata for a successful GP fit.

    Args:
        kernel_type (str): Kernel name shown in the UI.
        opt_l (float): Optimised length scale.
        l_color (str): Bootstrap colour for length-scale badge.
        opt_ampl (float): Optimised amplitude.
        amp_color (str): Bootstrap colour for amplitude badge.
        sigma_t (float): Peak time uncertainty (days).
        window_capped (bool): True when a max half-width trimmed this interval.

    Returns:
        list[dict]: ``label`` and ``color`` keys for each badge.
    """
    specs = [
        {"label": f"Kernel: {kernel_type.upper()}", "color": "dark"},
        {"label": f"Scale: {opt_l:.4f}", "color": l_color},
        {"label": f"Amp: {opt_ampl:.3f}", "color": amp_color},
        {"label": f"σ_t: {sigma_t:.4f}", "color": "secondary"},
    ]
    if window_capped:
        specs.append({"label": "window capped", "color": "warning"})
    return specs


def badges_from_specs(specs: list[dict]) -> list:
    """Turns badge specs into Dash Bootstrap badge components.

    Args:
        specs (list[dict]): Output of ``success_badge_specs`` or failure specs.

    Returns:
        list: ``dbc.Badge`` components.
    """
    return [
        dbc.Badge(spec["label"], color=spec["color"], className="me-1")
        for spec in specs
    ]


def serialise_review_entry(res_entry: dict, *, figure_json: dict | None = None) -> dict:
    """Converts an in-memory ``run_gp`` result row to a cache-friendly dict.

    Args:
        res_entry (dict): One element from ``results_for_storage``.
        figure_json (dict, optional): Plotly JSON for the card plot (success or
            failed-interval observations).

    Returns:
        dict: Row suitable for ``save_gp_review_run``.
    """
    row = {
        "is_fail": bool(res_entry.get("is_fail")),
        "jd_min": res_entry.get("jd_min"),
        "jd_max": res_entry.get("jd_max"),
        "badge_specs": res_entry.get("badge_specs", []),
        "kernel_type": res_entry.get("kernel_type"),
        "length_scale": res_entry.get("length_scale"),
        "amplitude": res_entry.get("amplitude"),
    }
    if row["is_fail"]:
        row["error"] = res_entry.get("error", "")
        if figure_json is not None:
            row["figure_json"] = figure_json
        return row
    row["jd_peak"] = res_entry["jd_peak"]
    row["jd_peak_std"] = res_entry["jd_peak_std"]
    row["scale_limit_flag"] = int(res_entry["scale_limit_flag"])
    row["figure_json"] = figure_json
    return row


def build_review_store_payload(
    run_id: str,
    entries: list[dict],
    *,
    stopped_early: bool = False,
    source_filename: str | None = None,
    max_half_width_d: float | None = None,
) -> dict:
    """Builds ``store-results-data`` content for a finished GP run.

    Args:
        run_id (str): Cache key for full review rows.
        entries (list[dict]): Serialised review entries (same order as intervals).
        stopped_early (bool): True when the user stopped the batch before all intervals.
        source_filename (str | None): Light-curve filename at the time of this run.
        max_half_width_d (float | None): Optional half-width cap used for this run.

    Returns:
        dict: Run id, page index, include flags, export rows, and source filename.
    """
    include = [not row["is_fail"] for row in entries]
    rows = []
    for row in entries:
        if row["is_fail"]:
            rows.append({"is_fail": True})
        else:
            rows.append(
                {
                    "is_fail": False,
                    "jd_peak": row["jd_peak"],
                    "jd_peak_std": row["jd_peak_std"],
                    "scale_limit_flag": int(row["scale_limit_flag"]),
                }
            )
    return {
        "run_id": run_id,
        "page": 0,
        "include": include,
        "rows": rows,
        "stopped_early": stopped_early,
        "source_filename": source_filename,
        "max_half_width_d": max_half_width_d,
    }


def review_page_label(page: int, total_count: int, page_size: int = PAGE_SIZE) -> str:
    """Formats the Review and Export page caption.

    Args:
        page (int): Zero-based page index.
        total_count (int): Total number of fit cards.
        page_size (int): Cards per page.

    Returns:
        str: Human-readable range and page numbers.
    """
    if total_count <= 0:
        return "No fits to review"
    total_pages = max(1, math.ceil(total_count / page_size))
    start = page * page_size
    end = min(start + page_size, total_count)
    return (
        f"Page {page + 1} of {total_pages} · "
        f"showing fits {start + 1}–{end} of {total_count}"
    )


def badge_row_for_entry(entry: dict, *, view: str, index: int) -> html.Div:
    """Builds the card badge row, with a hover/click FAILED popover on failures.

    Args:
        entry (dict): Serialised review row.
        view (str): ``review`` or ``live`` (keeps Dash ids unique).
        index (int): Card index in the full batch.

    Returns:
        html.Div: Badge row for the card header.
    """
    if entry.get("is_fail"):
        children = failed_fit_badge(
            title=_FAIL_TITLE,
            reason=entry.get("error") or "",
            jd_min=entry.get("jd_min"),
            jd_max=entry.get("jd_max"),
            target_id={"type": _FAIL_BADGE_TYPE, "index": index, "view": view},
        )
    else:
        children = badges_from_specs(entry.get("badge_specs", []))
    return html.Div(children, className="gp-review-badges")


def create_review_interval_card(
    entry: dict,
    global_index: int,
    *,
    include_in_export: bool,
) -> dbc.Col:
    """Wraps one review fit in a grid card.

    Args:
        entry (dict): Serialised review row from the server cache.
        global_index (int): Index across the full batch (for checkboxes and export).
        include_in_export (bool): Current include flag from ``store-results-data``.

    Returns:
        dbc.Col: Card with checkbox, badges, and graph.
    """
    is_fail = entry["is_fail"]
    badge_row = badge_row_for_entry(entry, view="review", index=global_index)

    checkbox = dbc.Checkbox(
        id={"type": "fit-selector", "index": global_index},
        value=include_in_export,
        disabled=is_fail,
        label="Keep result" if not is_fail else "Fit failed",
        className="mb-1 fw-bold",
    )

    content = review_card_graph(entry)

    return dbc.Col(
        html.Div(
            [checkbox, badge_row, content],
            style={
                "border": "1px solid #eee",
                "padding": "10px",
                "borderRadius": "5px",
                "backgroundColor": "#fdfdfd" if is_fail else "white",
            },
        ),
        width=CARD_COL_WIDTH,
        className="px-1 mb-2",
    )


def render_review_page(
    entries: list[dict],
    page: int,
    include_flags: list[bool],
    page_size: int = PAGE_SIZE,
) -> list:
    """Returns ``dbc.Col`` children for one page of the review grid.

    Args:
        entries (list[dict]): Full serialised review list.
        page (int): Zero-based page index.
        include_flags (list[bool]): Per-index export inclusion flags.
        page_size (int): Maximum cards on this page.

    Returns:
        list: Dash layout children for ``graphs-container``.
    """
    if not entries:
        return [html.P("No fits to review.", className="text-muted")]

    start = page * page_size
    end = min(start + page_size, len(entries))
    cards = []
    for global_index in range(start, end):
        entry = entries[global_index]
        cards.append(
            create_review_interval_card(
                entry,
                global_index,
                include_in_export=include_flags[global_index],
            )
        )
    return cards
