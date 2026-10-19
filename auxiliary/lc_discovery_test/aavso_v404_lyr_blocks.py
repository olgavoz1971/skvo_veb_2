"""Download AAVSO photometry for V404 Lyr and split it by observer and filter.

Anonymous VSX ``api.delim`` dump is kept as the original file. Split products
are ``volightcurve`` ``.dat`` files. Uncorrected blocks keep original AAVSO JD
as MJD (``JD0 = 2400000.5``). Two further trees apply Astropy light-travel
time to barycentric MJD, once treating the dump as geocentric/topocentric and
once treating it as heliocentric.
"""

from __future__ import annotations

import csv
import logging
import re
from collections import defaultdict
from pathlib import Path

import astropy.units as u
import numpy as np
import requests
from astropy.coordinates import EarthLocation, SkyCoord, solar_system_ephemeris
from astropy.table import Table
from astropy.time import Time
from volightcurve import assemble_volightcurve, write_lightcurve

logger = logging.getLogger(__name__)

STAR_QUERY = "V404 Lyr"
STAR_LABEL = "V0404 Lyr"
AAVSO_DELIM_URL = "https://vsx.aavso.org/index.php"
USER_AGENT = (
    "Mozilla/5.0 (compatible; lc_discovery-aavso-split/1.0; research download)"
)
OUT_ROOT = Path(__file__).resolve().parent / "data" / "v404_lyr_aavso"
ORIGINAL_DIR = OUT_ROOT / "original"
BLOCKS_DIR = OUT_ROOT / "blocks"
BLOCKS_BJD_FROM_TOPO_DIR = OUT_ROOT / "blocks_bjd_from_topocentric"
BLOCKS_BJD_FROM_HELIO_DIR = OUT_ROOT / "blocks_bjd_from_heliocentric"
SIMBAD_NAME = "V0404 Lyr"
GEOCENTER = EarthLocation.from_geocentric(0.0, 0.0, 0.0, unit=u.m)
JD0 = 2400000.5
PERIOD_DAY = 0.730943
EPOCH_JD = 2454954.2625
ZP_MAG = 10.0
ZP_FLUX = 1.0
MAG_SYS = "Vega"
QUALITY_FIELDS = ("val", "transformed", "fainterThan", "obsType", "mtype")


