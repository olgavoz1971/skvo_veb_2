"""Magnitude uncertainty helpers for Gaia epoch photometry products."""

from __future__ import annotations

import numpy as np

# sigma_m = (2.5 / ln 10) * (sigma_F / F) for Pogson photometry.
MAG_ERR_FROM_SNR_FACTOR = 1.0857362


def mag_error_from_flux_over_error(snr_values) -> np.ndarray:
    """Derives magnitude uncertainties from Gaia flux signal-to-noise ratios.

    Args:
        snr_values: ``flux_over_error`` values (flux divided by flux error).

    Returns:
        numpy.ndarray: Magnitude uncertainties in mag; invalid SNR entries are NaN.
    """
    snr = np.asarray(snr_values, dtype=float)
    mag_err = np.full_like(snr, np.nan, dtype=float)
    valid = np.isfinite(snr) & (snr > 0.0)
    mag_err[valid] = MAG_ERR_FROM_SNR_FACTOR / snr[valid]
    return mag_err
