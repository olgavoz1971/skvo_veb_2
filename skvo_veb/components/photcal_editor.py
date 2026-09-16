"""Shareable photometric calibration editor layout (Ticket 7 Phase 2).

Pages mount this body under their own collapse or sidebar block. Field ids are
prefixed so Processor, Discovery, and GP can host the same controls without
id clashes. Layout matches Processor Ephemeris: ``InputGroup`` rows. ZP
magnitude unit is always ``mag`` (not editable). Fill / Apply callbacks stay
page-owned.
"""

from __future__ import annotations

import logging

import dash_bootstrap_components as dbc

logger = logging.getLogger(__name__)

# Stable suffixes appended to the page id prefix.
PHOTCAL_FIELD_SUFFIXES: dict[str, str] = {
    "zp_flux": "zp-flux",
    "zp_flux_unit": "zp-flux-unit",
    "zp_mag": "zp-mag",
    "mag_sys": "mag-sys",
    "flux_unit": "flux-unit",
    "fill_missing": "fill-missing",
    "apply": "apply",
}


def photcal_field_ids(id_prefix: str) -> dict[str, str]:
    """Builds Dash component ids for one photcal editor instance.

    Args:
        id_prefix (str): Page-unique prefix, e.g. ``lc-processor-photcal``.

    Returns:
        dict[str, str]: Logical field name → full component id.
    """
    prefix = (id_prefix or "").strip().rstrip("-")
    if not prefix:
        raise ValueError("id_prefix must be a non-empty string")
    return {
        key: f"{prefix}-{suffix}" for key, suffix in PHOTCAL_FIELD_SUFFIXES.items()
    }


def photcal_editor_body(id_prefix: str) -> list:
    """Builds the PhotCal / flux-column unit stack (Ephemeris-style groups).

    ZP magnitude unit is fixed as ``mag`` and is not shown. Includes
    **Fill missing defaults** (empty fields only) and **Apply calibration**.

    Args:
        id_prefix (str): Page-unique prefix for all control ids.

    Returns:
        list: ``InputGroup`` rows plus Fill / Apply buttons.
    """
    ids = photcal_field_ids(id_prefix)
    logger.debug("Building photcal editor body prefix=%s", id_prefix)
    return [
        dbc.InputGroup(
            [
                dbc.InputGroupText("ZP flux"),
                dbc.Input(
                    id=ids["zp_flux"],
                    type="number",
                    step="any",
                    placeholder="Value",
                    className="skvo-photcal-zp-value",
                ),
                dbc.Input(
                    id=ids["zp_flux_unit"],
                    type="text",
                    placeholder="Unit",
                    className="skvo-photcal-zp-unit",
                ),
            ],
            size="sm",
            className="skvo-photcal-zp-flux-group",
        ),
        dbc.InputGroup(
            [
                dbc.InputGroupText("ZP mag"),
                dbc.Input(
                    id=ids["zp_mag"],
                    type="number",
                    step="any",
                    placeholder="Value",
                ),
            ],
            size="sm",
        ),
        dbc.InputGroup(
            [
                dbc.InputGroupText("Mag sys"),
                dbc.Input(
                    id=ids["mag_sys"],
                    type="text",
                    placeholder="Vega or AB",
                ),
            ],
            size="sm",
        ),
        dbc.InputGroup(
            [
                dbc.InputGroupText("Flux column unit"),
                dbc.Input(
                    id=ids["flux_unit"],
                    type="text",
                    placeholder="Blank = dimensionless",
                ),
            ],
            size="sm",
        ),
        dbc.Button(
            "Fill missing defaults",
            id=ids["fill_missing"],
            color="secondary",
            outline=True,
            size="sm",
            className="w-100",
        ),
        dbc.Button(
            "Apply calibration",
            id=ids["apply"],
            color="primary",
            size="sm",
            className="w-100",
        ),
    ]