def download_aavso_delim(destination: Path) -> Path:
    """Downloads the anonymous VSX delimited photometry table.

    Args:
        destination (Path): Output CSV path.

    Returns:
        Path: The written file.

    Raises:
        requests.HTTPError: If the server returns an error status.
        ValueError: If the body is not a delimited table.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(
        AAVSO_DELIM_URL,
        params={
            "view": "api.delim",
            "ident": STAR_QUERY,
            "fromjd": "2400000",
            "tojd": "2500000",
            "delimiter": ",",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    text = response.text
    if not text.lstrip().startswith("JD,"):
        raise ValueError(
            "AAVSO delim download did not start with a JD header; "
            f"got {text[:120]!r}"
        )
    destination.write_text(text, encoding="utf-8")
    logger.info("Wrote original AAVSO dump %s (%s bytes).", destination, len(text))
    return destination


def _cell(row: dict, key: str) -> str:
    """Returns a stripped cell, treating missing keys as empty.

    Args:
        row (dict): CSV row.
        key (str): Column name.

    Returns:
        str: Stripped text.
    """
    return str(row.get(key) or "").strip()


def _parse_float(text: str) -> float:
    """Parses a numeric AAVSO field, mapping blanks to NaN.

    Args:
        text (str): Cell text.

    Returns:
        float: Value or NaN.
    """
    token = text.strip()
    if token == "" or token.upper() in {"NA", "NAN", "NULL", "-"}:
        return float("nan")
    return float(token)


def _quality_tag(row: dict) -> str:
    """Builds a compact quality label from AAVSO flags.

    Args:
        row (dict): CSV row.

    Returns:
        str: Semicolon-separated key=value list.
    """
    parts = []
    for key in QUALITY_FIELDS:
        parts.append(f"{key}={_cell(row, key)}")
    return ";".join(parts)


def _safe_stem(observer: str, band: str) -> str:
    """Returns a filesystem-safe stem for one observer-filter block.

    Args:
        observer (str): AAVSO observer code.
        band (str): AAVSO band.

    Returns:
        str: Filename stem.
    """
    raw = f"V0404_Lyr_AAVSO_{observer}_{band}"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw)


def load_rows(csv_path: Path) -> list[dict]:
    """Reads the original AAVSO delimited dump.

    Args:
        csv_path (Path): Original CSV.

    Returns:
        list[dict]: Rows.
    """
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def split_rows(rows: list[dict]) -> tuple[dict[tuple[str, str], list[dict]], list[dict]]:
    """Splits rows into (observer, filter) blocks and a trash list.

    Args:
        rows (list[dict]): AAVSO rows.

    Returns:
        tuple: Mapping of blocks, and rows with missing observer or filter.
    """
    blocks: dict[tuple[str, str], list[dict]] = defaultdict(list)
    trash: list[dict] = []
    for row in rows:
        observer = _cell(row, "by")
        band = _cell(row, "band")
        if not observer or not band:
            trash.append(row)
            continue
        try:
            _parse_float(_cell(row, "JD"))
            _parse_float(_cell(row, "mag"))
        except ValueError:
            trash.append(row)
            continue
        blocks[(observer, band)].append(row)
    return blocks, trash


def resolve_star_coordinates() -> SkyCoord:
    """Resolves the star on Simbad through Sesame.

    Returns:
        astropy.coordinates.SkyCoord: ICRS position.

    Raises:
        astropy.coordinates.name_resolve.NameResolveError: If Sesame fails.
    """
    coord = SkyCoord.from_name(SIMBAD_NAME)
    logger.info(
        "Resolved %s at RA=%.8f deg Dec=%.8f deg (ICRS, Sesame/Simbad).",
        SIMBAD_NAME,
        coord.ra.deg,
        coord.dec.deg,
    )
    return coord


def barycentric_mjd(
    jd: np.ndarray,
    skycoord: SkyCoord | None,
    *,
    original: str,
) -> np.ndarray:
    """Converts JD values to barycentric MJD with Astropy light-travel time.

    The observer is the geocentre: the dump has no observatory coordinates.
    No UTC-to-TDB conversion is applied (light time only).

    Args:
        jd (numpy.ndarray): Original Julian Dates.
        skycoord (astropy.coordinates.SkyCoord, optional): Target ICRS
            position; required unless ``original`` is ``none``.
        original (str): ``none``, ``topocentric``, or ``heliocentric``.

    Returns:
        numpy.ndarray: MJD values (JD0 = 2400000.5).

    Raises:
        ValueError: If ``original`` is not a known assumption, or if
            ``skycoord`` is missing when a correction is requested.
    """
    if original == "none":
        return Time(jd, format="jd").mjd
    if skycoord is None:
        raise ValueError("skycoord is required for barycentric conversion.")
    t = Time(jd, format="jd", scale="utc", location=GEOCENTER)
    ltt_bary = t.light_travel_time(
        skycoord, kind="barycentric", location=GEOCENTER
    )
    if original == "topocentric":
        return (t + ltt_bary).mjd
    if original == "heliocentric":
        ltt_helio = t.light_travel_time(
            skycoord, kind="heliocentric", location=GEOCENTER
        )
        return (t + (ltt_bary - ltt_helio)).mjd
    raise ValueError(f"Unknown original time assumption: {original!r}")


def epoch_barycentric_mjd(skycoord: SkyCoord) -> float:
    """Converts the VSX epoch (documented as HJD) to barycentric MJD.

    Args:
        skycoord (astropy.coordinates.SkyCoord): Target ICRS position.

    Returns:
        float: Barycentric MJD of the VSX T0.
    """
    converted = barycentric_mjd(
        np.array([EPOCH_JD], dtype=float),
        skycoord,
        original="heliocentric",
    )
    return float(converted[0])


def _table_from_rows(
    rows: list[dict],
    *,
    include_quality: bool,
    skycoord: SkyCoord | None,
    original: str,
) -> Table:
    """Builds a volightcurve table from one block.

    Args:
        rows (list[dict]): AAVSO rows, one observer and filter.
        include_quality (bool): When True, add a trailing quality column.
        skycoord (astropy.coordinates.SkyCoord, optional): Needed unless
            ``original`` is ``none``.
        original (str): Time-origin assumption for the dump.

    Returns:
        astropy.table.Table: Columns ``mjd``, ``mag``, ``mag_err``, ``observer``
        and optional ``quality``.
    """
    jd = np.array([_parse_float(_cell(r, "JD")) for r in rows], dtype=float)
    mjd = barycentric_mjd(jd, skycoord, original=original)
    mag = np.array([_parse_float(_cell(r, "mag")) for r in rows], dtype=float)
    mag_err = np.array([_parse_float(_cell(r, "uncert")) for r in rows], dtype=float)
    observer = np.array([_cell(r, "by") for r in rows], dtype=object)
    order = np.argsort(mjd)
    data = {
        "mjd": mjd[order],
        "mag": mag[order],
        "mag_err": mag_err[order],
        "observer": observer[order],
    }
    if include_quality:
        quality = np.array([_quality_tag(r) for r in rows], dtype=object)
        data["quality"] = quality[order]
    return Table(data)


def _constant_quality_comments(rows: list[dict]) -> list[str]:
    """Returns metadata lines when quality flags are constant in the block.

    Args:
        rows (list[dict]): Block rows.

    Returns:
        list[str]: Comment lines.
    """
    tags = {_quality_tag(r) for r in rows}
    if len(tags) != 1:
        return []
    tag = next(iter(tags))
    return [f"AAVSO quality (constant in this block): {tag}"]


def _time_comments(
    *,
    original: str,
    skycoord: SkyCoord | None,
    epoch_mjd: float,
) -> list[str]:
    """Builds header lines that state the time system.

    Args:
        original (str): Dump time assumption.
        skycoord (astropy.coordinates.SkyCoord, optional): Target position.
        epoch_mjd (float): EPOCH keyword value.

    Returns:
        list[str]: Comment lines.
    """
    comments = [
        "Times: original AAVSO JD converted to MJD with astropy.time "
        f"(JD0 = {JD0}). No timescale was attached (AAVSO does not state it); "
        "treated as UTC-like for the conversion."
    ]
    if original == "none":
        comments.append(
            "Assumed topocentric; barycentric light-time correction not applied."
        )
        comments.append(
            f"PERIOD and EPOCH from VSX ({STAR_LABEL}): P = {PERIOD_DAY} d, "
            f"T0 = JD {EPOCH_JD} (written as MJD {epoch_mjd} to match the "
            "time column; VSX documents this epoch as HJD, left unconverted here)."
        )
        return comments
    if skycoord is None:
        raise ValueError("skycoord is required for barycentric metadata.")
    ra = skycoord.ra.to_string(unit=u.hourangle, precision=3, pad=True)
    dec = skycoord.dec.to_string(unit=u.deg, precision=2, alwayssign=True, pad=True)
    ephem = solar_system_ephemeris.get()
    comments.append(
        f"Star position: {SIMBAD_NAME} ICRS {ra} {dec} "
        f"(RA={skycoord.ra.deg:.8f} deg, Dec={skycoord.dec.deg:.8f} deg) "
        "from Sesame/Simbad. Proper motion not applied."
    )
    comments.append(
        "Observer location: geocentre (EarthLocation.from_geocentric(0,0,0)). "
        "AAVSO rows have no observatory coordinates, so a true topocentric "
        "correction is not possible; the Earth-radius light time is about 21 ms."
    )
    comments.append(
        "Light-travel time: astropy.time.Time.light_travel_time "
        f"(ephemeris={ephem!r}). UTC was not converted to TDB."
    )
    if original == "topocentric":
        comments.append(
            "Assumption: original AAVSO JD is geocentric/topocentric. "
            "Barycentric MJD = original + barycentric light-travel time."
        )
    elif original == "heliocentric":
        comments.append(
            "Assumption: original AAVSO JD is heliocentric (HJD). "
            "Barycentric MJD = original + (barycentric - heliocentric) "
            "light-travel time."
        )
    comments.append(
        f"PERIOD from VSX ({STAR_LABEL}): P = {PERIOD_DAY} d. "
        f"EPOCH is the VSX T0 JD {EPOCH_JD} (documented as HJD) converted to "
        f"barycentric MJD {epoch_mjd} with the same heliocentric-to-barycentric "
        "light-travel time, so it matches the time column."
    )
    return comments


def write_block_file(
    rows: list[dict],
    *,
    path: Path,
    observer: str,
    band: str,
    extra_comments: list[str],
    original: str = "none",
    skycoord: SkyCoord | None = None,
    epoch_mjd: float | None = None,
) -> None:
    """Writes one observer-filter block as a volightcurve ``.dat`` file.

    Args:
        rows (list[dict]): Photometry rows.
        path (Path): Output path.
        observer (str): Observer code.
        band (str): AAVSO band, used as FILTER.
        extra_comments (list[str]): Narrative header lines.
        original (str): Dump time assumption (``none``, ``topocentric``,
            ``heliocentric``).
        skycoord (astropy.coordinates.SkyCoord, optional): Target position.
        epoch_mjd (float, optional): EPOCH keyword; default is unconverted VSX MJD.
    """
    quality_tags = {_quality_tag(r) for r in rows}
    include_quality = len(quality_tags) > 1
    table = _table_from_rows(
        rows,
        include_quality=include_quality,
        skycoord=skycoord,
        original=original,
    )
    if epoch_mjd is None:
        epoch_mjd = float(Time(EPOCH_JD, format="jd").mjd)
    comments = list(extra_comments)
    comments.append(f"Star: {STAR_LABEL} (AAVSO ident {STAR_QUERY}).")
    comments.append(f"AAVSO observer code: {observer}.")
    comments.append(f"AAVSO band (FILTER): {band}.")
    comments.extend(
        _time_comments(original=original, skycoord=skycoord, epoch_mjd=epoch_mjd)
    )
    comments.append(
        "Source: anonymous VSX api.delim dump of the AAVSO International Database."
    )
    comments.extend(_constant_quality_comments(rows))
    if include_quality:
        comments.append(
            "Quality flags vary inside this block; see the quality column "
            "(val, transformed, fainterThan, obsType, mtype)."
        )
    volc = assemble_volightcurve(
        table,
        timeorigin=JD0,
        period=PERIOD_DAY,
        epoch=epoch_mjd,
        filter_id=band,
        filter_name=band,
        zp_flux=ZP_FLUX,
        zp_flux_unit=None,
        zp_mag=ZP_MAG,
        zp_mag_unit="mag",
        mag_sys=MAG_SYS,
        free_comments=comments,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_lightcurve(volc, "ascii.commented_header", destination=path)
    logger.info("Wrote %s rows=%s", path.name, len(rows))


def write_split_tree(
    rows: list[dict],
    out_dir: Path,
    *,
    original: str,
    skycoord: SkyCoord | None,
    epoch_mjd: float | None,
) -> None:
    """Writes one observer-filter tree, including the trash file.

    Args:
        rows (list[dict]): Full AAVSO dump.
        out_dir (Path): Output directory.
        original (str): Dump time assumption.
        skycoord (astropy.coordinates.SkyCoord, optional): Target position.
        epoch_mjd (float, optional): EPOCH keyword for this tree.
    """
    blocks, trash = split_rows(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    for (observer, band), block_rows in sorted(blocks.items()):
        dest = out_dir / f"{_safe_stem(observer, band)}.dat"
        write_block_file(
            block_rows,
            path=dest,
            observer=observer,
            band=band,
            extra_comments=[],
            original=original,
            skycoord=skycoord,
            epoch_mjd=epoch_mjd,
        )
    trash_path = out_dir / "V0404_Lyr_AAVSO_TRASH_missing_observer_or_filter.dat"
    if trash:
        write_block_file(
            trash,
            path=trash_path,
            observer="UNKNOWN",
            band="UNKNOWN",
            extra_comments=[
                "TRASH FILE: rows with missing observer code, missing filter, "
                "or a JD/mag value that is not numeric. Do not use for timing."
            ],
            original=original,
            skycoord=skycoord,
            epoch_mjd=epoch_mjd,
        )
        return
    empty = assemble_volightcurve(
        Table(
            {
                "mjd": np.array([], dtype=float),
                "mag": np.array([], dtype=float),
                "mag_err": np.array([], dtype=float),
                "observer": np.array([], dtype=object),
            }
        ),
        timeorigin=JD0,
        period=PERIOD_DAY,
        epoch=float(
            epoch_mjd
            if epoch_mjd is not None
            else Time(EPOCH_JD, format="jd").mjd
        ),
        filter_id="UNKNOWN",
        zp_flux=ZP_FLUX,
        zp_flux_unit=None,
        zp_mag=ZP_MAG,
        zp_mag_unit="mag",
        mag_sys=MAG_SYS,
        free_comments=[
            "TRASH FILE: no rows had a missing observer or filter in this dump.",
        ],
    )
    write_lightcurve(empty, "ascii.commented_header", destination=trash_path)
    logger.info("Wrote empty trash file %s", trash_path)


def main() -> None:
    """Downloads AAVSO data if needed, keeps the original dump, and writes splits."""
    logging.basicConfig(level=logging.INFO)
    original = ORIGINAL_DIR / "aavso_vsx_api_delim_V404_Lyr.csv"
    if original.is_file():
        logger.info("Reusing existing original dump %s", original)
    else:
        download_aavso_delim(original)
    rows = load_rows(original)
    bands = sorted({_cell(r, "band") for r in rows})
    types = sorted({_cell(r, "obsType") for r in rows})
    logger.info(
        "Original dump rows=%s observers=%s bands=%s obsType=%s",
        len(rows),
        len({_cell(r, "by") for r in rows}),
        bands,
        types,
    )
    if "Vis" not in bands and "Visual" not in bands:
        logger.warning(
            "Anonymous delim dump contains no Visual estimates. "
            "obsType values: %s. Full AID export on apps.aavso.org requires login.",
            types,
        )
    write_split_tree(
        rows,
        BLOCKS_DIR,
        original="none",
        skycoord=None,
        epoch_mjd=None,
    )
    skycoord = resolve_star_coordinates()
    epoch_bjd_mjd = epoch_barycentric_mjd(skycoord)
    logger.info("VSX epoch converted HJD->BJD MJD = %s", epoch_bjd_mjd)
    write_split_tree(
        rows,
        BLOCKS_BJD_FROM_TOPO_DIR,
        original="topocentric",
        skycoord=skycoord,
        epoch_mjd=epoch_bjd_mjd,
    )
    write_split_tree(
        rows,
        BLOCKS_BJD_FROM_HELIO_DIR,
        original="heliocentric",
        skycoord=skycoord,
        epoch_mjd=epoch_bjd_mjd,
    )


if __name__ == "__main__":
    main()
