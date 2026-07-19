"""Generic TAP query transport for lightcurve discovery providers."""

from skvo_veb.lc_providers.tap.client import run_tap_sync_query
from skvo_veb.lc_providers.tap.dialect import TapQueryDialect

__all__ = ["TapQueryDialect", "run_tap_sync_query"]
