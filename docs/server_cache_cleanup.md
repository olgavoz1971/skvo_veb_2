# Manual cache cleanup on the production server

Nothing deletes cached files automatically. This note describes what is stored where, what is
safe to remove, and the commands to do it by hand. Always run the `-print` (dry run) form
first and read the list before deleting.

## Where the caches are

| Folder | Set by | What is in it |
|---|---|---|
| `/var/www/.lightkurve/cache` (production) | `LIGHTKURVE_CACHE_DIR` in `/var/www/flask/.env` (see below) | `mastDownload/` SPOC light curves and target pixel files; `tesscut/` FFI cutouts |
| `$TESS_CACHE_DIR` (from `/var/www/flask/.env`) | `TESS_CACHE_DIR` | our own small files: `lc_search_metadata_*` (sector lists), `lc_native_id_lookup_*`, `tess_lc_column_info_*`, search results (`tpf_*`, `ffi_*`, `basic_search_*`, `search_lcf_refined_*`), and old `ffi_data_*` cutout copies |

Everything above is a cache: if a file is removed, the app downloads or rebuilds it on the next
request. The only cost is a slower first request.

## Setting the Lightkurve folder explicitly

Lightkurve does not read `.env` by itself. The app now applies one variable at start-up. Add this
line to `/var/www/flask/.env` and restart the app:

```
LIGHTKURVE_CACHE_DIR=/var/www/.lightkurve/cache
```

The folder must exist or be creatable, and be writable by the Apache user. If the variable is
missing, Lightkurve uses `~/.lightkurve/cache` of the running user, which for Apache is the same
folder. Leave it unset in the local debug `.env`.

## Safe to delete once: the old cutout copies

Before this change the app kept a second copy of every FFI cutout in `$TESS_CACHE_DIR`. Nothing
reads them any more. They are large (about 1 GB on the debug machine).

```bash
cd "$TESS_CACHE_DIR"
find . -maxdepth 1 -name 'ffi_data_*' -print          # dry run
find . -maxdepth 1 -name 'ffi_data_*' -delete         # delete
```

## Routine cleanup by age

Remove files nobody has used for a while (here: not modified for 180 days; change the number).

```bash
# FFI cutouts and SPOC downloads
find /var/www/.lightkurve/cache/tesscut -name '*_astrocut.fits' -mtime +180 -print
find /var/www/.lightkurve/cache/mastDownload -name '*.fits' -mtime +180 -print

# our own small files
find "$TESS_CACHE_DIR" -maxdepth 1 \( -name 'lc_search_metadata_*' -o -name 'lc_native_id_lookup_*' \
     -o -name 'tess_lc_column_info_*' -o -name 'tpf_*' -o -name 'ffi_*' -o -name 'basic_search_*' \
     -o -name 'search_lcf_refined_*' \) -mtime +180 -print
```

Replace `-print` by `-delete` to remove. Do not delete everything in `$TESS_CACHE_DIR`: it also
holds files of other features (for example `cache.db` and `lc_providers`).

To see how much space each part uses:

```bash
du -sh /var/www/.lightkurve/cache/tesscut /var/www/.lightkurve/cache/mastDownload "$TESS_CACHE_DIR"
```

## Things to know

- **Files with wrong coordinates (one-time).** Until 2026-10-17 a target written as `23:05:22.84 +47:40:34.72`
  was read as degrees, so cache files named `..._ra_<number>_dec_<number>_...` for such targets carry a wrong
  RA. They are no longer matched and just sit there; the age-based cleanup above removes them.

- **Do it at a quiet time.** A user who has a plot open on a file you delete gets an error on the
  next click and has to press Retrieve again. Nothing else breaks.
- **No restart is needed** after deleting cache files.
- **Leftovers that are harmless:** folders named `.tmp_tesscut_*` (a download that was interrupted)
  and files named `.lock_s*` inside `tesscut/`. Old `.tmp_tesscut_*` folders can be removed:
  `find /var/www/.lightkurve/cache -maxdepth 1 -name '.tmp_tesscut_*' -mmin +60 -exec rm -r {} +`
- **To refresh one object** users do not need you: Clean cache and ReRetrieve on the pages do that
  for a single target or a single sector.
- **Permissions:** run the commands as the Apache user (or `sudo -u www-data`), so new files keep
  the right owner.
