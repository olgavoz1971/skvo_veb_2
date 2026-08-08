import io
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.table import Table

from skvo_veb.utils.lc_config import (
    DOMAIN_FLUX,
    DOMAIN_MAG,
    EXPORT_FORMATS,
    JD_TO_MJD,
    METADATA_KEY_VO_ENVELOPE,
    METADATA_KEY_VO_ENVELOPE,
    PHOTCAL_KEY_EFFECTIVE_WAVELENGTH,
    PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT,
    PHOTCAL_KEY_FILTER_IDENTIFIER,
    PHOTCAL_KEY_FILTER_NAME,
    PHOTCAL_KEY_MAG_SYS,
    PHOTCAL_KEY_ZP_FLUX,
    PHOTCAL_KEY_ZP_FLUX_UNIT,
    PHOTCAL_KEY_ZP_MAG,
    PHOTCAL_KEY_ZP_MAG_UNIT,
    VO_ENVELOPE_KEY_LIGHTCURVE_TITLE,
    VO_ENVELOPE_KEY_PUBLICATION_ID,
    VO_ENVELOPE_KEY_TABLE_DESCRIPTION,
    VO_ENVELOPE_KEY_TABLE_NAME,
    VO_ENVELOPE_KEY_VOTABLE_DESCRIPTION,
    is_votable_export_format,
    votable_binary_encoding,
)
from skvo_veb.utils.my_tools import PipeException, sanitize_filename
from skvo_veb.volightcurve import (
    PhotCal,
    VOLightCurve,
    assign_photometry_column_semantics,
    get_time_colnames,
    get_flux_colnames,
    get_mag_colnames,
    get_error_colnames,
    is_mag_column,
    is_magnitude_phot_column,
    write_vo_lightcurve,
)
from skvo_veb.volightcurve.time_reference import (
    export_absolute_jd_as_time_offset,
    normalise_table_epoch_to_absolute_jd,
)

logger = logging.getLogger(__name__)

"""
Basic lightcurve data + metadate structure is
{
    "schema": {
        "time": "jd",
        "value": "mag", 
        "error": "mag_err"
    },
    "data": [
        [2459000.5, 15.2, 0.02, "source_1"],
        [2459001.5, 15.3, 0.05, "phase_2"]
        [2459001.5, 15.3, 0.05, "sector 12345"]
    ],
    "meta": {
        "active_domain": "mag",
        "jd0": 0.0,
        "photcal": {
            "zp_flux": 3631.0,
            "zp_flux_unit": "Jy",
            "zp_mag": 0.0,
            "mag_sys": "Vega"
        }
    }
}
"""


def read_to_volc(file_source):
    """Reads a lightcurve from a file path or an in-memory binary stream.

    Loads the given data source and returns an initialised VOLightCurve instance.

    Args:
        file_source (str or file-like object): Path to the input file or an active,
            open binary stream (e.g., io.BytesIO).

    Returns:
        VOLightCurve: The ingested and processed Virtual Observatory lightcurve instance.
    """
    try:
        # VOLightCurve internally uses Table.read, which handles file-like objects
        volc = VOLightCurve(file_source)
        return volc
    except Exception as e:
        logger.error(f"VOLightCurve read failed: {e}")
        raise


_LEGACY_DAT_COLUMN_COUNT = 3
_LEGACY_DAT_COLUMN_HINT = "jd, mag, mag_err"

# Must match label-like columns handled in ``volc_to_curvedash`` / export.
_DAT_FREE_TEXT_COLUMNS = frozenset({"label", "sector", "flag"})

_DAT_METADATA_COMMENT = re.compile(
    r"(?:JD0|MAG0|PERIOD|EPOCH|FILTER|BAND)\s*=",
    re.IGNORECASE,
)


def format_user_upload_error(exc: BaseException) -> str:
    """Returns a short user-facing message for failed lightcurve uploads.

    Args:
        exc (BaseException): Error raised during ingest.

    Returns:
        str: ``PipeException`` text unchanged; otherwise a generic line without Astropy dumps.
    """
    if isinstance(exc, PipeException):
        return str(exc)
    return (
        "Upload failed. The file could not be read. "
        "Details were logged on the server."
    )


def _is_dat_metadata_comment_line(line: str) -> bool:
    """True when a ``#`` comment carries ``KEY=value`` metadata, not column names.

    Args:
        line (str): Comment text without the leading ``#``.

    Returns:
        bool: True for lines such as ``JD0 = 0`` or ``FILTER=Gaia/GAIA3.G``.
    """
    text = line.strip().lstrip("#").strip()
    return bool(_DAT_METADATA_COMMENT.search(text))


def _dat_column_label_hint(col_names: list[str] | None) -> str:
    """Builds a parenthetical column hint for strict ``.dat`` row errors.

    Args:
        col_names (list, optional): Header names from a ``#`` comment line.

    Returns:
        str: Comma-separated names or the legacy default hint.
    """
    if col_names:
        return ", ".join(col_names)
    return _LEGACY_DAT_COLUMN_HINT + " (legacy default)"


def _dat_column_accepts_free_text(col_name: str) -> bool:
    """True when a declared ``.dat`` column holds arbitrary strings (e.g. ``label``).

    Args:
        col_name (str): Column name from the ``# jd mag ...`` header comment.

    Returns:
        bool: True for ``label``, ``sector``, and ``flag`` (case-insensitive).
    """
    return col_name.lower() in _DAT_FREE_TEXT_COLUMNS


def _parse_dat_cell(col_name: str, token: str, line_no: int, stripped: str):
    """Parses one whitespace-separated ``.dat`` field for table construction.

    Photometry and time columns must be numeric (``nan`` / ``NaN`` allowed). Free-text
    columns keep the raw token for promotion in ``VOLightCurve``.

    Args:
        col_name (str): Header column name for this field.
        token (str): Field text from the row.
        line_no (int): Source line number for errors.
        stripped (str): Full stripped row text for errors.

    Returns:
        float or str: Cell value for the Astropy column.

    Raises:
        PipeException: When a numeric column is not numeric.
    """
    if _dat_column_accepts_free_text(col_name):
        return token
    if token.lower() == "nan":
        return float("nan")
    try:
        return float(token)
    except ValueError as exc:
        raise PipeException(
            f"Invalid .dat row at line {line_no}: column {col_name!r} expects a "
            f"numeric value, got {token!r}.\n"
            f"Offending line: {stripped}"
        ) from exc


def _read_dat_upload_table(file_source) -> Table:
    """Reads a ``.dat`` upload with strict row validation and full ``#`` metadata.

    Comment lines are stored in ``table.meta['comments']`` (text without ``#``).
    Data rows must have a fixed token count: from the first non-metadata ``#`` header
    whose word count matches the data width, or exactly three columns for legacy files.
    Column typing follows the header names (``label`` / ``sector`` / ``flag`` stay
    strings); promotion to VO standards runs in ``VOLightCurve.from_table``.

    Args:
        file_source: Path or readable binary stream.

    Returns:
        astropy.table.Table: Parsed rows with ``meta['comments']`` populated.

    Raises:
        PipeException: On encoding issues, empty files, or ragged rows; numeric columns only.
    """
    if hasattr(file_source, "seek"):
        file_source.seek(0)
    if hasattr(file_source, "read"):
        raw = file_source.read()
    else:
        raw = Path(file_source).read_bytes()
    if isinstance(raw, str):
        text = raw
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PipeException(
                "Invalid .dat file: content is not valid UTF-8 text."
            ) from exc

    comments: list[str] = []
    data_rows: list[tuple[int, list[str], str]] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            comments.append(stripped.lstrip("#").strip())
            continue
        tokens = stripped.split()
        data_rows.append((line_no, tokens, stripped))

    if not data_rows:
        raise PipeException("Invalid .dat file: no data rows found.")

    first_line_no, first_tokens, _ = data_rows[0]
    n_data = len(first_tokens)
    for line_no, tokens, stripped in data_rows[1:]:
        if len(tokens) != n_data:
            raise PipeException(
                f"Invalid .dat row at line {line_no}: expected {n_data} columns "
                f"(same as first data row at line {first_line_no}), got {len(tokens)}.\n"
                f"Offending line: {stripped}"
            )

    header_names: list[str] | None = None
    header_candidates: list[list[str]] = []
    for comment in comments:
        if _is_dat_metadata_comment_line(comment):
            continue
        parts = comment.split()
        if parts:
            header_candidates.append(parts)

    for parts in header_candidates:
        if len(parts) == n_data:
            header_names = parts
            break

    if header_names is None and header_candidates:
        declared = header_candidates[0]
        raise PipeException(
            f"Invalid .dat file: column header declares {len(declared)} columns "
            f"({', '.join(declared)}) but data rows have {n_data} columns "
            f"(first data row at line {first_line_no})."
        )

    if header_names is None:
        if n_data != _LEGACY_DAT_COLUMN_COUNT:
            raise PipeException(
                f"Invalid .dat file: no column header comment with {n_data} names "
                f"and data rows have {n_data} columns; legacy .dat expects "
                f"{_LEGACY_DAT_COLUMN_COUNT} ({_LEGACY_DAT_COLUMN_HINT}). "
                f"Add a line such as '# jd mag mag_err' or fix the column count."
            )
        col_names = [f"col{i + 1}" for i in range(_LEGACY_DAT_COLUMN_COUNT)]
    else:
        col_names = header_names

    n_expected = len(col_names)
    hint = _dat_column_label_hint(header_names)
    columns: dict[str, list] = {name: [] for name in col_names}

    for line_no, tokens, stripped in data_rows:
        if len(tokens) != n_expected:
            raise PipeException(
                f"Invalid .dat row at line {line_no}: expected {n_expected} columns "
                f"({hint}), got {len(tokens)}.\n"
                f"Offending line: {stripped}"
            )
        for name, token in zip(col_names, tokens):
            columns[name].append(_parse_dat_cell(name, token, line_no, stripped))

    table = Table([columns[name] for name in col_names], names=col_names)
    table.meta["comments"] = comments
    return table


