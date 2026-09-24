# UPJŠ time series (`upjs_ts`)

## 1. Discovery

TAP `https://skvo.science.upjs.sk/tap`, ADQL 2.1, table `upjs_ts.ts_ssa`.

```sql
SELECT object_id, accref, ssa_bandpass, ssa_targname, ssa_targclass,
       ssa_location, ssa_length, ssa_collection, t_min, t_max, mean_mag
FROM upjs_ts.ts_ssa
WHERE <predicate>
```

`<predicate>` is `ssa_targname = '…'`, `object_id = '…'`, or
`1 = CONTAINS(ssa_location, CIRCLE(ra_deg, dec_deg, radius_deg))`.
Optional `t_min` / `t_max` bounds in MJD. A name lookup on
`upjs_ts.objects` (`simbad_name`, `vsx_name`) only resolves an
`object_id`; it does not return the light curve.

## 2. Retrieval

The points are not in the TAP result. `fetch_lightcurve` downloads the
`accref` URL from the SSA row.

## 3. What we change

Every product of this provider. The magnitude zero point is `0.0` mag when
the file has none and `photDM:PhotometryFilter.identifier` is one of
`Generic/Bessell.U`, `Generic/Bessell.B`, `Generic/Bessell.V`,
`Generic/Bessell.R`, `Generic/Bessell.I`, `SLOAN/SDSS.g`, `SLOAN/SDSS.r`,
`SLOAN/SDSS.i`. Any other
identifier is left unchanged. The flux zero point stays as published.

The TABLE title is rewritten to `<archive name> in <filter> filter`.

An error column that does not already reference a photcal receives the
photcal of the single magnitude or flux column that has one. An error
column the archive already linked is left as it is. The same step runs
for the other discovery providers.
