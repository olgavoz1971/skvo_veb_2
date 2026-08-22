# lc_approx spike

Experimental notes and scripts for trying
[mpyat2/lc_approx](https://github.com/mpyat2/lc_approx.git) extrema
approximators (AP / WSAP / WSL / A) on our EB light curves.

- **[NOTES.md](NOTES.md)** — review + Step 1 / Step 2 findings  
- **`scripts/run_interval_approx.py`** — one method, first N intervals  
- **`scripts/run_batch_approx.py`** — AP + WSAP + WSL on all intervals + compare  
- **`oc/run_oc_step1.py`** — Step 1 O-C from TOM CSV (cycle shifts + σ bars)  

```bash
cd auxiliary/lc_approx_spike
../../.venv/bin/python scripts/run_batch_approx.py \
  --domain flux --save-plots --plot-max 5
```

```bash
cd auxiliary/lc_approx_spike/oc
../../../.venv/bin/python run_oc_step1.py \
  --tom-csv ../data/runs/NSV_807_sector_97_flatten_NSV_807_sector_97_prim/approx_batch.csv \
  --method WSAP --t0 57711.3539 --p0 0.3389614 --time-scale mjd \
  --save-plot
```

Constraint: all spike work stays under this folder; project I/O is **imported**, not edited.
