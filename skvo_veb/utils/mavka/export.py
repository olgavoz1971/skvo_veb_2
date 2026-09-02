"""MAVKA extrema timing compact and extended (ZIP) result exports."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import plotly.graph_objects as go

from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD
from skvo_veb.utils.mavka.config import DEFAULT_METHOD
from skvo_veb.utils.my_tools import PipeException, sanitize_filename

EXTENDED_RESULTS_FILENAME = "results.tsv"
EXTENDED_PLOTS_DIR = "plots"
EXTENDED_README_FILENAME = "README.txt"
MAVKA_EXTREMA_COMPACT_EXTENSION = "dat"
MAVKA_EXTREMA_EXTENDED_SUFFIX = "_mavka_extrema"
MAVKA_TIMING_FALLBACK_PREFIX = "results"

_RESULTS_HEADER = (
    "jd_peak\tjd_peak_std\tjd_interval_start\tjd_interval_stop\t"
    "status\trms\tc4\tc5\ty_ext\twarning\tplot_file\terror\n"
)


def mavka_extrema_export_stem(stem: str | None) -> str:
    """Normalises the MAVKA extrema export basename from the review filename field.

    Args:
        stem (str | None): User-entered stem or legacy filename with extension.

    Returns:
        str: Sanitised basename without ``.dat`` / ``.zip`` suffixes.
    """
    raw = (stem or "results_mavka").strip() or "results_mavka"
    safe = sanitize_filename(raw) or "results_mavka"
    for suffix in (".dat", ".zip"):
        if safe.lower().endswith(suffix):
            safe = safe[: -len(suffix)]
    return safe or "results_mavka"


def mavka_suggested_timing_stem(
    lc_filename: str | None,
    method: str | None,
) -> str:
    """Builds the suggested MAVKA timing export stem from LC name and method.

    Args:
        lc_filename (str | None): Uploaded light-curve filename.
        method (str | None): Approximation id (``WSAP``, ``WSL``, ``AP``, ``A``).

    Returns:
        str: ``{lc_stem}_{method}``, or ``results_{method}`` when no LC name
        is available.
    """
    tag = str(method or "").strip() or DEFAULT_METHOD
    safe_tag = sanitize_filename(tag) or DEFAULT_METHOD
    if not lc_filename:
        return f"{MAVKA_TIMING_FALLBACK_PREFIX}_{safe_tag}"
    base = lc_filename.rsplit(".", 1)[0].strip()
    if not base:
        return f"{MAVKA_TIMING_FALLBACK_PREFIX}_{safe_tag}"
    suffix = f"_{safe_tag}"
    if base.lower().endswith(suffix.lower()):
        return base
    return f"{base}{suffix}"


def mavka_compact_extrema_download_name(stem: str | None) -> str:
    """Resolves the compact MAVKA extrema ``.dat`` download filename.

    Args:
        stem (str | None): User-entered export stem.

    Returns:
        str: Sanitised ``*.dat`` filename.
    """
    return f"{mavka_extrema_export_stem(stem)}.{MAVKA_EXTREMA_COMPACT_EXTENSION}"


def mavka_extended_extrema_download_name(stem: str | None) -> str:
    """Resolves the extended MAVKA extrema ZIP download filename.

    Args:
        stem (str | None): User-entered export stem.

    Returns:
        str: Sanitised ``*_mavka_extrema.zip`` filename.
    """
    base = mavka_extrema_export_stem(stem)
    return f"{base}{MAVKA_EXTREMA_EXTENDED_SUFFIX}.zip"


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
        display_epoch (float): Prep plot epoch offset.

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
        figure_json (dict): Serialised figure from the MAVKA review cache.

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
    """Builds a text stub for a failed fit (no MAVKA figure available).

    Args:
        entry (dict): Failed review row.
        display_epoch (float): Prep plot epoch offset.

    Returns:
        str: Human-readable failure summary.
    """
    jd_min = entry.get("jd_min")
    jd_max = entry.get("jd_max")
    mjd_lo = jd_to_display_mjd(jd_min, display_epoch)
    mjd_hi = jd_to_display_mjd(jd_max, display_epoch)
    method = entry.get("method") or ""
    return (
        "MAVKA fit failed\n"
        f"Method: {method}\n"
        f"Interval MJD: {mjd_lo:.6f} – {mjd_hi:.6f}\n"
        f"Interval JD: {jd_min} – {jd_max}\n"
        f"Error: {entry.get('error', '')}\n"
    )


def _method_comment_line(entries: list[dict]) -> str:
    """Builds a ``# Method:`` metadata line from the fitted method ids.

    A hash comment is not a TSV data row. Pandas, Astropy and ``numpy.loadtxt``
    skip ``#`` lines, so the header and table below stay valid TSV.

    Args:
        entries (list[dict]): Review cache rows (may include failures).

    Returns:
        str: One comment line ending in a newline.
    """
    methods: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        method = str(entry.get("method") or "").strip()
        if method and method not in seen:
            seen.add(method)
            methods.append(method)
    used = ", ".join(methods)
    return f"# Method: {used}\n"


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

    A ``# Method:`` comment precedes the header. That line is metadata, not a
    table row; TSV parsers that honour ``#`` comments will skip it.

    Args:
        entries (list[dict]): Full review cache rows.
        include_flags (list[bool]): Per-row include flags.
        plot_files (list[str]): Relative plot paths from ``assign_plot_filenames``.

    Returns:
        str: TSV body including comment, header, and data rows.
    """
    lines = [_method_comment_line(entries), _RESULTS_HEADER]
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
        warning = (entry.get("warning") or "").replace("\t", " ").replace("\n", " ")
        error = (entry.get("error") or "").replace("\t", " ").replace("\n", " ")
        lines.append(
            "\t".join(
                [
                    jd_peak,
                    jd_peak_std,
                    _format_float_cell(jd_min),
                    _format_float_cell(jd_max),
                    status,
                    _format_float_cell(entry.get("rms")),
                    _format_float_cell(entry.get("c4")),
                    _format_float_cell(entry.get("c5")),
                    _format_float_cell(entry.get("y_ext")),
                    warning,
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
    period: str | None = None,
    epoch: str | None = None,
    method: str | None = None,
) -> str:
    """Formats the compact extrema timing file (selected successes only).

    Args:
        rows (list[dict]): Slim rows from ``store-mavka-results-data``.
        include_flags (list[bool]): Per-row include flags.
        extrema_mode (str): ``min`` or ``max`` from the MAVKA sidebar.
        period (str | None): Folding period from accordion 1 (comment only).
        epoch (str | None): Display epoch from accordion 1 (comment only).
        method (str | None): Approximation id written next to the MAVKA header.

    Returns:
        str: ``.dat`` file body.

    Raises:
        PipeException: If a selected success row has no TOM.
    """
    mode_label = "Minimum" if extrema_mode == "min" else "Maximum"
    lines = [
        f"# MAVKA {mode_label} Results\n",
    ]
    method_tag = str(method or "").strip()
    if method_tag:
        lines.append(f"# method: {method_tag}\n")
    if period:
        lines.append(f"# PERIOD = {period}\n")
    if epoch:
        lines.append(f"# EPOCH = {epoch}\n")
    lines.append(f"# JD_{mode_label}\tJD_Std\n")
    for is_selected, row in zip(include_flags, rows, strict=True):
        if is_selected and not row.get("is_fail"):
            jd_peak = row.get("jd_peak")
            if jd_peak is None:
                raise PipeException(
                    "Selected MAVKA result is missing TOM (jd_peak)."
                )
            jd_std = row.get("jd_peak_std")
            std_txt = "" if jd_std is None else f"{float(jd_std):.6f}"
            lines.append(f"{float(jd_peak):.6f}\t{std_txt}\n")
    return "".join(lines)


def _extended_readme(
    extrema_mode: str,
    *,
    period: str | None = None,
    epoch: str | None = None,
) -> str:
    """Returns a short README for the extended export bundle."""
    mode_label = "minimum" if extrema_mode == "min" else "maximum"
    period_line = f"Period (days): {period}\n" if period else "Period (days): (not set)\n"
    epoch_line = (
        f"Epoch (display units): {epoch}\n" if epoch else "Epoch: (not set)\n"
    )
    return (
        "MAVKA extrema extended export\n"
        "=============================\n"
        f"Timing mode: {mode_label}\n"
        f"{period_line}"
        f"{epoch_line}"
        "Plot format: PNG (review-card size, ~700×400 px).\n"
        f"{EXTENDED_RESULTS_FILENAME}: ``# Method:`` comment, then one TSV row per fit "
        "(accepted, rejected, failed).\n"
        f"{EXTENDED_PLOTS_DIR}/: PNG fit plots or failure stubs (.txt).\n"
        "Link rows to plots via the plot_file column.\n"
        "Photometric uncertainties are not used in the fit; σ(TOM) is from covariance.\n"
    )


def build_extended_export_zip(
    entries: list[dict],
    include_flags: list[bool],
    *,
    bundle_folder: str,
    display_epoch: float = DEFAULT_EPOCH_JD,
    extrema_mode: str = "min",
    period: str | None = None,
    epoch: str | None = None,
) -> bytes:
    """Builds a ZIP archive with results table and per-fit plot artefacts.

    Args:
        entries (list[dict]): Full review cache rows.
        include_flags (list[bool]): Per-row include flags (for status labelling).
        bundle_folder (str): Root folder name inside the ZIP.
        display_epoch (float): Prep plot epoch offset.
        extrema_mode (str): ``min`` or ``max`` from the MAVKA sidebar.
        period (str | None): Folding period from accordion 1 (metadata only).
        epoch (str | None): Display epoch from accordion 1 (metadata only).

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
    tsv = build_extended_results_tsv(entries, include_flags, plot_files)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        prefix = f"{bundle_folder}/"
        zf.writestr(
            f"{prefix}{EXTENDED_README_FILENAME}",
            _extended_readme(extrema_mode, period=period, epoch=epoch),
        )
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
