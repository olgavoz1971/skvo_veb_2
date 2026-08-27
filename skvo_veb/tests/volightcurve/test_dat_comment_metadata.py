"""Tests for ``.dat`` comment-line metadata (JD0, FILTER, column header)."""

from __future__ import annotations

import io
import json

import pytest

from skvo_veb.utils.lc_bridge import (
    ingest_lightcurve_file,
    ingest_volightcurve_file,
    pack_volc_to_json,
)
from skvo_veb.utils.lc_config import (
    PHOTCAL_KEY_FILTER_IDENTIFIER,
    PHOTCAL_KEY_FILTER_NAME,
    PHOTCAL_KEY_ZP_FLUX,
    PHOTCAL_KEY_ZP_MAG,
)


def _sample_dat() -> bytes:
    return b"""# JD0 = 2400000.5
# FILTER = Gaia/GAIA3.G
# jd mag mag_err
52500.1 12.3 0.01
52501.2 12.4 0.01
"""


def test_dat_upload_reads_filter_from_comment_line():
    """FILTER= in a ``#`` comment is applied to photcal on GP/bridge upload."""
    volc = ingest_volightcurve_file(io.BytesIO(_sample_dat()), "curve.dat")
    assert volc.table.colnames[:3] == ["jd", "mag", "mag_err"]
    assert volc.timesys.timeorigin == 2400000.5
    assert volc.table.meta.get("filter") == "Gaia/GAIA3.G"

    packet = json.loads(pack_volc_to_json(volc))
    photcal = packet["meta"]["photcal"]
    assert photcal[PHOTCAL_KEY_FILTER_IDENTIFIER] == "Gaia/GAIA3.G"
    assert photcal[PHOTCAL_KEY_FILTER_NAME] == "Gaia/GAIA3.G"


def test_dat_epoch_stored_absolute_jd_mjd_ui_offset():
    """Ingest uses file JD0; UI epoch field uses MJD (``DEFAULT_EPOCH_JD``), same as time axis."""
    from skvo_veb.utils.lc_bridge import volc_to_curvedash
    from skvo_veb.utils.lc_config import DEFAULT_EPOCH_JD, display_epoch_offset

    dat = b"""# JD0=2400000
# EPOCH=58738.0
# jd phot flux_error
58738.68 1.0 0.1
"""
    volc = ingest_volightcurve_file(io.BytesIO(dat), "e.dat")
    lcd = volc_to_curvedash(volc, "e.dat")
    assert lcd.epoch == pytest.approx(58738.0 + 2400000.0)
    assert display_epoch_offset(lcd.epoch, DEFAULT_EPOCH_JD) == pytest.approx(58737.5)


def test_dat_upload_tess_votable_export_includes_filter_identifier():
    """Tabular ``.dat`` ingest must supply ``filter_identifier`` for TESS VOTable download."""
    from skvo_veb.utils.lc_bridge import export_curvedash
    from skvo_veb.utils.lc_config import VOTABLE_FORMAT_BINARY

    dat = b"""# JD0=2400000
# FILTER=VV
# jd phot flux_error
58738.68 6752.18 3.18
58738.70 6004.79 3.09
"""
    lcd = ingest_lightcurve_file(io.BytesIO(dat), "user.dat")
    assert lcd.metadata["photcal"][PHOTCAL_KEY_FILTER_IDENTIFIER] == "VV"

    payload = export_curvedash(lcd, VOTABLE_FORMAT_BINARY, profile="tess")
    assert b"VV" in payload
    assert b"filterIdentifier" in payload


def test_dat_mag0_reaches_curvedash_photcal():
    """``# MAG0=`` on a ``.dat`` file must survive ``ingest_lightcurve_file``."""
    from skvo_veb.utils.lc_bridge import photcal_from_metadata

    dat = b"""# JD0=2400000
# MAG0=10.0
# jd mag mag_err
59853.35869 0.112 0.003
59853.36101 0.052 0.002
"""
    lcd = ingest_lightcurve_file(io.BytesIO(dat), "curve.dat")
    photcal = lcd.metadata.get("photcal") or {}
    assert photcal.get(PHOTCAL_KEY_ZP_MAG) == pytest.approx(10.0)
    assert photcal.get(PHOTCAL_KEY_ZP_FLUX) == pytest.approx(1.0)
    pc = photcal_from_metadata(photcal)
    assert float(pc.zp_mag.value) == pytest.approx(10.0)