def ingest_volightcurve_file(
    file_source,
    filename: str,
    *,
    table_id: str | int | None = None,
) -> VOLightCurve:
    """Canonical user-upload ingest: always returns a ``VOLightCurve``.

    Dispatches by file extension so TESS, GP, and future pages share one parse path.
    VOTable products use full VO metadata ingest. Tabular formats use explicit readers;
    ``.dat`` uses strict line parsing in ``_read_dat_upload_table`` so every ``#`` metadata
    line is kept in ``table.meta['comments']`` before heuristics run.

    Args:
        file_source (str or file-like): Path or open binary stream.
        filename (str): Original upload filename (required for format detection).
        table_id (str or int, optional): Select one embedded VOTable table.

    Returns:
        VOLightCurve: Parsed lightcurve with timescale and photometry metadata.
    """
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in ("vot", "xml"):
        if hasattr(file_source, "seek"):
            file_source.seek(0)
        return VOLightCurve(file_source, table_id=table_id)

    tabular_formats = {
        "ecsv": "ascii.ecsv",
        "csv": "csv",
    }
    if ext == "dat":
        if hasattr(file_source, "seek"):
            file_source.seek(0)
        return VOLightCurve.from_table(_read_dat_upload_table(file_source))
    if ext in tabular_formats:
        if hasattr(file_source, "seek"):
            file_source.seek(0)
        table = Table.read(file_source, format=tabular_formats[ext])
        return VOLightCurve.from_table(table)

    if hasattr(file_source, "seek"):
        file_source.seek(0)
    return VOLightCurve(file_source, table_id=table_id)


def ingest_lightcurve_file(file_source, filename: str):
    """Ingests an uploaded lightcurve file into a ``CurveDash`` instance.

    VOTable files retain PhotCal metadata;     tabular formats (ECSV, CSV, DAT) restore
    only the basic metadata stored in the file header (ECSV) or column data alone.

    ``.dat`` files use strict row validation in ``_read_dat_upload_table`` (fixed column
    count per row; no padding). Failures raise ``PipeException`` with line numbers.

    Args:
        file_source (str or file-like): Path or open binary stream.
        filename (str): Original upload filename used for format detection.

    Returns:
        CurveDash: Parsed application lightcurve state.
    """
    ext = Path(filename).suffix.lower().lstrip(".")
    preserve_photcal = ext in ("vot", "xml")
    volc = ingest_volightcurve_file(file_source, filename)
    return volc_to_curvedash(volc, filename, preserve_photcal=preserve_photcal)


def tabular_table_to_curvedash(table: Table, filename: str):
    """Builds a ``CurveDash`` from a plain Astropy table (CSV/ECSV/DAT upload).

    Preserves exported column names and restores ECSV header metadata without PhotCal.

    Args:
        table (Table): Tabular data read by Astropy.
        filename (str): Original filename (used for object naming).

    Returns:
        CurveDash: Parsed application lightcurve state.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    meta = table.meta or {}
    time_col = None
    for name in ("jd", "obs_time", "time", "mjd"):
        if name in table.colnames:
            time_col = name
            break
    if time_col is None:
        raise ValueError("No time column found in the uploaded tabular file.")

    jd_vals = np.asarray(table[time_col], dtype=float)
    if time_col in ("obs_time", "mjd") and np.nanmax(jd_vals) < 1e6:
        jd_vals = jd_vals + JD_TO_MJD

    if "phot" in table.colnames:
        phot_col = "phot"
        is_mag = is_magnitude_phot_column(table, phot_col)
    elif "flux" in table.colnames:
        phot_col, is_mag = "flux", False
    elif "mag" in table.colnames:
        phot_col, is_mag = "mag", True
    else:
        raise ValueError("No photometry column found in the uploaded tabular file.")

    err_col = None
    for candidate in ("flux_error", "phot_error", "flux_err", "mag_err"):
        if candidate in table.colnames:
            err_col = candidate
            break
    if err_col is not None:
        err_vals = np.asarray(table[err_col], dtype=float)
    else:
        err_vals = np.zeros(len(jd_vals), dtype=float)

    phot_vals = np.asarray(table[phot_col], dtype=float)
    label_vals = np.asarray(table["label"]) if "label" in table.colnames else None
    target_name = meta.get("name") or Path(filename).stem
    if str(target_name).startswith("TESS_"):
        target_name = str(target_name)[5:]

    common_kwargs = dict(
        name=target_name,
        lookup_name=target_name,
        jd=jd_vals,
        label=label_vals,
        time_unit="d",
        timescale="tdb",
        photcal={},
        period=meta.get("period"),
        epoch=meta.get("epoch"),
        period_unit="d",
    )
    if is_mag:
        lcd = CurveDash(
            **common_kwargs,
            mag=phot_vals,
            mag_err=err_vals,
            mag_unit=str(table[phot_col].unit or "mag"),
            active_domain=DOMAIN_MAG,
        )
    else:
        lcd = CurveDash(
            **common_kwargs,
            flux=phot_vals,
            flux_err=err_vals,
            flux_unit=str(table[phot_col].unit or ""),
            active_domain=DOMAIN_FLUX,
        )

    lcd.metadata["photcal"] = {}
    _apply_tabular_meta_to_curvedash(lcd, meta)
    lcd.title = build_curvedash_title(lcd)
    lcd.metadata["title"] = lcd.title
    return lcd


# We need this to tame our float types zoo
class LCEncoder(json.JSONEncoder):
    """Custom JSON encoder handling NumPy primitives, arrays, and Astropy objects.

    Extends json.JSONEncoder to map types like float32, int64, and numpy.ndarray to standard,
    serialisable Python primitives, preventing float precision loss and serialisation errors.
    """

    def default(self, obj):
        if isinstance(obj, (np.floating, np.float32, np.float64)):
            return float(obj)
        if isinstance(obj, (np.integer, np.int32, np.int64)):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        # Fallback to the standard encoder
        return super().default(obj)


def pack_volc_to_json(lc: VOLightCurve, primary_col=None, error_col=None):
    """Packs a VOLightCurve instance into a compact, standardized JSON schema for Web/JS transport.

    Extracts core time, photometry, error, and flag series alongside associated ZeroPoint
    photometric calibrations and timescale offsets, converting them to native serialisable types.

    Args:
        lc (VOLightCurve): The input lightcurve container.
        primary_col (str, optional): The name of the primary photometry column to pack.
            Defaults to the first magnitude column (or flux column if none found).
        error_col (str, optional): The name of the statistical uncertainty column to pack.
            Defaults to None (which falls back to the corresponding mag or flux error column).

    Returns:
        str: A JSON-encoded string describing the schema, metadata, and observations.

    Raises:
        ValueError: If no timing columns are found or if no primary magnitude/flux columns
            can be resolved.
    """

    mag_cols = get_mag_colnames(lc)
    flux_cols = get_flux_colnames(lc)
    time_cols = get_time_colnames(lc)
    error_cols = get_error_colnames(lc)

    if not time_cols:
        raise ValueError("No time columns found in VOLightCurve.")

    if not primary_col:
        primary_col = mag_cols[0] if mag_cols else (flux_cols[0] if flux_cols else None)

    if not primary_col:
        raise ValueError("No magnitude or flux columns found in VOLightCurve.")

    # todo: this is a stub! Use a proper error column (mag or flux or calculate mag_err from flux_err (Gaia case)
    if is_mag_column(lc.table, primary_col):
        error_cols = lc.get_mag_error_colnames()
    else:
        error_cols = lc.get_flux_error_colnames()

    if not error_col:
        error_col = error_cols[0] if error_cols else None

    # "The Rest" - Flag Column Identification
    meaningful = set(time_cols + mag_cols + flux_cols + error_cols)
    flag_col = next((c for c in lc.table.colnames if c not in meaningful), None)

    # Photometry calibration extraction (full photcal GROUP)
    photcal_meta = _extract_photcal_meta(lc, primary_col)

    # Data Extraction
    # .value is used to strip Astropy units before JSON serialization
    time_col = time_cols[0]
    t = lc[time_col].value
    v = lc[primary_col].value

    # Use .tolist() or raw arrays to handle potential None/nulls safely
    e = lc[error_col].value if error_col else [None] * len(v)

    # Flags can be mixed types; .value (if it's a Quantity) or raw column
    f_data = lc.table[flag_col] if flag_col else [None] * len(v)
    f = f_data.value if hasattr(f_data, 'value') else f_data

    # Final Construction
    table_meta = lc.table.meta or {}
    meta_block = {
        "active_domain": "mag" if primary_col in mag_cols else "flux",
        "jd0": lc.timesys.jd0,
        "photcal": photcal_meta,
    }
    timesys = lc.timesys
    if timesys is not None:
        if timesys.timescale:
            meta_block["timescale"] = str(timesys.timescale).upper()
        if timesys.refposition:
            meta_block["refposition"] = str(timesys.refposition).upper()
    if table_meta.get("period") is not None:
        meta_block["period"] = float(table_meta["period"])
    if table_meta.get("epoch") is not None:
        try:
            meta_block["epoch"] = float(
                normalise_table_epoch_to_absolute_jd(lc, table_meta.get("epoch"))
            )
        except (ValueError, TypeError) as exc:
            logger.warning("Could not normalise epoch for transport JSON: %s", exc)

    meta_block[METADATA_KEY_VO_ENVELOPE] = _extract_vo_envelope_meta(
        lc,
        filename=str(
            table_meta.get("name")
            or table_meta.get("ID")
            or table_meta.get("lightcurve_title")
            or "lightcurve"
        ),
    )

    struct = {
        "schema": {
            "time": time_col,
            "value": primary_col,
            "error": error_col,  # None if missing
            "flag": flag_col,  # None if missing
        },
        "data": [list(row) for row in zip(t, v, e, f)],
        "meta": meta_block,
    }

    return json.dumps(struct, cls=LCEncoder)


def _transport_flag_column_to_labels(flag_values) -> np.ndarray:
    """Maps transport flag cells to ``CurveDash`` uint8 label array.

    Args:
        flag_values: Column from transport ``data`` (index 3).

    Returns:
        numpy.ndarray: Label array aligned with photometry rows.
    """
    labels = []
    for raw in flag_values:
        if raw is None:
            labels.append(0)
            continue
        try:
            labels.append(int(raw))
        except (TypeError, ValueError):
            labels.append(0)
    return np.asarray(labels, dtype=np.uint8)


def curvedash_from_transport_json(
    json_str: str,
    *,
    source_name: str | None = None,
):
    """Builds a ``CurveDash`` from GP/Dash transport JSON for bridge export.

    Args:
        json_str (str): Serialised packet from ``pack_volc_to_json`` (possibly
            updated by GP detrend or other prep steps).
        source_name (str, optional): Original upload filename for metadata title.

    Returns:
        CurveDash: Instance ready for ``export_curvedash``.

    Raises:
        PipeException: When the payload is empty or structurally invalid.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not json_str or not str(json_str).strip():
        raise PipeException("No light curve data to export.")

    try:
        packet = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise PipeException(f"Light curve transport JSON is invalid: {exc}") from exc

    data = packet.get("data")
    if not data:
        raise PipeException("Light curve transport contains no observations.")

    meta = packet.get("meta") or {}
    schema = packet.get("schema") or {}
    arr = np.array(data, dtype=object)
    if arr.ndim != 2 or arr.shape[1] < 2:
        raise PipeException("Light curve transport rows are malformed.")

    t_raw = arr[:, 0].astype(float)
    v_raw = arr[:, 1].astype(float)
    jd0 = float(_jd0_from_packet_meta(meta) or 0.0)
    jd = t_raw + jd0

    has_err = schema.get("error") is not None
    if has_err and arr.shape[1] > 2:
        err_list = []
        for cell in arr[:, 2]:
            if cell is None:
                err_list.append(np.nan)
                continue
            try:
                val = float(cell)
            except (TypeError, ValueError):
                err_list.append(np.nan)
                continue
            err_list.append(val if np.isfinite(val) else np.nan)
        err = np.asarray(err_list, dtype=float)
    else:
        err = np.full_like(v_raw, np.nan, dtype=float)

    if arr.shape[1] > 3 and schema.get("flag") is not None:
        label = _transport_flag_column_to_labels(arr[:, 3])
    else:
        label = np.zeros(len(v_raw), dtype=np.uint8)

    active_domain = meta.get("active_domain") or DOMAIN_MAG
    photcal = meta.get("photcal") or {}
    timescale = (meta.get("timescale") or "utc").lower()

    if source_name:
        stem = Path(source_name).stem
        display_name = stem
    else:
        display_name = meta.get("name") or "gp_lightcurve"
        stem = str(display_name)

    common_kwargs = dict(
        name=stem,
        title=stem,
        jd=jd,
        label=label,
        time_unit="d",
        timescale=timescale,
        photcal=photcal,
        period=meta.get("period"),
        epoch=meta.get("epoch"),
        period_unit="d",
        active_domain=active_domain,
    )

    if active_domain == DOMAIN_MAG:
        lcd = CurveDash(
            **common_kwargs,
            mag=v_raw,
            mag_err=err,
            mag_unit=str(meta.get("mag_unit") or "mag"),
        )
    else:
        flux_unit = meta.get("flux_unit") or photcal.get(PHOTCAL_KEY_ZP_FLUX_UNIT) or ""
        lcd = CurveDash(
            **common_kwargs,
            flux=v_raw,
            flux_err=err,
            flux_unit=str(flux_unit) if flux_unit else "",
            active_domain=DOMAIN_FLUX,
        )

    envelope = meta.get(METADATA_KEY_VO_ENVELOPE)
    if envelope:
        lcd.metadata[METADATA_KEY_VO_ENVELOPE] = envelope

    return lcd


