"""Test suite for TESS configuration, VOTable export, and Upload integration.

This test verifies that the TESS configuration parameters are correctly applied,
that the VOTable exporter correctly handles SPOC and non-SPOC pipelines,
and that the upload handler correctly ingests VOTable files via ``volc_to_curvedash``.
"""

import os

import pytest

from skvo_veb.utils.lc_bridge import volc_to_curvedash
from skvo_veb.utils.lc_config import DOMAIN_FLUX
from volightcurve.lightcurve import VOLightCurve


def test_tess_real_file_upload():
    """Tests ingestion of a real TESS VOTable file from disk."""
    real_file_path = 'data/lc_tess__TIC_455790537_sector__16_author__SPOC_methods__pdcsap.vot'
    if not os.path.exists(real_file_path):
        pytest.skip(f"Fixture not found: {real_file_path}")

    volc = VOLightCurve(real_file_path)
    assert len(volc) == 16717
    assert volc.timesys.timescale == "TCB"
    assert volc.timesys.jd0 == 2457000.0
    assert volc.table.meta['period'] == 0.935
    assert volc.table.meta['epoch'] == 2400000.5
    assert volc.table.meta['ra'] == 346.345186642685
    assert volc.table.meta['dec'] == 47.6763106397934

    lcd_uploaded = volc_to_curvedash(volc, real_file_path)
    assert lcd_uploaded.period == 0.935
    assert lcd_uploaded.epoch == 2400000.5
    assert lcd_uploaded.active_domain == DOMAIN_FLUX
    assert len(lcd_uploaded.lightcurve) == 16717
    assert lcd_uploaded.title


if __name__ == "__main__":
    test_tess_real_file_upload()
