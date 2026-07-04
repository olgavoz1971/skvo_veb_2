import io
import json
import logging
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
    is_votable_export_format,
    votable_binary_encoding,
)
from skvo_veb.utils.my_tools import PipeException, sanitize_filename
from skvo_veb.volightcurve import (
    VOLightCurve,
    get_time_colnames,
    get_flux_colnames,
    get_mag_colnames,
    get_error_colnames,
    is_mag_column,
    write_vo_lightcurve,
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

# Shared JS Logic for Dash Client-side Callbacks
# todo: this is a stub
JS_CODE = """
window.photUtils = {
    magToFlux: (mag, zp_mag, zp_flux) => zp_flux * Math.pow(10, -0.4 * (mag - zp_mag)),
    fluxToMag: (flux, zp_mag, zp_flux) => zp_mag - 2.5 * Math.log10(flux / zp_flux)
};
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


def ingest_lightcurve_file(file_source, filename: str):
    """Ingests an uploaded lightcurve file into a ``CurveDash`` instance.

    VOTable files retain PhotCal metadata; tabular formats (ECSV, CSV, DAT) restore
    only the basic metadata stored in the file header (ECSV) or column data alone.

    Args:
        file_source (str or file-like): Path or open binary stream.
        filename (str): Original upload filename used for format detection.

    Returns:
        CurveDash: Parsed application lightcurve state.
    """
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in ("vot", "xml"):
        volc = read_to_volc(file_source)
        return volc_to_curvedash(volc, filename, preserve_photcal=True)

    tabular_formats = {
        "ecsv": "ascii.ecsv",
        "csv": "csv",
        "dat": "ascii.commented_header",
    }
    if ext in tabular_formats:
        if hasattr(file_source, "seek"):
            file_source.seek(0)
        table = Table.read(file_source, format=tabular_formats[ext])
        return tabular_table_to_curvedash(table, filename)

    volc = read_to_volc(file_source)
    return volc_to_curvedash(volc, filename, preserve_photcal=False)


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

    if "flux" in table.colnames:
        phot_col, is_mag = "flux", False
    elif "mag" in table.colnames:
        phot_col, is_mag = "mag", True
    elif "phot" in table.colnames:
        phot_col, is_mag = "phot", False
    else:
        raise ValueError("No photometry column found in the uploaded tabular file.")

    err_col = "flux_err" if phot_col == "flux" else "mag_err"
    if err_col not in table.colnames and phot_col == "flux" and "flux_error" in table.colnames:
        err_col = "flux_error"
    if err_col in table.colnames:
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

    # Photometry Calibration Extraction
    photdm = lc.photdms.get(primary_col)
    photcal = photdm.photcal if photdm else None

    photcal_meta = {
        "zp_flux": photcal.zp_flux.value if photcal else 1.0,
        "zp_flux_unit": photcal.zp_flux.unit.to_string('vounit') if photcal else '',
        "zp_mag": photcal.zp_mag.value if photcal else 0.0,
        "zp_mag_unit": photcal.zp_mag.unit.to_string('vounit') if photcal else '',
        "mag_sys": photcal.mag_sys if photcal else 'Unknown'
    }

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
    struct = {
        "schema": {
            "time": time_col,
            "value": primary_col,
            "error": error_col,  # None if missing
            "flag": flag_col,  # None if missing
        },
        "data": [list(row) for row in zip(t, v, e, f)],
        "meta": {
            "active_domain": "mag" if primary_col in mag_cols else "flux",
            "jd0": lc.timesys.jd0,
            "photcal": photcal_meta
        }
    }

    return json.dumps(struct, cls=LCEncoder)


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

    # apply JD0
    jd0 = meta.get('jd0', 0)
    if jd0:
        t += jd0

    # Domain Logic
    current_domain = meta['active_domain']
    y_data = v
    e_data = e

    if view_mode != current_domain:
        zp_m = photcal['zp_mag']
        # todo: !!!!!!!!!
        # zp_m = 5.0
        zp_f = photcal['zp_flux']

        if view_mode == 'flux' and current_domain == 'mag':
            # Mag -> Flux
            y_data = zp_f * 10**(-0.4 * (v - zp_m))
            if has_err:
                # sigma_f = f * 0.921 * sigma_m
                e_data = y_data * 0.921034 * e

        elif view_mode == 'mag' and current_domain == 'flux':
            # Flux -> Mag (Safeguard against zero/negative flux)
            mask = v > 0
            y_data = np.full_like(v, np.nan)
            y_data[mask] = zp_m - 2.5 * np.log10(v[mask] / zp_f)

            if has_err:
                e_data = np.full_like(e, np.nan)
                e_data[mask] = 1.085736 * (e[mask] / v[mask])

    return {
        'x': t,
        'y': y_data,
        'err': e_data,
        'flag': f,
        'x_label': "Julian Date (JD)",
        'y_label': "Magnitude" if view_mode == 'mag' else "Flux",
        'is_mag': (view_mode == 'mag')
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
        phi_min (float): Minimum phase selection bound (between 0.0 and 1.0).
        phi_max (float): Maximum phase selection bound (between 0.0 and 1.0).
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
        print("Error: Input is not a valid JSON string.")
        return

    schema = packet.get("schema", {})
    meta = packet.get("meta", {})
    photcal = meta.get("photcal", {})
    data = packet.get("data", [])

    print("=" * 80)
    print(f"{'VOLightCurve JSON Transport Package':^80}")
    print("=" * 80)

    # 1. Metadata Section
    print(f"PRIMARY DOMAIN: {meta.get('active_domain', 'Unknown').upper()}")
    print(f"JD0 (Offset):   {meta.get('jd0', 'N/A')}")
    print(f"CALIBRATION:    Sys: {photcal.get('mag_sys', 'N/A')}")
    print(f"                ZP Mag:  {photcal.get('zp_mag')} {photcal.get('zp_mag_unit')}")
    print(f"                ZP Flux: {photcal.get('zp_flux')} {photcal.get('zp_flux_unit')}")
    print("-" * 80)

    # 2. Schema Section
    print("SCHEMA / COLUMN MAPPING:")
    for key, colname in schema.items():
        # Display "[Not Provided]" if the colname is None/Null
        label = colname if colname else "[Not Provided]"
        print(f"  {key:10} -> {label}")
    print("-" * 80)

    # 3. Data Summary Section
    total_rows = len(data)
    print(f"DATA ({total_rows} rows):")

    # Clean Headers: Use the actual column name or a placeholder if missing
    h_time = schema.get('time') or "Time"
    h_val = schema.get('value') or "Value"
    h_err = schema.get('error') or "Error"
    h_flag = schema.get('flag') or "Flag"

    headers = [h_time, h_val, h_err, h_flag]
    # Increased width to 18 to handle long JDs and names
    print(f"  {' | '.join([f'{h:^18}' for h in headers])}")
    print(f"  {'-' * 78}")

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

    # Rows (head and tail)
    if total_rows > (max_rows * 2):
        for row in data[:max_rows]:
            print(f"  {format_row(row)}")

        divider = [". . ."] * 4
        print(f"  {' | '.join([f'{d:^18}' for d in divider])}")

        for row in data[-max_rows:]:
            print(f"  {format_row(row)}")
    else:
        for row in data:
            print(f"  {format_row(row)}")

    print("=" * 80)


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


def _extract_photcal_meta(volc: VOLightCurve, phot_col: str) -> dict:
    """Extracts photometric calibration metadata from a VOLightCurve column.

    Args:
        volc (VOLightCurve): Parsed lightcurve container.
        phot_col (str): Primary photometry column name.

    Returns:
        dict: Serialisable zero-point metadata for CurveDash storage.
    """
    photdm = volc.photdms.get(phot_col)
    photcal = photdm.photcal if photdm else None
    return {
        "zp_flux": photcal.zp_flux.value if photcal else 1.0,
        "zp_flux_unit": photcal.zp_flux.unit.to_string("vounit") if photcal else "Jy",
        "zp_mag": photcal.zp_mag.value if photcal else 0.0,
        "zp_mag_unit": photcal.zp_mag.unit.to_string("vounit") if photcal else "mag",
        "mag_sys": photcal.mag_sys if photcal else "Unknown",
    }


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

    Args:
        volc (VOLightCurve): Parsed lightcurve container.

    Returns:
        str or None: Column name for flux or magnitude values.
    """
    if "phot" in volc.table.colnames:
        return "phot"
    flux_cols = get_flux_colnames(volc)
    mag_cols = get_mag_colnames(volc)
    if flux_cols:
        return flux_cols[0]
    if mag_cols:
        return mag_cols[0]
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
    if "flux_error" in volc.table.colnames:
        return "flux_error"
    if phot_col == "flux" and "flux_err" in volc.table.colnames:
        return "flux_err"
    if phot_col == "mag" and "mag_err" in volc.table.colnames:
        return "mag_err"
    if is_mag_column(volc.table, phot_col):
        error_cols = volc.get_mag_error_colnames()
        return error_cols[0] if error_cols else None
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
        lcd.metadata["filter"] = meta["filter"]
    for key in ("ra", "dec", "period", "epoch", "name"):
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
    is_mag = phot_col == 'mag' or is_mag_column(volc.table, phot_col)
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

    common_kwargs = dict(
        name=target_name,
        lookup_name=target_name,
        jd=jd_absolute,
        label=label_vals,
        time_unit="d",
        timescale=volc.timesys.timescale.lower(),
        photcal=photcal_meta,
        period=meta.get('period'),
        epoch=meta.get('epoch'),
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
    for key in ('authors', 'sectors', 'flux_origins'):
        if key in meta:
            lcd.metadata[key] = _parse_list_meta(meta[key])
    if not preserve_photcal:
        lcd.metadata['photcal'] = {}
        _apply_tabular_meta_to_curvedash(lcd, meta)
    if meta.get('stitched') in (True, 'true', 'True', '1', 1):
        lcd.metadata['stitched'] = True
        lcd.metadata['photcal'] = {}
    for key in ('cutout_source', 'mask_mode'):
        if key in meta:
            lcd.metadata[key] = meta[key]
    if meta.get('cutout_source') or meta.get('mask_mode'):
        lcd.metadata['photcal'] = {}
        title = build_cutout_title(lcd)
    else:
        title = build_curvedash_title(lcd)
    lcd.title = title
    lcd.metadata['title'] = title

    return lcd


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

    t_out = Table()
    t_out['obs_time'] = lcd.jd.values - JD_TO_MJD
    t_out['phot'] = lcd.phot.values
    if lcd.phot_err is not None:
        t_out['flux_error'] = lcd.phot_err.values

    if lcd.label is not None and 'label' in lcd.lightcurve.columns:
        t_out['label'] = lcd.lightcurve['label'].values

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
            'ra', 'dec', 'period', 'epoch', 'sectors', 'flux_origins', 'authors', 'name',
            'cutout_source', 'mask_mode', 'flux_correction',
        ):
            if lcd.metadata.get(key) is not None:
                meta_export[key] = lcd.metadata[key]
        if lcd.metadata.get('stitched'):
            meta_export['stitched'] = 'true'
    if lcd.title:
        meta_export['title'] = lcd.title
    elif lcd.name:
        meta_export['name'] = lcd.name
    if meta_export:
        t_out.meta = meta_export

    return t_out


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

    tab = Table()
    tab['jd'] = lcd.jd.values
    if lcd.active_domain == DOMAIN_MAG:
        tab['mag'] = lcd.phot.values
        if lcd.phot_err is not None:
            tab['mag_err'] = lcd.phot_err.values
        if lcd.phot_unit:
            try:
                tab['mag'].unit = u.mag
                tab['mag_err'].unit = u.mag
            except ValueError:
                logger.warning('Could not assign magnitude units during tabular export.')
    else:
        tab['flux'] = lcd.phot.values
        if lcd.phot_err is not None:
            tab['flux_err'] = lcd.phot_err.values
        phot_unit = lcd.phot_unit
        if phot_unit:
            try:
                tab['flux'].unit = u.Unit(phot_unit)
                tab['flux_err'].unit = u.Unit(phot_unit)
            except ValueError:
                logger.warning('Could not assign flux units during tabular export.')

    if lcd.label is not None and 'label' in lcd.lightcurve.columns:
        tab['label'] = lcd.lightcurve['label'].values

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
    name = meta.get('name') or lcd.name or lcd.title
    if name:
        header['name'] = name
    for key in ('ra', 'dec', 'period', 'epoch'):
        if meta.get(key) is not None:
            header[key] = meta[key]
    filter_name = meta.get('filter') or meta.get('filter_name')
    if filter_name:
        header['filter'] = filter_name
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


def export_curvedash(lcd, table_format: str, profile: str | None = None) -> bytes:
    """Exports a CurveDash instance to the requested file format.

    VOTable uses ``write_vo_lightcurve`` with mission profiles. ECSV stores basic
    metadata in the header; CSV and commented-header DAT export data columns only.

    Args:
        lcd (CurveDash): Application lightcurve state container.
        table_format (str): Target format identifier (e.g. ``'votable_binary'``, ``'ascii.ecsv'``).
        profile (str, optional): Export profile name (``'tess'`` or ``'cutout'`` for VOTable).

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
        if profile == 'tess':
            kwargs = _build_tess_votable_kwargs(lcd)
        elif profile == 'cutout':
            kwargs = _build_cutout_votable_kwargs(lcd)
        else:
            raise PipeException(
                f"Unsupported VOTable export profile '{profile}'. "
                "Use profile='tess' or profile='cutout'."
            )
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


def resolve_cutout_mask_mode(auto_mask, mask_type: str | None) -> str:
    """Maps UI mask controls to a descriptive mask mode label.

    Args:
        auto_mask: Truthy when automatic mask generation is enabled.
        mask_type (str, optional): ``'pipeline'`` or ``'threshold'`` when auto mask is on.

    Returns:
        str: One of ``'handmade'``, ``'threshold'``, or ``'pipeline'``.
    """
    if not auto_mask:
        return 'handmade'
    if mask_type == 'pipeline':
        return 'pipeline'
    return 'threshold'


def build_cutout_title(lcd) -> str:
    """Builds a display title for user cutout lightcurves.

    Args:
        lcd (CurveDash): Cutout lightcurve with cutout metadata populated.

    Returns:
        str: Title string for Plotly figures and export metadata.
    """
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash):
        return 'TESS cutout lightcurve'

    meta = lcd.metadata or {}
    stored = meta.get('title') or lcd.title
    if stored:
        return stored

    parts = []
    source = meta.get('cutout_source') or meta.get('pixel_type')
    if source:
        parts.append(str(source).upper())

    lookup = meta.get('lookup_name') or ''
    name = meta.get('name') or ''
    if lookup:
        parts.append(str(lookup))
    if name and str(name) != str(lookup):
        parts.append(str(name))

    sectors = _parse_list_meta(meta.get('sectors'))
    if sectors:
        parts.append(f"sector:{','.join(sectors)}")

    mask_mode = meta.get('mask_mode')
    if mask_mode:
        parts.append(f"mask:{mask_mode}")

    parts.append('user cutout')
    return ' '.join(parts) if parts else 'TESS cutout lightcurve'


def enrich_cutout_curvedash(lcd, pixel_metadata: dict, sector, mask_mode: str, ra=None, dec=None):
    """Attaches cutout-specific metadata to a CurveDash instance.

    User cutout photometry is uncalibrated; ``photcal`` is cleared and the pipeline
    author is tagged as ``user`` for VOTable export.

    Args:
        lcd (CurveDash): Newly constructed cutout lightcurve.
        pixel_metadata (dict): Sector download metadata (``pixel_type``, ``lookup_name``, etc.).
        sector (int or str): TESS sector number.
        mask_mode (str): ``handmade``, ``threshold``, or ``pipeline``.
        ra (float, optional): Target right ascension in degrees.
        dec (float, optional): Target declination in degrees.

    Returns:
        CurveDash: The same instance with metadata and title populated.
    """
    from skvo_veb.utils import tess_config
    from skvo_veb.utils.curve_dash import CurveDash

    if not isinstance(lcd, CurveDash):
        raise PipeException('enrich_cutout_curvedash expects a CurveDash instance.')

    lcd.metadata['photcal'] = {}
    lcd.metadata['authors'] = [tess_config.CUTOUT_PIPELINE_AUTHOR]
    lcd.metadata['sectors'] = [str(sector)]
    lcd.metadata['cutout_source'] = str(pixel_metadata.get('pixel_type', 'TPF')).upper()
    lcd.metadata['mask_mode'] = mask_mode
    if ra is not None:
        lcd.metadata['ra'] = ra
    if dec is not None:
        lcd.metadata['dec'] = dec

    title = build_cutout_title(lcd)
    lcd.title = title
    lcd.metadata['title'] = title
    return lcd


def _build_cutout_votable_kwargs(lcd) -> dict:
    """Builds keyword arguments for uncalibrated TESS cutout VOTable export.

    FFI and TPF cutout photometry is aperture-based and uncalibrated; zero points
    are never written. Source type and mask mode are recorded in descriptions.

    Args:
        lcd (CurveDash): Cutout lightcurve with ``cutout_source`` and ``mask_mode`` metadata.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.
    """
    from skvo_veb.utils import tess_config

    meta = lcd.metadata or {}
    tic_id = lcd.name or lcd.lookup_name or "Unknown Target"
    source = str(meta.get('cutout_source') or meta.get('pixel_type') or 'unknown').upper()
    mask_mode = meta.get('mask_mode', 'unknown')
    sectors = _parse_list_meta(meta.get('sectors')) or []
    sectors_str = ", ".join(sectors) if sectors else "unknown"
    flux_correction = meta.get('flux_correction') or ''
    processing_note = f" Processing applied: {flux_correction}." if flux_correction else ""

    calibration_note = (
        " Photometry is uncalibrated aperture summation; "
        "photometric zero points are omitted from the PhotCal group."
    )
    desc_core = (
        f"Uncalibrated TESS cutout lightcurve for target {tic_id}. "
        f"Data source: {source}. Aperture mask mode: {mask_mode}. "
        f"Sector: {sectors_str}. Pipeline: {tess_config.CUTOUT_PIPELINE_AUTHOR}."
        f"{processing_note}"
    )

    return {
        "table_name": f"TESS_cutout_{sanitize_filename(tic_id)}",
        "filter_identifier": tess_config.TESS_FILTER_IDENTIFIER,
        "refposition": tess_config.TESS_REFPOSITION,
        "timescale": tess_config.TESS_TIMESCALE,
        "timeorigin": JD_TO_MJD,
        "votable_description": desc_core + calibration_note,
        "table_description": desc_core + calibration_note,
        "creator": f"TESS {tess_config.CUTOUT_PIPELINE_AUTHOR} cutout",
        "zero_point_flux": None,
        "zero_point_ref_mag": None,
        "effective_wavelength": tess_config.TESS_EFFECTIVE_WAVELENGTH.to(u.m).value,
        "effective_wavelength_unit": "m",
        "ra": meta.get('ra'),
        "dec": meta.get('dec'),
        "filter_name": "TESS",
        "period": meta.get('period'),
        "epoch": meta.get('epoch'),
        "binary": True,
    }


def _build_tess_votable_kwargs(lcd) -> dict:
    """Builds keyword arguments for TESS-profile VOTable export.

    Args:
        lcd (CurveDash): Application lightcurve with TESS metadata.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.
    """
    from skvo_veb.utils import tess_config

    authors = lcd.metadata.get('authors', [])
    if not authors and lcd.metadata.get('author'):
        authors = [lcd.metadata.get('author')]
    pipeline_str = ", ".join(_parse_list_meta(authors) or []) if authors else "Unknown"
    is_spoc = tess_config.is_spoc_pipeline(authors)
    is_stitched = _is_stitched_lightcurve(lcd)
    include_zero_points = is_spoc and not is_stitched
    tic_id = lcd.name or lcd.lookup_name or "Unknown Target"

    sectors = _parse_list_meta(lcd.metadata.get('sectors')) or []
    flux_origins = _parse_list_meta(lcd.metadata.get('flux_origins')) or []
    methods_str = ", ".join(dict.fromkeys(flux_origins)) if flux_origins else "unknown"
    sectors_str = ", ".join(sectors) if sectors else "unknown"

    calibration_note = (
        " Photometric zero points are omitted because sector stitching invalidates "
        "pipeline flux calibration."
        if is_stitched
        else ""
    )

    return {
        "table_name": f"TESS_{sanitize_filename(tic_id)}",
        "filter_identifier": tess_config.TESS_FILTER_IDENTIFIER,
        "refposition": tess_config.TESS_REFPOSITION,
        "timescale": tess_config.TESS_TIMESCALE,
        "timeorigin": JD_TO_MJD,
        "votable_description": (
            f"TESS space telescope lightcurve for target {tic_id}, "
            f"processed via the {pipeline_str} pipeline. "
            f"Photometry method(s): {methods_str}."
            f"{calibration_note}"
        ),
        "table_description": (
            f"Photometric time-series observations of {tic_id} from the TESS mission. "
            f"Data produced by the {pipeline_str} pipeline. "
            f"Sectors: {sectors_str}. Photometry method(s): {methods_str}."
            f"{calibration_note}"
        ),
        "creator": f"TESS {pipeline_str} Pipeline",
        "zero_point_flux": tess_config.TESS_SPOC_ZERO_POINT_FLUX if include_zero_points else None,
        "zero_point_ref_mag": tess_config.TESS_SPOC_ZERO_POINT_REF_MAG if include_zero_points else None,
        "effective_wavelength": tess_config.TESS_EFFECTIVE_WAVELENGTH.to(u.m).value,
        "effective_wavelength_unit": "m",
        "ra": lcd.metadata.get('ra'),
        "dec": lcd.metadata.get('dec'),
        "filter_name": "TESS",
        "period": lcd.metadata.get('period'),
        "epoch": lcd.metadata.get('epoch'),
        "binary": True,
    }


def main():
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
        print(f'\n\n\n Ingesting {filename}')

        lc1 = read_to_volc(filename)
        print(lc1)
        json_str = pack_volc_to_json(lc1)
        pretty_print_lc_json(json_str)


if __name__ == "__main__":
    main()