def unpack_json_for_plotly(json_str: str, view_mode='mag'):
    """Lean NumPy decoder that unpacks a transport JSON package and prepares arrays for Plotly rendering.

    Optimized for high-speed operation inside Dash callbacks, decoding and cleansing 
    data streams (e.g. handling NaNs in TESS datasets) without the overhead of Pandas.

    Args:
        json_str (str): The serialised JSON transport string.
        view_mode (str, optional): The target visual domain ('mag' or 'flux'). Defaults to 'mag'.

    Returns:
        dict: A dictionary containing NumPy arrays or Series for rendering:
            - 'x': Cleverly cleansed, absolute Julian Dates.
            - 'y': Calibrated photometry values.
            - 'err': Cleansed uncertainties (or None).
            - 'flag': Custom metadata flags or group sectors.
            - 'x_label': X-axis plotting label.
            - 'y_label': Y-axis plotting label.
            - 'is_mag': Flag denoting if Y-data is currently represented in magnitude space.
    """
    packet = json.loads(json_str)
    meta = packet['meta']
    photcal = meta['photcal']

    # Convert list of lists to a 2D NumPy array
    # Array indices: 0=time, 1=value, 2=error, 3=flag
    data = np.array(packet['data'], dtype=object)

    # Raw extraction
    t_raw = data[:, 0].astype(float)
    v_raw = data[:, 1].astype(float)

    # Cleansing (particularly important for TESS lightcurves)
    valid_mask = ~np.isnan(t_raw) & ~np.isnan(v_raw)
    t = t_raw[valid_mask]
    v = v_raw[valid_mask]

    # Handle the 'None' in errors safely
    e_raw = data[valid_mask, 2] # Apply mask to row indexing
    has_err = packet['schema']['error'] is not None
    e = e_raw.astype(float) if has_err else None

    # e_raw = data[:, 2]
    # has_err = packet['schema']['error'] is not None
    # e = e_raw.astype(float) if has_err else None

    f = data[valid_mask, 3]     # Apply mask, keep flags as objects/strings
    # f = data[:, 3]

    # apply JD0 (packed from VOLightCurve.timesys.jd0)
    jd0 = _jd0_from_packet_meta(meta)
    if jd0:
        t += jd0

    # Domain Logic
    current_domain = meta['active_domain']
    y_data = v
    e_data = e

    if view_mode != current_domain:
        pc = photcal_from_metadata(photcal)
        flux_unit = pc.zp_flux.unit

        if view_mode == DOMAIN_FLUX and current_domain == DOMAIN_MAG:
            mag_q = v * u.mag
            flux_q = pc.mag_to_flux(mag_q)
            y_data = np.asarray(flux_q.value, dtype=float)
            if has_err:
                err_q = e * u.mag
                e_data = np.asarray(
                    pc.mag_err_to_flux_err(mag_q, err_q).value, dtype=float
                )

        elif view_mode == DOMAIN_MAG and current_domain == DOMAIN_FLUX:
            mask = v > 0
            y_data = np.full_like(v, np.nan)
            flux_q = v[mask] * flux_unit
            y_data[mask] = np.asarray(pc.flux_to_mag(flux_q).value, dtype=float)

            if has_err:
                e_data = np.full_like(e, np.nan)
                err_q = e[mask] * flux_unit
                e_data[mask] = np.asarray(
                    pc.flux_err_to_mag_err(flux_q, err_q).value, dtype=float
                )

    return {
        'x': t,
        'y': y_data,
        'err': e_data,
        'flag': f,
        'x_label': "Julian Date (JD)",
        'y_label': "Magnitude" if view_mode == 'mag' else "Flux",
        'is_mag': (view_mode == 'mag'),
        'timescale': meta.get('timescale'),
        'refposition': meta.get('refposition'),
    }


