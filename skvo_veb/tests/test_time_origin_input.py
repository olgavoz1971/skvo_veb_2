"""Tests of the upload rule for relative times without a declared origin."""

import io
import json

import numpy as np
import pytest

from skvo_veb.utils.gp.ingest import pack_uploaded_lightcurve
from skvo_veb.utils.lc_bridge import PipeException, ingest_lightcurve_file

_RELATIVE_DAT = b"# FILTER=V\n# MAG0=20.0\n1.0 12.0 0.01\n2.0 12.1 0.01\n3.0 12.2 0.01\n"
_DECLARED_DAT = b"# filter=V\n# JD0=2400000\n# mag0=20\n# jd mag mag_err\n60821.4 12.9 0.05\n60822.4 10.7 0.01\n"


def test_relative_times_without_origin_say_which_header_row_to_add():
    """Both upload paths fail fast and name the ``# JD0=`` header row, not a UI step."""
    with pytest.raises((ValueError, PipeException), match=r"# JD0=<value>") as bridge_error:
        ingest_lightcurve_file(io.BytesIO(_RELATIVE_DAT), "r.dat")
    assert "Calibration" not in str(bridge_error.value)
    with pytest.raises((ValueError, PipeException), match=r"# JD0=<value>"):
        pack_uploaded_lightcurve(_RELATIVE_DAT, "r.dat")


def test_declared_origin_makes_the_times_absolute():
    """A ``# JD0=`` row in the file is the way to supply the origin."""
    lcd = ingest_lightcurve_file(io.BytesIO(_DECLARED_DAT), "vv.dat")
    assert lcd.metadata["vo_envelope"]["source_timeorigin"] == 2400000.0
    packet = json.loads(pack_uploaded_lightcurve(_DECLARED_DAT, "vv.dat"))
    assert packet["meta"]["jd0"] == 2400000.0
    assert np.isclose(packet["data"][0][0] + packet["meta"]["jd0"], 2460821.4)
