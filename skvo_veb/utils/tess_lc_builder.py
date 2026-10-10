"""TESS archive lightcurve builder for the application layer.

Constructs ``CurveDash`` instances from Lightkurve search results. Keeps
Lightkurve-specific ingestion logic out of Dash page callbacks.
"""

import logging

import lightkurve as lk
import numpy as np

from skvo_veb.utils import lightkurve_cache
from skvo_veb.utils import tess_cache as cache
from skvo_veb.utils import tess_lc_search
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_config import DOMAIN_FLUX
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.mission_config.tess import (
    TESS_TIMEORIGIN,
    archive_flux_unit_for_pipeline,
    attach_tess_archive_export_provenance,
    is_tars_pipeline,
    resolve_photcal,
)
from skvo_veb.utils.tess_flux_column_registry import (
    FLUX_METHOD_DEFAULT,
    apply_flux_column_selection,
    build_flux_radio_options,
    default_flux_option_label,
    parse_sector_from_mission_label,
    resolve_default_flux_origin,
)

logger = logging.getLogger(__name__)


def _tess_mag_from_lightkurve_list(lc_list) -> float | None:
    """Collects a single ``TESSMAG`` reference from downloaded Lightkurve products.

    QLP (and related) pipelines store target catalogue magnitude in FITS header
    metadata as ``TESSMAG``. When several products are concatenated, values
    should agree; a warning is logged when they differ.

    Args:
        lc_list (list): Downloaded Lightkurve lightcurve objects.

    Returns:
        float or None: Reference magnitude for QLP photcal, or ``None`` when absent.
    """
    values: list[float] = []
    for lc in lc_list:
        meta = getattr(lc, "meta", None) or {}
        raw = meta.get("TESSMAG")
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            logger.warning("Invalid TESSMAG in Lightkurve metadata: %r", raw)
    if not values:
        return None
    rounded = {round(v, 6) for v in values}
    if len(rounded) > 1:
        logger.warning(
            "Multiple TESSMAG values across selected sectors %s; using %.6f.",
            values,
            values[0],
        )
    return values[0]


def _header_float(meta: dict, key: str) -> float | None:
    """Reads a finite float from Lightkurve FITS metadata.

    Args:
        meta (dict): Lightkurve ``meta`` mapping.
        key (str): Header keyword.

    Returns:
        float or None: Parsed value, or None when missing or invalid.
    """
    raw = meta.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(value):
        return None
    return value


def _tars_ephemeris_from_lightkurve_list(lc_list) -> tuple[float | None, float | None]:
    """Reads TARS ``PER1`` (days) and ``TMIN1`` (BTJD) as period and absolute JD epoch.

    ``TMIN1`` is the time of first minimum of the sine at ``PER1``, in BTJD.
    The stored epoch is absolute JD (``TMIN1 + TESS_TIMEORIGIN``). The TESS
    page fold field then shows MJD via ``display_epoch_offset``.

    Args:
        lc_list (list): Downloaded Lightkurve products.

    Returns:
        tuple: ``(period_days, epoch_jd)``; either item may be None.
    """
    periods: list[float] = []
    epochs_jd: list[float] = []
    for lc in lc_list:
        meta = getattr(lc, "meta", None) or {}
        period = _header_float(meta, "PER1")
        tmin_btjd = _header_float(meta, "TMIN1")
        if period is not None:
            periods.append(period)
        if tmin_btjd is not None:
            epochs_jd.append(tmin_btjd + TESS_TIMEORIGIN)
    period_out = None
    if periods:
        rounded = {round(v, 8) for v in periods}
        if len(rounded) > 1:
            logger.warning(
                "Multiple TARS PER1 values across selected sectors %s; using %.8f d.",
                periods,
                periods[0],
            )
        period_out = periods[0]
    epoch_out = None
    if epochs_jd:
        rounded_e = {round(v, 8) for v in epochs_jd}
        if len(rounded_e) > 1:
            logger.warning(
                "Multiple TARS TMIN1 values across selected sectors %s; using %.8f JD.",
                epochs_jd,
                epochs_jd[0],
            )
        epoch_out = epochs_jd[0]
    return period_out, epoch_out


