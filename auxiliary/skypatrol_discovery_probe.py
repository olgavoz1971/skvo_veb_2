#!/usr/bin/env python3
"""Manual probe for ASAS-SN Sky Patrol discovery vs lightcurve download.

Use this script to inspect what ``SkyPatrolClient`` returns before wiring the
ASAS-SN lightcurve provider. Discovery-style calls use ``download=False``
(catalog metadata as a pandas DataFrame). Fetch-style calls use
``download=True`` (``LightCurveCollection`` with photometry).

Documentation:
http://asas-sn.ifa.hawaii.edu/documentation/pyasassn.html

Examples (from repository root, project venv active)::

    python auxiliary/skypatrol_discovery_probe.py cone \\
        --ra 346.345168 --dec 47.676292 --radius-arcsec 10

    python auxiliary/skypatrol_discovery_probe.py query-list-gaia \\
        --gaia-id 1936512041221649536

    python auxiliary/skypatrol_discovery_probe.py adql \\
        --sql "SELECT * FROM stellar_main WHERE gaia_id = 1936512041221649536 LIMIT 10"

Sky Patrol SQL uses PostgreSQL-style ``LIMIT``, not ADQL ``TOP``.

Discovery cone on ``stellar_main`` with explicit ``cols`` (not ``master_list``
defaults) can return ``pstarrs_g_mag`` in one ``cone_search(..., download=False)``
call — see ``STELLAR_MAIN_DISCOVERY_COLS`` below.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# AA And — same Gaia source used across Gaia debug / Discovery tests.
PRESET_AA_AND_GAIA_ID = 1936512041221649536
PRESET_AA_AND_RA_DEG = 346.3451680066482
PRESET_AA_AND_DEC_DEG = 47.676291847527416
PRESET_AA_AND_NAME = "AA And"

# Provider-oriented discovery: stellar_main + explicit columns (pyasassn default
# cone catalog is master_list with only asas_sn_id, ra_deg, dec_deg).
STELLAR_MAIN_DISCOVERY_CATALOG = "stellar_main"
STELLAR_MAIN_DISCOVERY_COLS: tuple[str, ...] = (
    "asas_sn_id",
    "ra_deg",
    "dec_deg",
    "pstarrs_g_mag",
)


def _column_list_from_arg(cols: str | None, *, use_discovery_defaults: bool) -> list[str] | None:
    """Parses ``--cols`` or applies discovery defaults for ``stellar_main``.

    Args:
        cols (str, optional): Comma-separated column names from the CLI.
        use_discovery_defaults (bool): When true and ``cols`` is omitted, return
            ``STELLAR_MAIN_DISCOVERY_COLS``.

    Returns:
        list[str] or None: Column list for ``cone_search`` / ``query_list``.
    """
    if cols:
        return [c.strip() for c in cols.split(",") if c.strip()]
    if use_discovery_defaults:
        return list(STELLAR_MAIN_DISCOVERY_COLS)
    return None


def _configure_logging(verbose: bool) -> None:
    """Initialises logging for interactive probe runs.

    Args:
        verbose (bool): When true, emit DEBUG records to stderr.
    """
    try:
        from skvo_veb.logging_config import configure_logging

        configure_logging()
    except ImportError:
        logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


def _stdout(section: str, body: str) -> None:
    """Writes a formatted block to stdout for manual inspection.

    Auxiliary probe scripts intentionally print human-readable reports;
    application modules should use logging instead.

    Args:
        section (str): Short heading for the report block.
        body (str): Body text (may be multi-line).
    """
    width = 72
    line = "=" * width
    sys.stdout.write(f"\n{line}\n{section}\n{line}\n{body}\n")
    if not body.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def _client(*, verbose: bool):
    """Constructs a ``SkyPatrolClient``.

    Args:
        verbose (bool): Passed to the client constructor when supported.

    Returns:
        SkyPatrolClient: Connected client instance.

    Raises:
        RuntimeError: When ``pyasassn`` is not installed.
    """
    try:
        from pyasassn.client import SkyPatrolClient
    except ImportError as exc:
        raise RuntimeError(
            "pyasassn is not installed in this environment. "
            "Activate the project venv and install dependencies."
        ) from exc
    return SkyPatrolClient(verbose=verbose)


def _type_label(value: Any) -> str:
    """Returns a readable type name for probe reports.

    Args:
        value (object): Returned Sky Patrol object.

    Returns:
        str: ``type.__name__`` with module when helpful.
    """
    kind = type(value)
    return f"{kind.__module__}.{kind.__name__}"


def _dataframe_report(df: pd.DataFrame, *, max_rows: int = 20) -> str:
    """Formats a pandas DataFrame for stdout inspection.

    Args:
        df (pandas.DataFrame): Catalog metadata frame.
        max_rows (int): Maximum rows to show in the sample table.

    Returns:
        str: Multi-line report string.
    """
    lines = [
        f"shape: {df.shape[0]} rows x {df.shape[1]} columns",
        f"columns ({len(df.columns)}): {list(df.columns)}",
        "",
        "dtypes:",
        df.dtypes.to_string(),
        "",
    ]
    if len(df) == 0:
        lines.append("(empty DataFrame)")
        return "\n".join(lines)

    sample = df.head(max_rows)
    lines.append(f"head (max {max_rows} rows):")
    lines.append(sample.to_string())
    lines.append("")
    lines.append("first row as JSON (NaN → null):")
    first = sample.iloc[0].where(pd.notnull(sample.iloc[0]), None)
    lines.append(json.dumps(first.to_dict(), indent=2, default=str))
    return "\n".join(lines)


def _lightcurve_collection_report(collection: Any, *, band_hint: str | None = None) -> str:
    """Formats a ``LightCurveCollection`` for stdout inspection.

    Args:
        collection: Object returned when ``download=True``.
        band_hint (str, optional): If set, summarise ``phot_filter`` for this band.

    Returns:
        str: Multi-line report string.
    """
    lines: list[str] = []
    catalog_info = getattr(collection, "catalog_info", None)
    if catalog_info is not None:
        if isinstance(catalog_info, pd.DataFrame):
            lines.append("catalog_info (DataFrame):")
            lines.append(_dataframe_report(catalog_info, max_rows=5))
        else:
            lines.append(f"catalog_info: {_type_label(catalog_info)}")
            lines.append(repr(catalog_info))
        lines.append("")

    data = getattr(collection, "data", None)
    if data is None:
        lines.append("No .data attribute on collection.")
        return "\n".join(lines)

    if isinstance(data, pd.DataFrame):
        lines.append("collection.data (single DataFrame):")
        lines.append(_dataframe_report(data, max_rows=15))
        if "phot_filter" in data.columns:
            lines.append("")
            lines.append(f"phot_filter value_counts:\n{data['phot_filter'].value_counts().to_string()}")
        if band_hint and "phot_filter" in data.columns:
            subset = data[data["phot_filter"] == band_hint]
            lines.append("")
            lines.append(f"rows with phot_filter == {band_hint!r}: {len(subset)}")
        return "\n".join(lines)

    lines.append(f"collection.data: {_type_label(data)} (not a flat DataFrame)")
    lines.append("Trying first light curve via itercurves() when available...")
    iterator = getattr(collection, "itercurves", None)
    if callable(iterator):
        try:
            first = next(iterator())
            lc_df = getattr(first, "data", first)
            if isinstance(lc_df, pd.DataFrame):
                lines.append(_dataframe_report(lc_df, max_rows=15))
                if "phot_filter" in lc_df.columns:
                    lines.append(
                        f"\nphot_filter value_counts:\n{lc_df['phot_filter'].value_counts().to_string()}"
                    )
        except StopIteration:
            lines.append("(itercurves empty)")
        except Exception as exc:
            lines.append(f"itercurves failed: {exc}")
    return "\n".join(lines)


def _report_result(label: str, result: Any, *, band_hint: str | None = None) -> None:
    """Logs and prints a unified report for any Sky Patrol return value.

    Args:
        label (str): Probe step description.
        result (object): Client return value.
        band_hint (str, optional): Band code for fetch reports.
    """
    logger.info("Probe %s returned %s", label, _type_label(result))
    header = f"{label}\nreturn type: {_type_label(result)}"

    if isinstance(result, pd.DataFrame):
        body = _dataframe_report(result)
    elif result is None:
        body = "(None)"
    elif hasattr(result, "data") or hasattr(result, "catalog_info"):
        body = _lightcurve_collection_report(result, band_hint=band_hint)
    else:
        body = textwrap.dedent(
            f"""
            Unhandled return type. repr (truncated):
            {repr(result)[:2000]}
            """
        ).strip()

    _stdout(header, body)


def run_cone_search(
    client: Any,
    *,
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    catalog: str,
    download: bool,
    cols: str | None,
    thin_cols: bool = False,
) -> None:
    """Runs ``SkyPatrolClient.cone_search`` and prints the result.

    Args:
        client: Sky Patrol client instance.
        ra_deg (float): Cone centre RA in degrees.
        dec_deg (float): Cone centre Dec in degrees.
        radius_arcsec (float): Cone radius in arcseconds.
        catalog (str): Input catalog name (use ``stellar_main`` for discovery mags).
        download (bool): Metadata-only vs full lightcurve download.
        cols (str, optional): Comma-separated column list, or ``None`` for discovery defaults.
        thin_cols (bool): When true, omit ``cols`` so the client uses its default trio.
    """
    if thin_cols:
        column_list = None
    else:
        column_list = _column_list_from_arg(cols, use_discovery_defaults=True)
    label = (
        f"cone_search(ra={ra_deg}, dec={dec_deg}, radius={radius_arcsec} arcsec, "
        f"catalog={catalog!r}, download={download}, cols={column_list})"
    )
    logger.info("Running %s", label)
    result = client.cone_search(
        ra_deg,
        dec_deg,
        radius_arcsec,
        units="arcsec",
        catalog=catalog,
        cols=column_list,
        download=download,
    )
    _report_result(label, result)


def run_query_list_gaia(
    client: Any,
    *,
    gaia_id: int,
    download: bool,
    cols: str | None,
) -> None:
    """Runs ``query_list`` on ``stellar_main`` by ``gaia_id``.

    Args:
        client: Sky Patrol client instance.
        gaia_id (int): Gaia DR3 source identifier.
        download (bool): Metadata-only vs photometry download.
        cols (str, optional): Comma-separated column list or discovery defaults.
    """
    column_list = _column_list_from_arg(cols, use_discovery_defaults=True)
    label = (
        f"query_list(gaia_id={gaia_id}, catalog='stellar_main', id_col='gaia_id', "
        f"download={download}, cols={column_list})"
    )
    logger.info("Running %s", label)
    result = client.query_list(
        [gaia_id],
        id_col="gaia_id",
        catalog="stellar_main",
        cols=column_list,
        download=download,
    )
    _report_result(label, result)


def run_adql(client: Any, *, sql: str, download: bool) -> None:
    """Runs ``SkyPatrolClient.adql_query``.

    Args:
        client: Sky Patrol client instance.
        sql (str): ADQL query string.
        download (bool): Metadata-only vs photometry download.
    """
    label = f"adql_query(download={download})\n{sql.strip()}"
    logger.info("Running ADQL download=%s", download)
    result = client.adql_query(sql, download=download)
    _report_result(label, result)


def run_simbad_lookup(client: Any, *, name: str, download: bool) -> None:
    """Runs ``SkyPatrolClient.simbad_lookup``.

    Args:
        client: Sky Patrol client instance.
        name (str): Simbad-resolvable target name.
        download (bool): Metadata-only vs photometry download.
    """
    label = f"simbad_lookup(name={name!r}, download={download})"
    logger.info("Running %s", label)
    result = client.simbad_lookup(name, download=download)
    _report_result(label, result)


def run_fetch_gaia_band(
    client: Any,
    *,
    gaia_id: int,
    band: str,
) -> None:
    """Downloads a lightcurve and reports band filter columns (legacy page path).

    Mirrors ``request_asassn.load_asassn_lightcurve`` Gaia branch with
    ``download=True``, then slices ``phot_filter``.

    Args:
        client: Sky Patrol client instance.
        gaia_id (int): Gaia DR3 source identifier.
        band (str): ASAS-SN filter code (``g`` or ``V``).
    """
    sql = (
        "SELECT asas_sn_id, epoch, period FROM stellar_main "
        f"JOIN aavsovsx USING(asas_sn_id) WHERE gaia_id = {gaia_id}"
    )
    _stdout("Step 1 — metadata ADQL (download=False)", sql)
    meta = client.adql_query(sql, download=False)
    _report_result("adql metadata (epoch/period)", meta)

    label = f"adql_query(... WHERE gaia_id = {gaia_id}, download=True)"
    logger.info("Running %s", label)
    res = client.adql_query(
        f"SELECT asas_sn_id, epoch, period FROM stellar_main "
        f"JOIN aavsovsx USING(asas_sn_id) WHERE gaia_id = {gaia_id}",
        download=True,
    )
    _report_result(label, res, band_hint=band)

    lc_df = getattr(res, "data", None)
    if isinstance(lc_df, pd.DataFrame) and "phot_filter" in lc_df.columns:
        subset = lc_df[lc_df["phot_filter"] == band][["jd", "flux", "flux_err", "camera"]]
        _stdout(
            f"Band slice phot_filter == {band!r}",
            f"rows: {len(subset)}\n{subset.head(10).to_string()}",
        )


def run_compare_download_gaia(client: Any, *, gaia_id: int) -> None:
    """Runs the same Gaia lookup with ``download=False`` then ``download=True``.

    Args:
        client: Sky Patrol client instance.
        gaia_id (int): Gaia DR3 source identifier.
    """
    _stdout("Compare download flag", f"Gaia id {gaia_id}")
    run_query_list_gaia(client, gaia_id=gaia_id, download=False, cols=None)
    run_query_list_gaia(client, gaia_id=gaia_id, download=True, cols=None)


def run_preset_aa_and(client: Any, *, radius_arcsec: float) -> None:
    """Runs a fixed battery of probes around AA And / its Gaia id.

    Args:
        client: Sky Patrol client instance.
        radius_arcsec (float): Cone radius for the preset cone search.
    """
    _stdout("Preset battery", "AA And / Gaia 1936512041221649536")
    run_cone_search(
        client,
        ra_deg=PRESET_AA_AND_RA_DEG,
        dec_deg=PRESET_AA_AND_DEC_DEG,
        radius_arcsec=radius_arcsec,
        catalog="stellar_main",
        download=False,
        cols=None,
    )
    run_query_list_gaia(client, gaia_id=PRESET_AA_AND_GAIA_ID, download=False, cols=None)
    run_simbad_lookup(client, name=PRESET_AA_AND_NAME, download=False)
    try:
        run_adql(
            client,
            sql=(
                "SELECT asas_sn_id, ra_deg, dec_deg, gaia_id, pstarrs_g_mag "
                f"FROM stellar_main WHERE gaia_id = {PRESET_AA_AND_GAIA_ID} LIMIT 10"
            ),
            download=False,
        )
    except Exception as exc:
        logger.warning("Preset ADQL step failed (dialect may differ from TAP): %s", exc)
        _stdout("adql_query FAILED", str(exc))


def _build_parser() -> argparse.ArgumentParser:
    """Builds the CLI argument parser.

    Returns:
        argparse.ArgumentParser: Configured parser with subcommands.
    """
    parser = argparse.ArgumentParser(
        description="Probe Sky Patrol discovery (download=False) vs fetch (download=True).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(__doc__ or "").strip(),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging on stderr.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    cone = sub.add_parser("cone", help="cone_search with units=arcsec")
    cone.add_argument("--ra", type=float, required=True, help="RA degrees (ICRS)")
    cone.add_argument("--dec", type=float, required=True, help="Dec degrees (ICRS)")
    cone.add_argument("--radius-arcsec", type=float, default=10.0, help="Cone radius")
    cone.add_argument(
        "--catalog",
        default="stellar_main",
        help="Sky Patrol input catalog (default: stellar_main)",
    )
    cone.add_argument(
        "--download",
        action="store_true",
        help="download=True (lightcurves); default is metadata only",
    )
    cone.add_argument(
        "--cols",
        default=None,
        help=(
            "Comma-separated cols for cone_search; default is discovery set "
            "(asas_sn_id, ra_deg, dec_deg, pstarrs_g_mag)"
        ),
    )
    cone.add_argument(
        "--thin-cols",
        action="store_true",
        help="Use client default columns only (omit cols=)",
    )

    ql = sub.add_parser("query-list-gaia", help="query_list on stellar_main by gaia_id")
    ql.add_argument("--gaia-id", type=int, required=True)
    ql.add_argument("--download", action="store_true")
    ql.add_argument("--cols", default=None)

    adql = sub.add_parser("adql", help="adql_query")
    adql.add_argument("--sql", required=True, help="ADQL query string")
    adql.add_argument("--download", action="store_true")

    simbad = sub.add_parser("simbad", help="simbad_lookup")
    simbad.add_argument("--name", required=True)
    simbad.add_argument("--download", action="store_true")

    fetch = sub.add_parser(
        "fetch-gaia",
        help="Legacy-style Gaia download=True path + band slice",
    )
    fetch.add_argument("--gaia-id", type=int, required=True)
    fetch.add_argument("--band", default="g", help="ASAS-SN phot_filter value (g or V)")

    cmp_cmd = sub.add_parser(
        "compare-download-gaia",
        help="Same query_list with download False then True",
    )
    cmp_cmd.add_argument("--gaia-id", type=int, default=PRESET_AA_AND_GAIA_ID)

    preset = sub.add_parser(
        "preset-aa-and",
        help="Cone + query_list + simbad + ADQL for AA And preset",
    )
    preset.add_argument("--radius-arcsec", type=float, default=10.0)

    sub.add_parser("catalogs", help="Print client.catalogs / master_list metadata if present")

    return parser


def run_catalogs(client: Any) -> None:
    """Prints available input catalog metadata from the client.

    Args:
        client: Sky Patrol client instance.
    """
    catalogs = getattr(client, "catalogs", None)
    if catalogs is None:
        _stdout("catalogs", "client has no .catalogs attribute")
        return
    _stdout("client.catalogs", repr(catalogs))
    master = getattr(catalogs, "master_list", None)
    if master is not None:
        _stdout("catalogs.master_list", repr(master))
    names = getattr(catalogs, "catalog_names", None)
    if callable(names):
        try:
            _stdout("catalog_names()", "\n".join(names()))
        except Exception as exc:
            _stdout("catalog_names()", f"failed: {exc}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv (list[str], optional): Arguments; defaults to ``sys.argv[1:]``.

    Returns:
        int: Process exit code (0 success, 1 on probe failure).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    try:
        client = _client(verbose=args.verbose)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    try:
        if args.command == "cone":
            run_cone_search(
                client,
                ra_deg=args.ra,
                dec_deg=args.dec,
                radius_arcsec=args.radius_arcsec,
                catalog=args.catalog,
                download=args.download,
                cols=args.cols,
                thin_cols=getattr(args, "thin_cols", False),
            )
        elif args.command == "query-list-gaia":
            run_query_list_gaia(
                client,
                gaia_id=args.gaia_id,
                download=args.download,
                cols=args.cols,
            )
        elif args.command == "adql":
            run_adql(client, sql=args.sql, download=args.download)
        elif args.command == "simbad":
            run_simbad_lookup(client, name=args.name, download=args.download)
        elif args.command == "fetch-gaia":
            run_fetch_gaia_band(client, gaia_id=args.gaia_id, band=args.band)
        elif args.command == "compare-download-gaia":
            run_compare_download_gaia(client, gaia_id=args.gaia_id)
        elif args.command == "preset-aa-and":
            run_preset_aa_and(client, radius_arcsec=args.radius_arcsec)
        elif args.command == "catalogs":
            run_catalogs(client)
        else:
            parser.error(f"Unknown command {args.command!r}")
    except Exception as exc:
        if args.command == "preset-aa-and":
            logger.exception("Preset battery aborted: %s", exc)
            return 1
        logger.exception("Probe failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
