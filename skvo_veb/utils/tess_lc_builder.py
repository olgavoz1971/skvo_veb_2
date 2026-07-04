"""TESS archive lightcurve builder for the application layer.

Constructs ``CurveDash`` instances from Lightkurve search results. Keeps
Lightkurve-specific ingestion logic out of Dash page callbacks.
"""

import logging
import re

import lightkurve as lk
import numpy as np

from skvo_veb.utils import lightkurve_cache
from skvo_veb.utils import tess_cache as cache
from skvo_veb.utils import tess_lc_search
from skvo_veb.utils.curve_dash import CurveDash
from skvo_veb.utils.lc_config import DOMAIN_FLUX
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.tess_config import TESS_TIMEORIGIN

logger = logging.getLogger(__name__)


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
        flux_method (str): Flux column selector (``'pdcsap'`` or ``'sap'``).
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

    full_search = tess_lc_search.restore_search_result(search_store) if search_store else None

    lc_list = []
    authors = []
    sectors = []
    flux_origins = []

    for row in selected_data:
        row_idx = row['#']
        if full_search is not None:
            lc = lightkurve_cache.download_lightcurve_row_with_recovery(full_search, row_idx)
        else:
            target = f'TIC {row.get("target", None)}'
            author = row["author"]
            exptime = row["exptime"]
            match = re.search(r'Sector (\d+)', row.get('mission', ''))
            sector = int(match.group(1)) if match else -1
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

        if flux_method == 'pdcsap' and 'pdcsap_flux' in lc.columns:
            lc.flux = lc.pdcsap_flux
            flux_origin = flux_method
        elif flux_method == 'sap' and 'sap_flux' in lc.columns:
            lc.flux = lc.sap_flux
            flux_origin = flux_method
        else:
            flux_origin = lc.FLUX_ORIGIN

        sectors.append(str(lc.SECTOR))
        authors.append(lc.AUTHOR)
        flux_origins.append(flux_origin)
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
        flux_unit = str(lc_list[0].flux.unit)

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
    lcd.metadata['authors'] = authors
    lcd.metadata['sectors'] = sectors
    lcd.metadata['flux_origins'] = flux_origins
    if stitch:
        lcd.metadata['stitched'] = True
        lcd.metadata['photcal'] = {}

    title = (
        f'{lcd.lookup_name} {lc_list[0].LABEL} sector: {",".join(sectors)} '
        f'author: {",".join(authors)} methods: {",".join(flux_origins)}'
    )
    if stitch:
        title = 'Stitched curve ' + title
    lcd.title = title
    lcd.metadata['title'] = title

    return lcd.serialize()
