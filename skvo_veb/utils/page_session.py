"""Helpers for persisting Dash page state across multi-page navigation."""

import pandas as pd

# Use on dcc.Store so values survive leaving and returning to a page.
SESSION_STORE = dict(storage_type='session')


def table_rows_from_lk_search_dict(search_store, *, include_distance=False):
    """Rebuild AgGrid rowData from a serialized Lightkurve search_result dict."""
    if not search_store or 'search_result' not in search_store:
        return None

    df = pd.DataFrame.from_dict(search_store['search_result'])
    rows = []
    for _, row in df.iterrows():
        item = {
            '#': row['#'],
            'mission': row['mission'],
            'year': row['year'],
            'target': row.get('target_name', row.get('target')),
            'author': row['author'],
            'exptime': row['exptime'],
        }
        if include_distance and 'distance' in row.index:
            item['distance'] = row['distance']
        rows.append(item)
    return rows
