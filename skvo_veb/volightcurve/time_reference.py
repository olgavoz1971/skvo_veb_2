"""TIMESYS resolution and time-origin conversions for VO lightcurves."""

from __future__ import annotations

from typing import TYPE_CHECKING

from skvo_veb.utils.lc_config import JD_TO_MJD, TIME_OFFSET_ABSOLUTE_JD_THRESHOLD

if TYPE_CHECKING:
    from skvo_veb.volightcurve.lightcurve import TimeSys, VOLightCurve


def extract_timesys_registry_from_astropy(vot_file) -> dict[str, TimeSys]:
    """Builds a ``TIMESYS/@ID`` registry from an astropy VOTable tree.

    Args:
        vot_file: Parsed ``astropy.io.votable.tree.VOTableFile``.

    Returns:
        dict[str, TimeSys]: Mapping of TIMESYS identifier to parsed metadata.
    """
    from skvo_veb.volightcurve.lightcurve import TimeSys

    registry: dict[str, TimeSys] = {}
    for res in vot_file.resources:
        for ts in res.time_systems or []:
            ts_id = ts.ID or "ts"
            try:
                timeorigin = float(ts.timeorigin) if ts.timeorigin is not None else 0.0
            except (TypeError, ValueError):
                timeorigin = 0.0
            registry[ts_id] = TimeSys(
                refposition=ts.refposition or "HELIOCENTER",
                timeorigin=timeorigin,
                timescale=ts.timescale or "UTC",
            )
    return registry


def extract_field_timesys_refs_from_astropy(vot_file) -> dict[str, str]:
    """Maps TABLE field names to their ``TIMESYS`` reference identifiers.

    Args:
        vot_file: Parsed ``astropy.io.votable.tree.VOTableFile``.

    Returns:
        dict[str, str]: Field name to TIMESYS ``ID`` (from ``FIELD/@ref``).
    """
    refs: dict[str, str] = {}
    table = vot_file.get_first_table()
    if table is None:
        return refs
    for field in table.fields:
        if field.name and field.ref:
            refs[field.name] = str(field.ref)
    return refs


def extract_param_timesys_refs_from_astropy(vot_file) -> dict[str, str | None]:
    """Maps TABLE PARAM names to optional ``TIMESYS`` reference identifiers.

    Args:
        vot_file: Parsed ``astropy.io.votable.tree.VOTableFile``.

    Returns:
        dict[str, str or None]: Param name to TIMESYS ``ID`` when ``PARAM/@ref`` is set.
    """
    refs: dict[str, str | None] = {}
    table = vot_file.get_first_table()
    if table is None:
        return refs
    for param in table.params or []:
        if param.name:
            ref = getattr(param, "ref", None)
            refs[param.name] = str(ref) if ref else None
    return refs


def resolve_observation_timesys(volc: VOLightCurve) -> TimeSys:
    """Resolves the TIMESYS shared by observation-time columns (``ucd=time.epoch``).

    When a single time column references a TIMESYS, that system is returned. When
    several time columns are present they must all reference the same ``timeorigin``;
    otherwise an error is raised.

    Args:
        volc (VOLightCurve): Parsed lightcurve product.

    Returns:
        TimeSys: Shared time system for observation epochs.

    Raises:
        ValueError: When time columns disagree on ``timeorigin`` or none are found.
    """
    from skvo_veb.volightcurve.lightcurve import TimeSys, get_time_colnames

    time_cols = get_time_colnames(volc.table)
    if not time_cols:
        for fallback in ("obs_time", "time", "jd", "mjd"):
            if fallback in volc.table.colnames:
                time_cols = [fallback]
                break
    if not time_cols:
        raise ValueError("No observation time column found for TIMESYS resolution.")

    registry = getattr(volc, "timesys_by_id", None) or {}
    field_refs = getattr(volc, "field_timesys_ref", None) or {}
    default_ts = volc.timesys or TimeSys()
    resolved: list[TimeSys] = []

    for col in time_cols:
        ref_id = field_refs.get(col)
        if ref_id and ref_id in registry:
            resolved.append(registry[ref_id])
        elif ref_id and ref_id not in registry:
            raise ValueError(
                f"Time column {col!r} references unknown TIMESYS {ref_id!r}."
            )
        else:
            resolved.append(default_ts)

    origins = {float(ts.timeorigin or 0.0) for ts in resolved}
    if len(origins) > 1:
        raise ValueError(
            "Multiple time columns reference different TIMESYS timeorigin values."
        )
    return resolved[0]


