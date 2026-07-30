import math

import healpy as hp
import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u


# -----------------------------------------------------------------------------
# Approximate angular size (degrees) of a HEALPix pixel.
# This is the square root of the pixel area.
# -----------------------------------------------------------------------------
def healpix_pixel_size_deg(level):
    """
    Approximate linear size of a HEALPix pixel in degrees.

    Parameters
    ----------
    level : int
        HEALPix order (0...12)

    Returns
    -------
    float
        Approximate pixel size in degrees.
    """
    nside = 2 ** level
    area_sr = hp.nside2pixarea(nside)
    area_deg2 = area_sr * (180.0 / np.pi) ** 2

    return math.sqrt(area_deg2)


# -----------------------------------------------------------------------------
# Choose a suitable HEALPix level.
# -----------------------------------------------------------------------------
# Parameters controlling the optimisation:
# We prefer to have approximately this many HEALPix pixels.
TARGET_PIXEL_COUNT = 4

# Never use a level finer than Gaia's.
MAX_LEVEL = 12

# Start with a very coarse tessellation.

def choose_healpix_level(ra_deg, dec_deg, radius_deg):
    """
        Choose a HEALPix level that produces a reasonable number of
        intersected pixels.

        Parameters
        ----------
        ra_deg : float
        dec_deg : float
        radius_deg : float

        Returns
        -------
        level : int
            Selected HEALPix level.

        pixels : list[int]
            Pixels intersecting the cone at the selected level.
    """

    coord = SkyCoord(
        ra=ra_deg * u.deg,
        dec=dec_deg * u.deg,
        frame="icrs"
    )

    theta = np.radians(90.0 - coord.dec.degree)
    phi = np.radians(coord.ra.degree)
    vec = hp.ang2vec(theta, phi)

    print()
    print("Searching optimal HEALPix level")
    print("--------------------------------")

    for level in range(MAX_LEVEL, -1, -1):  # Go up-down
        nside = 2 ** level
        pixels = hp.query_disc(
            nside=nside,
            vec=vec,
            radius=np.radians(radius_deg),
            inclusive=True,
            nest=True       # Gaia uses nested HEALPix 
        )
        npixels = len(pixels)
        print(
            f"Level {level:2d}: "
            f"{npixels:4d} intersected pixels"
        )
        # Perfect solution:
        if len(pixels) <= TARGET_PIXEL_COUNT:
            print(f"--> selected level {level}")
            break
    print(f"--> selected level {level} pruduces {len(pixels)} pixels")
    return level, sorted(pixels)    # we alwais are able to fallback to 12-level (Gaia)

    """
    Choose the coarsest HEALPix level whose pixels are not much larger
    than the search radius.

    Returns
    -------
    int
        HEALPix level (0...12)
    """

    # We compare with the radius, not diameter.
    # Feel free to change the criterion later.

    for level in range(13):

        pixel_size = healpix_pixel_size_deg(level)

        if pixel_size <= radius_deg:
            return level

    return 12

# Convert one HEALPix pixel at level L into Gaia source_id interval

def healpix_to_gaia_interval(pixel, level):
    """
    Convert one HEALPix pixel of arbitrary level into the corresponding
    Gaia source_id interval.

    Parameters
    ----------
    pixel : int
        HEALPix pixel number at 'level'.

    level : int
        HEALPix level.

    Returns
    -------
    (int, int)
        (source_id_min, source_id_max)
    """

    # Number of additional HEALPix bits needed to reach level 12.
    hp_shift = 2 * (12 - level)

    # First and last level-12 descendant pixels.
    hp12_min = pixel << hp_shift
    hp12_max = ((pixel + 1) << hp_shift) - 1

    # Gaia stores level-12 pixel shifted by 35 bits.
    source_id_min = hp12_min << 35
    source_id_max = ((hp12_max + 1) << 35) - 1

    return source_id_min, source_id_max


# -----------------------------------------------------------------------------
# Main routine.
# -----------------------------------------------------------------------------
def cone_to_gaia_intervals(ra_deg, dec_deg, radius_deg):
    """
        Compute Gaia source_id intervals roughly covering a cone search.

        Parameters
        ----------
        ra_deg : float
            Right Ascension (degrees)

        dec_deg : float
            Declination (degrees)

        radius_deg : float
            Cone radius (degrees)

        Returns
        -------
        list
            List of tuples

            [
                (source_id_min, source_id_max),
                ...
            ]
    """

    print()
    print("=" * 70)
    print("Cone search")
    print("=" * 70)

    print(f"RA     : {ra_deg:.6f} deg")
    print(f"Dec    : {dec_deg:.6f} deg")
    print(f"Radius : {radius_deg:.6f} deg")

    # -----------------------------------------------------------------
    # Choose HEALPix level.
    # -----------------------------------------------------------------

    level, pixels = choose_healpix_level(ra_deg, dec_deg, radius_deg)

    print()
    print(f"Chosen HEALPix level : {level}")
    print(
        f"Approx. pixel size   : "
        f"{healpix_pixel_size_deg(level):.4f} deg"
    )


    print()
    print(f"Intersected level-{level} pixels ({len(pixels)}):")
    print(pixels)

    intervals = []

    print()
    print("Conversion:")

    hp_shift = 2 * (12 - level)

    for pixel in pixels:

        hp12_min = pixel << hp_shift
        hp12_max = ((pixel + 1) << hp_shift) - 1

        source_min, source_max = healpix_to_gaia_interval(
            pixel,
            level,
        )

        print(
            f"Pixel {pixel}"
            f" --> level12 [{hp12_min} .. {hp12_max}]"
            f" --> Gaia BETWEEN {source_min} AND {source_max}"
        )

        intervals.append((source_min, source_max))

    print()
    print(f"Returned {len(intervals)} Gaia intervals.")
    print("=" * 70)

    return intervals

intervals = cone_to_gaia_intervals(
    ra_deg=346.345,
    dec_deg=47.676,
    radius_deg=10,
)
