"""Rules for choosing the timing peak on a folded GP template.

The template grid produced by Step 1 is padded beyond the folded data so that the
GP mean stays smooth at the ends. Peak selection therefore works on the
*data-supported* part of the grid only, inset by an edge margin, and ranks
candidates by true topographic prominence rather than by raw height.

Because the extended fold stacks ``phi`` and ``phi + 1``, every physical extremum
appears twice, one period apart. Candidates are grouped into phase classes
(``tau / period`` modulo 1); the dominant class is selected, and the copy used for
timing is the one whose Step 2 mask is fully covered by data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

logger = logging.getLogger(__name__)

EXTREMA_MODES = ("max", "min")
PEAK_SELECT_RULES = ("dominant", "nearest_phase0")


@dataclass(frozen=True)
class PeakCandidate:
    """One local extremum of the template mean.

    Attributes:
        tau (float): Fold coordinate of the extremum in days.
        mu (float): GP mean at ``tau``.
        prominence (float): Topographic prominence in normalised flux units,
            measured on the data-supported part of the grid.
        prominence_frac (float): ``prominence`` divided by the peak-to-peak
            amplitude of the template inside the data range.
        phase (float): ``tau / period`` modulo 1.
        accepted (bool): Whether the candidate passed all cuts.
        reject_reason (str | None): Why the candidate was dropped, if it was.
    """

    tau: float
    mu: float
    prominence: float
    prominence_frac: float
    phase: float
    accepted: bool
    reject_reason: str | None = None

    def as_dict(self) -> dict:
        """Return a JSON-serialisable view for ``template_meta.json``."""
        return {
            "tau": self.tau,
            "mu": self.mu,
            "prominence": self.prominence,
            "prominence_frac": self.prominence_frac,
            "phase": self.phase,
            "accepted": self.accepted,
            "reject_reason": self.reject_reason,
        }


@dataclass(frozen=True)
class PeakSelection:
    """Outcome of :func:`select_template_peak`.

    Attributes:
        tau_peak (float): Selected fold coordinate for timing, in days.
        mu_peak (float): GP mean at ``tau_peak``.
        prominence_frac (float): Prominence of the selected extremum as a
            fraction of the in-range amplitude.
        phase (float): Phase class of the selected extremum.
        class_tau (tuple[float, ...]): All copies of the selected extremum.
        search_min (float): Lower bound of the candidate search window.
        search_max (float): Upper bound of the candidate search window.
        amplitude (float): Peak-to-peak template amplitude inside the data range.
        support_half_width (float): Widest symmetric half window around
            ``tau_peak`` still covered by folded photometry, in days.
        support_half_width_phase (float): Same support expressed in phase units.
        reason (str): Human-readable account of how the peak was chosen.
        candidates (tuple[PeakCandidate, ...]): Every extremum considered.
    """

    tau_peak: float
    mu_peak: float
    prominence_frac: float
    phase: float
    class_tau: tuple[float, ...]
    search_min: float
    search_max: float
    amplitude: float
    support_half_width: float
    support_half_width_phase: float
    reason: str
    candidates: tuple[PeakCandidate, ...]

    def as_dict(self) -> dict:
        """Return a JSON-serialisable view for ``template_meta.json``."""
        return {
            "tau_peak": self.tau_peak,
            "mu_peak": self.mu_peak,
            "prominence_frac": self.prominence_frac,
            "phase": self.phase,
            "class_tau": list(self.class_tau),
            "search_min": self.search_min,
            "search_max": self.search_max,
            "amplitude": self.amplitude,
            "support_half_width": self.support_half_width,
            "support_half_width_phase": self.support_half_width_phase,
            "reason": self.reason,
            "candidates": [c.as_dict() for c in self.candidates],
        }


def _extrema_sign(extrema_mode: str) -> float:
    """Return ``+1`` for maxima and ``-1`` for minima."""
    if extrema_mode not in EXTREMA_MODES:
        raise ValueError(f"extrema_mode must be one of {EXTREMA_MODES}, got {extrema_mode!r}")
    return 1.0 if extrema_mode == "max" else -1.0


def _phase_distance(phase_a: float, phase_b: float) -> float:
    """Circular distance between two phases in ``[0, 0.5]``."""
    delta = abs(phase_a - phase_b) % 1.0
    return min(delta, 1.0 - delta)


def _format_candidates(candidates: list[PeakCandidate]) -> str:
    """One-line-per-candidate table for logs and error messages."""
    if not candidates:
        return "  (none)"
    return "\n".join(
        f"  tau={c.tau:+.5f} mu={c.mu:+.4f} prominence={c.prominence:.4f} "
        f"({c.prominence_frac:.3f} of amplitude) phase={c.phase:.3f}"
        f"{'' if c.accepted else '  rejected: ' + str(c.reject_reason)}"
        for c in candidates
    )


def _group_by_phase(
    accepted: list[PeakCandidate],
    duplicate_phase_tol: float,
) -> list[list[PeakCandidate]]:
    """Group duplicate copies of the same extremum by fold phase.

    Classes are seeded by the most prominent candidate, so a weak edge copy joins
    the strong one rather than starting a class of its own.

    Args:
        accepted (list[PeakCandidate]): Candidates that passed all cuts.
        duplicate_phase_tol (float): Maximum circular phase distance within a class.

    Returns:
        list[list[PeakCandidate]]: Classes, most prominent first.
    """
    classes: list[list[PeakCandidate]] = []
    for cand in sorted(accepted, key=lambda c: c.prominence, reverse=True):
        for members in classes:
            if _phase_distance(cand.phase, members[0].phase) <= duplicate_phase_tol:
                members.append(cand)
                break
        else:
            classes.append([cand])
    return classes


def symmetric_support(tau: float, *, tau_data_min: float, tau_data_max: float) -> float:
    """Widest symmetric half window around ``tau`` still covered by folded data.

    Args:
        tau (float): Fold coordinate in days.
        tau_data_min (float): Lowest ``tau`` covered by folded data.
        tau_data_max (float): Highest ``tau`` covered by folded data.

    Returns:
        float: ``min(tau - tau_data_min, tau_data_max - tau)``; negative if outside.
    """
    return min(tau - tau_data_min, tau_data_max - tau)


def _choose_copy(
    members: list[PeakCandidate],
    *,
    tau_data_min: float,
    tau_data_max: float,
) -> PeakCandidate:
    """Pick the best-centred copy of one extremum.

    The extended fold spans two periods, so of the two copies of any extremum one
    always sits at least half a period away from both ends of the folded data.
    Choosing the copy with the widest symmetric support therefore guarantees that
    any Step 2 window up to half a period wide is backed by real photometry.
    Ties are broken towards ``tau = 0``, the copy targeted by ``local_epoch``.

    Args:
        members (list[PeakCandidate]): Copies of the same physical extremum.
        tau_data_min (float): Lowest ``tau`` covered by folded data.
        tau_data_max (float): Highest ``tau`` covered by folded data.

    Returns:
        PeakCandidate: The copy to use for timing.
    """
    return max(
        members,
        key=lambda c: (
            round(symmetric_support(c.tau, tau_data_min=tau_data_min, tau_data_max=tau_data_max), 12),
            -abs(c.tau),
        ),
    )


def select_template_peak(
    tau: np.ndarray,
    mu: np.ndarray,
    period: float,
    *,
    tau_data_min: float,
    tau_data_max: float,
    extrema_mode: str = "max",
    edge_margin_frac_period: float = 0.05,
    min_separation_frac_period: float = 0.15,
    min_prominence_frac: float = 0.25,
    duplicate_phase_tol: float = 0.05,
    select: str = "dominant",
    tau_hint: float | None = None,
) -> PeakSelection:
    """Choose ``tau_peak`` for timing on the GP template grid.

    Candidates are local extrema of the GP mean restricted to the folded data
    range, inset by an edge margin, and ranked by topographic prominence relative
    to the in-range peak-to-peak amplitude. Duplicate copies produced by the
    extended fold are grouped by phase before the dominant extremum is selected;
    of the surviving copies the best-centred one is used, which keeps any Step 2
    window up to half a period wide inside real photometry.

    Args:
        tau (numpy.ndarray): Template grid in days (phase fold coordinate).
        mu (numpy.ndarray): GP mean on ``tau``.
        period (float): Fold period in days; sets the duplicate-copy spacing.
        tau_data_min (float): Lowest ``tau`` covered by folded data (grid pad excluded).
        tau_data_max (float): Highest ``tau`` covered by folded data (grid pad excluded).
        extrema_mode (str): ``max`` to time a maximum, ``min`` to time a minimum.
        edge_margin_frac_period (float): Candidate search window is inset from the
            data range by this fraction of ``period`` at each end.
        min_separation_frac_period (float): Minimum separation between candidates
            as a fraction of ``period``.
        min_prominence_frac (float): Minimum prominence as a fraction of the
            in-range peak-to-peak amplitude.
        duplicate_phase_tol (float): Phase tolerance for treating two candidates
            as copies of the same extremum.
        select (str): ``dominant`` (most prominent class) or ``nearest_phase0``.
        tau_hint (float | None): If given, the class nearest this ``tau`` wins,
            overriding ``select``.

    Returns:
        PeakSelection: Selected peak plus the full candidate diagnostics.

    Raises:
        ValueError: If the inputs are inconsistent or no candidate survives the
            edge margin and prominence cuts.
    """
    sign = _extrema_sign(extrema_mode)
    if select not in PEAK_SELECT_RULES:
        raise ValueError(f"peak_select must be one of {PEAK_SELECT_RULES}, got {select!r}")
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if tau_data_max <= tau_data_min:
        raise ValueError(f"empty data tau range [{tau_data_min}, {tau_data_max}]")

    tau = np.asarray(tau, dtype=float)
    mu = np.asarray(mu, dtype=float)

    in_data = (tau >= tau_data_min) & (tau <= tau_data_max)
    if int(np.count_nonzero(in_data)) < 8:
        raise ValueError(
            f"only {int(np.count_nonzero(in_data))} grid points inside the data tau range "
            f"[{tau_data_min:.5f}, {tau_data_max:.5f}]; increase n_grid"
        )
    tau_in = tau[in_data]
    mu_in = mu[in_data]
    z_in = sign * mu_in

    amplitude = float(np.max(z_in) - np.min(z_in))
    if not np.isfinite(amplitude) or amplitude <= 0:
        raise ValueError("template is flat inside the data range; cannot locate an extremum")

    margin = edge_margin_frac_period * period
    search_min = tau_data_min + margin
    search_max = tau_data_max - margin
    if search_max <= search_min:
        raise ValueError(
            f"peak_edge_margin_frac_period={edge_margin_frac_period} leaves no search window "
            f"in tau range [{tau_data_min:.5f}, {tau_data_max:.5f}] for period={period}"
        )

    d_tau = float(np.median(np.diff(tau_in)))
    distance = max(1, int(round(min_separation_frac_period * period / d_tau)))
    idx, props = find_peaks(z_in, prominence=0.0, distance=distance)

    candidates: list[PeakCandidate] = []
    accepted: list[PeakCandidate] = []
    for i, prom in zip(idx, props["prominences"]):
        t_i = float(tau_in[i])
        frac = float(prom) / amplitude
        if t_i < search_min or t_i > search_max:
            reason: str | None = "inside the edge margin"
        elif frac < min_prominence_frac:
            reason = f"prominence {frac:.3f} below peak_min_prominence_frac={min_prominence_frac}"
        else:
            reason = None
        cand = PeakCandidate(
            tau=t_i,
            mu=float(mu_in[i]),
            prominence=float(prom),
            prominence_frac=frac,
            phase=float((t_i / period) % 1.0),
            accepted=reason is None,
            reject_reason=reason,
        )
        candidates.append(cand)
        if cand.accepted:
            accepted.append(cand)

    if not accepted:
        raise ValueError(
            f"no {extrema_mode} survives peak selection in tau window "
            f"[{search_min:.5f}, {search_max:.5f}] (amplitude={amplitude:.4f}); "
            f"lower peak_min_prominence_frac or peak_edge_margin_frac_period, or set "
            f"peak_tau_hint. Candidates:\n{_format_candidates(candidates)}"
        )

    classes = _group_by_phase(accepted, duplicate_phase_tol)
    if tau_hint is not None:
        members = min(classes, key=lambda m: min(abs(c.tau - tau_hint) for c in m))
        rule = f"class nearest peak_tau_hint={tau_hint:.5f}"
    elif select == "nearest_phase0":
        members = min(classes, key=lambda m: min(abs(c.tau) for c in m))
        rule = "class nearest phase 0"
    else:
        members = max(classes, key=lambda m: max(c.prominence for c in m))
        rule = "most prominent class"

    chosen = _choose_copy(
        members,
        tau_data_min=tau_data_min,
        tau_data_max=tau_data_max,
    )
    support = symmetric_support(
        chosen.tau, tau_data_min=tau_data_min, tau_data_max=tau_data_max
    )
    reason = (
        f"{rule}; {len(classes)} class(es) from {len(accepted)}/{len(candidates)} candidates; "
        f"copy {len(members)} of phase {chosen.phase:.3f} at tau={chosen.tau:+.5f} "
        f"(prominence {chosen.prominence_frac:.3f} of amplitude, symmetric support "
        f"+/-{support:.5f} d = {support / period:.3f} in phase)"
    )
    logger.info("Peak selection: %s", reason)
    logger.debug("Peak candidates:\n%s", _format_candidates(candidates))

    return PeakSelection(
        tau_peak=chosen.tau,
        mu_peak=chosen.mu,
        prominence_frac=chosen.prominence_frac,
        phase=chosen.phase,
        class_tau=tuple(sorted(c.tau for c in members)),
        search_min=search_min,
        search_max=search_max,
        amplitude=amplitude,
        support_half_width=float(support),
        support_half_width_phase=float(support / period),
        reason=reason,
        candidates=tuple(candidates),
    )
