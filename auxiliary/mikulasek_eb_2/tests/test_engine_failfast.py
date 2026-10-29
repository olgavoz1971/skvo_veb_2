"""Fail-fast behaviour: no silent drops, no silent non-convergence."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import mikulasek_eb as engine
from mikulasek_eb import EBModel, FitDidNotConverge, phase, virtual_minima

PERIOD_D = 0.5
M0_D = 0.1
SPAN_D = 4.0
CADENCE_D = 6.0 / 1440.0
PARAMS = dict(A1=0.4, A2=0.3, D1=0.04, G1=1.5, C1=0.0)
MIN_FAILED_EVENTS = 10


def _simple_data():
    """Return a noiseless short synthetic light curve and its model."""
    t = np.arange(0.0, SPAN_D, CADENCE_D)
    model = EBModel(profile=1, harmonics=(), ocon=False)
    mag = model(phase(t, M0_D, PERIOD_D), PARAMS)
    return t, mag, np.full(len(t), 0.002), model


def test_non_converged_solution_raises():
    """A solver result without success is an error, not a result."""
    bad = SimpleNamespace(success=False, status=0, message="max evaluations", jac=np.eye(2))
    with pytest.raises(FitDidNotConverge):
        engine._check_solution(bad, "test")


def test_rank_deficient_jacobian_is_flagged():
    """Degenerate parameters are reported through the return value."""
    ok = SimpleNamespace(success=True, status=1, message="ok", jac=np.eye(2))
    degenerate = SimpleNamespace(success=True, status=1, message="ok",
                                 jac=np.array([[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]))
    assert engine._check_solution(ok, "test") is False
    assert engine._check_solution(degenerate, "test") is True


def test_failed_event_fit_is_recorded_not_dropped(monkeypatch):
    """An exception in one event fit lands in ``rejected`` as ``fit_failed``."""
    t, mag, sig, model = _simple_data()

    def boom(*args, **kwargs):
        raise ValueError("synthetic failure")

    monkeypatch.setattr(engine, "fit_minimum", boom)
    rejected: list = []
    vm = virtual_minima(t, mag, sig, model, PARAMS, dict(M0=M0_D, P0=PERIOD_D),
                        window=0.25, order=1, rejected=rejected)
    assert len(vm["T"]) == 0
    failed = [row for row in rejected if row["reason"] == "fit_failed"]
    assert len(failed) >= MIN_FAILED_EVENTS
    assert all("synthetic failure" in row["detail"] for row in failed)
    # Edge events may also be rejected for coverage; nothing else is allowed.
    others = {row["reason"] for row in rejected} - {"fit_failed"}
    assert others <= {"too_few_points", "one_side_uncovered", "walls_uncovered"}
