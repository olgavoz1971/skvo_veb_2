"""Paginated Review and Export grid for the MAVKA accordion."""

from __future__ import annotations

import math
from typing import Any

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import dcc, html

from skvo_veb.utils.mavka.config import MAVKA_REVIEW_PAGE_SIZE
from skvo_veb.utils.mavka.models import ApproxFitResult


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


def success_badge_specs(fit: ApproxFitResult) -> list[dict]:
    """Builds serialisable badge metadata for a successful MAVKA fit.

    Args:
        fit (ApproxFitResult): Successful interval fit.

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
    fit: ApproxFitResult, jd_min: float, jd_max: float
) -> dict:
    """Builds one in-memory review row from a MAVKA fit result.

    Args:
        fit (ApproxFitResult): Interval fit (success or failure).
        jd_min (float): Interval start (absolute JD).
        jd_max (float): Interval stop (absolute JD).

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
            "badge_specs": success_badge_specs(fit),
        }
    )
    return base


def serialise_review_entry(res_entry: dict, *, figure_json: dict | None = None) -> dict:
    """Converts an in-memory MAVKA result row to a cache-friendly dict.

    Args:
        res_entry (dict): One element from the batch result list.
        figure_json (dict, optional): Plotly JSON for successful fits.

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
) -> dict:
    """Builds ``store-mavka-results-data`` content for a finished MAVKA run.

    Args:
        run_id (str): Cache key for full review rows.
        entries (list[dict]): Serialised review entries (same order as intervals).
        stopped_early (bool): True when the user stopped the batch before all intervals.
        source_filename (str | None): Light-curve filename at the time of this run.

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
                }
            )
    return {
        "run_id": run_id,
        "page": 0,
        "include": include,
        "rows": rows,
        "stopped_early": stopped_early,
        "source_filename": source_filename,
    }


def review_page_label(
    page: int, total_count: int, page_size: int = MAVKA_REVIEW_PAGE_SIZE
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


def fail_card_content(entry: dict) -> html.Div:
    """Builds the alert block for a failed interval.

    Args:
        entry (dict): Serialised review row with ``is_fail`` true.

    Returns:
        html.Div: Failure alert and tooltip target.
    """
    jd_min = entry.get("jd_min")
    jd_max = entry.get("jd_max")
    err_id = f"err-mavka-{str(jd_min).replace('.', '')}"
    return html.Div(
        [
            dbc.Alert(
                [
                    html.B("MAVKA fit failed"),
                    html.Div(
                        f"Range: {jd_min:.2f}-{jd_max:.2f}",
                        className="gp-fail-range",
                    ),
                    html.Hr(),
                    html.Div(
                        "Hover for error",
                        id=err_id,
                        className="gp-fail-hint",
                    ),
                ],
                color="danger",
                className="m-0",
            ),
            dbc.Tooltip(entry.get("error", ""), target=err_id),
        ]
    )


def create_review_interval_card(
    entry: dict,
    global_index: int,
    *,
    include_in_export: bool,
) -> dbc.Col:
    """Wraps one review fit in a two-column grid card.

    Args:
        entry (dict): Serialised review row from the server cache.
        global_index (int): Index across the full batch (for checkboxes and export).
        include_in_export (bool): Current include flag from ``store-mavka-results-data``.

    Returns:
        dbc.Col: Card with checkbox, badges, and graph or failure alert.
    """
    is_fail = entry["is_fail"]
    badges = badges_from_specs(entry.get("badge_specs", []))
    badge_row = html.Div(badges, className="gp-review-badges")

    checkbox = dbc.Checkbox(
        id={"type": "mavka-fit-selector", "index": global_index},
        value=include_in_export,
        disabled=is_fail,
        label="Keep result" if not is_fail else "Fit failed",
        className="mb-1 fw-bold",
    )

    if is_fail:
        content = fail_card_content(entry)
    else:
        fig = go.Figure(entry["figure_json"])
        content = dcc.Graph(figure=fig, config={"displaylogo": False})  # type: ignore[arg-type]

    card_class = "gp-review-card gp-review-card-fail" if is_fail else "gp-review-card"
    return dbc.Col(
        html.Div(
            [checkbox, badge_row, content],
            className=card_class,
        ),
        width=6,
        className="px-1 mb-2",
    )


def render_review_page(
    entries: list[dict],
    page: int,
    include_flags: list[bool],
    page_size: int = MAVKA_REVIEW_PAGE_SIZE,
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
