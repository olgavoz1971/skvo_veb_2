# Spike experiment scripts

## Step 1 — single method on first N intervals

```bash
cd auxiliary/lc_approx_spike
../../.venv/bin/python scripts/run_interval_approx.py \
  --lc data/NSV_807_sector_97_flatten.vot \
  --intervals data/NSV_807_sector_97_prim.dat \
  --domain flux \
  --method WSAP \
  --max-intervals 3 \
  --save-plots
```

## Step 2 — batch AP / WSAP / WSL comparison

```bash
cd auxiliary/lc_approx_spike
../../.venv/bin/python scripts/run_batch_approx.py \
  --domain flux \
  --save-plots --plot-max 5
```

Defaults: NSV 807 sector 97 flatten + prim intervals, all windows.
Outputs: ``approx_batch.csv``, ``approx_compare.csv``, optional multi-panel PNGs.

See ``../NOTES.md`` for interpretation.
