"""Measurement policy boundary tests: the fluctuation threshold must hold exactly."""

import pytest

from project_doctor.features.diagnosis.compare import (
    MeasurementPolicy,
    distinguishable,
    stable,
)

POLICY = MeasurementPolicy()


def test_policy_rejects_degenerate_values() -> None:
    with pytest.raises(ValueError):
        MeasurementPolicy(minimum_repetitions=2)
    with pytest.raises(ValueError):
        MeasurementPolicy(maximum_relative_spread=0)
    with pytest.raises(ValueError):
        MeasurementPolicy(maximum_relative_spread=1.5)
    with pytest.raises(ValueError):
        MeasurementPolicy(minimum_delta_ms=0)


def test_stable_requires_minimum_repetitions() -> None:
    assert stable([10.0, 11.0], POLICY) is False
    assert stable([10.0, 10.5, 11.0], POLICY) is True


def test_stable_rejects_negative_or_zero_center() -> None:
    assert stable([0.0, 0.0, 0.0], POLICY) is False
    assert stable([-1.0, -1.0, -1.0], POLICY) is False


def test_stable_enforces_relative_spread_boundary() -> None:
    # Relative spread exactly at 25% passes (inclusive); a hair above fails.
    assert stable([100.0, 112.5, 125.0], POLICY) is True  # (125-100)/112.5 ≈ 0.2222
    assert stable([100.0, 100.0, 125.0], POLICY) is True  # (125-100)/100 == 0.25
    assert stable([100.0, 100.0, 125.1], POLICY) is False  # 0.251 > 0.25


def test_distinguishable_requires_both_sides_stable() -> None:
    good = [100.0, 101.0, 102.0]
    noisy = [1.0, 50.0, 99.0]
    assert distinguishable(good, noisy, POLICY) is False


def test_distinguishable_rejects_when_delta_below_minimum() -> None:
    # Medians differ by 0.5 ms, below minimum_delta_ms=1.0.
    assert distinguishable([100.0, 100.0, 100.0], [99.5, 99.5, 99.5], POLICY) is False


def test_distinguishable_requires_delta_above_noise() -> None:
    # Medians differ by 2 ms, but the noise floor exceeds it.
    baseline = [98.0, 100.0, 102.0]
    candidate = [97.0, 98.0, 99.0]
    noise = (max(baseline) - min(baseline)) + (max(candidate) - min(candidate))  # 4 + 2 = 6
    assert noise > 2
    assert distinguishable(baseline, candidate, POLICY) is False


def test_distinguishable_accepts_clear_signal() -> None:
    baseline = [100.0, 100.0, 100.0]
    candidate = [20.0, 20.0, 20.0]
    assert distinguishable(baseline, candidate, POLICY) is True