def get_flux_fragment(json_str: str, jd_min: float, jd_max: float) -> pd.DataFrame:
    """Extracts a JD-sliced fragment of the lightcurve in the physical FLUX domain.

    Useful for supplying raw flux data directly to mathematical modules (such as Gaussian Processes).

    Args:
        json_str (str): The serialised JSON transport string.
        jd_min (float): The minimum absolute Julian Date bound.
        jd_max (float): The maximum absolute Julian Date bound.

    Returns:
        pandas.DataFrame: A DataFrame containing 'jd', 'flux', and 'flux_err' columns.
    """
    # We force view_mode='flux' so the bridge handles the math
    lc = unpack_json_for_plotly(json_str, view_mode='flux')

    # Build the DataFrame
    df = pd.DataFrame({
        'jd': lc['x'],
        'flux': lc['y'],
        'flux_err': lc['err'] if lc['err'] is not None else np.nan
    })

    # Slice by JD
    mask = (df['jd'] >= jd_min) & (df['jd'] <= jd_max)
    frag = df[mask].copy()

    # Drop any row where flux is NaN (FOR TESS!)
    frag = frag.dropna(subset=['jd', 'flux'])

    return frag


def get_jd_limits(json_str):
    """Extracts the absolute minimum and maximum Julian Date bounds from the lightcurve transport.

    Args:
        json_str (str): The serialised JSON transport string.

    Returns:
        tuple of float: (min_jd, max_jd) defining the full observation window.
    """
    packet = json.loads(json_str)
    # Our 'data' array always has JD at index 0
    times = [row[0] for row in packet['data']]
    jd0 = packet['meta'].get('jd0', 0)
    return min(times) + jd0, max(times) + jd0


def get_intervals_from_phase(json_str, phi_min: float, phi_max: float, period: float, epoch=None):
    """Converts selected phase boundaries into concrete absolute JD intervals.

    Identifies which cycles fall within the dataset's time window, maps phase coordinates back
    to absolute dates, and clips them to the bounds of the actual observations.

    Args:
        json_str (str): The serialised JSON transport string.
        phi_min (float): Minimum phase selection bound (may be below 0 on the extended prep axis).
        phi_max (float): Maximum phase selection bound (may exceed 1 on the extended prep axis).
        period (float): Fold period of the star in days.
        epoch (float, optional): Reference zero-phase epoch Julian Date.
            Defaults to the start of the dataset.

    Returns:
        list of list: A list of absolute time segments [[start_jd, end_jd], ...]
            clipped to the observation window.
    """
    jd_start, jd_end = get_jd_limits(json_str)
    t0 = epoch if epoch is not None else jd_start

    # Cycle detection
    e_start = np.floor((jd_start - t0) / period)
    e_end = np.ceil((jd_end - t0) / period)

    intervals = []
    for e in np.arange(e_start, e_end + 1):
        t_start = t0 + period * (e + phi_min)
        t_end = t0 + period * (e + phi_max)

        # Clip to observation window
        actual_start = max(t_start, jd_start)
        actual_end = min(t_end, jd_end)

        if actual_end > actual_start:
            intervals.append([round(actual_start, 6), round(actual_end, 6)])

    return intervals


def phase_vrect_bounds_for_jd_interval(
    jd_min: float,
    jd_max: float,
    epoch_jd: float,
    period: float,
) -> list[tuple[float, float]]:
    """Maps a stored absolute-JD interval to phase-axis vrect bounds for display only.

    Does not modify the interval. Uses the same folding convention as the GP prep plot:
    ``phase = ((JD - epoch) / period) % 1``.

    Args:
        jd_min (float): Interval start in absolute Julian Date.
        jd_max (float): Interval end in absolute Julian Date.
        epoch_jd (float): Folding epoch (absolute JD).
        period (float): Fold period in days.

    Returns:
        list[tuple[float, float]]: One or two ``(x0, x1)`` pairs on ``[0, 1]`` (wrap splits).
    """
    if period <= 0 or not np.isfinite(period):
        return []
    start = float(min(jd_min, jd_max))
    end = float(max(jd_min, jd_max))
    if end <= start:
        return []

    phi0 = ((start - epoch_jd) / period) % 1.0
    phi1 = ((end - epoch_jd) / period) % 1.0

    if (end - start) >= period:
        return [(0.0, 1.0)]
    if phi0 <= phi1:
        return [(phi0, phi1)]
    return [(phi0, 1.0), (0.0, phi1)]


def pretty_print_lc_json(json_str: str, max_rows: int = 5):
    """Parses a lightcurve JSON transport package and prints a clean, human-readable summary.

    Useful for terminal-based validation and debugging, displaying active domains, calibrations,
    schemas, and a head/tail slice of observations.

    Args:
        json_str (str): The serialised JSON transport string.
        max_rows (int, optional): The number of rows from the head and tail to display.
            Defaults to 5.
    """
    try:
        packet = json.loads(json_str)
    except json.JSONDecodeError:
        logger.error("Error: Input is not a valid JSON string.")
        return

    schema = packet.get("schema", {})
    meta = packet.get("meta", {})
    photcal = meta.get("photcal", {})
    data = packet.get("data", [])

    lines = [
        "=" * 80,
        f"{'VOLightCurve JSON Transport Package':^80}",
        "=" * 80,
        f"PRIMARY DOMAIN: {meta.get('active_domain', 'Unknown').upper()}",
        f"JD0 (Offset):   {meta.get('jd0', 'N/A')}",
        f"CALIBRATION:    Sys: {photcal.get('mag_sys', 'N/A')}",
        f"                ZP Mag:  {photcal.get('zp_mag')} {photcal.get('zp_mag_unit')}",
        f"                ZP Flux: {photcal.get('zp_flux')} {photcal.get('zp_flux_unit')}",
        "-" * 80,
        "SCHEMA / COLUMN MAPPING:",
    ]
    for key, colname in schema.items():
        label = colname if colname else "[Not Provided]"
        lines.append(f"  {key:10} -> {label}")
    lines.append("-" * 80)

    total_rows = len(data)
    lines.append(f"DATA ({total_rows} rows):")

    h_time = schema.get('time') or "Time"
    h_val = schema.get('value') or "Value"
    h_err = schema.get('error') or "Error"
    h_flag = schema.get('flag') or "Flag"

    headers = [h_time, h_val, h_err, h_flag]
    lines.append(f"  {' | '.join([f'{h:^18}' for h in headers])}")
    lines.append(f"  {'-' * 78}")

    def format_row(row):
        parts = []
        for item in row:
            if item is None:
                parts.append(f"{'-':^18}")
            elif isinstance(item, float):
                # 6 decimal places is plenty for a quick look
                parts.append(f"{item:^18.6f}")
            else:
                parts.append(f"{str(item):^18}")
        return " | ".join(parts)

    if total_rows > (max_rows * 2):
        for row in data[:max_rows]:
            lines.append(f"  {format_row(row)}")

        divider = [". . ."] * 4
        lines.append(f"  {' | '.join([f'{d:^18}' for d in divider])}")

        for row in data[-max_rows:]:
            lines.append(f"  {format_row(row)}")
    else:
        for row in data:
            lines.append(f"  {format_row(row)}")

    lines.append("=" * 80)
    for line in lines:
        logger.info(line)


def _parse_list_meta(value):
    """Normalises a VOTable PARAM value into a list of strings.

    Args:
        value: Scalar, comma-separated string, or list from table metadata.

    Returns:
        list of str or None: Parsed list values.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    if isinstance(value, str):
        parts = [v.strip() for v in value.split(',') if v.strip()]
        return parts or None
    return [str(value)]


def build_curvedash_title(lcd) -> str:
    """Builds a human-readable plot title from CurveDash metadata.

    Mirrors the title format produced by ``tess_lc_builder`` for archive downloads.

    Args:
        lcd (CurveDash): Application lightcurve with populated metadata.

    Returns:
        str: Title string for Plotly figures and export metadata.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash):
        return 'Uploaded lightcurve'

    meta = lcd.metadata or {}
    stored = meta.get('title') or lcd.title
    if stored:
        return stored

    lookup = meta.get('lookup_name') or ''
    name = meta.get('name') or ''
    parts = []
    if lookup:
        parts.append(str(lookup))
    if name and str(name) != str(lookup):
        parts.append(str(name))

    sectors = _parse_list_meta(meta.get('sectors'))
    if sectors:
        parts.append(f"sector: {','.join(sectors)}")

    authors = _parse_list_meta(meta.get('authors'))
    if authors:
        parts.append(f"author: {','.join(authors)}")

    flux_origins = _parse_list_meta(meta.get('flux_origins'))
    if flux_origins:
        parts.append(f"methods: {','.join(flux_origins)}")

    if parts:
        return ' '.join(parts)
    return name or lookup or 'Uploaded lightcurve'


def _strip_zero_points_from_photcal(photcal: dict | None) -> dict:
    """Removes zero-point keys while preserving filter passband metadata.

    Args:
        photcal (dict, optional): Serialised photcal GROUP metadata.

    Returns:
        dict: Photcal metadata without absolute calibration fields.
    """
    pc = dict(photcal or {})
    for key in (
        PHOTCAL_KEY_ZP_FLUX,
        PHOTCAL_KEY_ZP_FLUX_UNIT,
        PHOTCAL_KEY_ZP_MAG,
        PHOTCAL_KEY_ZP_MAG_UNIT,
        PHOTCAL_KEY_MAG_SYS,
    ):
        pc.pop(key, None)
    return pc


