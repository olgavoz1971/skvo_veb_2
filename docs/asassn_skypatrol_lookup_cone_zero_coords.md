# ASAS-SN Sky Patrol: `lookup_cone` fails at RA or Dec = 0

## Summary

Cone metadata queries through **pyasassn** (`SkyPatrolClient.cone_search`) hit the Hawaii HTTP API:

```text
POST http://asassn-lb01.ifa.hawaii.edu:9006/lookup_cone/radius{R}_ra{RA}_dec{Dec}
```

When **either** `RA` or `Dec` is exactly **0.0** (e.g. `_ra1.0_dec0.0` or `_ra0.0_dec1.0`), the server responds with **HTTP 500** (internal error). Slightly non-zero centres (e.g. `ra=0.0001`, `dec=0.00001`) succeed.

This is a **server-side path parsing bug**, not a Dash or skvo_veb logic error. The failure was previously misread as a generic archive overload.

## Reproduction (2026-08)

| Centre (deg) | HTTP status |
|--------------|-------------|
| RA=1, Dec=0  | 500         |
| RA=1, Dec=1e-5 | 200       |
| RA=0, Dec=1  | 500         |
| RA=1e-8, Dec=1 | 200       |
| RA=0.0001, Dec=0.00001 | 200 |

Radius and catalog (`stellar_main`, `download=False`) do not change the zero-coordinate behaviour.

## Mitigation in this repository

1. **Discovery provider** — `skvo_veb/lc_providers/asassn/skypatrol_fetch.py` nudges exact zeros via `skypatrol_cone_centre_for_lookup_url()` before calling `cone_search` (offset **1e-8 deg**, negligible vs any discovery cone).

2. **Forked skypatrol** — `third_party/skypatrol` (installed as `skypatrol` per `requirements.txt`) applies the same nudge in `pyasassn/client.py` (`_cone_coord_for_lookup_url`) so all `cone_search` callers benefit after reinstall.

Reinstall the fork after pulling client changes:

```bash
pip install --force-reinstall "skypatrol @ file:///…/third_party/skypatrol"
```

(Path matches `requirements.txt`.)

## Upstream

Report to [ASAS-SN Sky Patrol](https://github.com/asas-sn/skypatrol) / Hawaii service maintainers: URL template should accept `dec0.0` and `ra0.0`, or coordinates should move to the JSON body instead of the path.

## Related code

- `skvo_veb/lc_providers/asassn/skypatrol_cone_url.py`
- `scripts/skypatrol_discovery_probe.py` (direct client probes)
