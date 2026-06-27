# Caching Architecture

This document describes the caching architecture and strategies implemented in this project to balance two competing requirements:
1. **Public Data Caching (Shared Archive Cache):** Reducing external network requests and processing for identical queries by caching public, immutable physical observations (such as TESS search results, Target Pixel Files, and Lightcurves) so multiple users can reuse them.
2. **Private Data Caching (User Session Cache):** Enabling low-latency user sessions by caching large, user-specific data (uploads, deleted outliers, locally processed lightcurves) on the server side using a unique session UUID, rather than transferring massive payloads back and forth to the client via `dcc.Store`.

---

## 1. Caching Subsystems and Organisation

The caching mechanisms are split into three dedicated subsystems depending on the scope, ownership, and source of the data:

```text
                               ┌────────────────────────────────┐
                               │       Incoming Request         │
                               └────────────────┬───────────────┘
                                                │
                       ┌────────────────────────┴────────────────────────┐
                       ▼                                                 ▼
             [ Public Data Search ]                           [ User-Specific View/Edit ]
                       │                                                 │
            ┌──────────┴──────────┐                            ┌─────────┴─────────┐
            ▼                     ▼                            ▼                   ▼
     { Cache Hit? }        { Cache Miss? }              { Cache Hit? }      { Cache Miss? }
            │                     │                            │                   │
   ┌────────┴────────┐   ┌────────┴────────┐          ┌────────┴────────┐  ┌───────┴───────┐
   │ Read from Local │   │ Fetch from MAST │          │ Read from       │  │ User must     │
   │ TESS/ASAS Cache │   │ / VO Services   │          │ SQLite-backed   │  │ download /    │
   └─────────────────┘   └────────┬────────┘          │ user_cache      │  │ upload first  │
                                  │                   └─────────────────┘  └───────────────┘
                                  ▼
                         Cache on Disk for
                          Future Sharing
```

### A. The User Session Cache (`user_cache`)
* **Underlying Technology:** SQLite-backed `diskcache` (multi-process and thread-safe).
* **Location Configuration:** Specified by the `USER_CACHE_DIR` environment variable.
* **Role:** Stores user-specific, customised, or uploaded lightcurve data. TESS lightcurves are represented as high-level scientific curves (`CurveDash` instances) and can be quite large. Passing these data payloads to the browser via `dcc.Store` would cause severe network and browser rendering lags. Instead, the application generates a unique `user_tab_id` and caches the data on the server.
* **Key Implementation Details:**
  * **Tab UUID Generation:** When a user initialises the page, a unique UUID (`user_tab_id`) is generated on the server and stored in a lightweight `dcc.Store` on the client.
  * **Sliding Expiration:** To prevent server-disk exhaustion from inactive sessions, the cache uses a **sliding expiration window** of 24 hours (`expire=86400` seconds). Every read operation refreshes this timer.

