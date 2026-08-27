"""GP extrema timing compact and extended (ZIP) result exports."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import plotly.graph_objects as go

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.utils.my_tools import PipeException

EXTENDED_RESULTS_FILENAME = "results.tsv"
EXTENDED_PLOTS_DIR = "plots"
EXTENDED_README_FILENAME = "README.txt"

_RESULTS_HEADER = (
    "jd_peak\tjd_peak_std\tjd_interval_start\tjd_interval_stop\t"
    "status\tkernel\tlength_scale\tamplitude\tplot_file\terror\n"
)

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


def jd_to_display_mjd(jd: float, display_epoch: float = DEFAULT_EPOCH_JD) -> float:
    """Maps absolute JD to the prep-plot MJD axis (``jd - display_epoch``).

    Args:
        jd (float): Absolute Julian Date.
        display_epoch (float): Display epoch offset (``jd0`` on the GP page).

    Returns:
        float: MJD-compatible coordinate used on the prep light curve plot.
    """
    return float(jd) - float(display_epoch)


def fit_export_status(entry: dict, included: bool) -> str:
    """Derives export status for one review row.

    Args:
        entry (dict): Serialised review cache row.
        included (bool): User ``Keep result`` flag.

    Returns:
        str: ``accepted``, ``rejected``, or ``failed``.
    """
    if entry.get("is_fail"):
        return "failed"
    if not included:
        return "rejected"
    return "accepted"


def _plot_link_mjd(entry: dict, display_epoch: float) -> float:
    """Returns the MJD key used to name plot artefacts for one fit."""
    if not entry.get("is_fail") and entry.get("jd_peak") is not None:
        return jd_to_display_mjd(entry["jd_peak"], display_epoch)
    jd_min = float(entry["jd_min"])
    jd_max = float(entry["jd_max"])
    return jd_to_display_mjd(0.5 * (jd_min + jd_max), display_epoch)


def assign_plot_filenames(
    entries: list[dict],
    include_flags: list[bool],
    *,
    display_epoch: float = DEFAULT_EPOCH_JD,
) -> list[str]:
    """Builds unique ``plots/…`` paths for each fit row.

    Args:
        entries (list[dict]): Full review cache rows.
        include_flags (list[bool]): Per-row include flags from the UI store.
        display_epoch (float): GP prep plot epoch offset.

    Returns:
        list[str]: Relative ZIP paths aligned with ``entries``.
    """
    used: dict[str, int] = {}
    paths: list[str] = []
    for entry, included in zip(entries, include_flags, strict=True):
        status = fit_export_status(entry, included)
        mjd_key = f"{_plot_link_mjd(entry, display_epoch):.2f}"
        base = f"fit_mjd_{mjd_key}_{status}"
        count = used.get(base, 0)
        used[base] = count + 1
        suffix = f"_{count:02d}" if count else ""
        ext = "txt" if entry.get("is_fail") else "png"
        paths.append(f"{EXTENDED_PLOTS_DIR}/{base}{suffix}.{ext}")
    return paths


def figure_json_to_png_bytes(figure_json: dict) -> bytes:
    """Renders one Plotly figure JSON payload to PNG bytes.

    Uses Kaleido defaults (review-card layout size; no upscale).

    Args:
        figure_json (dict): Serialised figure from the GP review cache.

    Returns:
        bytes: PNG image data.

    Raises:
        PipeException: When static image export fails (for example missing Kaleido).
    """
    fig = go.Figure(figure_json)
    try:
        return fig.to_image(format="png", engine="kaleido")
    except Exception as exc:
        raise PipeException(
            "Could not render fit plot to PNG. Ensure the Kaleido package is installed."
        ) from exc


def format_failure_plot_stub(entry: dict, display_epoch: float) -> str:
    """Builds a text stub for a failed fit (no GP figure available).

    Args:
        entry (dict): Failed review row.
        display_epoch (float): GP prep plot epoch offset.

    Returns:
        str: Human-readable failure summary.
    """
    jd_min = entry.get("jd_min")
    jd_max = entry.get("jd_max")
    mjd_lo = jd_to_display_mjd(jd_min, display_epoch)
    mjd_hi = jd_to_display_mjd(jd_max, display_epoch)
    return (
        "GP fit failed\n"
        f"Interval MJD: {mjd_lo:.6f} – {mjd_hi:.6f}\n"
        f"Interval JD: {jd_min} – {jd_max}\n"
        f"Error: {entry.get('error', '')}\n"
    )


def _format_float_cell(value: Any) -> str:
    """Formats one optional numeric table cell."""
    if value is None:
        return ""
    try:
        val = float(value)
    except (TypeError, ValueError):
        return ""
    if not val == val:  # NaN
        return ""
    return f"{val:.8f}"


def build_extended_results_tsv(
    entries: list[dict],
    include_flags: list[bool],
    plot_files: list[str],
) -> str:
    """Builds the extended results table (tab-separated, one row per fit).

    Args:
        entries (list[dict]): Full review cache rows.
        include_flags (list[bool]): Per-row include flags.
        plot_files (list[str]): Relative plot paths from ``assign_plot_filenames``.

    Returns:
        str: TSV body including header row.
    """
    lines = [_RESULTS_HEADER]
    for entry, included, plot_file in zip(
        entries, include_flags, plot_files, strict=True
    ):
        status = fit_export_status(entry, included)
        jd_min = entry.get("jd_min")
        jd_max = entry.get("jd_max")
        if entry.get("is_fail") or entry.get("jd_peak") is None:
            jd_peak = ""
            jd_peak_std = ""
        else:
            jd_peak = _format_float_cell(entry.get("jd_peak"))
            jd_peak_std = _format_float_cell(entry.get("jd_peak_std"))
        kernel = entry.get("kernel_type") or ""
        length_scale = _format_float_cell(entry.get("length_scale"))
        amplitude = _format_float_cell(entry.get("amplitude"))
        error = (entry.get("error") or "").replace("\t", " ").replace("\n", " ")
        lines.append(
            "\t".join(
                [
                    jd_peak,
                    jd_peak_std,
                    _format_float_cell(jd_min),
                    _format_float_cell(jd_max),
                    status,
                    str(kernel),
                    length_scale,
                    amplitude,
                    plot_file,
                    error,
                ]
            )
            + "\n"
        )
    return "".join(lines)


def format_compact_extrema_dat(
    rows: list[dict],
    include_flags: list[bool],
    *,
    extrema_mode: str,
) -> str:
    """Formats the legacy compact extrema timing file (selected successes only).

    Args:
        rows (list[dict]): Slim rows from ``store-results-data``.
        include_flags (list[bool]): Per-row include flags.
        extrema_mode (str): ``min`` or ``max`` from the GP sidebar.

    Returns:
        str: ``.dat`` file body (JD, σ, integer ``scale_limit``). All comment
        lines start with ``#`` so xmgrace ignores them.
    """
    mode_label = "Minimum" if extrema_mode == "min" else "Maximum"
    lines = [
        f"# GP {mode_label} Results\n",
        "# scale_limit: 0=ok 1=length_scale_min 2=length_scale_max\n",
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


def _extended_readme(extrema_mode: str) -> str:
    """Returns a short README for the extended export bundle."""
    mode_label = "minimum" if extrema_mode == "min" else "maximum"
    return (
        "GP extrema extended export\n"
        "==========================\n"
        f"Timing mode: {mode_label}\n"
        "Plot format: PNG (review-card size, ~700×400 px).\n"
        f"{EXTENDED_RESULTS_FILENAME}: one row per interval fit (accepted, rejected, failed).\n"
        f"{EXTENDED_PLOTS_DIR}/: PNG fit plots or failure stubs (.txt).\n"
        "Link rows to plots via the plot_file column.\n"
    )


def build_extended_export_zip(
    entries: list[dict],
    include_flags: list[bool],
    *,
    bundle_folder: str,
    display_epoch: float = DEFAULT_EPOCH_JD,
    extrema_mode: str = "max",
) -> bytes:
    """Builds a ZIP archive with results table and per-fit plot artefacts.

    Args:
        entries (list[dict]): Full review cache rows.
        include_flags (list[bool]): Per-row include flags (for status labelling).
        bundle_folder (str): Root folder name inside the ZIP.
        display_epoch (float): GP prep plot epoch offset.
        extrema_mode (str): ``min`` or ``max`` from the GP sidebar.

    Returns:
        bytes: ZIP file content.

    Raises:
        PipeException: When PNG rendering fails.
    """
    plot_files = assign_plot_filenames(
        entries,
        include_flags,
        display_epoch=display_epoch,
    )
    tsv = build_extended_results_tsv(
        entries, include_flags, plot_files
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        prefix = f"{bundle_folder}/"
        zf.writestr(f"{prefix}{EXTENDED_README_FILENAME}", _extended_readme(extrema_mode))
        zf.writestr(f"{prefix}{EXTENDED_RESULTS_FILENAME}", tsv)
        for entry, plot_path in zip(entries, plot_files, strict=True):
            full_path = f"{prefix}{plot_path}"
            if entry.get("is_fail"):
                stub = format_failure_plot_stub(entry, display_epoch)
                zf.writestr(full_path, stub)
            else:
                figure_json = entry.get("figure_json")
                if not figure_json:
                    raise PipeException(
                        f"Missing plot data for fit interval "
                        f"{entry.get('jd_min')}–{entry.get('jd_max')}."
                    )
                zf.writestr(full_path, figure_json_to_png_bytes(figure_json))
    return buffer.getvalue()
