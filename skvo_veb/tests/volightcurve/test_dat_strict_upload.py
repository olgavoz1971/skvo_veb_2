"""Strict ``.dat`` upload validation (shared ``lc_bridge`` ingest)."""

from __future__ import annotations

import io

import pytest

from skvo_veb.utils.lc_bridge import _read_dat_upload_table, ingest_volightcurve_file
from skvo_veb.utils.my_tools import PipeException


def test_strict_dat_rejects_short_row_with_line_number():
    dat = b"""# jd mag mag_err
52500.1 12.3 0.01
52501.2 12.4
"""
    with pytest.raises(PipeException) as exc_info:
        _read_dat_upload_table(io.BytesIO(dat))
    msg = str(exc_info.value)
    assert "line 3" in msg
    assert "expected 3 columns" in msg
    assert "got 2" in msg
    assert "52501.2 12.4" in msg
    assert "guess" not in msg.lower()


def test_strict_dat_rejects_extra_columns():
    dat = b"""# jd mag mag_err
52500.1 12.3 0.01 9.9
"""
    with pytest.raises(PipeException) as exc_info:
        ingest_volightcurve_file(io.BytesIO(dat), "bad.dat")
    msg = str(exc_info.value)
    assert "declares 3 columns" in msg
    assert "data rows have 4 columns" in msg


def test_strict_dat_legacy_three_columns_without_header():
    dat = b"""52500.1 12.3 0.01
52501.2 12.4 0.02
"""
    table = _read_dat_upload_table(io.BytesIO(dat))
    assert len(table) == 2
    assert table.colnames == ["col1", "col2", "col3"]


def test_dat_label_column_accepts_arbitrary_strings():
    import math

    dat = b"""# jd mag mag_err label
59853.35869 0.112 0.003 TE
59854.41140 -0.033 NaN SK
"""
    volc = ingest_volightcurve_file(io.BytesIO(dat), "curve.dat")
    assert volc.table.colnames[-1] == "label"
    assert list(volc.table["label"]) == ["TE", "SK"]
    assert math.isnan(volc.table["mag_err"][1])


def test_strict_dat_rejects_two_columns_without_header_comment():
    dat = b"""52500.1 12.3
"""
    with pytest.raises(PipeException) as exc_info:
        _read_dat_upload_table(io.BytesIO(dat))
    assert "legacy" in str(exc_info.value).lower()