def photcal_from_metadata(photcal: dict | None) -> PhotCal:
    """Builds a ``PhotCal`` from CurveDash ``metadata['photcal']``.

    Required keys: ``PHOTCAL_KEY_ZP_FLUX`` and ``PHOTCAL_KEY_ZP_MAG``.
    ``PHOTCAL_KEY_ZP_FLUX_UNIT`` is optional; when absent or empty the zero-point
    flux is dimensionless. Other magnitude-system and unit keys pass through when
    present.

    Args:
        photcal (dict): Serialised photcal GROUP from CurveDash metadata.

    Returns:
        PhotCal: Calibration for mag/flux conversion.

    Raises:
        ValueError: If required zero-point fields are missing.
    """
    if not photcal:
        raise ValueError("photcal metadata is required for domain conversion.")

    zp_flux = photcal.get(PHOTCAL_KEY_ZP_FLUX)
    zp_mag = photcal.get(PHOTCAL_KEY_ZP_MAG)
    zp_flux_unit = photcal.get(PHOTCAL_KEY_ZP_FLUX_UNIT)
    if zp_flux is None or zp_mag is None:
        raise ValueError(
            "Incomplete photcal metadata for conversion: "
            "require zp_flux and zp_mag."
        )

    # An empty ``zp_flux_unit`` means dimensionless zero-point flux (for example
    # TESS QLP archive products stored with ``u.dimensionless_unscaled``). ``PhotCal``
    # already defaults to dimensionless when no unit is supplied. A non-empty string
    # must be a valid Astropy/VO unit label (for example SPOC ``electron s-1``).
    kwargs = {
        "zp_flux": float(zp_flux),
        "zp_mag": float(zp_mag),
    }
    if zp_flux_unit:
        kwargs["zp_flux_unit"] = zp_flux_unit
    zp_mag_unit = photcal.get(PHOTCAL_KEY_ZP_MAG_UNIT)
    if zp_mag_unit:
        kwargs["zp_mag_unit"] = zp_mag_unit
    mag_sys = photcal.get(PHOTCAL_KEY_MAG_SYS)
    if mag_sys:
        kwargs["mag_sys"] = mag_sys
    return PhotCal(**kwargs)


def _jd0_from_packet_meta(meta: dict) -> float:
    """Returns JD0 from a JSON transport packet ``meta`` block.

    The value is written by ``pack_volc_to_json`` from ``VOLightCurve.timesys.jd0``.

    Args:
        meta (dict): Transport ``meta`` block.

    Returns:
        float: Julian Date origin offset (``0.0`` is valid when explicitly stored).

    Raises:
        ValueError: If ``jd0`` is absent from ``meta``.
    """
    if "jd0" not in meta:
        raise ValueError(
            "Transport meta missing 'jd0' (expected from VOLightCurve.timesys.jd0)."
        )
    return float(meta["jd0"])


def _unit_to_storage_string(unit) -> str:
    """Serialises an Astropy unit for CurveDash metadata storage.

    VOUnit cannot represent every Astropy unit (for example TESS ``electron``).
    Non-standard units fall back to Astropy's canonical string form.

    Args:
        unit (astropy.units.Unit): Physical unit to serialise.

    Returns:
        str: Unit label safe to store in application metadata.
    """
    if unit is None:
        return ""
    try:
        return unit.to_string("vounit")
    except (ValueError, u.UnitsError, u.UnitTypeError):
        return unit.to_string()


def _serialise_photcal_group(photdm, table_meta: dict | None = None) -> dict:
    """Serialises an IVOA photcal GROUP into CurveDash ``metadata['photcal']``.

    Reads filter and zero-point fields from ``PhotDM`` / table metadata only;
    no bridge-level calibration defaults are invented.

    Args:
        photdm: ``PhotDM`` instance from ``VOLightCurve.photdms``, or None.
        table_meta (dict, optional): Table-level metadata (e.g. ECSV ``filter`` param).

    Returns:
        dict: JSON-serialisable photcal GROUP metadata.
    """
    meta: dict = {}
    table_meta = table_meta or {}

    phot_filter = photdm.filter if photdm else None
    if phot_filter and phot_filter.filter_id:
        meta[PHOTCAL_KEY_FILTER_IDENTIFIER] = phot_filter.filter_id
    if phot_filter and phot_filter.spectral_location is not None:
        try:
            wl_m = phot_filter.spectral_location.to(u.m)
            meta[PHOTCAL_KEY_EFFECTIVE_WAVELENGTH] = float(wl_m.value)
            meta[PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT] = "m"
        except (u.UnitsError, u.UnitTypeError, TypeError, ValueError) as exc:
            logger.warning("Could not serialise effective wavelength: %s", exc)

    filter_name = table_meta.get("filter") or table_meta.get("filter_name")
    if not filter_name and phot_filter and phot_filter.filter_id:
        filter_name = phot_filter.filter_id
    if filter_name:
        meta[PHOTCAL_KEY_FILTER_NAME] = str(filter_name)

    photcal = photdm.photcal if photdm else None
    if photcal is not None:
        if photcal.zp_flux is not None:
            meta[PHOTCAL_KEY_ZP_FLUX] = float(photcal.zp_flux.value)
            meta[PHOTCAL_KEY_ZP_FLUX_UNIT] = _unit_to_storage_string(photcal.zp_flux.unit)
        if photcal.zp_mag is not None:
            meta[PHOTCAL_KEY_ZP_MAG] = float(photcal.zp_mag.value)
            meta[PHOTCAL_KEY_ZP_MAG_UNIT] = (
                _unit_to_storage_string(photcal.zp_mag.unit) if photcal.zp_mag.unit else "mag"
            )
        if photcal.mag_sys:
            meta[PHOTCAL_KEY_MAG_SYS] = photcal.mag_sys

    return meta


def _photcal_group_to_votable_fields(photcal: dict | None, include_zero_points: bool = True) -> dict:
    """Maps stored ``metadata['photcal']`` onto ``write_vo_lightcurve`` keyword arguments.

    Args:
        photcal (dict): Serialised photcal GROUP from CurveDash metadata.
        include_zero_points (bool): When false, omit zero-point PARAM values.

    Returns:
        dict: Subset of ``write_vo_lightcurve`` kwargs derived from stored metadata.
    """
    photcal = photcal or {}
    fields = {}

    filter_id = photcal.get(PHOTCAL_KEY_FILTER_IDENTIFIER)
    if filter_id:
        fields["filter_identifier"] = filter_id

    eff_wl = photcal.get(PHOTCAL_KEY_EFFECTIVE_WAVELENGTH)
    if eff_wl is not None:
        fields["effective_wavelength"] = float(eff_wl)
        eff_wl_unit = photcal.get(PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT)
        if eff_wl_unit:
            fields["effective_wavelength_unit"] = eff_wl_unit

    filter_name = photcal.get(PHOTCAL_KEY_FILTER_NAME)
    if filter_name:
        fields["filter_name"] = filter_name

    if include_zero_points:
        zp_flux = photcal.get(PHOTCAL_KEY_ZP_FLUX)
        zp_mag = photcal.get(PHOTCAL_KEY_ZP_MAG)
        if zp_flux is not None and zp_mag is not None:
            fields["zero_point_flux"] = float(zp_flux)
            fields["zero_point_ref_mag"] = float(zp_mag)
            zp_flux_unit = photcal.get(PHOTCAL_KEY_ZP_FLUX_UNIT)
            if zp_flux_unit:
                fields["zero_point_flux_unit"] = zp_flux_unit
            mag_sys = photcal.get(PHOTCAL_KEY_MAG_SYS)
            if mag_sys:
                fields["magnitude_system"] = mag_sys
        else:
            fields["zero_point_flux"] = None
            fields["zero_point_ref_mag"] = None
    else:
        fields["zero_point_flux"] = None
        fields["zero_point_ref_mag"] = None
        mag_sys = photcal.get(PHOTCAL_KEY_MAG_SYS)
        if mag_sys:
            fields["magnitude_system"] = mag_sys

    return fields


def _extract_photcal_meta(volc: VOLightCurve, phot_col: str) -> dict:
    """Extracts photometric calibration metadata from a VOLightCurve column.

    Args:
        volc (VOLightCurve): Parsed lightcurve container.
        phot_col (str): Primary photometry column name.

    Returns:
        dict: Serialisable photcal GROUP metadata for CurveDash storage.
    """
    photdm = volc.photdms.get(phot_col)
    table_meta = volc.table.meta or {}
    return _serialise_photcal_group(photdm, table_meta)


def _time_column_to_jd_array(volc: VOLightCurve, time_col: str) -> np.ndarray:
    """Converts a VOLightCurve time column to absolute Julian Date values.

    Args:
        volc (VOLightCurve): Parsed lightcurve container.
        time_col (str): Column name holding epoch data.

    Returns:
        numpy.ndarray: Absolute JD values (may still need MJD offset correction).
    """
    col = volc.table[time_col]
    if hasattr(col, "jd"):
        jd_vals = np.asarray(col.jd, dtype=float)
    else:
        jd_vals = volc[time_col]
        if hasattr(jd_vals, "value"):
            jd_vals = jd_vals.value
        jd_vals = np.asarray(jd_vals, dtype=float)
    return jd_vals


