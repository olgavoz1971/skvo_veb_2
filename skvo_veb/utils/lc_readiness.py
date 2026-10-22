"""Readiness report for a freshly ingested lightcurve (Ticket 34).

Collects, as plain JSON-safe data, what the file left undeclared or malformed:
time system gaps, unit findings, calibration gaps for mag-flux conversion, and the
suggested values for exactly those gaps. Nothing is applied here; the UI shows the
report and the user decides.
"""

from __future__ import annotations

import logging

from volightcurve import VOLightCurve
from volightcurve.suggestions import SUGGESTION_REASONS, suggestions_for_missing

logger = logging.getLogger(__name__)

READINESS_KEY_TIME = "time_problems"
READINESS_KEY_UNITS = "unit_findings"
READINESS_KEY_CONVERSION = "conversion_problems"
READINESS_KEY_SUGGESTIONS = "suggestions"


def readiness_report(volc: VOLightCurve, phot_col: str | None = None) -> dict:
    """Builds the readiness report of a parsed lightcurve. Changes nothing.

    Args:
        volc (VOLightCurve): Parsed lightcurve.
        phot_col (str, optional): Photometry column in use. When given, the conversion
            check and the suggestions cover only that column.

    Returns:
        dict: JSON-safe report with ``time_problems`` (list of sentences),
            ``unit_findings`` (key to list of sentences), ``conversion_problems``
            (list of sentences for ``phot_col``, empty without it) and ``suggestions``
            (``time_system`` and ``calibration`` values with a ``reasons`` map). Empty
            parts are empty containers, so the report is always complete.
    """
    unit_findings: dict[str, list[str]] = {}
    for key, report in volc.check_units().items():
        unit_findings[key] = [*report.errors, *report.notes]

    conversion = volc.conversion_problems(phot_col) if phot_col else []

    suggestions = suggestions_for_missing(volc)
    if phot_col and "calibration" in suggestions:
        own = suggestions["calibration"].get(phot_col)
        if own:
            suggestions["calibration"] = {phot_col: own}
        else:
            suggestions.pop("calibration")
    if suggestions:
        suggestions["reasons"] = dict(SUGGESTION_REASONS)

    return {
        READINESS_KEY_TIME: volc.time_problems(),
        READINESS_KEY_UNITS: unit_findings,
        READINESS_KEY_CONVERSION: conversion,
        READINESS_KEY_SUGGESTIONS: suggestions,
    }