def _sector_from_lightcurve(lc, row: dict | None = None) -> int | None:
    """Resolves the TESS sector number for a downloaded light curve.

    Args:
        lc: Lightkurve light curve instance.
        row (dict, optional): AgGrid row used for download when ``lc.SECTOR`` is absent.

    Returns:
        int or None: Sector number when available.
    """
    sector = getattr(lc, "SECTOR", None)
    if sector is not None:
        return int(sector)
    if row is not None:
        return parse_sector_from_mission_label(row.get("mission", ""))
    return None


def create_lc_from_selected_rows(
    selected_rows,
    table_data,
    flux_method,
    metadata,
    phase_view=False,
    period=None,
    epoch=None,
    search_store=None,
) -> str:
    """Builds a serialised CurveDash payload from selected TESS search rows.

    Retrieves the Lightkurve light curve for the single selected table row and
    stores native pipeline flux of that one row; no merging and no domain
    conversion.

    Args:
        selected_rows: One selected AgGrid row index or row dict.
        table_data: Full AgGrid row data when indices are supplied.
        flux_method (str): ``default``, ``background``, or a registry flux column name.
        metadata (dict): Target metadata including optional ``lookup_name``.
        phase_view (bool, optional): Initial folded-view flag.
        period (float, optional): Variability period in days. TARS fills
            ``PER1`` when this is omitted.
        epoch (float, optional): Reference epoch as absolute Julian Date.
            TARS fills ``TMIN1 + TESS_TIMEORIGIN`` when this is omitted; the
            archive page shows that epoch as MJD (``Epoch-{2400000.5}``).
        search_store: Serialised Tess search result for cache recovery.

    Returns:
        str: JSON serialisation of the constructed ``CurveDash`` instance.

    Raises:
        PipeException: If not exactly one row is selected or search data is missing.
    """
    if not selected_rows:
        raise PipeException('Search for the lightcurves first and try again')
    if isinstance(selected_rows[0], dict):
        selected_data = selected_rows
    else:
        if not table_data:
            raise PipeException('Search for the lightcurves first and try again')
        selected_data = [table_data[i] for i in selected_rows]

    if len(selected_data) != 1:
        raise PipeException(
            'Select exactly one search row: each retrieve builds one product.'
        )
    row = selected_data[0]

    full_search = tess_lc_search.restore_search_result(search_store) if search_store else None

    row_idx = row['#']
    if full_search is not None:
        lc = lightkurve_cache.download_lightcurve_row_with_recovery(full_search, row_idx)
    else:
        target = f'TIC {row.get("target", None)}'
        author = row["author"]
        exptime = row["exptime"]
        sector = parse_sector_from_mission_label(row.get('mission', ''))
        if sector is None:
            sector = -1
        args = {
            'target': target,
            'author': author,
            'mission': 'TESS',
            'sector': sector,
            'exptime': exptime,
        }
        search_lcf_refined = cache.load("search_lcf_refined", **args)
        if search_lcf_refined is None:
            search_lcf_refined = lk.search_lightcurve(**args)
            if len(search_lcf_refined) > 0:
                cache.save(search_lcf_refined, "search_lcf_refined", **args)
        lc = lightkurve_cache.download_lightcurve_row_with_recovery(search_lcf_refined, 0)

    author = lc.AUTHOR
    sector = _sector_from_lightcurve(lc, row)
    try:
        flux_origin, is_background = apply_flux_column_selection(
            lc, author, sector, flux_method
        )
    except ValueError as exc:
        raise PipeException(str(exc)) from exc

    lc_list = [lc]
    authors = [author]
    sectors = [str(sector if sector is not None else getattr(lc, "SECTOR", ""))]
    flux_origins = [flux_origin]
    is_background_flags = [is_background]

    jd = np.asarray(lc.time.value, dtype=float)
    flux = np.asarray(lc.flux.value, dtype=float)
    flux_err = np.asarray(lc.flux_err.value, dtype=float)
    sector_array = np.full_like(jd, fill_value=lc.SECTOR, dtype=np.uint8)
    flux_unit = archive_flux_unit_for_pipeline(authors, lc.flux.unit)

    tess_mag = _tess_mag_from_lightkurve_list(lc_list)
    photcal_meta = resolve_photcal(authors, tess_mag=tess_mag)
    tars_period = None
    tars_epoch_jd = None
    if is_tars_pipeline(authors):
        tars_period, tars_epoch_jd = _tars_ephemeris_from_lightkurve_list(lc_list)
        if period is None:
            period = tars_period
        if epoch is None:
            epoch = tars_epoch_jd

    lcd = CurveDash(
        name=lc_list[0].LABEL,
        lookup_name=metadata.get('lookup_name', None),
        jd=jd + TESS_TIMEORIGIN,
        flux=flux,
        flux_err=flux_err,
        label=sector_array,
        time_unit='jd',
        timescale='tdb',
        flux_unit=flux_unit,
        active_domain=DOMAIN_FLUX,
        photcal=photcal_meta,
        folded_view=phase_view,
        period=period,
        epoch=epoch,
        period_unit='d',
    )

    ra_val = getattr(lc_list[0], 'ra', None)
    dec_val = getattr(lc_list[0], 'dec', None)
    if hasattr(ra_val, 'value'):
        ra_val = ra_val.value
    if hasattr(dec_val, 'value'):
        dec_val = dec_val.value

    lcd.metadata['ra'] = ra_val
    lcd.metadata['dec'] = dec_val
    lcd.metadata['mission'] = 'tess'
    lcd.metadata['authors'] = authors
    lcd.metadata['sectors'] = sectors
    lcd.metadata['flux_origins'] = flux_origins
    lcd.metadata['flux_method'] = flux_method
    lcd.metadata['is_background_flux'] = any(is_background_flags)
    if tess_mag is not None:
        lcd.metadata['tess_mag'] = tess_mag
    if tars_period is not None:
        lcd.metadata['tars_period_days'] = tars_period
    if tars_epoch_jd is not None:
        lcd.metadata['tars_epoch_jd'] = tars_epoch_jd

    title = (
        f'{lcd.lookup_name} {lc_list[0].LABEL} sector: {",".join(sectors)} '
        f'author: {",".join(authors)} methods: {",".join(flux_origins)}'
    )
    lcd.title = title
    lcd.metadata['title'] = title
    attach_tess_archive_export_provenance(lcd)

    return lcd.serialize()


