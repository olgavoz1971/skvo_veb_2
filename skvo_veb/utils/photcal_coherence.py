"""Photcal coherence policy (Ticket 7 Phase 1).

Reconciles ``metadata['photcal']`` before mag↔flux conversion:

* **Incomplete** ZP pair → fill from ``volightcurve.photcal_defaults`` and warn.
* **Invalid or mismatched** ``zp_flux_unit`` → flux column unit wins; write
  that unit into photcal and warn explicitly.
* Never silently demote invalid units inside ``PhotCal`` without this step.

**Dangerous mutators — never call silently.** Both
:func:`reconcile_curve_photcal` and :func:`reconcile_photcal_dict` **invent**
missing zero points (``DEFAULT_ZP_FLUX`` / ``DEFAULT_ZP_MAG``) and rewrite
stored photcal. Callers **must** surface every returned warning to the user
(``status_alert`` or equivalent). Discarding the warning list is forbidden.

**Allowed invent call sites:**

* :func:`reconcile_photcal_dict` — GP upload (``gp_for_oc`` + ``status_alert``);
  ``gp.flux.resolve_gp_photcal`` (after upload promote); Processor form Apply
  (``photcal_dict_from_form_values``).
* :func:`reconcile_curve_photcal` — reserved for intentional CurveDash promote
  with a UI warning path; **not** used by domain switch.

**Domain switch** uses :func:`inspect_curve_photcal` /
:func:`inspect_photcal_dict` only (via ``lc_bridge.apply_phot_domain_view``).
Incomplete photcal → refuse conversion; do not invent.

Unitless values are stored as ``None`` (see ``vo_unit_codec``); UI messages use
:func:`to_display` so callers never surface bare ``None``.
"""

from __future__ import annotations

import logging
from typing import Any

import astropy.units as u

from skvo_veb.utils.lc_config import (
    PHOTCAL_KEY_MAG_SYS,
    PHOTCAL_KEY_ZP_FLUX,
    PHOTCAL_KEY_ZP_FLUX_UNIT,
    PHOTCAL_KEY_ZP_MAG,
    PHOTCAL_KEY_ZP_MAG_UNIT,
)
from volightcurve.photcal_defaults import (
    DEFAULT_MAG_SYS,
    DEFAULT_ZP_FLUX,
    DEFAULT_ZP_FLUX_UNIT,
    DEFAULT_ZP_MAG,
    DEFAULT_ZP_MAG_UNIT,
)
from volightcurve.vo_unit_codec import to_display, to_internal

logger = logging.getLogger(__name__)


def _unit_label(unit_str: str | None) -> str:
    """Formats a unit for user-facing British English messages.

    Args:
        unit_str (str, optional): Stored unit string, or ``None``/empty.

    Returns:
        str: Display label such as ``dimensionless`` or the unit text.
    """
    return to_display(to_internal(unit_str))


def _parse_unit(unit_str: str | None) -> u.Unit | None:
    """Parses a stored unit; ``None``/empty/``---`` means dimensionless.

    Args:
        unit_str (str, optional): Stored unit label.

    Returns:
        astropy.units.Unit or None: Parsed unit, or ``None`` if invalid.
    """
    internal = to_internal(unit_str)
    if internal is None:
        return u.dimensionless_unscaled
    try:
        return u.Unit(internal)
    except (ValueError, TypeError, u.UnitsError, u.UnitTypeError):
        return None


def _units_equivalent(a: str | None, b: str | None) -> bool:
    """Returns whether two stored unit labels are equivalent.

    Args:
        a (str, optional): First unit string.
        b (str, optional): Second unit string.

    Returns:
        bool: ``True`` when both parse and are equivalent.
    """
    ua = _parse_unit(a)
    ub = _parse_unit(b)
    if ua is None or ub is None:
        return False
    try:
        return ua.is_equivalent(ub)
    except (ValueError, u.UnitsError, u.UnitTypeError):
        return False


