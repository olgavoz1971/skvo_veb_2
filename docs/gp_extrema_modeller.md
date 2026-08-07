# Gaussian Process extrema modeller (GP O-C page)

This document describes the GP O-C workflow for researchers preparing uploads and
interpreting results. Sections will be added incrementally.

Technical ingest rules for ``.dat`` files are also summarised in
[dat_lightcurve_comments.md](dat_lightcurve_comments.md).

---

## Light curve file formats

Upload on the GP page uses the **same ingest path** as the TESS light curve page:
VOTable (``.vot`` / ``.xml``), CSV, ECSV, and ASCII **``.dat``**.

### ``.dat`` files (ASCII)

For **``.dat`` files only**, you may include metadata in ``#`` comment lines
(case-insensitive):

| Pattern | Meaning |
|---------|---------|
| ``JD0 = <value>`` | Time origin added to the time column to obtain absolute Julian Date (default **0** if omitted). |
| ``MAG0 = <value>`` | Reference magnitude for photometric calibration when converting to the normalised flux used internally by the GP (paired with a dimensionless instrumental zero point). |
| ``PERIOD = <value>`` | Folding period in days (populates the **P** field after upload). |
| ``EPOCH = <value>`` | Reference epoch in the same units and scale as the time column (populates **Epoch-2400000.5**; combined with ``JD0`` when forming absolute JD). |
| ``FILTER=`` / ``BAND=`` | Filter or band label stored in metadata. |

You may also put a **header comment** whose words match the column count
(for example ``# jd mag mag_err`` or ``# jd mag mag_err label``). If there is no
such line, a legacy three-column layout is assumed: time, magnitude, and
magnitude error by position.

Each data row must have a **fixed** number of fields on every line. Rows with the
wrong column count are rejected with a line number in the upload error message.
Columns named ``label``, ``sector``, or ``flag`` may hold arbitrary text; other
columns must be numeric. Use ``NaN`` in the file for a missing magnitude error on
that row.

The GP fit works on **normalised flux**; **timing (JD)** is what matters for O-C
outputs. The y-axis in fit panels is not labelled with physical flux units (Jy or
e/s).

### Other formats (brief)

- **VOTable**: preferred when full VO metadata (time system, photometric calibration,
  filter) is already in the file.
- **CSV / ECSV**: column headers and ECSV metadata; ``.dat``-style ``#`` comment
  conventions do not apply.

---

## Photometric uncertainties and the “Guess sigma” control

When you upload a light curve, the modeller needs a noise level to weight the
Gaussian Process fit. 

**If your file includes a magnitude or flux error column and every point in a selected interval has a usable value**, those uncertainties are
converted to flux space and used (scaled by the **Noise divisor** on the page),
unless you turn on **Guess sigma**, which deliberately ignores the column and
estimates scatter from the data. 

**If errors are absent for the whole interval**
(for example every value is ``NaN``, or you use a two-column legacy file with no
error column), the application **automatically** estimates noise from the data in the same way as Guess sigma, even when that checkbox is off. 

**If some points have errors and others do not in the same interval**, behaviour is ambiguous today: the fit may not treat missing errors consistently; prefer complete error columns, all-
``NaN`` errors where unknown, or enable Guess sigma when you do not trust the
tabulated values. 

The prep plot **Show error bars** switch affects display only;
it does not change how the GP run uses uncertainties.

---

## Marking intervals on the prep plot (unfolded)

Enable **Mark bands** in the toolbar above the prep plot, then **double-click**
(on or very near) a photometry point inside a green interval band. Marked bands
turn red; double-click again to unmark. **Remove marked** applies to the registry;
**Mark bands** and **Remove trend** cannot both be active (they share the same
clicks). Marks are kept when the plot is redrawn (view mode, error bars, and so
on) until you remove them or change the interval list.

---

## Manual trend removal (unfolded prep plot)

Switch on **Remove trend** in the toolbar above the prep plot, **click once** on
the unfolded curve to place a
**horizontal** dashed line across most of the visible time range (about four-fifths
of the plot width), drag the handles to
adjust, then **Apply trend removal**.
The correction uses the current **Magnitudes / Flux** view: subtract the line in
mag, divide by it in flux. Uncertainties are unchanged in mag view and scaled in
flux view. Reload the light curve file to undo. GP fitting still uses the usual
internal flux conversion after your working curve is updated.

---

## Mixed magnitude errors in one GP interval (Guess sigma off)

When **Guess sigma** is off, noise for each selected interval is decided from the
``flux_err`` values **in that interval only** (after conversion from magnitude
errors where applicable).

| Share of rows with a finite error | Behaviour |
|-----------------------------------|-----------|
| **None** (all ``NaN``) | Same as leaving errors blank: scatter is estimated from the data (MAD), as if Guess sigma were on for that interval. |
| **Below 70%** | Not enough tabulated coverage: **MAD guess for every point** in the interval. |
| **70% or more** | Tabulated errors are used: each missing row gets the **median** of the finite ``flux_err`` values in that interval, then all points are scaled by the **Noise divisor**. |

Turning **Guess sigma** on still ignores the error column for the whole interval
and always uses the MAD estimate. The 70% threshold is fixed in application
configuration (``GP_MIN_FINITE_ERROR_FRACTION``).
