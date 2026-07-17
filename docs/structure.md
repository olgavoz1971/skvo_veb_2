skvo_veb/
├── assets/
├── components/         # frontend components
├── pages/              # frontend
├── utils/              # backend only — no test_*.py files anymore
├── tests/              # all unit/integration tests
│   ├── test_lc_interaction.py
│   ├── test_lc_selection.py
│   ├── test_lc_epoch.py
│   ├── test_lc_tabular_export.py
│   ├── test_asassn_export.py
│   └── volightcurve/
│       ├── test_cutout_export.py
│       ├── test_tess_export.py
│       ├── test_tess_upload.py
│       └── test_write_vo.py
└── volightcurve/       # common module
