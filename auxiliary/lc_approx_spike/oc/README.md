# Spike O-C (Step 1 only)

Compute O-C residuals from ``run_batch_approx`` TOM tables, with optional cycle
corrections — the same Step 1 maths as ``auxiliary/oc``, scoped to this spike.

## Run

```bash
cd auxiliary/lc_approx_spike/oc
../../../.venv/bin/python run_oc_step1.py \
  --tom-csv ../data/runs/NSV_807_sector_97_flatten_NSV_807_sector_97_prim/approx_batch.csv \
  --method WSAP \
  --t0 57711.3539 --p0 0.3389614 --time-scale mjd \
  --save-plot --show
```

Compare methods by changing ``--method`` to ``AP``, ``WSL``, or ``BEST``.

### Cycle corrections

Same rule as ``auxiliary/oc``: for every TOM with ``jd_ext >= at_time``, add
``delta_E`` to the rounded cycle. Times use ``--time-scale``.

```bash
--cycle-shift 60940:1
--cycle-shift 60950:-1
```

### Outputs

Written next to the TOM CSV (or ``--out-dir``):

| File | Content |
|------|---------|
| ``oc_<method>.csv`` | ``cycle_number``, ``jd_ext``, ``OC``, ``sigma_jd_ext``, ``sigma_s`` |
| ``oc_<method>.png`` | O-C vs E with σ(TOM) error bars (if ``--save-plot``) |

``approx_compare.csv`` is also accepted (wide columns).