def _storage_unit_from_flux_column(flux_unit: str | None) -> str | None:
    """Chooses the photcal ZP flux unit storage value from the flux column.

    Args:
        flux_unit (str, optional): CurveDash ``metadata['flux_unit']``.

    Returns:
        str or None: Unit string to store, or ``None`` for dimensionless.
    """
    internal = to_internal(flux_unit)
    if internal is None:
        return DEFAULT_ZP_FLUX_UNIT
    parsed = _parse_unit(internal)
    if parsed is None:
        return DEFAULT_ZP_FLUX_UNIT
    if parsed is u.dimensionless_unscaled or parsed == u.dimensionless_unscaled:
        return DEFAULT_ZP_FLUX_UNIT
    return internal


def reconcile_photcal_dict(
    photcal: dict | None,
    *,
    flux_unit: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Promotes/repairs a serialised photcal dict for application use.

    **Do not call silently.** Returned warnings must be shown to the user.
    Incomplete ZP pairs are filled from ``photcal_defaults`` — that is an
    invented calibration, not archive truth.

    * Incomplete ZP pair → fill application defaults and warn.
    * Invalid ZP flux unit → promote to the **concrete** flux column unit when
      available; otherwise leave the declared text and warn.
    * Concrete flux / ZP unit mismatch → flux column wins and warn.
    * Missing ``flux_unit`` is **not** treated as dimensionless (never wipe a
      real ZP unit such as ``Jy`` against a phantom empty column unit).

    Args:
        photcal (dict, optional): Existing photcal metadata (may be empty).
        flux_unit (str, optional): Native flux column unit when known.

    Returns:
        tuple: Updated photcal dict and user-facing promotion/warning messages.
            Callers must not discard the warning list.
    """
    pc: dict[str, Any] = dict(photcal or {})
    warnings: list[str] = []

    # Normalise legacy empty-string / Astropy ``---`` storage to internal None.
    if PHOTCAL_KEY_ZP_FLUX_UNIT in pc:
        pc[PHOTCAL_KEY_ZP_FLUX_UNIT] = to_internal(pc.get(PHOTCAL_KEY_ZP_FLUX_UNIT))

    concrete_flux_unit = to_internal(flux_unit)
    has_concrete_flux_unit = concrete_flux_unit is not None

    zp_flux = pc.get(PHOTCAL_KEY_ZP_FLUX)
    zp_mag = pc.get(PHOTCAL_KEY_ZP_MAG)
    incomplete = zp_flux is None or zp_mag is None
    if incomplete:
        if zp_flux is None:
            pc[PHOTCAL_KEY_ZP_FLUX] = float(DEFAULT_ZP_FLUX)
        else:
            pc[PHOTCAL_KEY_ZP_FLUX] = float(zp_flux)
        if zp_mag is None:
            pc[PHOTCAL_KEY_ZP_MAG] = float(DEFAULT_ZP_MAG)
        else:
            pc[PHOTCAL_KEY_ZP_MAG] = float(zp_mag)
        if not pc.get(PHOTCAL_KEY_ZP_MAG_UNIT):
            pc[PHOTCAL_KEY_ZP_MAG_UNIT] = DEFAULT_ZP_MAG_UNIT
        if not pc.get(PHOTCAL_KEY_MAG_SYS):
            pc[PHOTCAL_KEY_MAG_SYS] = DEFAULT_MAG_SYS
        if PHOTCAL_KEY_ZP_FLUX_UNIT not in pc or pc.get(PHOTCAL_KEY_ZP_FLUX_UNIT) is None:
            pc[PHOTCAL_KEY_ZP_FLUX_UNIT] = _storage_unit_from_flux_column(flux_unit)
        warnings.append(
            "Photometric calibration was incomplete (missing zp_flux and/or "
            "zp_mag). Defaults were applied: "
            f"zp_flux={pc[PHOTCAL_KEY_ZP_FLUX]} "
            f"({_unit_label(pc.get(PHOTCAL_KEY_ZP_FLUX_UNIT))}), "
            f"zp_mag={pc[PHOTCAL_KEY_ZP_MAG]} "
            f"{pc.get(PHOTCAL_KEY_ZP_MAG_UNIT) or DEFAULT_ZP_MAG_UNIT}"
        )
        logger.warning("%s", warnings[-1])

    zp_flux_unit = to_internal(pc.get(PHOTCAL_KEY_ZP_FLUX_UNIT))
    pc[PHOTCAL_KEY_ZP_FLUX_UNIT] = zp_flux_unit

    zp_unit_valid = True
    if zp_flux_unit is not None:
        try:
            u.Unit(zp_flux_unit)
        except (ValueError, TypeError, u.UnitsError, u.UnitTypeError):
            zp_unit_valid = False

    if not zp_unit_valid:
        old = _unit_label(zp_flux_unit)
        if has_concrete_flux_unit:
            pc[PHOTCAL_KEY_ZP_FLUX_UNIT] = concrete_flux_unit
            warnings.append(
                f"Zeropoint flux unit ({old}) is not a valid Astropy unit. "
                "Calibration will use the flux column unit: "
                f"'{_unit_label(concrete_flux_unit)}'"
            )
        else:
            warnings.append(
                f"Zeropoint flux unit ({old}) is not a valid Astropy unit. "
                "No flux column unit was available to promote it."
            )
        logger.warning("%s", warnings[-1])
    elif has_concrete_flux_unit:
        zp_unit_obj = (
            u.dimensionless_unscaled
            if zp_flux_unit is None
            else u.Unit(zp_flux_unit)
        )
        flux_unit_obj = u.Unit(concrete_flux_unit)
        if not zp_unit_obj.is_equivalent(flux_unit_obj):
            old = _unit_label(zp_flux_unit)
            pc[PHOTCAL_KEY_ZP_FLUX_UNIT] = concrete_flux_unit
            warnings.append(
                f"Flux column unit ({_unit_label(concrete_flux_unit)}) and "
                f"zeropoint flux unit ({old}) do not match. Calibration will "
                f"use flux column unit: "
                f"'{_unit_label(concrete_flux_unit)}'"
            )
            logger.warning("%s", warnings[-1])

    zp_mag_unit = pc.get(PHOTCAL_KEY_ZP_MAG_UNIT)
    if zp_mag_unit not in (None, ""):
        try:
            u.Unit(str(zp_mag_unit).strip())
        except (ValueError, TypeError, u.UnitsError, u.UnitTypeError):
            old = str(zp_mag_unit)
            pc[PHOTCAL_KEY_ZP_MAG_UNIT] = DEFAULT_ZP_MAG_UNIT
            warnings.append(
                f"Zeropoint magnitude unit ({old}) is not a valid Astropy unit. "
                f"We will use '{DEFAULT_ZP_MAG_UNIT}'"
            )
            logger.warning("%s", warnings[-1])

    return pc, warnings


def reconcile_curve_photcal(lcd) -> list[str]:
    """Reconciles ``lcd.metadata['photcal']`` using the flux column unit.

    **Forbidden to call silently.** Mutates session photcal and can invent
    ``ZP_FLUX`` / ``ZP_MAG`` from ``photcal_defaults``. Every non-empty warning
    **must** be shown in the UI (``status_alert`` or equivalent).

    Domain switch must **not** call this — use :func:`inspect_curve_photcal`
    and refuse conversion. Production invent paths use
    :func:`reconcile_photcal_dict` (GP upload, Processor Apply). This CurveDash
    wrapper is reserved for an explicit promote-with-warning UI only.

    Args:
        lcd: ``CurveDash`` instance (mutated in place).

    Returns:
        list[str]: User-facing warning messages (may be empty). Must be
            surfaced when non-empty; never discard without UI feedback.
    """
    meta = lcd.metadata if isinstance(getattr(lcd, "metadata", None), dict) else {}
    flux_unit = to_internal(
        meta.get("flux_unit") or getattr(lcd, "flux_unit", None)
    )
    photcal, warnings = reconcile_photcal_dict(
        meta.get("photcal"),
        flux_unit=flux_unit,
    )
    meta = dict(meta)
    meta["photcal"] = photcal
    if "flux_unit" in meta:
        meta["flux_unit"] = to_internal(meta.get("flux_unit"))
    lcd.metadata = meta
    return warnings


def inspect_photcal_dict(
    photcal: dict | None,
    *,
    flux_unit: str | None = None,
) -> list[str]:
    """Reports photcal problems without mutating the dict.

    Suitable for domain-switch gating: incomplete ZP pair, invalid units, or a
    concrete flux-column / ZP flux unit mismatch. Missing flux unit is not
    treated as dimensionless (avoids false mismatches on mag-native curves).

    Args:
        photcal (dict, optional): Stored ``metadata['photcal']``.
        flux_unit (str, optional): Concrete flux column unit when available.

    Returns:
        list[str]: Problem messages (empty when photcal looks usable for switch).
    """
    source = dict(photcal or {})
    warnings: list[str] = []

    zp_flux = source.get(PHOTCAL_KEY_ZP_FLUX)
    zp_mag = source.get(PHOTCAL_KEY_ZP_MAG)
    if zp_flux is None or zp_mag is None:
        warnings.append(
            "Photometric calibration is incomplete (missing zp_flux and/or "
            "zp_mag). Domain switch was not applied."
        )

    zp_flux_unit = to_internal(source.get(PHOTCAL_KEY_ZP_FLUX_UNIT))
    concrete_flux_unit = to_internal(flux_unit)

    if zp_flux_unit is not None:
        try:
            u.Unit(zp_flux_unit)
        except (ValueError, TypeError, u.UnitsError, u.UnitTypeError):
            warnings.append(
                f"Zeropoint flux unit ({_unit_label(zp_flux_unit)}) is not a "
                "valid Astropy unit. Domain switch was not applied."
            )

    if concrete_flux_unit is not None and zp_flux_unit is not None:
        try:
            ua = u.Unit(zp_flux_unit)
            ub = u.Unit(concrete_flux_unit)
            if not ua.is_equivalent(ub):
                warnings.append(
                    f"Flux column unit ({_unit_label(concrete_flux_unit)}) and "
                    f"zeropoint flux unit ({_unit_label(zp_flux_unit)}) do not "
                    "match. Domain switch was not applied."
                )
        except (ValueError, TypeError, u.UnitsError, u.UnitTypeError):
            pass
    elif concrete_flux_unit is not None and zp_flux_unit is None:
        # Dimensionless ZP vs concrete flux column.
        try:
            if not u.dimensionless_unscaled.is_equivalent(u.Unit(concrete_flux_unit)):
                warnings.append(
                    f"Flux column unit ({_unit_label(concrete_flux_unit)}) and "
                    "zeropoint flux unit (dimensionless) do not match. "
                    "Domain switch was not applied."
                )
        except (ValueError, TypeError, u.UnitsError, u.UnitTypeError):
            warnings.append(
                f"Flux column unit ({_unit_label(concrete_flux_unit)}) cannot be "
                "compared with a dimensionless zeropoint. Domain switch was not "
                "applied."
            )

    zp_mag_unit = source.get(PHOTCAL_KEY_ZP_MAG_UNIT)
    if zp_mag_unit not in (None, ""):
        try:
            u.Unit(str(zp_mag_unit).strip())
        except (ValueError, TypeError, u.UnitsError, u.UnitTypeError):
            warnings.append(
                f"Zeropoint magnitude unit ({zp_mag_unit}) is not a valid "
                "Astropy unit. Domain switch was not applied."
            )

    for message in warnings:
        logger.warning("%s", message)
    return warnings


def inspect_curve_photcal(lcd) -> list[str]:
    """Reports photcal problems on a ``CurveDash`` without mutating it.

    Args:
        lcd: ``CurveDash`` instance.

    Returns:
        list[str]: Problem messages (empty when switch may proceed).
    """
    meta = lcd.metadata if isinstance(getattr(lcd, "metadata", None), dict) else {}
    flux_unit = to_internal(
        meta.get("flux_unit") or getattr(lcd, "flux_unit", None)
    )
    return inspect_photcal_dict(meta.get("photcal"), flux_unit=flux_unit)


def format_photcal_warning_message(warnings: list[str]) -> str | None:
    """Joins photcal warning lines for a single ``status_alert``.

    Args:
        warnings (list[str]): Messages from reconcile helpers.

    Returns:
        str or None: Combined text, or ``None`` when there are no warnings.
    """
    if not warnings:
        return None
    return "\n\n".join(warnings)


def _form_unit_text(internal: str | None) -> str:
    """Maps internal unit storage to an editable form string.

    Args:
        internal (str, optional): Internal unit (``None`` = dimensionless).

    Returns:
        str: Empty string for dimensionless; otherwise the unit label.
    """
    if internal is None:
        return ""
    text = str(internal).strip()
    return "" if text in ("", "---") else text


def _parse_optional_float(value: Any) -> float | None:
    """Parses a form number field.

    Args:
        value: Raw Dash input value.

    Returns:
        float or None: Parsed number, or ``None`` when empty.
    """
    if value is None or value == "":
        return None
    return float(value)


def photcal_form_values_from_storage(
    photcal: dict | None,
    flux_unit: str | None,
) -> dict[str, Any]:
    """Builds calibration editor values from CurveDash / transport storage.

    Args:
        photcal (dict, optional): ``metadata['photcal']``.
        flux_unit (str, optional): ``metadata['flux_unit']`` (``None`` =
            dimensionless).

    Returns:
        dict: Keys ``zp_flux``, ``zp_flux_unit``, ``zp_mag``, ``mag_sys``,
        ``flux_unit`` ready for Dash ``Input`` ``value`` props.
        Dimensionless units are empty strings. ZP mag unit is not editable
        (always ``mag`` on write).
    """
    pc = dict(photcal or {})
    zp_flux = pc.get(PHOTCAL_KEY_ZP_FLUX)
    zp_mag = pc.get(PHOTCAL_KEY_ZP_MAG)
    return {
        "zp_flux": None if zp_flux is None else float(zp_flux),
        "zp_flux_unit": _form_unit_text(to_internal(pc.get(PHOTCAL_KEY_ZP_FLUX_UNIT))),
        "zp_mag": None if zp_mag is None else float(zp_mag),
        "mag_sys": str(pc.get(PHOTCAL_KEY_MAG_SYS) or "").strip(),
        "flux_unit": _form_unit_text(to_internal(flux_unit)),
    }


def fill_missing_photcal_form_values(current: dict[str, Any]) -> dict[str, Any]:
    """Fills empty editor fields from application defaults; never overwrites.

    Populates only missing ``zp_flux``, ``zp_mag``, and ``mag_sys``. Leaves
    ``zp_flux_unit`` and ``flux_unit`` unchanged (blank means dimensionless,
    not “please invent Jy”).

    Args:
        current (dict): Current form values (may be partial).

    Returns:
        dict: Copy with gaps filled from ``photcal_defaults``.
    """
    out = dict(current)
    if out.get("zp_flux") is None or out.get("zp_flux") == "":
        out["zp_flux"] = float(DEFAULT_ZP_FLUX)
    if out.get("zp_mag") is None or out.get("zp_mag") == "":
        out["zp_mag"] = float(DEFAULT_ZP_MAG)
    if not str(out.get("mag_sys") or "").strip():
        out["mag_sys"] = DEFAULT_MAG_SYS
    return out


def apply_photcal_form_values(
    *,
    zp_flux: Any,
    zp_flux_unit: Any,
    zp_mag: Any,
    mag_sys: Any,
    flux_unit: Any,
    existing_photcal: dict | None = None,
) -> tuple[dict[str, Any], str | None, list[str]]:
    """Builds reconciled photcal + flux column unit from editor form values.

    Does not rescale photometry: flux column unit is metadata only. ZP
    magnitude unit is always ``DEFAULT_ZP_MAG_UNIT`` (``mag``).

    Args:
        zp_flux: Form zero-point flux.
        zp_flux_unit: Form ZP flux unit (blank = dimensionless).
        zp_mag: Form zero-point magnitude.
        mag_sys: Form magnitude system.
        flux_unit: Form flux column unit (blank = dimensionless).
        existing_photcal (dict, optional): Existing photcal to preserve
            non-editor keys (filter name, wavelength, …).

    Returns:
        tuple: ``(photcal_dict, flux_unit_internal, warnings)``.
    """
    pc = dict(existing_photcal or {})
    pc[PHOTCAL_KEY_ZP_FLUX] = _parse_optional_float(zp_flux)
    pc[PHOTCAL_KEY_ZP_FLUX_UNIT] = to_internal(zp_flux_unit)
    pc[PHOTCAL_KEY_ZP_MAG] = _parse_optional_float(zp_mag)
    pc[PHOTCAL_KEY_ZP_MAG_UNIT] = DEFAULT_ZP_MAG_UNIT
    sys_text = str(mag_sys).strip() if mag_sys not in (None, "") else ""
    if sys_text:
        pc[PHOTCAL_KEY_MAG_SYS] = sys_text
    elif PHOTCAL_KEY_MAG_SYS in pc and not pc.get(PHOTCAL_KEY_MAG_SYS):
        pc.pop(PHOTCAL_KEY_MAG_SYS, None)

    flux_internal = to_internal(flux_unit)
    photcal, warnings = reconcile_photcal_dict(pc, flux_unit=flux_internal)
    return photcal, flux_internal, warnings


def photcal_form_values_from_curvedash(lcd) -> dict[str, Any]:
    """Reads calibration editor values from a ``CurveDash`` instance.

    Args:
        lcd: ``CurveDash`` with ``metadata``.

    Returns:
        dict: Same shape as :func:`photcal_form_values_from_storage`.
    """
    meta = lcd.metadata if isinstance(getattr(lcd, "metadata", None), dict) else {}
    return photcal_form_values_from_storage(
        meta.get("photcal"),
        meta.get("flux_unit"),
    )


def write_photcal_form_to_curvedash(
    lcd,
    *,
    zp_flux: Any,
    zp_flux_unit: Any,
    zp_mag: Any,
    mag_sys: Any,
    flux_unit: Any,
) -> list[str]:
    """Writes editor form values into ``lcd.metadata`` (mutates in place).

    Args:
        lcd: ``CurveDash`` instance.
        zp_flux: Form zero-point flux.
        zp_flux_unit: Form ZP flux unit.
        zp_mag: Form zero-point magnitude.
        mag_sys: Form magnitude system.
        flux_unit: Form flux column unit.

    Returns:
        list[str]: Reconcile / promotion warnings.
    """
    meta = dict(lcd.metadata) if isinstance(getattr(lcd, "metadata", None), dict) else {}
    photcal, flux_internal, warnings = apply_photcal_form_values(
        zp_flux=zp_flux,
        zp_flux_unit=zp_flux_unit,
        zp_mag=zp_mag,
        mag_sys=mag_sys,
        flux_unit=flux_unit,
        existing_photcal=meta.get("photcal"),
    )
    meta["photcal"] = photcal
    meta["flux_unit"] = flux_internal
    lcd.metadata = meta
    return warnings
