"""Interactive Step 2 fit review: per-interval method selection and rejection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt

from manifest_config import TIMING_METHODS
from plot_style import FONT_SIZE
from template_fit import ShiftFitResult, TemplateCurve
from template_fit_pipeline import plot_interval_fits, plot_segment_anchor_fits

logger = logging.getLogger(__name__)

REVIEW_METHOD_ORDER = ("cc", "nls", "nls_clean", "nls_scale_clean")

METHOD_KEY_LABELS = {
    "cc": "1 / c",
    "nls": "2 / n",
    "nls_clean": "3 / l",
    "nls_scale_clean": "4 / s",
}

METHOD_KEYS: dict[str, str] = {
    "1": "cc",
    "c": "cc",
    "2": "nls",
    "n": "nls",
    "3": "nls_clean",
    "l": "nls_clean",
    "4": "nls_scale_clean",
    "s": "nls_scale_clean",
}

REJECT_KEYS = frozenset({"r", "R", "reject"})


@dataclass(frozen=True)
class ReviewDecision:
    """Outcome of one interactive interval review."""

    selected_method: str | None
    rejected: bool


def _review_help_text(default_method: str) -> str:
    """Build on-figure keyboard legend for review mode."""
    parts = [
        f"Keys: {METHOD_KEY_LABELS['cc']}=cc",
        f"{METHOD_KEY_LABELS['nls']}=nls",
        f"{METHOD_KEY_LABELS['nls_clean']}=nls_clean",
        f"{METHOD_KEY_LABELS['nls_scale_clean']}=nls_scale_clean",
        "r=reject (comment row in all CSVs)",
        f"default={default_method}",
    ]
    return " | ".join(parts)


def review_interval_fits(
    index: int,
    t_start: float,
    t_end: float,
    t,
    y,
    curve: TemplateCurve,
    cc: ShiftFitResult,
    nls: ShiftFitResult,
    nls_clean: ShiftFitResult,
    nls_scale_clean: ShiftFitResult,
    *,
    dt_min: float,
    dt_max: float,
    default_method: str,
    piece_id: str,
) -> ReviewDecision:
    """Show four fit panels and wait for accept (method key) or reject.

    Args:
        index (int): Interval index within the piece.
        t_start (float): Interval start time (LC units).
        t_end (float): Interval end time (LC units).
        t: LC time array for this interval.
        y: Normalised flux array for this interval.
        curve (TemplateCurve): Template curve used for fitting.
        cc (ShiftFitResult): Cross-correlation fit.
        nls (ShiftFitResult): Nonlinear least-squares fit.
        nls_clean (ShiftFitResult): NLS with iterative outlier cleaning.
        nls_scale_clean (ShiftFitResult): NLS with scale and outlier cleaning.
        dt_min (float): Lower fit-mask edge in days from the fitted peak.
        dt_max (float): Upper fit-mask edge in days from the fitted peak.
        default_method (str): Manifest default; used when Enter is pressed.
        piece_id (str): Piece identifier for the window title.

    Returns:
        ReviewDecision: Selected official method, or ``rejected=True``.
    """
    if default_method not in TIMING_METHODS:
        raise ValueError(f"unsupported default_method: {default_method}")

    fig = plot_interval_fits(
        index,
        t_start,
        t_end,
        t,
        y,
        curve,
        cc,
        nls,
        nls_clean,
        nls_scale_clean,
        dt_min=dt_min,
        dt_max=dt_max,
        save_path=None,
        show=False,
        return_figure=True,
    )
    decision: dict[str, ReviewDecision | None] = {"value": None}

    def _finish(selected_method: str | None, *, rejected: bool) -> None:
        decision["value"] = ReviewDecision(
            selected_method=selected_method,
            rejected=rejected,
        )
        plt.close(fig)

    def _on_key(event) -> None:
        if decision["value"] is not None:
            return
        key = event.key
        if key in REJECT_KEYS:
            logger.info(
                "Piece %s interval %s: rejected by reviewer",
                piece_id,
                index,
            )
            _finish(None, rejected=True)
            return
        if key in ("enter", "return", " "):
            logger.info(
                "Piece %s interval %s: accepted default method %s",
                piece_id,
                index,
                default_method,
            )
            _finish(default_method, rejected=False)
            return
        method = METHOD_KEYS.get(key)
        if method is not None:
            logger.info(
                "Piece %s interval %s: accepted method %s",
                piece_id,
                index,
                method,
            )
            _finish(method, rejected=False)

    help_line = _review_help_text(default_method)
    fig.suptitle(
        f"{piece_id} interval {index}: [{t_start:.5f}, {t_end:.5f}]",
        fontsize=FONT_SIZE,
        y=0.98,
    )
    fig.text(
        0.5,
        0.93,
        help_line,
        ha="center",
        va="top",
        fontsize=FONT_SIZE * 0.65,
        transform=fig.transFigure,
    )
    fig.subplots_adjust(top=0.82)
    fig.canvas.mpl_connect("key_press_event", _on_key)
    plt.show()

    if decision["value"] is None:
        logger.warning(
            "Piece %s interval %s: window closed without key; using default %s",
            piece_id,
            index,
            default_method,
        )
        return ReviewDecision(selected_method=default_method, rejected=False)
    return decision["value"]


def review_segment_anchor_fits(
    index: int,
    t_start: float,
    t_end: float,
    tau,
    y,
    curve: TemplateCurve,
    t_anchor: float,
    anchor_epoch: str,
    cc: ShiftFitResult,
    nls: ShiftFitResult,
    nls_clean: ShiftFitResult,
    nls_scale_clean: ShiftFitResult,
    *,
    dt_min: float,
    dt_max: float,
    default_method: str,
    piece_id: str,
    template_npz: Path | None = None,
) -> ReviewDecision:
    """Interactive review for ensemble ToM (folded stack + four methods).

    Args:
        index (int): Segment index (0 for segment_anchor).
        t_start (float): Fit window start.
        t_end (float): Fit window end.
        tau: Fold coordinates of the fit-window LC (days).
        y: Normalised flux.
        curve (TemplateCurve): Step 1 template.
        t_anchor (float): Calendar time of the unshifted template peak on the
            reporting cycle.
        anchor_epoch (str): Anchor kind for the title.
        cc, nls, nls_clean, nls_scale_clean: Stored fit results.
        dt_min (float): Fit-mask lower edge (days from peak).
        dt_max (float): Fit-mask upper edge (days from peak).
        default_method (str): Manifest default timing method.
        piece_id (str): Piece identifier.
        template_npz (Path | None): ``template.npz`` for GP sigma bands.

    Returns:
        ReviewDecision: Selected method or rejection.
    """
    if default_method not in TIMING_METHODS:
        raise ValueError(f"unsupported default_method: {default_method}")

    fig = plot_segment_anchor_fits(
        index,
        t_start,
        t_end,
        tau,
        y,
        curve,
        t_anchor,
        anchor_epoch,
        cc,
        nls,
        nls_clean,
        nls_scale_clean,
        dt_min=dt_min,
        dt_max=dt_max,
        save_path=None,
        show=False,
        return_figure=True,
        template_npz=template_npz,
    )
    decision: dict[str, ReviewDecision | None] = {"value": None}

    def _finish(selected_method: str | None, *, rejected: bool) -> None:
        decision["value"] = ReviewDecision(
            selected_method=selected_method,
            rejected=rejected,
        )
        plt.close(fig)

    def _on_key(event) -> None:
        if decision["value"] is not None:
            return
        key = event.key
        if key in REJECT_KEYS:
            logger.info(
                "Piece %s segment anchor %s: rejected by reviewer",
                piece_id,
                index,
            )
            _finish(None, rejected=True)
            return
        if key in ("enter", "return", " "):
            logger.info(
                "Piece %s segment anchor %s: accepted default method %s",
                piece_id,
                index,
                default_method,
            )
            _finish(default_method, rejected=False)
            return
        method = METHOD_KEYS.get(key)
        if method is not None:
            logger.info(
                "Piece %s segment anchor %s: accepted method %s",
                piece_id,
                index,
                method,
            )
            _finish(method, rejected=False)

    help_line = _review_help_text(default_method)
    fig.suptitle(
        f"{piece_id} segment anchor {index}: [{t_start:.5f}, {t_end:.5f}], "
        f"anchor={anchor_epoch}",
        fontsize=FONT_SIZE,
        y=0.98,
    )
    fig.text(
        0.5,
        0.93,
        help_line,
        ha="center",
        va="top",
        fontsize=FONT_SIZE * 0.65,
        transform=fig.transFigure,
    )
    fig.subplots_adjust(top=0.88)
    fig.canvas.mpl_connect("key_press_event", _on_key)
    plt.show()

    if decision["value"] is None:
        logger.warning(
            "Piece %s segment anchor %s: window closed without key; using default %s",
            piece_id,
            index,
            default_method,
        )
        return ReviewDecision(selected_method=default_method, rejected=False)
    return decision["value"]


def parse_rejected_flag(value: object) -> bool:
    """Normalise ``rejected`` values read from CSV or in-memory rows."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "rejected"}


def normalise_review_fields(row: dict, *, default_method: str) -> None:
    """Ensure ``selected_method`` and ``rejected`` exist on a summary row."""
    if not row.get("selected_method"):
        legacy = row.get("timing_method") or default_method
        row["selected_method"] = legacy
    row["rejected"] = "true" if parse_rejected_flag(row.get("rejected")) else "false"


def apply_review_decision(
    row: dict,
    decision: ReviewDecision,
    *,
    default_method: str,
) -> None:
    """Update one summary row from an interactive review decision."""
    if decision.rejected:
        row["rejected"] = "true"
        row["selected_method"] = row.get("selected_method") or default_method
        return
    method = decision.selected_method or default_method
    row["rejected"] = "false"
    row["selected_method"] = method
    if f"delta_t_{method}" not in row:
        return
    from template_fit_pipeline import sync_official_columns

    sync_official_columns(row, method)
