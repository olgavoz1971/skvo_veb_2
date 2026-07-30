import healpy as hp
import numpy as np
import random
from pyvo.dal import TAPService

RA, DEC, RADIUS = 346.34518681105993, 47.676310843299994, 50.0
TARGET_N = 150
ROWS_PER_PIXEL = 3
N_PIXELS = max(1, TARGET_N // ROWS_PER_PIXEL)

vec = hp.ang2vec(np.radians(90 - DEC), np.radians(RA))

# pick the coarsest HEALPix level that still gives us enough overlapping pixels
for level in range(0, 13):
    nside = 2**level
    pix_list = hp.query_disc(nside, vec, np.radians(RADIUS), nest=True, inclusive=True)
    if len(pix_list) >= N_PIXELS or level == 12:
        break

chosen = random.sample(list(pix_list), min(N_PIXELS, len(pix_list)))
shift = 2**35 * 4**(12 - level)   # source_id span of one pixel at this level

subqueries = [
    f"""SELECT * FROM (
        SELECT TOP {ROWS_PER_PIXEL} source_id, ra, dec, phot_g_mean_mag, random_index
        FROM gaiadr3.gaia_source
        WHERE source_id BETWEEN {p*shift} AND {(p+1)*shift - 1}
          AND 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {RA}, {DEC}, {RADIUS}))
        ORDER BY random_index
    ) AS sub"""
    for p in chosen
]
query = "\nUNION ALL\n".join(subqueries)

service = TAPService("https://gaia.aip.de/tap")
job = service.submit_job(query)
job.run(); job.wait()
result = job.fetch_result().to_table()
print(result)