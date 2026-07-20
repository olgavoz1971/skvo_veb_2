"""
Resolve variable-star names via the AAVSO VSX index (not Simbad).

Two-step approach, because VSX's own API and its web page expose different
information:

  1. view=api.object  -> XML with OID, coordinates, variability type,
                          period, mag range, spectral type, etc.
  2. view=detail.top   -> HTML detail page, scraped for "Other names"
                          (cross-identifications) and catalog cross-matches,
                          which are NOT in the api.object output.

Notes / caveats (as of July 2026):
  - VSX has moved to https://vsx.aavso.org/index.php (the old
    www.aavso.org/vsx/index.php endpoint still works as of this writing but
    AAVSO says it is being retired).
  - format=json on the new host is unreliable; we request XML instead.
  - The new server has bot protection. Use a real User-Agent, keep request
    rates low, and don't parallelize aggressively.
  - For bulk resolution (hundreds+ of names), AAVSO recommends VSX-on-VizieR
    (catalog "B/vsx") via astroquery instead of repeated HTTP calls here.
  - The HTML scraping step is inherently fragile - if AAVSO changes their
    page layout, update _parse_other_names().
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

VSX_BASE = "https://vsx.aavso.org/index.php"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; vsx-resolve-script/1.0; "
        "+mailto:you@example.org)"
    )
}
TIMEOUT = 20


@dataclass
class VSXObject:
    name: str | None = None
    oid: str | None = None
    auid: str | None = None
    ra2000_deg: float | None = None
    dec2000_deg: float | None = None
    pm_ra: float | None = None
    pm_dec: float | None = None
    variability_type: str | None = None
    period_days: float | None = None
    epoch_jd: float | None = None
    max_mag: str | None = None
    min_mag: str | None = None
    spectral_type: str | None = None
    constellation: str | None = None
    category: str | None = None
    other_names: list[str] = field(default_factory=list)
    detail_url: str | None = None
    raw_xml: str | None = None


def _get(url: str, params: dict) -> requests.Response:
    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


def _parse_api_object_xml(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    if root.tag != "VSXObject":
        # VSX returns an empty/near-empty document (or an error page) when
        # the identifier isn't resolved.
        return {}

    def text(tag):
        el = root.find(tag)
        return el.text if el is not None else None

    def fnum(tag):
        v = text(tag)
        try:
            return float(v) if v is not None else None
        except ValueError:
            return None

    return {
        "name": text("Name"),
        "oid": text("OID"),
        "auid": text("AUID"),
        "ra2000_deg": fnum("RA2000"),
        "dec2000_deg": fnum("Declination2000"),
        "pm_ra": fnum("ProperMotionRA"),
        "pm_dec": fnum("ProperMotionDec"),
        "variability_type": text("VariabilityType"),
        "period_days": fnum("Period"),
        "epoch_jd": fnum("Epoch"),
        "max_mag": text("MaxMag"),
        "min_mag": text("MinMag"),
        "spectral_type": text("SpectralType"),
        "constellation": text("Constellation"),
        "category": text("Category"),
    }


def _parse_other_names(html_text: str) -> list[str]:
    """Extract the 'Other names' (cross-identification) list from a VSX
    detail.top page. Best-effort: VSX's markup isn't formally documented,
    so this walks the table looking for the 'Other names' label cell and
    reads whatever sits next to it.
    """
    soup = BeautifulSoup(html_text, "lxml")
    names: list[str] = []

    label_cell = None
    for cell in soup.find_all(["td", "th"]):
        if cell.get_text(strip=True).lower() == "other names":
            label_cell = cell
            break

    if label_cell is not None:
        # Names are usually in the next sibling cell(s) in the same row,
        # sometimes in the row(s) immediately below (AAVSO login users get
        # an extra SIMBAD-alias row).
        row = label_cell.find_parent("tr")
        candidates = []
        if row is not None:
            sibs = [c for c in row.find_all(["td", "th"]) if c is not label_cell]
            candidates.extend(sibs)
            nxt = row.find_next_sibling("tr")
            if nxt is not None:
                candidates.extend(nxt.find_all(["td", "th"]))

        for c in candidates:
            raw = c.get_text(separator="|", strip=True)
            for part in raw.split("|"):
                part = part.strip()
                if not part:
                    continue
                low = part.lower()
                if low in ("(internal only)", "add name", "(not logged in) add name"):
                    continue
                if "add name" in low or "log in" in low:
                    continue
                names.append(part)

    # de-dupe, preserve order
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def resolve_vsx(identifier: str, fetch_other_names: bool = True,
                 pause: float = 1.0) -> VSXObject:
    """Resolve a star identifier (any VSX-known designation, including
    transient/TCP-style names) against the AAVSO VSX index.

    Returns a VSXObject; fields are None/empty if the star wasn't found.
    """
    resp = _get(VSX_BASE, {"view": "api.object", "ident": identifier})
    fields = _parse_api_object_xml(resp.text)

    obj = VSXObject(raw_xml=resp.text, **fields) if fields else VSXObject(raw_xml=resp.text)
    if not fields:
        return obj  # not resolved

    if fetch_other_names and obj.oid:
        if pause:
            time.sleep(pause)  # be polite to VSX's bot protection
        detail_resp = _get(VSX_BASE, {"view": "detail.top", "oid": obj.oid})
        obj.other_names = _parse_other_names(detail_resp.text)
        obj.detail_url = (
            f"{VSX_BASE}?view=detail.top&oid={obj.oid}"
        )

    return obj


if __name__ == "__main__":
    star = resolve_vsx("TCP J23580961+5502508")
    if star.oid is None:
        print("Not resolved in VSX.")
    else:
        print(f"Name:            {star.name}")
        print(f"OID:             {star.oid}")
        print(f"AUID:            {star.auid}")
        print(f"RA/Dec (J2000):  {star.ra2000_deg}, {star.dec2000_deg}")
        print(f"Variability:     {star.variability_type}")
        print(f"Period (d):      {star.period_days}")
        print(f"Mag range:       {star.max_mag} - {star.min_mag}")
        print(f"Spectral type:   {star.spectral_type}")
        print(f"Other names:     {star.other_names}")
        print(f"Detail page:     {star.detail_url}")
