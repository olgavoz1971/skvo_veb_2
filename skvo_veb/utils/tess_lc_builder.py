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
from skvo_veb.utils.mission_config.tess import TESS_TIMEORIGIN, archive_flux_unit_for_pipeline, resolve_photcal
from skvo_veb.utils.tess_flux_column_registry import (
    FLUX_METHOD_DEFAULT,
    apply_flux_column_selection,
    build_flux_radio_options,
    default_flux_option_label,
    merge_flux_radio_options,
    parse_sector_from_mission_label,
    resolve_default_flux_origin,
    storage_flux_unit_for_selection,
)

logger = logging.getLogger(__name__)


def _tess_mag_from_lightkurve_list(lc_list) -> float | None:
    """Collects a single ``TESSMAG`` reference from downloaded Lightkurve products.

    QLP (and related) pipelines store target catalogue magnitude in FITS header
    metadata as ``TESSMAG``. When several sectors are combined unstitched, values
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


def _resolve_flux_unit(authors, flux_methods, is_background_flags, lc_list, stitch: bool) -> str:
    """Chooses a serialised flux-unit label for the combined light curve.

    Args:
        authors (list): Pipeline author tags per sector.
        flux_methods (list): Flux selection per sector (may repeat).
        is_background_flags (list): Whether each sector uses a background column.
        lc_list (list): Downloaded Lightkurve products.
        stitch (bool): Whether sectors were stitched.

    Returns:
        str: Flux unit string for ``CurveDash`` metadata.
    """
    from skvo_veb.utils.tess_flux_column_registry import UNIT_DIMENSIONLESS

    if stitch:
        return "relative flux"

    if len(set(flux_methods)) == 1 and flux_methods[0] == FLUX_METHOD_DEFAULT:
        if len(set(authors)) == 1:
            return archive_flux_unit_for_pipeline(authors, lc_list[0].flux.unit)
        return UNIT_DIMENSIONLESS

    if len(set(is_background_flags)) == 1 and is_background_flags[0]:
        return storage_flux_unit_for_selection(authors[0], flux_methods[0])
    if len(set(authors)) == 1 and len(set(flux_methods)) == 1:
        if flux_methods[0] == FLUX_METHOD_DEFAULT:
            return archive_flux_unit_for_pipeline(authors, lc_list[0].flux.unit)
        return storage_flux_unit_for_selection(authors[0], flux_methods[0])
    if len(set(authors)) == 1:
        return archive_flux_unit_for_pipeline(authors, lc_list[0].flux.unit)
    raise PipeException(
        "Cannot combine sectors with different flux-column selections across mixed "
        "pipeline authors; use author default flux or select a single sector."
    )


def create_lc_from_selected_rows(
    selected_rows,
    table_data,
    stitch,
    flux_method,
    metadata,
    phase_view=False,
    period=None,
    epoch=None,
    search_store=None,
) -> str:
    """Builds a serialised CurveDash payload from selected TESS search rows.

    Downloads Lightkurve lightcurves for the selected table rows, optionally
    stitches them, and stores the result in flux domain without domain conversion.

    Args:
        selected_rows: Selected AgGrid row indices or row dicts.
        table_data: Full AgGrid row data when indices are supplied.
        stitch (bool): Whether to stitch sectors into one continuous curve.
        flux_method (str): ``default``, ``background``, or a registry flux column name.
        metadata (dict): Target metadata including optional ``lookup_name``.
        phase_view (bool, optional): Initial folded-view flag.
        period (float, optional): Variability period in days.
        epoch (float, optional): Reference epoch Julian date.
        search_store: Serialised Tess search result for cache recovery.

    Returns:
        str: JSON serialisation of the constructed ``CurveDash`` instance.

    Raises:
        PipeException: If no rows are selected or search data is missing.
    """
    if not selected_rows:
        raise PipeException('Search for the lightcurves first and try again')
    if isinstance(selected_rows[0], dict):
        selected_data = selected_rows
    else:
        if not table_data:
            raise PipeException('Search for the lightcurves first and try again')
        selected_data = [table_data[i] for i in selected_rows]

    if len(selected_data) > 1:
        flux_method = FLUX_METHOD_DEFAULT

    full_search = tess_lc_search.restore_search_result(search_store) if search_store else None

    lc_list = []
    authors = []
    sectors = []
    flux_origins = []
    flux_methods_applied = []
    is_background_flags = []

    for row in selected_data:
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

        sectors.append(str(sector if sector is not None else getattr(lc, "SECTOR", "")))
        authors.append(author)
        flux_origins.append(flux_origin)
        flux_methods_applied.append(flux_method)
        is_background_flags.append(is_background)
        lc_list.append(lc)

    if stitch:
        lc_res = lk.LightCurveCollection(lc_list).stitch()
        jd = lc_res.time.value
        flux = lc_res.flux.value
        flux_err = lc_res.flux_err.value
        sector_array = np.concatenate([
            np.full(len(lc_item), lc_item.SECTOR, dtype=np.uint8)
            for lc_item in lc_list
        ])
        flux_unit = 'relative flux'
    else:
        jd = np.array([], dtype=float)
        flux = np.array([], dtype=float)
        flux_err = np.array([], dtype=float)
        sector_array = np.array([], dtype=np.uint8)
        for lc_item in lc_list:
            flux = np.concatenate([flux, lc_item.flux.value])
            flux_err = np.concatenate([flux_err, lc_item.flux_err.value])
            jd = np.concatenate([jd, lc_item.time.value])
            sector_array = np.concatenate([
                sector_array,
                np.full_like(lc_item.time.value, fill_value=lc_item.SECTOR, dtype=np.uint8),
            ])
        flux_unit = _resolve_flux_unit(
            authors, flux_methods_applied, is_background_flags, lc_list, stitch=False
        )

    tess_mag = _tess_mag_from_lightkurve_list(lc_list)
    photcal_meta = resolve_photcal(authors, stitched=stitch, tess_mag=tess_mag)

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
    if stitch:
        lcd.metadata['stitched'] = True

    title = (
        f'{lcd.lookup_name} {lc_list[0].LABEL} sector: {",".join(sectors)} '
        f'author: {",".join(authors)} methods: {",".join(flux_origins)}'
    )
    if stitch:
        title = 'Stitched curve ' + title
    lcd.title = title
    lcd.metadata['title'] = title

    return lcd.serialize()


def effective_flux_method_for_selection(selected_rows, table_data, flux_method: str) -> str:
    """Returns the flux column choice applied when building a light curve.

    Multi-row downloads always use the author default flux; a prior single-row
    radio selection must not carry over.

    Args:
        selected_rows: Selected AgGrid row indices or row dicts.
        table_data: Full AgGrid row data when indices are supplied.
        flux_method (str): Current flux radio value.

    Returns:
        str: Flux method passed to ``create_lc_from_selected_rows``.
    """
    if not selected_rows:
        return flux_method
    if isinstance(selected_rows[0], dict):
        count = len(selected_rows)
    elif table_data:
        count = len(selected_rows)
    else:
        count = 1
    if count > 1:
        return FLUX_METHOD_DEFAULT
    return flux_method


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
    if len(per_row_options) == 1:
        return per_row_options[0]
    return merge_flux_radio_options(per_row_options)
