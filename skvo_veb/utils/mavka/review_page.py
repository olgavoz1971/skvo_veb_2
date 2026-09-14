"""Paginated Review and Export grid for the MAVKA accordion."""

from __future__ import annotations

import math
from typing import Any

import dash_bootstrap_components as dbc
from dash import html

from skvo_veb.components.fail_fit_badge import failed_fit_badge, review_card_graph
from skvo_veb.components.extrema_modeller_appearance import CARD_COL_WIDTH, PAGE_SIZE
from skvo_veb.utils.mavka.models import ApproxFitResult

_FAIL_TITLE = "MAVKA fit failed"
_FAIL_BADGE_TYPE = "mavka-fail-badge"


def _json_number(value: Any) -> float | None:
    """Converts a numeric value to a JSON-safe Python float.

    Args:
        value: Raw number (including NumPy scalars).

    Returns:
        float | None: Finite float, or ``None`` when missing or non-finite.
    """
    if value is None:
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(val):
        return None
    return val


def format_sigma_t_seconds_label(sigma_t_days: float) -> str:
    """Formats σ(TOM) uncertainty in seconds for the grey review badge.

    Args:
        sigma_t_days (float): Formal TOM uncertainty in days (same units as JD).

    Returns:
        str: Badge label, e.g. ``σ_t: 864 s``.
    """
    if not math.isfinite(sigma_t_days):
        return "σ_t: —"
    seconds = sigma_t_days * 86400.0
    return f"σ_t: {seconds:.1f} s"


def success_badge_specs(
    fit: ApproxFitResult, *, window_capped: bool = False
) -> list[dict]:
    """Builds serialisable badge metadata for a successful MAVKA fit.

    Args:
        fit (ApproxFitResult): Successful interval fit.
        window_capped (bool): True when a max half-width trimmed this interval.

    Returns:
        list[dict]: ``label`` and ``color`` keys for each badge.
    """
    specs = [
        {"label": fit.method, "color": "dark"},
        {"label": format_sigma_t_seconds_label(fit.sigma_t_ext), "color": "secondary"},
        {"label": f"rms: {fit.rms:.4f}", "color": "info"},
    ]
    if fit.warning:
        specs.append({"label": "Warning", "color": "warning"})
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


def review_entry_from_fit(
    fit: ApproxFitResult,
    jd_min: float,
    jd_max: float,
    *,
    window_capped: bool = False,
) -> dict:
    """Builds one in-memory review row from a MAVKA fit result.

    Args:
        fit (ApproxFitResult): Interval fit (success or failure).
        jd_min (float): Fit-window start (absolute JD).
        jd_max (float): Fit-window stop (absolute JD).
        window_capped (bool): True when a max half-width trimmed this interval.

    Returns:
        dict: Row ready for ``serialise_review_entry``.
    """
    base = {
        "jd_min": _json_number(jd_min),
        "jd_max": _json_number(jd_max),
        "method": fit.method,
        "rms": _json_number(fit.rms),
        "c4": _json_number(fit.c4),
        "c5": _json_number(fit.c5),
        "y_ext": _json_number(fit.y_ext),
        "warning": fit.warning,
        "n_points": int(fit.n_points),
    }
    if not fit.ok:
        base.update(
            {
                "is_fail": True,
                "error": fit.fail_reason or "MAVKA fit failed",
                "badge_specs": [{"label": "FAILED", "color": "danger"}],
            }
        )
        return base
    base.update(
        {
            "is_fail": False,
            "jd_peak": _json_number(fit.t_ext),
            "jd_peak_std": _json_number(fit.sigma_t_ext),
            "badge_specs": success_badge_specs(fit, window_capped=window_capped),
        }
    )
    return base


def serialise_review_entry(res_entry: dict, *, figure_json: dict | None = None) -> dict:
    """Converts an in-memory MAVKA result row to a cache-friendly dict.

    Args:
        res_entry (dict): One element from the batch result list.
        figure_json (dict, optional): Plotly JSON for the card plot (success or
            failed-interval observations).

    Returns:
        dict: Row suitable for ``save_mavka_review_run``.
    """
    row = {
        "is_fail": bool(res_entry.get("is_fail")),
        "jd_min": res_entry.get("jd_min"),
        "jd_max": res_entry.get("jd_max"),
        "badge_specs": res_entry.get("badge_specs", []),
        "method": res_entry.get("method"),
        "rms": res_entry.get("rms"),
        "c4": res_entry.get("c4"),
        "c5": res_entry.get("c5"),
        "y_ext": res_entry.get("y_ext"),
        "warning": res_entry.get("warning"),
        "n_points": res_entry.get("n_points"),
    }
    if row["is_fail"]:
        row["error"] = res_entry.get("error", "")
        if figure_json is not None:
            row["figure_json"] = figure_json
        return row
    row["jd_peak"] = res_entry["jd_peak"]
    row["jd_peak_std"] = res_entry["jd_peak_std"]
    row["figure_json"] = figure_json
    return row


def build_review_store_payload(
    run_id: str,
    entries: list[dict],
    *,
    stopped_early: bool = False,
    source_filename: str | None = None,
    method: str | None = None,
    max_half_width_d: float | None = None,
) -> dict:
    """Builds ``store-mavka-results-data`` content for a finished MAVKA run.

    Args:
        run_id (str): Cache key for full review rows.
        entries (list[dict]): Serialised review entries (same order as intervals).
        stopped_early (bool): True when the user stopped the batch before all intervals.
        source_filename (str | None): Light-curve filename at the time of this run.
        method (str | None): Approximation id used for this run (``WSAP``, …).
        max_half_width_d (float | None): Optional half-width cap used for this run.

    Returns:
        dict: Run id, page index, include flags, export rows, source filename,
        and method.
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
                }
            )
    return {
        "run_id": run_id,
        "page": 0,
        "include": include,
        "rows": rows,
        "stopped_early": stopped_early,
        "source_filename": source_filename,
        "method": method,
        "max_half_width_d": max_half_width_d,
    }


def review_page_label(
    page: int, total_count: int, page_size: int = PAGE_SIZE
) -> str:
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
        include_in_export (bool): Current include flag from ``store-mavka-results-data``.

    Returns:
        dbc.Col: Card with checkbox, badges, and graph.
    """
    is_fail = entry["is_fail"]
    badge_row = badge_row_for_entry(entry, view="review", index=global_index)

    checkbox = dbc.Checkbox(
        id={"type": "mavka-fit-selector", "index": global_index},
        value=include_in_export,
        disabled=is_fail,
        label="Keep result" if not is_fail else "Fit failed",
        className="mb-1 fw-bold",
    )

    content = review_card_graph(entry)

    card_class = "gp-review-card gp-review-card-fail" if is_fail else "gp-review-card"
    return dbc.Col(
        html.Div(
            [checkbox, badge_row, content],
            className=card_class,
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
        list: Dash layout children for ``mavka-graphs-container``.
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
