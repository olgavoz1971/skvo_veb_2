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


def test_reconcile_does_not_invent_missing_zero_points():
    """An incomplete photcal stays incomplete and the warning names the gap."""
    from skvo_veb.utils.photcal_coherence import reconcile_photcal_dict

    photcal, warnings = reconcile_photcal_dict({"zp_flux": 3.0}, flux_unit=None)
    assert "zp_mag" not in photcal or photcal["zp_mag"] is None
    assert photcal["zp_flux"] == 3.0
    assert len(warnings) == 1
    assert "zp_mag" in warnings[0]
    assert "Nothing was assumed" in warnings[0]


def test_fill_button_uses_the_suggested_values():
    """The explicit fill action offers Vega, magnitude 0 and relative flux 1."""
    out = fill_missing_photcal_form_values(
        {"filter_name": "", "zp_flux": None, "zp_mag": None, "mag_sys": ""}
    )
    assert (out["zp_flux"], out["zp_mag"], out["mag_sys"]) == (1.0, 0.0, "Vega")
