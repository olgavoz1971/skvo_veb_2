"""The shared export path keeps the source VOTABLE description, table text and INFOs."""

import io
from pathlib import Path

from volightcurve.io import read_lightcurve

from skvo_veb.utils.lc_bridge import (
    export_curvedash,
    ingest_volightcurve_file,
    volc_to_curvedash,
)

_FULL = Path(__file__).parent / "fixtures" / "ogle_lmc_rrlyr_13820_full.vot"
_TABLE_TEXT = "The OGLE lightcurve for OGLE-LMC-RRLYR-13820 in I passband"


def _exported():
    """Runs the Discovery path (ingest, CurveDash, export) and reads the result back.

    Returns:
        VOLightCurve: The exported VOTable parsed again.
    """
    volc = ingest_volightcurve_file(_FULL, _FULL.name)
    lcd = volc_to_curvedash(volc, _FULL.name)
    payload = export_curvedash(lcd, "votable")
    return read_lightcurve(io.BytesIO(payload), filename="exported.vot")


def test_export_keeps_the_votable_level_description():
    """The long survey text from the VOTABLE root is still there, unchanged."""
    out = _exported()
    assert "".join(out.votable_description.split()).startswith(
        "".join("The **Optical Gravitational Lensing Experiment (OGLE)**".split())
    )
    assert "Processing note:" not in out.votable_description


def test_export_table_description_is_source_text_then_note():
    """The table text is the original sentence first and the processing note last."""
    description = _exported().table.meta["description"]
    assert description.startswith(_TABLE_TEXT)
    assert description.index(_TABLE_TEXT) < description.index("Processing note:")


def test_export_keeps_every_info_element():
    """All 19 creators and the legal and rights notices survive the whole path."""
    out = _exported()
    names = [entry["name"] for entry in out.infos]
    assert names.count("creator") == 19
    for required in ("legal", "rights", "publisher", "contact", "ivoid"):
        assert required in names
