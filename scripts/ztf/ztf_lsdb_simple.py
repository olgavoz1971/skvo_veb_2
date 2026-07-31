import lsdb
from dask.distributed import Client
import os

ztf_lc_catalog = lsdb.open_catalog(
    "s3://ipac-irsa-ztf/ztf/enhanced/dr24/lc/hats",
    columns=["objectid", "objra", "objdec", "filterid", "nepochs", "lightcurve"],
)

# find the indexed column name (it's 'objectid' for Lightcurves)
idx_col = list(ztf_lc_catalog.hc_collection.all_indexes.keys())[0]

# oids from your earlier discovery step (objects table cone search, crossmatch, etc.)
object_ids = [686103400034440, 686103400106565]

lcs = ztf_lc_catalog.id_search(values={idx_col: object_ids})

with Client(n_workers=min(os.cpu_count(), lcs.npartitions + 1),
            threads_per_worker=1, memory_limit=None) as client:
    lcs_df = lcs.compute()
print(lcs_df)