### B. The TESS Public Data Cache (`tess_cache`)
* **Underlying Technology:** Custom file-based key-value wrapper (`skvo_veb/utils/tess_cache.py`).
* **Location Configuration:** Specified by the `TESS_CACHE_DIR` environment variable.
* **Role:** Caching raw public data retrieved from MAST (NASA's Mikulski Archive for Space Telescopes) to optimise search and retrieval times.
* **Key Implementation Details:**
  * **Query-Based Hashing:** Caching search queries (`SearchResult` tables) using standard serialisation (`dill`) under filenames deterministically mapped to the query parameters using an MD5 hash of the parameters.
  * **FITS Storage:** High-level Target Pixel Files (TPF) and Full Frame Image (FFI) cutouts are stored as standard `.fits` files (`save_tpf_fits`, `save_ffi_fits`).
  * **Corrupted Cache Healing:** If a download is corrupted (e.g., incomplete network streams), the wrapper automatically resolves the file path on disk, clears the corrupted file, and retries the MAST query, ensuring the cache is self-healing.

### C. The ASAS-SN Public Data Cache
* **Underlying Technology:** Direct file serialization (`pickle`).
* **Location Configuration:** Specified by the `ASASSN_CACHE_DIR` environment variable.
* **Role:** Caches ASAS-SN physical lightcurves under `asassn_lc_{gaia_id}.pkl` using `pandas.DataFrame.to_pickle` to avoid repeated remote VO service lookups.

---

## 2. Local Debug Mode vs. Production (Apache) Mode

The system handles differences between local development and an Apache production environment using environment-level configurations and adaptive imports:

### A. Local Debug Mode (`main.py` / Standalone Execution)
* **Environment Variables:** Loaded from the local `.env` file, setting `USE_REDIS=false` and `DEBUG_LOCAL=1`.
* **Background Processing:** In `config.py`, when `USE_REDIS` is `False`, the app registers `DiskcacheManager` as the global background callback manager.
* **Standalone Safety:** When running `tess_cutout.py` or `lightcurve_tess_srv.py` directly, a local standalone `Dash` server is instantiated. If `DISK_CACHE` / `DISK_CACHE_LOCAL` is configured as `False`, the background callbacks are forced to run **synchronously** in the foreground (`background_callback = False`). This makes it simple to debug issues since stack traces print directly to the terminal, and standard debuggers can step through code without multi-process complications.

### B. Production Mode (Apache WSGI / `deployment/skvo_veb.wsgi`)
* **Environment Variables:** Loaded from `/var/www/flask/.env`.
* **Background Processing:** Under Apache, multiple server worker processes handle incoming requests. Long-running calls (downloads, stitching) are offloaded asynchronously. If `USE_REDIS` is set to `True` in production, the application registers `CeleryManager` backed by Redis, distributing background tasks safely to standalone Celery workers so Apache worker processes do not timeout or block.
* **Process Concurrency Protection:** Apache serves multiple clients concurrently through separate worker processes.
  * **Diskcache Multi-Process Safety:** The `user_cache` uses SQLite-backed `diskcache`. SQLite uses write-ahead logging (WAL) and POSIX file locking, making it completely process-safe and thread-safe. Multiple Apache processes can safely write session data to the same `USER_CACHE_DIR` without corrupting the database.
  * **Module-Reload Persistence:** Under Apache, processes are spawned and recycled periodically. If the cache was cleared on module initialisation, a recycled worker process would wipe out all user-session caches. The application prevents this by specifically disabling cache clearing during imports when running in production.

---

## 3. Caching Flows & Comparison Summary

| Feature | TESS/ASAS-SN Public Cache | User Session Private Cache (`user_cache`) |
| :--- | :--- | :--- |
| **Target Data** | Public MAST / ASAS-SN physical files, metadata, queries. | User uploads, phase folding state, deleted points, current view state. |
| **Storage Medium** | Dill / Pickled frames, raw `.fits` files. | SQLite database via `diskcache`. |
| **Access Key** | Deterministic MD5 hash of query arguments. | Unique, browser-persisted `user_tab_id` (UUID). |
| **Sharing** | Publicly shared across all user sessions. | Private to each browser tab/session. |
| **Expiration** | Infinite (data is immutable). | Sliding 24-hour expiration window. |
| **Apache Safety** | Read-only access after initial fetch. | Safe multi-process locking handled by SQLite WAL. |

---

## 4. Robust Implementation & Concurrency Safety Enhancements

To prevent severe potential issues (such as concurrent write corruption, directory absence, non-deterministic keys, and corrupted cache exceptions), the Public Data Caching layers implement the following production-grade practices:

### A. Atomic Writes (OS-Level Safety)
Standard file writing with `open()`, `dill.dump()`, or `DataFrame.to_pickle()` is not atomic. If two concurrent Apache workers attempt to write to the same cache file simultaneously, or if a write is interrupted, the cache file becomes corrupted. 
To prevent this, we write to a temporary file (`tempfile.NamedTemporaryFile`) within the *same* target cache directory, and then perform an atomic rename using `os.replace`. Because `os.replace` is atomic at the OS kernel level on POSIX filesystems, concurrent reads will only ever see either the old file or the fully written new file—never a partially written or corrupted one.

### B. Safe Temporary Workspaces
During complex serialization tasks (such as saving zipped lightcurve collections), writing temporary files directly to the current working directory creates high risk of collision or permission issues under Apache. The cache now uses process-isolated workspaces via `tempfile.TemporaryDirectory()`, which are automatically cleaned up on completion.

### C. Self-Healing Reads (Corruption Interception)
If a cached `.fits` or `.pkl` file becomes corrupted (e.g. from an incomplete previous download or manual tampering), subsequent loads will catch reader exceptions, log warnings, delete the corrupted file from disk, and return `None` (cache miss). This ensures that the application recovers automatically by triggering a fresh download of the public data.

### D. Deterministic Parameter Keying
Hashing arbitrary keyword arguments using `str(kwargs)` is non-deterministic because dictionary element insertion order can theoretically vary across Python runs, or nested elements might serialize differently. The keying mechanism now sorts the parameters recursively/deterministically (`str(sorted(kwargs.items()))`) before generating MD5 hashes, ensuring stable cache lookup addresses.

### E. Smarter Tolerance-Aware Coordinates Lookup & Normalization
To prevent unnecessary duplicate downloads caused by minor coordinate adjustments or querying the same region using different designations (such as looking up by coordinates versus looking up by a star's name), the caching mechanism parses and normalizes targets into physical astronomical coordinates (`astropy.coordinates.SkyCoord`).
- **Coordinate-Aware Filenames:** Filenames for public caches automatically encode parsed coordinates, e.g. `{prefix}_ra_{ra:.6f}_dec_{dec:.6f}_[non_coordinate_hash].{ext}`.
- **Pole-Safe Angular Separation:** When fetching items from the cache, the directory is scanned and candidate cached coordinates are compared using `SkyCoord.separation()`. This calculates exact angular separation on a sphere, remaining perfectly robust even near celestial convergence zones (the celestial poles).
- **Tolerances:** The lookup uses a configurable coordinate separation tolerance (`COORD_TOLERANCE_DEG = 0.02` degrees, approx 1.2 arcminutes) and cutout field size tolerance (`SIZE_TOLERANCE = 1` pixel) to resolve and reuse matching cached records.
- **Explicit Cache/Remote State Logging:** Every "Search Sector" and "Download Sector" operation explicitly reports its cache status (`[CACHE HIT]` vs `[CACHE MISS]`) to standard output and log files, clearly outlining whether the operation retrieved local cached files or performed remote MAST / SkyPatrol downloads.

### F. Cache Eviction / Clean Cache Action
Because archives constantly acquire new observations (new TESS sectors) and disk files might occasionally suffer from corruption, a dedicated **Clean Cache** button is integrated into the user interface:
- **Clean Cache UI Action:** Users can click the "Clean Cache" button in the Search panel next to standard controls.
- **Thorough Target Eviction:** Behind the scenes, `cache.delete_target_cache` is invoked with the target coordinates/name. It scans the cache directory and deletes all files whose encoded coordinates fall within the `COORD_TOLERANCE_DEG` distance. It also computes fallback hashes for the exact target signature and removes those, completely evicting any stale sector list files (`tpf`, `ffi`), pixel data arrays (`tpf_data`, `ffi_data`), and curves (`lc`) associated with that region.
- **Interactive Feedback:** Returns real-time user notification (using a bootstrap `info` alert) reporting the exact number of cache files removed from the server.

