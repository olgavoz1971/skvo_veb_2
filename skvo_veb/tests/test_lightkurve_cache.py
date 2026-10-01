"""Tests for Lightkurve retrieve error classification and generic FITS open."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from lightkurve import LightkurveError

from skvo_veb.utils.lightkurve_cache import (
    classify_lightkurve_read_failure,
    download_lightcurve_row_with_recovery,
    format_lightkurve_retrieve_error,
    open_lightcurve_product,
)
from skvo_veb.utils.my_tools import PipeException


def _lk_error_from_cause(cause: BaseException) -> LightkurveError:
    """Returns a LightkurveError with ``__cause__`` set like ``raise ... from``."""
    try:
        raise LightkurveError(
            "Error in reading Data product /tmp/x.fits of type generic .\n"
            "This file may be corrupt due to an interrupted download. "
            "Please remove it from your disk and try again."
        ) from cause
    except LightkurveError as exc:
        return exc


def test_classify_generic_quality_bitmask_is_unsupported():
    """Generic reader TypeError is not a truncated cache."""
    cause = TypeError(
        "read_generic_lightcurve() got an unexpected keyword argument 'quality_bitmask'"
    )
    exc = _lk_error_from_cause(cause)
    assert classify_lightkurve_read_failure(exc) == "unsupported_product"


def test_classify_buffer_too_small_is_truncated():
    """NumPy buffer error is treated as truncated FITS."""
    cause = TypeError("buffer is too small for requested array")
    exc = _lk_error_from_cause(cause)
    assert classify_lightkurve_read_failure(exc) == "truncated_cache"


def test_canned_corrupt_sentence_alone_is_not_truncated():
    """Lightkurve's canned download sentence must not trigger purge."""
    exc = LightkurveError(
        "Not recognized as a supported data product:\n/tmp/x.fits\n"
        "This file may be corrupt due to an interrupted download. "
        "Please remove it from your disk and try again."
    )
    assert classify_lightkurve_read_failure(exc) == "other"


def test_format_unsupported_omits_corrupt_and_names_pipeline():
    """User text names the pipeline and does not claim a corrupt file."""
    cause = TypeError(
        "read_generic_lightcurve() got an unexpected keyword argument 'quality_bitmask'"
    )
    exc = _lk_error_from_cause(cause)
    message = format_lightkurve_retrieve_error(exc, row_idx=13, author="TARS")
    assert "row 13" in message
    assert "TARS" in message
    assert "corrupt" not in message.lower()
    assert "interrupted download" not in message.lower()
    assert "recognised TESS pipeline" in message


def test_format_other_strips_canned_corrupt_sentence():
    """Non-classified failures keep the inner text without the canned paragraph."""
    cause = ValueError("No reference time found in /tmp/x.fits.")
    exc = _lk_error_from_cause(cause)
    message = format_lightkurve_retrieve_error(exc, row_idx=2)
    assert "No reference time found" in message
    assert "corrupt" not in message.lower()
    assert "interrupted download" not in message.lower()


def test_recovery_does_not_purge_unsupported_product(monkeypatch):
    """Unsupported generic read must not delete the cached FITS."""
    cause = TypeError(
        "read_generic_lightcurve() got an unexpected keyword argument 'quality_bitmask'"
    )
    lk_exc = _lk_error_from_cause(cause)
    message = format_lightkurve_retrieve_error(lk_exc, row_idx=13, author="TARS")
    pipe = PipeException(message)
    pipe.__cause__ = lk_exc

    def _fail(_search, _idx):
        raise pipe

    purged = {"called": False}

    def _purge(_search, _idx):
        purged["called"] = True
        return True

    monkeypatch.setattr(
        "skvo_veb.utils.lightkurve_cache.download_lightcurve_row",
        _fail,
    )
    monkeypatch.setattr(
        "skvo_veb.utils.lightkurve_cache.purge_lightkurve_cached_fits",
        _purge,
    )
    with pytest.raises(PipeException, match="cached file was left unchanged"):
        download_lightcurve_row_with_recovery(MagicMock(), 13)
    assert purged["called"] is False


def test_recovery_purges_truncated_cache(monkeypatch):
    """Truncated FITS still purges once and retries."""
    cause = TypeError("buffer is too small for requested array")
    lk_exc = _lk_error_from_cause(cause)
    message = format_lightkurve_retrieve_error(lk_exc, row_idx=1)
    pipe = PipeException(message)
    pipe.__cause__ = lk_exc
    calls = {"n": 0}

    def _download(_search, _idx):
        calls["n"] += 1
        if calls["n"] == 1:
            raise pipe
        return "ok-lc"

    purged = {"called": False}

    def _purge(_search, _idx):
        purged["called"] = True
        return True

    monkeypatch.setattr(
        "skvo_veb.utils.lightkurve_cache.download_lightcurve_row",
        _download,
    )
    monkeypatch.setattr(
        "skvo_veb.utils.lightkurve_cache.purge_lightkurve_cached_fits",
        _purge,
    )
    result = download_lightcurve_row_with_recovery(MagicMock(), 1)
    assert result == "ok-lc"
    assert purged["called"] is True
    assert calls["n"] == 2


def _write_generic_lc_fits(path: Path, *, include_flux: bool) -> None:
    """Writes a minimal TESS-like table FITS for generic-reader tests.

    Args:
        path (Path): Output path.
        include_flux (bool): When false, omit the FLUX column.
    """
    names = ["TIME"]
    data = {"TIME": np.array([1000.0, 1001.0])}
    if include_flux:
        names.append("FLUX")
        data["FLUX"] = np.array([1.0, 1.1])
    table = Table(data)
    hdu = fits.BinTableHDU(table, name="LIGHTCURVE")
    hdu.header["BJDREFI"] = 2457000
    hdu.header["TUNIT1"] = "d"
    hdu.header["TIMESYS"] = "tdb"
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "TESS"
    primary.header["TIMESYS"] = "TDB"
    fits.HDUList([primary, hdu]).writeto(path, overwrite=True)


def test_open_generic_product_without_quality_bitmask(tmp_path):
    """Generic TIME+FLUX FITS opens without SPOC quality_bitmask."""
    path = tmp_path / "generic_lc.fits"
    _write_generic_lc_fits(path, include_flux=True)
    lc = open_lightcurve_product(str(path), row_idx=3, author="TARS")
    assert "flux" in lc.colnames
    assert len(lc) == 2


def test_open_generic_product_refuses_missing_flux(tmp_path):
    """Generic FITS without FLUX is an unsupported product, not a corrupt cache."""
    path = tmp_path / "no_flux.fits"
    _write_generic_lc_fits(path, include_flux=False)
    with pytest.raises(PipeException, match="recognised TESS pipeline"):
        open_lightcurve_product(str(path), row_idx=4, author="TARS")


def test_open_cached_tars_file_when_present():
    """Opens a real TARS cache file if the developer already retrieved it."""
    path = (
        Path.home()
        / ".lightkurve/cache/mastDownload/HLSP/"
        "hlsp_tars_tess_ffi_s0016-0000000409455615_tess/"
        "hlsp_tars_tess_ffi_s0016-0000000409455615_tess_v01_lc.fits"
    )
    if not path.is_file():
        pytest.skip("TARS example FITS is not in the local Lightkurve cache")
    lc = open_lightcurve_product(str(path), row_idx=13, author="TARS")
    assert "flux" in lc.colnames
    assert len(lc) > 0
