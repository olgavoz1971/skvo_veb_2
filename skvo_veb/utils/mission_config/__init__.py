"""Mission-specific lightcurve configuration and VOTable export profiles.

Each module under this package owns instrument constants, ingest photcal resolution,
and ``write_vo_lightcurve`` keyword builders for **legacy mission pages** only.

Supported VOTable export profiles (``export_curvedash(..., profile=...)``):

- ``tess`` — TESS archive pipeline lightcurves (``mission_config.tess``)
- ``cutout`` — uncalibrated TESS FFI/TPF cutouts (``mission_config.tess``)
- ``asassn`` — ASAS-SN Sky Patrol (``mission_config.asassn``)

Lightcurve Discovery providers live under ``lc_providers/`` and must not depend on
this package (except where a legacy page shares utilities explicitly).
"""