def _absolute_jd_from_time_column(volc: VOLightCurve, time_col: str) -> np.ndarray:
    """Resolves display or relative time columns to absolute Julian Date.

    Args:
        volc (VOLightCurve): Parsed lightcurve container.
        time_col (str): Column name holding epoch data.

    Returns:
        numpy.ndarray: Absolute JD values.
    """
    jd_vals = _time_column_to_jd_array(volc, time_col)
    jd0_offset = volc.timesys.jd0 or 0.0
    if time_col == "obs_time" or (jd0_offset > 0 and np.nanmax(jd_vals) < 1e6):
        return jd_vals + jd0_offset
    if jd0_offset == 0.0 and np.nanmax(jd_vals) < 1e6:
        return jd_vals + JD_TO_MJD
    return jd_vals


def _resolve_photometry_column(volc: VOLightCurve) -> str | None:
    """Finds the primary photometry column in an ingested table.

    Prefers magnitude columns with attached ``photcal`` metadata, then other
    photcal-linked columns, before falling back to generic flux/mag detection.

    Args:
        volc (VOLightCurve): Parsed lightcurve container.

    Returns:
        str or None: Column name for flux or magnitude values.
    """
    if "phot" in volc.table.colnames:
        return "phot"

    mag_cols = get_mag_colnames(volc.table)
    flux_cols = get_flux_colnames(volc.table)
    photdms = getattr(volc, "photdms", {}) or {}

    for col in mag_cols:
        if col in photdms:
            return col
    for col in flux_cols:
        if col in photdms:
            return col
    if mag_cols:
        return mag_cols[0]
    if flux_cols:
        return flux_cols[0]
    if "flux" in volc.table.colnames:
        return "flux"
    if "mag" in volc.table.colnames:
        return "mag"
    return None


def _resolve_photometry_error_column(volc: VOLightCurve, phot_col: str) -> str | None:
    """Finds the uncertainty column paired with a photometry column.

    Args:
        volc (VOLightCurve): Parsed lightcurve container.
        phot_col (str): Primary photometry column name.

    Returns:
        str or None: Error column name, if present.
    """
    is_mag = (
        phot_col == "mag"
        or (phot_col == "phot" and is_magnitude_phot_column(volc.table, phot_col))
        or is_mag_column(volc.table, phot_col)
    )
    if is_mag:
        if "mag_err" in volc.table.colnames:
            return "mag_err"
        error_cols = volc.get_mag_error_colnames()
        return error_cols[0] if error_cols else None

    if "flux_error" in volc.table.colnames:
        return "flux_error"
    if phot_col == "flux" and "flux_err" in volc.table.colnames:
        return "flux_err"
    error_cols = volc.get_flux_error_colnames()
    return error_cols[0] if error_cols else None


def _apply_tabular_meta_to_curvedash(lcd, meta: dict) -> None:
    """Maps ECSV header metadata onto ``CurveDash`` without PhotCal fields.

    Args:
        lcd (CurveDash): Target instance to mutate in place.
        meta (dict): Table metadata read from an ECSV header.
    """
    if meta.get("pipeline"):
        lcd.metadata["authors"] = _parse_list_meta(meta["pipeline"])
    if meta.get("method"):
        lcd.metadata["flux_origins"] = _parse_list_meta(meta["method"])
    if meta.get("filter"):
        lcd.metadata.setdefault("photcal", {})
        filter_label = str(meta["filter"])
        lcd.metadata["photcal"][PHOTCAL_KEY_FILTER_NAME] = filter_label
        lcd.metadata["photcal"][PHOTCAL_KEY_FILTER_IDENTIFIER] = filter_label
    for key in ("ra", "dec", "period", "name"):
        if meta.get(key) is not None:
            lcd.metadata[key] = meta[key]


def volc_to_curvedash(volc: VOLightCurve, filename: str, preserve_photcal: bool = True):
    """Converts a VOLightCurve instance into a CurveDash instance.

    Resolves columns, reconstructs absolute Julian dates from ``obs_time`` and
    ``TIMESYS/@timeorigin`` (MJD + offset), and stores photometry in its native
    domain (magnitude or flux) without conversion.

    Args:
        volc (VOLightCurve): The parsed Virtual Observatory lightcurve.
        filename (str): The name of the uploaded file.
        preserve_photcal (bool): When false, skip PhotCal restoration (tabular uploads).

    Returns:
        CurveDash: The populated CurveDash instance.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    time_cols = get_time_colnames(volc)
    if not time_cols:
        for name in ['obs_time', 'time', 'jd', 'mjd']:
            if name in volc.table.colnames:
                time_cols = [name]
                break
    if not time_cols:
        raise ValueError("No time column found in the uploaded file.")

    time_col = time_cols[0]
    jd_absolute = _absolute_jd_from_time_column(volc, time_col)

    phot_col = _resolve_photometry_column(volc)
    if not phot_col:
        raise ValueError("No photometry (flux or magnitude) column found in the uploaded file.")

    phot_vals = volc[phot_col]
    if hasattr(phot_vals, 'value'):
        phot_vals = phot_vals.value

    meta = volc.table.meta or {}
    is_mag = (
        phot_col == "mag"
        or (phot_col == "phot" and is_magnitude_phot_column(volc.table, phot_col))
        or is_mag_column(volc.table, phot_col)
    )
    photcal_meta = _extract_photcal_meta(volc, phot_col) if preserve_photcal else {}

    err_col = _resolve_photometry_error_column(volc, phot_col)

    if err_col:
        err_vals = volc[err_col]
        if hasattr(err_vals, 'value'):
            err_vals = err_vals.value
    else:
        err_vals = np.zeros_like(phot_vals)

    label_col = None
    for name in ['label', 'sector', 'flag']:
        if name in volc.table.colnames:
            label_col = name
            break
    if label_col:
        label_vals = volc[label_col]
        if hasattr(label_vals, 'value'):
            label_vals = label_vals.value
    else:
        label_vals = None
        sectors_meta = _parse_list_meta(meta.get('sectors'))
        if sectors_meta and len(sectors_meta) == 1:
            try:
                sector_id = int(sectors_meta[0])
                label_vals = np.full(len(phot_vals), sector_id, dtype=np.uint8)
            except ValueError:
                label_vals = None
    target_name = meta.get('name') or Path(filename).stem
    if target_name.startswith("TESS_"):
        target_name = target_name[5:]

    if "lookup_name" in meta:
        lookup_name = meta.get("lookup_name") or ""
    else:
        lookup_name = target_name

    absolute_epoch = None
    if meta.get("epoch") is not None:
        try:
            absolute_epoch = normalise_table_epoch_to_absolute_jd(volc, meta.get("epoch"))
        except ValueError as exc:
            raise PipeException(str(exc)) from exc

    common_kwargs = dict(
        name=target_name,
        lookup_name=lookup_name,
        jd=jd_absolute,
        label=label_vals,
        time_unit="d",
        timescale=volc.timesys.timescale.lower(),
        photcal=photcal_meta,
        period=meta.get('period'),
        epoch=absolute_epoch,
        period_unit="d",
    )

    if is_mag:
        lcd = CurveDash(
            **common_kwargs,
            mag=phot_vals,
            mag_err=err_vals,
            mag_unit=str(volc.table[phot_col].unit or "mag"),
            active_domain=DOMAIN_MAG,
        )
    else:
        lcd = CurveDash(
            **common_kwargs,
            flux=phot_vals,
            flux_err=err_vals,
            flux_unit=str(volc.table[phot_col].unit or ""),
            active_domain=DOMAIN_FLUX,
        )

    lcd.metadata['ra'] = meta.get('ra')
    lcd.metadata['dec'] = meta.get('dec')
    for key in ("facility_name", "instrument_name", "lookup_name", "ztf_oid", "user_search_target"):
        if key in meta:
            lcd.metadata[key] = meta.get(key)
    lcd.metadata[METADATA_KEY_VO_ENVELOPE] = _extract_vo_envelope_meta(volc, filename=filename)
    for key in ('authors', 'sectors', 'flux_origins'):
        if key in meta:
            lcd.metadata[key] = _parse_list_meta(meta[key])
    if not preserve_photcal:
        lcd.metadata['photcal'] = {}
        _apply_tabular_meta_to_curvedash(lcd, meta)
    if absolute_epoch is not None:
        lcd.epoch = absolute_epoch
    if meta.get('stitched') in (True, 'true', 'True', '1', 1):
        lcd.metadata['stitched'] = True
        lcd.metadata['photcal'] = _strip_zero_points_from_photcal(lcd.metadata.get('photcal'))
    for key in ('cutout_source', 'mask_mode'):
        if key in meta:
            lcd.metadata[key] = meta[key]
    if meta.get('cutout_source') or meta.get('mask_mode'):
        from skvo_veb.utils.mission_config import tess as tess_mission

        tess_mission.apply_upload_cutout_metadata(lcd)
        title = tess_mission.build_cutout_title(lcd)
    else:
        envelope = lcd.metadata.get(METADATA_KEY_VO_ENVELOPE) or {}
        title = envelope.get(VO_ENVELOPE_KEY_LIGHTCURVE_TITLE) or build_curvedash_title(lcd)
    lcd.title = title
    lcd.metadata['title'] = title

    return lcd


def valid_photometry_row_mask(lcd) -> np.ndarray:
    """Returns rows with meaningful photometry in the lightcurve's active domain.

    Only the primary photometry column (``flux`` or ``mag``) is evaluated. Rows
    with masked, null, or non-finite photometry are excluded. Missing or invalid
    uncertainty values do not affect retention.

    Args:
        lcd (CurveDash): Application lightcurve instance.

    Returns:
        numpy.ndarray: Boolean mask — ``True`` where the row should be kept.

    Raises:
        PipeException: When the lightcurve is empty or the photometry column is missing.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash) or lcd.lightcurve is None:
        raise PipeException("Cannot evaluate photometry rows on an empty CurveDash instance.")

    phot_col = "mag" if lcd.active_domain == DOMAIN_MAG else "flux"
    if phot_col not in lcd.lightcurve.columns:
        raise PipeException(
            f"Active domain {lcd.active_domain!r} is missing expected column {phot_col!r}."
        )

    series = lcd.lightcurve[phot_col]
    if len(series) == 0:
        return np.array([], dtype=bool)

    raw = series.to_numpy()
    array_mask = (
        np.ma.getmaskarray(raw)
        if isinstance(raw, np.ma.MaskedArray)
        else np.zeros(len(raw), dtype=bool)
    )
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    return (~array_mask) & np.isfinite(numeric)


