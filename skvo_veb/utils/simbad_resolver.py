"""Shared Simbad name resolution for multi-mission catalogue search."""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass

from astropy import units as u
from astropy.coordinates import SkyCoord

from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

_CONNECTIVITY_MESSAGE_HINTS = (
    "network is unreachable",
    "name or service not known",
    "connection refused",
    "connection reset",
    "timed out",
    "timeout",
    "no route to host",
    "temporary failure in name resolution",
    "failed to establish a new connection",
    "max retries exceeded",
    "nodename nor servname provided",
    "getaddrinfo failed",
    "errno 101",
    "errno 110",
    "errno 111",
)


@dataclass(frozen=True)
class SimbadResolveResult:
    """Normalised Simbad response for search orchestration.

    Attributes:
        query_name (str): User-supplied name passed to Simbad.
        main_id (str): Simbad main identifier (preferred retry label).
        identifiers (tuple[str, ...]): Cross-identifiers returned by Simbad.
        ra_deg (float): ICRS right ascension in degrees.
        dec_deg (float): ICRS declination in degrees.
    """

    query_name: str
    main_id: str
    identifiers: tuple[str, ...]
    ra_deg: float
    dec_deg: float


def _is_connectivity_error(exc: BaseException) -> bool:
    """Returns whether an exception indicates network failure rather than no match.

    Args:
        exc (BaseException): Exception raised by Simbad, Sesame, or HTTP clients.

    Returns:
        bool: ``True`` when the failure is likely due to connectivity.
    """
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, OSError) and not isinstance(exc, FileNotFoundError):
        return True

    try:
        import requests

        if isinstance(exc, requests.exceptions.RequestException):
            return True
    except ImportError:
        pass

    try:
        from urllib.error import URLError

        if isinstance(exc, URLError):
            return True
    except ImportError:
        pass

    message = str(exc).lower()
    if any(hint in message for hint in _CONNECTIVITY_MESSAGE_HINTS):
        return True

    cause = exc.__cause__
    if cause is not None and cause is not exc:
        return _is_connectivity_error(cause)
    return False


def _table_column(row, *names: str):
    """Returns the first matching table column, accepting legacy and TAP names.

    Args:
        row: Astropy table row.
        *names (str): Candidate column names (case-insensitive).

    Returns:
        Any: Cell value for the first name found in ``row``.

    Raises:
        KeyError: When none of the names exist on the row.
    """
    index = {column.lower(): column for column in row.colnames}
    for name in names:
        column = index.get(name.lower())
        if column is not None:
            return row[column]
    raise KeyError(names[0])


def _skycoord_from_simbad_row(row) -> SkyCoord:
    """Builds an ICRS ``SkyCoord`` from a Simbad ``query_object`` row.

    Args:
        row: Astropy table row from ``Simbad.query_object``.

    Returns:
        SkyCoord: Parsed ICRS coordinates.

    Raises:
        KeyError: When RA/Dec columns are missing.
        astropy.units.UnitsError: When coordinate values cannot be parsed.
    """
    ra_value = _table_column(row, "ra", "RA")
    dec_value = _table_column(row, "dec", "DEC")
    try:
        return SkyCoord(
            ra=ra_value,
            dec=dec_value,
            unit=(u.deg, u.deg),
            frame="icrs",
        )
    except (u.UnitConversionError, TypeError, ValueError):
        return SkyCoord(
            ra=ra_value,
            dec=dec_value,
            unit=(u.hourangle, u.deg),
            frame="icrs",
        )


def _raise_simbad_resolution_failure(
    query: str,
    *,
    connectivity_errors: list[BaseException],
    last_error: BaseException | None,
) -> None:
    """Raises a user-facing resolution error with an accurate cause.

    Args:
        query (str): User-supplied target name.
        connectivity_errors (list[BaseException]): Network-related failures seen.
        last_error (BaseException, optional): Final exception from Sesame fallback.

    Raises:
        PipeException: When Simbad/Sesame resolution cannot complete.
    """
    if connectivity_errors:
        raise PipeException(
            f"Cannot reach Simbad or Sesame to resolve '{query}'. "
            "Check your network connection and try again."
        ) from (last_error or connectivity_errors[-1])

    raise PipeException(
        f"Object '{query}' was not found in Simbad or Sesame."
    ) from last_error


def resolve_simbad_name(name: str) -> SimbadResolveResult:
    """Resolves an object name through Simbad (with Sesame fallback for coordinates).

    Args:
        name (str): Catalogue name or alias entered by the user.

    Returns:
        SimbadResolveResult: Main id, identifier list, and ICRS coordinates.

    Raises:
        PipeException: When the name is empty, the archive is unreachable, or the
            name cannot be resolved.
    """
    query = str(name or "").strip()
    if not query:
        raise PipeException("Target name is empty.")

    from astroquery.simbad import Simbad

    logger.info("Simbad resolve started for %r.", query)
    main_id = query
    identifiers: list[str] = []
    coord: SkyCoord | None = None
    connectivity_errors: list[BaseException] = []

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        try:
            logger.info("Simbad query_object(%r) …", query)
            object_table = Simbad.query_object(query)
            if object_table is not None and len(object_table) > 0:
                row = object_table[0]
                main_id = str(_table_column(row, "main_id", "MAIN_ID"))
                coord = _skycoord_from_simbad_row(row)
                logger.info(
                    "Simbad query_object resolved %r → main_id=%r RA=%.5f° Dec=%.5f°.",
                    query,
                    main_id,
                    float(coord.ra.deg),
                    float(coord.dec.deg),
                )
            else:
                logger.info("Simbad query_object returned no rows for %r.", query)
        except Exception as exc:
            if _is_connectivity_error(exc):
                connectivity_errors.append(exc)
            logger.warning("Simbad query_object failed for %r: %s", query, exc)

        try:
            logger.info("Simbad query_objectids(%r) …", query)
            id_table = Simbad.query_objectids(query)
            if id_table is not None and len(id_table) > 0:
                identifiers = [
                    str(value) for value in _table_column(id_table, "id", "ID")
                ]
                logger.info(
                    "Simbad query_objectids returned %s identifier(s) for %r.",
                    len(identifiers),
                    query,
                )
                if main_id == query and identifiers:
                    main_id = identifiers[0]
            else:
                logger.info("Simbad query_objectids returned no rows for %r.", query)
        except Exception as exc:
            if _is_connectivity_error(exc):
                connectivity_errors.append(exc)
            logger.warning("Simbad query_objectids failed for %r: %s", query, exc)

    if coord is None:
        sesame_error: BaseException | None = None
        try:
            logger.info(
                "Simbad coordinates missing for %r; trying Sesame (SkyCoord.from_name) …",
                query,
            )
            coord = SkyCoord.from_name(query)
            logger.info("Resolved %r via Sesame/SkyCoord.from_name fallback.", query)
        except Exception as exc:
            sesame_error = exc
            if _is_connectivity_error(exc):
                connectivity_errors.append(exc)
            logger.warning("Sesame fallback failed for %r: %s", query, exc)
            _raise_simbad_resolution_failure(
                query,
                connectivity_errors=connectivity_errors,
                last_error=sesame_error,
            )

    unique_ids = tuple(dict.fromkeys([main_id, *identifiers]))
    logger.info(
        "Simbad resolve finished for %r: main_id=%r identifiers=%s.",
        query,
        main_id,
        len(unique_ids),
    )
    return SimbadResolveResult(
        query_name=query,
        main_id=main_id,
        identifiers=unique_ids,
        ra_deg=float(coord.ra.deg),
        dec_deg=float(coord.dec.deg),
    )
