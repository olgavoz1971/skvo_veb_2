"""Step 2 fit window: which part of the cycle around the peak is fitted.

The fit window is a *fitting* decision, not a template property: it is declared in
the manifest (``fit_defaults``, overridable per piece via ``fit:``) and re-resolved
on every run, so switching from a narrow window to a whole cycle never requires
rebuilding a Gaussian process template.

Two modes are supported, both symmetric about the timed extremum:

``whole_period``
    One full cycle, ``t - t_max`` in ``[-P/2, +P/2]``.
``frac_period``
    ``t - t_max`` in ``[-h*P, +h*P]`` with ``h = fit_mask_half_width_phase`` in
    phase units, capped at 0.5 (0.5 is exactly ``whole_period``).

The period only ever acts as "how long is one cycle in days"; it is taken from the
template's own ``fold_period``, so the window matches the ``tau`` axis on which the
template was stacked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

FIT_MASK_MODES = ("whole_period", "frac_period")
WHOLE_PERIOD_HALF_WIDTH_PHASE = 0.5


@dataclass(frozen=True)
class FitMask:
    """Resolved Step 2 fit window in both peak-centred and fold coordinates.

    Attributes:
        mode (str): ``whole_period`` or ``frac_period``.
        half_width_phase (float): Half width in phase units (0.5 = one full cycle).
        half_width_days (float): Half width in days, ``half_width_phase * period``.
        dt_min (float): Lower bound of ``t - t_max`` in days.
        dt_max (float): Upper bound of ``t - t_max`` in days.
        tau_min (float): Same window on the template ``tau`` axis.
        tau_max (float): Same window on the template ``tau`` axis.
        period (float): Period in days used for the phase-to-days conversion.
        tau_peak (float): Template peak the window is centred on.
    """

    mode: str
    half_width_phase: float
    half_width_days: float
    dt_min: float
    dt_max: float
    tau_min: float
    tau_max: float
    period: float
    tau_peak: float

    def as_dict(self) -> dict:
        """Return a JSON-serialisable view for ``template_meta.json``."""
        return {
            "mode": self.mode,
            "half_width_phase": self.half_width_phase,
            "half_width_days": self.half_width_days,
            "dt_min": self.dt_min,
            "dt_max": self.dt_max,
            "tau_min": self.tau_min,
            "tau_max": self.tau_max,
            "period": self.period,
            "tau_peak": self.tau_peak,
        }

    def describe(self) -> str:
        """One-line human-readable summary for logs."""
        return (
            f"{self.mode}: +/-{self.half_width_phase:.3f} in phase "
            f"= +/-{self.half_width_days:.5f} d around tau_peak={self.tau_peak:+.5f} "
            f"(tau {self.tau_min:+.5f} .. {self.tau_max:+.5f}, period={self.period:.6f} d)"
        )


def validate_fit_mask_settings(
    mode: str,
    half_width_phase: float,
    *,
    context: str = "fit",
) -> None:
    """Check manifest fit-mask settings, raising on anything ambiguous.

    Args:
        mode (str): Requested mode.
        half_width_phase (float): Requested half width in phase units.
        context (str): Label used in error messages, e.g. ``fit`` or a piece id.

    Raises:
        ValueError: If the mode is unknown or the half width is outside ``(0, 0.5]``.
    """
    if mode not in FIT_MASK_MODES:
        raise ValueError(
            f"{context}.fit_mask_mode must be one of {list(FIT_MASK_MODES)}, got {mode!r}"
        )
    hw = float(half_width_phase)
    if not 0.0 < hw <= WHOLE_PERIOD_HALF_WIDTH_PHASE:
        raise ValueError(
            f"{context}.fit_mask_half_width_phase must be in (0, "
            f"{WHOLE_PERIOD_HALF_WIDTH_PHASE}], got {hw}; "
            f"use fit_mask_mode: whole_period for a full cycle"
        )


def resolve_fit_mask(
    *,
    mode: str,
    half_width_phase: float,
    period: float,
    tau_peak: float,
) -> FitMask:
    """Turn manifest fit-mask settings into concrete day and ``tau`` bounds.

    Args:
        mode (str): ``whole_period`` or ``frac_period``.
        half_width_phase (float): Half width in phase units; ignored for
            ``whole_period``, which always uses 0.5.
        period (float): Period in days (template ``fold_period``).
        tau_peak (float): Template peak in days on the fold axis.

    Returns:
        FitMask: Resolved window.

    Raises:
        ValueError: If the settings are invalid or the period is not positive.
    """
    validate_fit_mask_settings(mode, half_width_phase)
    if period <= 0:
        raise ValueError(f"fit mask needs a positive period, got {period}")
    hw_phase = (
        WHOLE_PERIOD_HALF_WIDTH_PHASE if mode == "whole_period" else float(half_width_phase)
    )
    hw_days = hw_phase * period
    return FitMask(
        mode=mode,
        half_width_phase=hw_phase,
        half_width_days=hw_days,
        dt_min=-hw_days,
        dt_max=hw_days,
        tau_min=float(tau_peak - hw_days),
        tau_max=float(tau_peak + hw_days),
        period=float(period),
        tau_peak=float(tau_peak),
    )


def warn_fit_mask_support(
    mask: FitMask,
    *,
    tau_data_min: float,
    tau_data_max: float,
    context: str,
) -> None:
    """Warn when the requested window reaches outside the folded photometry.

    Template values outside ``[tau_data_min, tau_data_max]`` are treated as
    undefined by :class:`template_fit.TemplateCurve`, so points there drop out of
    the fit instead of being matched against GP extrapolation.

    Args:
        mask (FitMask): Resolved fit window.
        tau_data_min (float): Lowest ``tau`` covered by folded data.
        tau_data_max (float): Highest ``tau`` covered by folded data.
        context (str): Label used in the message, typically the piece id.
    """
    if mask.tau_min < tau_data_min or mask.tau_max > tau_data_max:
        logger.warning(
            "%s: fit mask tau [%.5f, %.5f] reaches outside the folded data "
            "[%.5f, %.5f]; the template is undefined there and those points are "
            "dropped from every fit",
            context,
            mask.tau_min,
            mask.tau_max,
            tau_data_min,
            tau_data_max,
        )