def curvedash_to_table(lcd) -> Table:
    """Extracts a standards-oriented Astropy Table from a CurveDash instance.

    Strips application-only columns (``selected``, ``perm_index``, ``phase``) and
    maps the active photometric domain to ``obs_time``, ``phot``, and ``flux_error``.
    ``obs_time`` is written in Modified Julian Date (MJD = JD - ``JD_TO_MJD``);
    the VOTable ``TIMESYS/@timeorigin`` must carry the same offset.

    Args:
        lcd (CurveDash): Application lightcurve state container.

    Returns:
        astropy.table.Table: Clean table suitable for ``write_vo_lightcurve``.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash) or lcd.lightcurve is None:
        raise PipeException('Cannot export an empty CurveDash instance.')

    keep = valid_photometry_row_mask(lcd)
    if not keep.any():
        raise PipeException(
            "Cannot export: no rows with valid photometry in the active domain."
        )

    t_out = Table()
    t_out['obs_time'] = lcd.jd.values[keep] - JD_TO_MJD
    t_out['phot'] = lcd.phot.values[keep]
    if lcd.phot_err is not None:
        t_out['flux_error'] = lcd.phot_err.values[keep]

    if lcd.label is not None and 'label' in lcd.lightcurve.columns:
        t_out['label'] = lcd.lightcurve['label'].values[keep]

    phot_unit = lcd.phot_unit
    if phot_unit:
        try:
            t_out['phot'].unit = u.Unit(phot_unit)
            if 'flux_error' in t_out.colnames:
                t_out['flux_error'].unit = u.Unit(phot_unit)
        except ValueError:
            logger.warning('Could not assign photometric unit %s during export.', phot_unit)

    meta_export = {}
    if lcd.metadata:
        for key in (
            'ra', 'dec', 'period', 'sectors', 'flux_origins', 'authors', 'name',
            'cutout_source', 'mask_mode', 'flux_correction',
        ):
            if lcd.metadata.get(key) is not None:
                meta_export[key] = lcd.metadata[key]
        exported_epoch = export_absolute_jd_as_time_offset(
            lcd.metadata.get("epoch"),
            timeorigin=JD_TO_MJD,
        )
        if exported_epoch is not None:
            meta_export["epoch"] = exported_epoch
        if lcd.metadata.get('stitched'):
            meta_export['stitched'] = 'true'
    if lcd.title:
        meta_export['title'] = lcd.title
    elif lcd.name:
        meta_export['name'] = lcd.name
    if meta_export:
        t_out.meta = meta_export

    assign_photometry_column_semantics(
        t_out,
        force_magnitude=(lcd.active_domain == DOMAIN_MAG),
    )
    return t_out


def apply_phot_domain_view(lcd, show_magnitude: bool) -> None:
    """Converts the stored lightcurve to flux or magnitude view in place.

    Args:
        lcd (CurveDash): Cached lightcurve to mutate.
        show_magnitude (bool): When true, convert to magnitude domain.
    """
    if show_magnitude:
        lcd.convert_to_mag()
    else:
        lcd.convert_to_flux()


def curvedash_to_tabular_table(lcd) -> Table:
    """Builds a plain tabular export table with JD and active photometry columns.

    Omits application-only columns (``phase``, ``selected``, ``perm_index``).

    Args:
        lcd (CurveDash): Application lightcurve state container.

    Returns:
        astropy.table.Table: Data columns suitable for CSV, DAT, or ECSV export.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash) or lcd.lightcurve is None:
        raise PipeException('Cannot export an empty CurveDash instance.')

    keep = valid_photometry_row_mask(lcd)
    if not keep.any():
        raise PipeException(
            "Cannot export: no rows with valid photometry in the active domain."
        )

    tab = Table()
    tab['jd'] = lcd.jd.values[keep]
    tab['phot'] = lcd.phot.values[keep]
    if lcd.phot_err is not None:
        tab['flux_error'] = lcd.phot_err.values[keep]

    phot_unit = lcd.phot_unit
    if phot_unit:
        try:
            unit = u.mag if lcd.active_domain == DOMAIN_MAG else u.Unit(phot_unit)
            tab['phot'].unit = unit
            if 'flux_error' in tab.colnames:
                tab['flux_error'].unit = unit
        except (ValueError, u.UnitsError, u.UnitTypeError):
            logger.warning('Could not assign photometric units during tabular export.')

    if lcd.label is not None and 'label' in lcd.lightcurve.columns:
        tab['label'] = lcd.lightcurve['label'].values[keep]

    assign_photometry_column_semantics(
        tab,
        force_magnitude=(lcd.active_domain == DOMAIN_MAG),
    )
    return tab


def _build_ecsv_metadata(lcd) -> dict:
    """Selects basic descriptive metadata for ECSV header export.

    PhotCal zero points are intentionally excluded; only the filter name is kept.

    Args:
        lcd (CurveDash): Application lightcurve state container.

    Returns:
        dict: ECSV YAML header metadata.
    """
    meta = lcd.metadata or {}
    header = {}
    name = (
        meta.get('lookup_name')
        or lcd.lookup_name
        or meta.get('name')
        or lcd.name
        or lcd.title
    )
    if name and str(name).lower() != 'none':
        header['name'] = name
    for key in ('ra', 'dec', 'period', 'epoch'):
        if meta.get(key) is not None:
            header[key] = meta[key]
    filter_name = (meta.get("photcal") or {}).get(PHOTCAL_KEY_FILTER_NAME)
    if filter_name:
        header["filter"] = filter_name
    authors = _parse_list_meta(meta.get('authors'))
    if authors:
        header['pipeline'] = ', '.join(str(a) for a in authors)
    methods = _parse_list_meta(meta.get('flux_origins'))
    if methods:
        header['method'] = ', '.join(str(m) for m in methods)
    return header


def export_file_extension(table_format: str) -> str:
    """Returns the download filename extension for an export format identifier.

    Args:
        table_format (str): Export format value from the UI or ``export_curvedash``.

    Returns:
        str: File extension without a leading dot.
    """
    if is_votable_export_format(table_format):
        return "vot"
    from skvo_veb.utils.curve_dash import CurveDash

    return CurveDash.get_file_extension(table_format)


_VOTABLE_EXPORT_BUILDERS = {
    "tess": ("skvo_veb.utils.mission_config.tess", "build_archive_votable_kwargs"),
    "cutout": ("skvo_veb.utils.mission_config.tess", "build_cutout_votable_kwargs"),
    "asassn": ("skvo_veb.utils.mission_config.asassn", "build_votable_kwargs"),
}


def _extract_vo_envelope_meta(volc: VOLightCurve, *, filename: str) -> dict:
    """Captures TIMESYS and VOTable envelope fields for later mission-blind export.

    Ingested ``TIMESYS/@timeorigin`` is stored as ``source_timeorigin`` for
    provenance only. Export always writes ``obs_time`` in MJD via
    ``curvedash_to_table`` and therefore uses ``JD_TO_MJD`` as ``timeorigin``.

    Args:
        volc (VOLightCurve): Parsed provider fetch product.
        filename (str): Bridge filename stem used during ingest.

    Returns:
        dict: JSON-serialisable envelope metadata for ``CurveDash.metadata``.
    """
    table_meta = volc.table.meta or {}
    envelope: dict[str, str | float] = {}

    timesys = volc.timesys
    if timesys is not None:
        if timesys.timescale:
            envelope["timescale"] = str(timesys.timescale).upper()
        if timesys.refposition:
            envelope["refposition"] = str(timesys.refposition).upper()
        if timesys.timeorigin is not None:
            envelope["source_timeorigin"] = float(timesys.timeorigin)

    table_name = table_meta.get("lightcurve_title") or table_meta.get("name") or table_meta.get("ID")
    if table_name and str(table_name).strip():
        title_text = str(table_name).strip()
    else:
        title_text = sanitize_filename(Path(filename).stem)
    envelope[VO_ENVELOPE_KEY_TABLE_NAME] = title_text
    envelope[VO_ENVELOPE_KEY_LIGHTCURVE_TITLE] = title_text

    description = table_meta.get("description")
    if description and str(description).strip():
        text = str(description).strip()
        envelope[VO_ENVELOPE_KEY_TABLE_DESCRIPTION] = text
        envelope[VO_ENVELOPE_KEY_VOTABLE_DESCRIPTION] = text

    publication_id = table_meta.get("bibcode") or table_meta.get("publication_id")
    if publication_id and str(publication_id).strip():
        envelope[VO_ENVELOPE_KEY_PUBLICATION_ID] = str(publication_id).strip()

    for key in ("facility_name", "instrument_name"):
        if key in table_meta:
            envelope[key] = table_meta.get(key)

    creator = table_meta.get("creator")
    if creator:
        envelope["creator"] = str(creator)

    coosys = volc.coosys
    if coosys is not None and coosys.system:
        envelope["coosys_id"] = str(coosys.coosys_id or "system")
        envelope["coosys_system"] = str(coosys.system)
        if coosys.epoch is not None:
            envelope["coosys_epoch"] = coosys.epoch

    return envelope


