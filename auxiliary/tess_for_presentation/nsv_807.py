"""
Inspect FFI (TESSCut) and TPF/SPOC-lightcurve cadence/exposure metadata
for TIC 35119266, Sector 30.

Requires: pip install lightkurve
"""

import lightkurve as lk

TARGET = "TIC 35119266"
SECTOR = 30

# Header/metadata keys worth checking for cadence/exposure info.
# (Not all products carry all of these -- we print whatever is present.)
CADENCE_KEYS = [
    "TELAPSE",   # [days] time elapsed = TSTOP - TSTART
    "EXPOSURE",  # [days] effective exposure time (after CR-mitigation loss)
    "TIMEDEL",   # [days] time resolution / cadence step
    "INT_TIME",  # [s] photon integration time per frame
    "READTIME",  # [s] readout time per frame
    "FRAMETIM",  # [s] frame time (INT_TIME + READTIME)
    "NUM_FRM",   # number of frames co-added per cadence
    "NREADOUT",  # number of readouts (alt. keyword some products use)
    "TSTART",
    "TSTOP",
]


def print_header_keys(header, label):
    print(f"\n--- {label} ---")
    found_any = False
    for key in CADENCE_KEYS:
        if key in header:
            print(f"  {key:10s} = {header[key]}")
            found_any = True
    if not found_any:
        print("  (none of the tracked keys found in this header)")


# ---------------------------------------------------------------------
# 1) FFI / TESSCut
# ---------------------------------------------------------------------
print("=" * 70)
print(f"Searching all FFI (TESSCut) availability for {TARGET}")
print("=" * 70)
ffi_search = lk.search_tesscut(TARGET)
print(ffi_search)

print(f"\nDownloading Sector {SECTOR} FFI cutout...")
ffi_search_s = lk.search_tesscut(TARGET, sector=SECTOR)
ffi_tpf = ffi_search_s.download(cutout_size=15)  # returns a TessTargetPixelFile
print(ffi_tpf)

# Metadata: primary header + first extension header (pixel data) can both
# carry different keys depending on product/version, so check both.
print_header_keys(ffi_tpf.hdu[0].header, "FFI cutout - primary header")
print_header_keys(ffi_tpf.hdu[1].header, "FFI cutout - extension header")

ffi_tpf.plot(frame=0)
# If running interactively, add plt.show(); in a script, save instead:
# import matplotlib.pyplot as plt
# plt.savefig("ffi_sector30_cutout.png", dpi=150, bbox_inches="tight")


# ---------------------------------------------------------------------
# 2) TPFs (all authors/sectors), then Sector 30 SPOC light curve
# ---------------------------------------------------------------------
print("\n" + "=" * 70)
print(f"Searching all TPFs for {TARGET}")
print("=" * 70)
tpf_search = lk.search_targetpixelfile(TARGET)
print(tpf_search)

print(f"\nSearching Sector {SECTOR} SPOC light curve for {TARGET}")
lc_search = lk.search_lightcurve(TARGET, sector=SECTOR, author="SPOC")
print(lc_search)

lc = lc_search.download()
print(lc)

print_header_keys(lc.meta, "Sector 30 SPOC light curve - metadata")

lc.plot()
# import matplotlib.pyplot as plt
# plt.savefig("lc_sector30_spoc.png", dpi=150, bbox_inches="tight")
