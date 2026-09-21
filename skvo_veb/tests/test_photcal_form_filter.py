"""Photcal editor form: filter label round-trip."""

from skvo_veb.utils.lc_config import PHOTCAL_KEY_FILTER_NAME
from skvo_veb.utils.photcal_coherence import (
    apply_photcal_form_values,
    fill_missing_photcal_form_values,
    photcal_form_values_from_storage,
)


def test_photcal_form_reads_filter_from_metadata():
    """Filter label is loaded from ``metadata['photcal']`` when present."""
    vals = photcal_form_values_from_storage(
        {PHOTCAL_KEY_FILTER_NAME: "Gaia G"},
        flux_unit=None,
    )
    assert vals["filter_name"] == "Gaia G"


def test_fill_missing_does_not_invent_filter():
    """Fill missing defaults never sets the filter field."""
    out = fill_missing_photcal_form_values(
        {
            "filter_name": "",
            "zp_flux": None,
            "zp_mag": None,
            "mag_sys": "",
        }
    )
    assert out["filter_name"] == ""


def test_apply_photcal_form_writes_filter_name():
    """Apply stores a non-empty filter label in photcal metadata."""
    photcal, _flux_unit, _warnings = apply_photcal_form_values(
        filter_name="TESS",
        zp_flux=1.0,
        zp_flux_unit="",
        zp_mag=0.0,
        mag_sys="Vega",
        flux_unit="",
        existing_photcal={PHOTCAL_KEY_FILTER_NAME: "old"},
    )
    assert photcal[PHOTCAL_KEY_FILTER_NAME] == "TESS"
