"""Application-wide photometric calibration defaults.

These values live under ``volightcurve`` so every page (Processor, GP,
Discovery, TESS, …) shares one explicit fallback convention when photcal
is incomplete. Callers must surface a user-visible warning when applying
them — never treat this as a silent promotion.
"""

from __future__ import annotations

# Zero-point flux when photcal lacks ``zp_flux`` (instrumental / relative flux).
DEFAULT_ZP_FLUX = 1.0

# ``None`` means dimensionless (Astropy ``dimensionless_unscaled``).
DEFAULT_ZP_FLUX_UNIT: str | None = None

# Reference magnitude when photcal lacks ``zp_mag`` (Pogson-style conversion).
DEFAULT_ZP_MAG = 20.0

DEFAULT_ZP_MAG_UNIT = "mag"

DEFAULT_MAG_SYS = "Vega"
