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
