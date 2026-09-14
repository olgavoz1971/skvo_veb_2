"""GP extrema timing compact ``.dat`` export."""

from __future__ import annotations

from skvo_veb.utils.lc_working_window import format_max_half_width_comment

# Compact .dat third column (xmgrace numeric). Same 1% slack as review badges.
SCALE_LIMIT_OK = 0
SCALE_LIMIT_HIT_MIN = 1
SCALE_LIMIT_HIT_MAX = 2
_SCALE_LIMIT_SLACK = 0.01


def scale_limit_flag(
    length_scale: float,
    length_scale_min: float,
    length_scale_max: float,
) -> int:
    """Returns an xmgrace-safe integer when length-scale bounds are hit.

    Uses the same 1% slack as the review Scale badge. Does not inspect amplitude.

    Args:
        length_scale (float): Fitted length scale.
        length_scale_min (float): Sidebar minimum bound used for the fit.
        length_scale_max (float): Sidebar maximum bound used for the fit.

    Returns:
        int: ``0`` ok, ``1`` hit minimum, ``2`` hit maximum.
    """
    if length_scale <= length_scale_min * (1.0 + _SCALE_LIMIT_SLACK):
        return SCALE_LIMIT_HIT_MIN
    if length_scale >= length_scale_max * (1.0 - _SCALE_LIMIT_SLACK):
        return SCALE_LIMIT_HIT_MAX
    return SCALE_LIMIT_OK


def format_compact_extrema_dat(
    rows: list[dict],
    include_flags: list[bool],
    *,
    extrema_mode: str,
    max_half_width_d: float | None = None,
) -> str:
    """Formats the compact extrema timing file (selected successes only).

    Args:
        rows (list[dict]): Slim rows from ``store-results-data``.
        include_flags (list[bool]): Per-row include flags.
        extrema_mode (str): ``min`` or ``max`` from the GP sidebar.
        max_half_width_d (float | None): Optional half-width cap used for this run.

    Returns:
        str: ``.dat`` file body (JD, σ, integer ``scale_limit``). All comment
        lines start with ``#`` so xmgrace ignores them.
    """
    mode_label = "Minimum" if extrema_mode == "min" else "Maximum"
    lines = [
        f"# GP {mode_label} Results\n",
        "# scale_limit: 0=ok 1=length_scale_min 2=length_scale_max\n",
        format_max_half_width_comment(max_half_width_d),
        f"# JD_{mode_label}\tJD_Std\tscale_limit\n",
    ]
    for is_selected, row in zip(include_flags, rows, strict=True):
        if is_selected and not row.get("is_fail"):
            flag = row.get("scale_limit_flag")
            if flag is None:
                raise ValueError(
                    "A kept GP result is missing scale_limit. Re-run Gaussian Process."
                )
            lines.append(
                f"{row['jd_peak']:.6f}\t{row['jd_peak_std']:.6f}\t{int(flag)}\n"
            )
    return "".join(lines)
