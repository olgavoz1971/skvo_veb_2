"""Compact xmgrace O-C ``.dat`` export."""

from __future__ import annotations

from typing import Any

from skvo_veb.utils.gp.export import gp_suggested_timing_stem
from skvo_veb.utils.mavka.export import mavka_suggested_timing_stem
from skvo_veb.utils.my_tools import sanitize_filename

OC_DAT_EXTENSION = "dat"
OC_STEM_SUFFIX = "_oc"
OC_FALLBACK_STEM = "results_oc"
_SEP = "  "


def oc_source_filename(
    source: str,
    *,
    gp_store: dict | None = None,
    mavka_store: dict | None = None,
    uploaded: dict | list | None = None,
) -> str | None:
    """Returns the file name captured when the selected ToMs were created.

    Args:
        source (str): ``gp``, ``mavka``, or ``upload``.
        gp_store (dict | None): ``store-results-data``.
        mavka_store (dict | None): ``store-mavka-results-data``.
        uploaded (dict | list | None): ``store-oc-uploaded-toms``.

    Returns:
        str | None: Original filename, or ``None`` when that source has none.
    """
    if source == "gp":
        return (gp_store or {}).get("source_filename")
    if source == "mavka":
        return (mavka_store or {}).get("source_filename")
    if source == "upload" and isinstance(uploaded, dict):
        return uploaded.get("filename")
    return None


def oc_default_export_stem_for_source(
    source: str,
    *,
    gp_store: dict | None = None,
    mavka_store: dict | None = None,
    uploaded: dict | list | None = None,
) -> str:
    """Builds the O-C export stem from the ToM source that produced this diagram.

    GP and MAVKA use the same basename as their timing ``.dat`` suggestion,
    then ``_oc``. Upload uses the uploaded ToM filename.

    Args:
        source (str): ``gp``, ``mavka``, or ``upload``.
        gp_store (dict | None): ``store-results-data``.
        mavka_store (dict | None): ``store-mavka-results-data``.
        uploaded (dict | list | None): ``store-oc-uploaded-toms``.

    Returns:
        str: ``{timing_stem}_oc``, or ``results_oc`` when no name is available.
    """
    key = str(source or "")
    if key == "gp":
        return oc_default_export_stem(
            gp_suggested_timing_stem((gp_store or {}).get("source_filename"))
        )
    if key == "mavka":
        store = mavka_store or {}
        return oc_default_export_stem(
            mavka_suggested_timing_stem(
                store.get("source_filename"),
                store.get("method"),
            )
        )
    if key == "upload" and isinstance(uploaded, dict):
        return oc_default_export_stem(uploaded.get("filename"))
    return OC_FALLBACK_STEM


def oc_default_export_stem(source_filename: str | None) -> str:
    """Builds the default O-C export stem from a ToM-source file name.

    Args:
        source_filename (str | None): Light curve or compact ToM filename stored
            with those ToMs.

    Returns:
        str: ``{stem}_oc``, or ``results_oc`` when no name is available.
    """
    raw = (source_filename or "").strip()
    if not raw:
        return OC_FALLBACK_STEM
    base = raw.rsplit(".", 1)[0].strip()
    safe = sanitize_filename(base) or OC_FALLBACK_STEM
    if safe.lower().endswith(OC_STEM_SUFFIX):
        return safe
    return f"{safe}{OC_STEM_SUFFIX}"


def oc_export_stem(stem: str | None) -> str:
    """Normalises the O-C export basename.

    Args:
        stem (str | None): User-entered stem.

    Returns:
        str: Sanitised basename without ``.dat``.
    """
    raw = (stem or OC_FALLBACK_STEM).strip() or OC_FALLBACK_STEM
    safe = sanitize_filename(raw) or OC_FALLBACK_STEM
    if safe.lower().endswith(".dat"):
        safe = safe[: -len(".dat")]
    return safe or OC_FALLBACK_STEM


def oc_export_download_name(stem: str | None) -> str:
    """Resolves the O-C ``.dat`` download filename.

    Args:
        stem (str | None): User-entered export stem.

    Returns:
        str: Sanitised ``*.dat`` filename.
    """
    return f"{oc_export_stem(stem)}.{OC_DAT_EXTENSION}"


def format_oc_dat(payload: dict[str, Any]) -> str:
    """Formats an xmgrace O-C table from a Plot payload.

    Metadata and the column-name line start with ``#``. When the ToMs came from
    an uploaded file, every original ``#`` comment is copied after ``# source``.
    Data columns (double space): ``cycle_number``, ``OC``, ``sigma_jd_ext``,
    ``jd_ext``.

    Args:
        payload (dict): Output of ``compute_step1_oc``. May include
            ``source_metadata_lines`` (``#`` comments copied from an uploaded
            ToM file).

    Returns:
        str: File body.

    Raises:
        ValueError: If ``payload`` has no points.
    """
    n = int(payload.get("n") or 0)
    if n <= 0:
        raise ValueError("No O-C points to export. Plot first.")
    source = str(payload.get("source") or "")
    t0_jd = float(payload["t0_jd"])
    p0 = float(payload["p0"])
    shifts = payload.get("cycle_shifts") or []
    lines = [
        "# oc_tool: skvo_veb O-C\n",
        f"# source: {source}\n",
    ]
    for raw in payload.get("source_metadata_lines") or []:
        text = str(raw).rstrip("\r\n")
        if not text:
            continue
        if not text.startswith("#"):
            text = f"# {text}"
        lines.append(f"{text}\n")
    lines.extend(
        [
            "# algorithm: O-C = jd_ext - (T0 + E*P0); "
            "E = round((jd_ext-T0)/P0) after cycle_shifts\n",
            f"# ephemeris_T0_JD: {t0_jd:.8f}\n",
            f"# ephemeris_P0_d: {p0:.10f}\n",
            f"# cycle_shifts_applied: {len(shifts)}\n",
        ]
    )
    for row in shifts:
        lines.append(
            f"# cycle_shift: at_jd={float(row['at_jd']):.8f} "
            f"delta_E={int(row['delta_e'])}\n"
        )
    lines.append(f"# cycle_number{_SEP}OC{_SEP}sigma_jd_ext{_SEP}jd_ext\n")
    for i in range(n):
        cycle_e = int(round(float(payload["E"][i])))
        oc_days = float(payload["OC"][i])
        sig = float(payload["sigma_jd"][i])
        sig_txt = f"{sig:.10e}" if sig == sig else "nan"
        jd_obs = float(payload["jd_ext"][i])
        lines.append(
            f"{cycle_e}{_SEP}{oc_days:.10e}{_SEP}{sig_txt}{_SEP}{jd_obs:.8f}\n"
        )
    return "".join(lines)
