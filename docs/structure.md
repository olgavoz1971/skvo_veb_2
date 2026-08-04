skvo_veb/
├── assets/
├── components/         # frontend components
├── pages/              # frontend (includes lightcurve_discovery.py)
├── lc_providers/       # plugin registry: strategy/adapters + shared provider interface (no Dash)
├── volightcurve/       # IVOA VO lightcurve standard (ingest + write_vo_lightcurve)
├── utils/              # backend — no test_*.py files
│   ├── mission_config/ # static PhotCal + export profiles per mission
│   ├── lc_bridge.py    # VOLightCurve ↔ CurveDash ↔ export
│   ├── lc_discovery_search.py  # Discovery search orchestration (§9)
│   ├── simbad_resolver.py      # shared Simbad resolve for orchestrator
│   └── …
└── tests/              # all unit/integration tests
    ├── test_lc_*.py
    ├── test_asassn_export.py
    └── volightcurve/

**Architecture docs:**
- `docs/adding_a_lightcurve_provider.md` — step-by-step guide to plug in a new provider (includes TAP section)
- `docs/mission_lightcurve_providers.md` — full multi-mission LC architecture, search orchestration (§9), and provider API
- `docs/lc_discovery_messages.md` — Search / Plot tab alerts and status lifetimes on Lightcurve Discovery
- `docs/lc_discovery_css.md` — CSS tuning for the Discovery page layout
- `docs/asassn_skypatrol_lookup_cone_zero_coords.md` — Hawaii `lookup_cone` HTTP 500 at RA/Dec = 0 and client workaround
- `docs/tess_background_lightkurve.md` — Lightkurve background columns vs cutout extraction; archive vs cutout pages
