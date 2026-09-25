# Personal collections (`personal_ts`)

Expands [schema.md](../schema.md).

## 1. Discovery

TAP `https://skvo.science.upjs.sk/tap`, ADQL 2.1, table `personal.ts_ssa`.

An object lookup uses `object_id = '<object id>'`. A cone search uses
`1 = CONTAINS(ssa_location, CIRCLE(ra_deg, dec_deg, radius_deg))`.
Optional `t_min` / `t_max` bounds in MJD. A name lookup on
`personal.objects` only resolves an `object_id`; it does not return the
light curve.

## 2. Retrieval

The points are not in the TAP result. `fetch_lightcurve` downloads the
`accref` URL from the SSA row.

## 3. What we change

Every product of this provider. The magnitude zero point is `0.0` mag when
the file has none and `photDM:PhotometryFilter.identifier` is one of
`Generic/Bessell.U`, `Generic/Bessell.B`, `Generic/Bessell.V`,
`Generic/Bessell.R`, `Generic/Bessell.I`, `Palomar/Arp1961.103aO_atm`.
Any other identifier is left unchanged. A magnitude zero point the archive
already published is left as it is. The flux zero point stays as published.
The archive table name, description, and column names are kept.

When the product has one photcal group, an error column that does not
already reference a photcal receives that group's id. If the group has no
id, the id `photcal` is set so the reference can be written. An error
column the archive already linked is left as it is. Several photcal groups
are left unlinked.