def resolve_timesys_for_table_param(volc: VOLightCurve, param_name: str) -> TimeSys:
    """Resolves TIMESYS metadata for a TABLE PARAM holding a time epoch.

    Uses an explicit ``PARAM/@ref`` when present; otherwise assumes the same TIMESYS
    as the sole (or uniquely consistent) observation-time column.

    Args:
        volc (VOLightCurve): Parsed lightcurve product.
        param_name (str): TABLE PARAM name (e.g. ``epoch``).

    Returns:
        TimeSys: Time system governing the parameter value.

    Raises:
        ValueError: When references are missing or ambiguous.
    """
    param_refs = getattr(volc, "param_timesys_ref", None) or {}
    registry = getattr(volc, "timesys_by_id", None) or {}
    ref_id = param_refs.get(param_name)
    if ref_id:
        if ref_id not in registry:
            raise ValueError(
                f"PARAM {param_name!r} references unknown TIMESYS {ref_id!r}."
            )
        return registry[ref_id]
    return resolve_observation_timesys(volc)


def time_offset_to_absolute_jd(raw_value: float, timeorigin: float) -> float:
    """Converts a VOTable time offset to absolute Julian Date.

    Values above ``TIME_OFFSET_ABSOLUTE_JD_THRESHOLD`` are treated as already
    absolute Julian dates (legacy catalogues sometimes store full JD).

    Args:
        raw_value (float): Stored PARAM or column value.
        timeorigin (float): ``TIMESYS/@timeorigin`` for the linked system.

    Returns:
        float: Absolute Julian Date.
    """
    value = float(raw_value)
    if value >= TIME_OFFSET_ABSOLUTE_JD_THRESHOLD:
        return value
    return value + float(timeorigin or 0.0)


def absolute_jd_to_time_offset(absolute_jd: float, timeorigin: float) -> float:
    """Converts absolute Julian Date to a VOTable time offset for a TIMESYS.

    Args:
        absolute_jd (float): Absolute Julian Date used internally by CurveDash.
        timeorigin (float): Target ``TIMESYS/@timeorigin`` for export.

    Returns:
        float: Offset value such that ``absolute_jd = offset + timeorigin``.
    """
    return float(absolute_jd) - float(timeorigin or 0.0)


def normalise_table_epoch_to_absolute_jd(volc: VOLightCurve, raw_epoch) -> float | None:
    """Normalises a folding ``epoch`` TABLE PARAM to absolute Julian Date.

    Args:
        volc (VOLightCurve): Parsed lightcurve with TIMESYS cross-reference metadata.
        raw_epoch: Raw ``epoch`` PARAM value from ``table.meta``.

    Returns:
        float or None: Absolute Julian Date for CurveDash folding, or ``None`` when
            ``raw_epoch`` is absent.
    """
    if raw_epoch is None:
        return None
    timesys = resolve_timesys_for_table_param(volc, "epoch")
    return time_offset_to_absolute_jd(float(raw_epoch), timesys.timeorigin or 0.0)


def export_absolute_jd_as_time_offset(
    absolute_jd: float | None,
    *,
    timeorigin: float = JD_TO_MJD,
) -> float | None:
    """Serialises an absolute Julian Date using a target ``TIMESYS/@timeorigin``.

    Args:
        absolute_jd (float, optional): Absolute Julian Date from CurveDash metadata.
        timeorigin (float): Export ``TIMESYS/@timeorigin`` (default MJD standard).

    Returns:
        float or None: Offset suitable for ``PARAM name=\"epoch\"`` alongside
            ``obs_time`` written under the same TIMESYS.
    """
    if absolute_jd is None:
        return None
    return absolute_jd_to_time_offset(float(absolute_jd), timeorigin)
