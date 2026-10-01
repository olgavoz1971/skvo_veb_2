"""
Build an animated GIF "flipbook" from TESS TPF cutout frames --
one page per cadence -- for TIC 35119266, Sector 30, SPOC 120-s cadence.

Requires: pip install lightkurve pillow
No external GIF tools (ffmpeg/imagemagick) are needed: matplotlib's
built-in 'pillow' animation writer encodes the GIF directly via the
Pillow library.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import lightkurve as lk
from astropy.visualization import ImageNormalize, AsinhStretch, ZScaleInterval

TARGET = "TIC 35119266"
SECTOR = 30

# --- flipbook settings ---
N_FRAMES = 100      # how many cadences to include (None-like: just slice a lot if you want all)
FRAME_STEP = 10     # use every Nth cadence; raise this to cover more time per gif
FPS = 8            # playback speed
# OUTPUT_GIF = "tic35119266_s30_tpf_flipbook.gif"
OUTPUT_GIF = "tic35119266_s30_tpf_flipbook_100.gif"

# ---------------------------------------------------------------------
# Download the 120-s SPOC TPF
# ---------------------------------------------------------------------
print(f"Searching Sector {SECTOR} SPOC TPF (120 s) for {TARGET}...")
search = lk.search_targetpixelfile(TARGET, sector=SECTOR, author="SPOC", exptime=120)
print(search)

tpf = search.download()
print(tpf)

# tpf.flux has shape (n_cadences, n_rows, n_cols), units e-/s
flux = tpf.flux.value
n_total = flux.shape[0]

idx = np.arange(0, n_total, FRAME_STEP)
if N_FRAMES is not None:
    idx = idx[:N_FRAMES]

print(f"Building flipbook from {len(idx)} of {n_total} available cadences "
      f"(step={FRAME_STEP})")

# ---------------------------------------------------------------------
# Fix one color scale across all frames -- otherwise each frame
# autoscales independently and brightness changes look artificial.
# ---------------------------------------------------------------------
#vmin, vmax = np.nanpercentile(flux[idx], [5, 99])
#
# fig, ax = plt.subplots(figsize=(5, 5))
# im = ax.imshow(flux[idx[0]], origin="lower", vmin=vmin, vmax=vmax, cmap="viridis")
# title = ax.set_title("")
# ax.set_xlabel("Column")
# ax.set_ylabel("Row")
# fig.colorbar(im, ax=ax, label="Flux (e-/s)")


# Compute the normalization ONCE, from the whole frame stack (not per-frame!),
# so real background brightening over time stays visible rather than being
# renormalized away frame by frame.
norm = ImageNormalize(flux[idx[:100]], interval=ZScaleInterval(), stretch=AsinhStretch(a=0.01))

fig, ax = plt.subplots(figsize=(5, 5))
im = ax.imshow(flux[idx[0]], origin="lower", norm=norm, cmap="viridis")
title = ax.set_title("")
# ax.set_xlabel("Column")
# ax.set_ylabel("Row")
# fig.colorbar(im, ax=ax, label="Flux (e-/s)")


def update(frame_i):
    im.set_data(flux[frame_i])
    t = tpf.time.value[frame_i]
#    title.set_text(f"{TARGET}  Sector {SECTOR}  cadence {frame_i}  t={t:.3f} BTJD")
    title.set_text(f"{frame_i}  t={t:.3f} BTJD")
    return [im, title]


ani = animation.FuncAnimation(fig, update, frames=idx, blit=False)

print(f"Writing {OUTPUT_GIF} ...")
ani.save(OUTPUT_GIF, writer="pillow", fps=FPS)
print("Done.")