def flux_radio_options_for_rows(
    selected_rows,
    table_data,
    search_store=None,
) -> list[dict[str, str]]:
    """Builds flux-selector options for the currently selected search rows.

    Args:
        selected_rows: Selected AgGrid row indices or row dicts.
        table_data: Full AgGrid row data when indices are supplied.
        search_store: Serialised Tess search result for cache recovery.

    Returns:
        list[dict]: Dash RadioItems options with default plus explicit columns.
    """
    if not selected_rows:
        return []

    if isinstance(selected_rows[0], dict):
        selected_data = selected_rows
    else:
        if not table_data:
            return []
        selected_data = [table_data[i] for i in selected_rows]

    full_search = tess_lc_search.restore_search_result(search_store) if search_store else None
    per_row_options: list[list[dict[str, str]]] = []

    for row in selected_data:
        author = row.get("author", "")
        sector = parse_sector_from_mission_label(row.get("mission", ""))
        colnames = None
        default_origin = None
        if full_search is not None:
            try:
                lc = lightkurve_cache.download_lightcurve_row_with_recovery(full_search, row["#"])
                colnames = list(lc.columns)
                default_origin = resolve_default_flux_origin(lc)
            except Exception as exc:
                logger.warning("Could not read columns for flux options: %s", exc)
        if default_origin is None:
            logger.error(
                "Missing default flux column name for author=%r sector=%s; "
                "download the sector file before showing flux options.",
                author,
                sector,
            )
            continue
        try:
            per_row_options.append(
                build_flux_radio_options(
                    author,
                    sector,
                    colnames=colnames,
                    default_origin=default_origin,
                )
            )
        except Exception as exc:
            logger.warning(
                "Flux options fallback for author=%r sector=%s: %s",
                author,
                sector,
                exc,
            )
            per_row_options.append(
                [
                    {
                        "label": default_flux_option_label(default_origin),
                        "value": FLUX_METHOD_DEFAULT,
                    }
                ]
            )

    if not per_row_options:
        return []
    return per_row_options[0]