def build_votable_kwargs_from_metadata(lcd) -> dict:
    """Builds ``write_vo_lightcurve`` kwargs from ingested ``CurveDash`` metadata.

    Used by mission-agnostic pages (e.g. Lightcurve Discovery) where fetch already
    produced a VO-compliant product and export must not select a mission profile.

    ``curvedash_to_table`` always serialises ``obs_time`` in Modified Julian Date
    (MJD). The exported ``TIMESYS/@timeorigin`` is therefore always ``JD_TO_MJD``,
    independent of the archive's native offset stored in
    ``metadata['vo_envelope']['source_timeorigin']``.

    Args:
        lcd (CurveDash): Application lightcurve with ``metadata['photcal']`` and
            ``metadata['vo_envelope']`` populated by ``volc_to_curvedash``.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.

    Raises:
        PipeException: When mandatory photometric metadata is missing.
    """
    meta = lcd.metadata or {}
    envelope = dict(meta.get(METADATA_KEY_VO_ENVELOPE) or {})
    photcal = meta.get("photcal") or {}

    filter_identifier = photcal.get(PHOTCAL_KEY_FILTER_IDENTIFIER)
    if not filter_identifier:
        raise PipeException(
            "Cannot export VOTable: missing filter_identifier in CurveDash photcal metadata. "
            "Re-load the lightcurve from the archive provider."
        )

    is_stitched = _is_stitched_lightcurve(lcd)
    include_zero_points = (
        photcal.get(PHOTCAL_KEY_ZP_FLUX) is not None
        and photcal.get(PHOTCAL_KEY_ZP_MAG) is not None
        and not is_stitched
    )
    photcal_fields = _photcal_group_to_votable_fields(
        photcal,
        include_zero_points=include_zero_points,
    )

    table_name = envelope.get(VO_ENVELOPE_KEY_TABLE_NAME) or envelope.get(VO_ENVELOPE_KEY_LIGHTCURVE_TITLE)
    if not table_name:
        table_name = sanitize_filename(lcd.title or lcd.name or "lightcurve")

    description = (
        envelope.get(VO_ENVELOPE_KEY_TABLE_DESCRIPTION)
        or envelope.get(VO_ENVELOPE_KEY_VOTABLE_DESCRIPTION)
    )
    if not description or not str(description).strip():
        raise PipeException(
            "Cannot export VOTable: missing lightcurve table description in metadata. "
            "Re-load the lightcurve from the archive provider."
        )

    kwargs = {
        "table_name": str(table_name),
        "filter_identifier": filter_identifier,
        "refposition": envelope.get("refposition") or "BARYCENTER",
        "timescale": envelope.get("timescale") or str(meta.get("timescale") or "TCB").upper(),
        "timeorigin": JD_TO_MJD,
        "table_description": str(description).strip(),
        "votable_description": str(
            envelope.get(VO_ENVELOPE_KEY_VOTABLE_DESCRIPTION) or description
        ).strip(),
        "ra": meta.get("ra"),
        "dec": meta.get("dec"),
        "period": meta.get("period"),
        "epoch": export_absolute_jd_as_time_offset(
            meta.get("epoch"),
            timeorigin=JD_TO_MJD,
        ),
        **photcal_fields,
    }

    publication_id = envelope.get(VO_ENVELOPE_KEY_PUBLICATION_ID)
    if publication_id:
        kwargs["publication_id"] = str(publication_id)

    creator = envelope.get("creator")
    if creator:
        kwargs["creator"] = creator

    coosys_system = envelope.get("coosys_system")
    if coosys_system:
        kwargs["coosys_id"] = envelope.get("coosys_id") or "system"
        kwargs["coosys_system"] = str(coosys_system)
        if envelope.get("coosys_epoch") is not None:
            kwargs["coosys_epoch"] = envelope["coosys_epoch"]

    for key in ("facility_name", "instrument_name"):
        if key in meta:
            kwargs[key] = meta.get(key)
        elif key in envelope:
            kwargs[key] = envelope.get(key)

    return kwargs


def _votable_kwargs_for_profile(lcd, profile: str | None) -> dict:
    """Resolves ``write_vo_lightcurve`` kwargs for a named or metadata export path.

    Args:
        lcd (CurveDash): Application lightcurve state container.
        profile (str, optional): Legacy export profile name (``tess``, ``cutout``,
            ``asassn``). When ``None``, kwargs are assembled from ingested metadata.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.

    Raises:
        PipeException: If ``profile`` is set but not registered.
    """
    if profile is None:
        return build_votable_kwargs_from_metadata(lcd)

    import importlib

    spec = _VOTABLE_EXPORT_BUILDERS.get(profile)
    if spec is None:
        supported = ", ".join(sorted(_VOTABLE_EXPORT_BUILDERS))
        raise PipeException(
            f"Unsupported VOTable export profile '{profile}'. "
            f"Supported profiles: {supported}."
        )
    module_name, func_name = spec
    mod = importlib.import_module(module_name)
    return getattr(mod, func_name)(lcd)


def export_curvedash(lcd, table_format: str, profile: str | None = None) -> bytes:
    """Exports a CurveDash instance to the requested file format.

    VOTable export uses ``write_vo_lightcurve``. When ``profile`` is ``None``,
    kwargs are rebuilt from ingested ``metadata`` (mission-blind round-trip). Legacy
    pages pass ``profile='tess'``, ``'cutout'``, or ``'asassn'`` for bespoke rules.

    Args:
        lcd (CurveDash): Application lightcurve state container.
        table_format (str): Target format identifier (e.g. ``'votable_binary'``, ``'ascii.ecsv'``).
        profile (str, optional): Legacy export profile for VOTable. Omit for metadata-driven export.

    Returns:
        bytes: Serialised file content.

    Raises:
        PipeException: If the format or profile is unsupported.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash):
        raise PipeException('export_curvedash expects a CurveDash instance.')

    if table_format not in EXPORT_FORMATS and table_format != "votable":
        raise PipeException(
            f"Unsupported export format '{table_format}'. "
            f"Supported formats: {', '.join(EXPORT_FORMATS)}"
        )

    if is_votable_export_format(table_format):
        kwargs = _votable_kwargs_for_profile(lcd, profile)
        kwargs['binary'] = votable_binary_encoding(table_format)
        buf = io.BytesIO()
        write_vo_lightcurve(
            output_stream_or_path=buf,
            table_data=curvedash_to_table(lcd),
            **kwargs,
        )
        return buf.getvalue()

    tab = curvedash_to_tabular_table(lcd)
    if table_format == 'ascii.ecsv':
        tab.meta = _build_ecsv_metadata(lcd)
    else:
        tab.meta = {}

    text_formats = {'ascii.ecsv', 'csv', 'ascii.commented_header'}
    buf = io.StringIO() if table_format in text_formats else io.BytesIO()
    tab.write(buf, format=table_format, overwrite=True)
    payload = buf.getvalue()
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    return payload


def _is_stitched_lightcurve(lcd) -> bool:
    """Detects whether a lightcurve was produced by sector stitching.

    Stitching applies arithmetic normalisation across sectors, so pipeline
    photometric zero points are no longer valid for the combined flux scale.

    Args:
        lcd (CurveDash): Application lightcurve state container.

    Returns:
        bool: True if the curve is stitched.
    """
    meta = lcd.metadata or {}
    if meta.get('stitched') in (True, 'true', 'True', '1', 1):
        return True
    title = meta.get('title') or getattr(lcd, 'title', None) or ''
    return str(title).startswith('Stitched curve')


def main():
    from skvo_veb.logging_config import configure_logging

    configure_logging()
    # filename = 'data/ASAS19pm/ASas19pm.DAT'
    # lc = vo.VOLightCurve(file_path=filename)
    # print(lc)
    for filename in [
        # 'data/lc_tess_HD182144_TIC_406949643_sector__40_author__SPOC_methods__pdcsap.vot',
        # 'data/OGLE-SMC-CEP-0325-I.vot',
        # 'data/6009363278148078848-G.vot',
        # 'data/AY_Lac-R.vot',
        # 'data/g2_jk.vot',
        # 'data/my_g3.vot',
        'data/ASAS19pm/ASas19pm.dat'
    ]:
        logger.info('Ingesting %s', filename)

        lc1 = ingest_volightcurve_file(filename, Path(filename).name)
        logger.info('%s', lc1)
        json_str = pack_volc_to_json(lc1)
        pretty_print_lc_json(json_str)


if __name__ == "__main__":
    main()
