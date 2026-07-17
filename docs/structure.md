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

**Architecture docs:** see `docs/mission_lightcurve_providers.md` for the multi-mission LC page, search orchestration (§9), and provider API.
