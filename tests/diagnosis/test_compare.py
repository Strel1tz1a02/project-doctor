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


def test_stable_uses_iqr_dispersion_with_absolute_floor() -> None:
    # Dispersion is the interquartile range (middle 50%), robust to a single
    # extreme: a lone outlier no longer fails an otherwise-stable group.
    assert stable([100.0, 100.0, 100.0, 100.0, 200.0], POLICY) is True  # IQR == 0
    # Middle-50% spread beyond the 25% relative tolerance fails (n=3 → IQR is half the range).
    assert stable([75.0, 100.0, 140.0], POLICY) is False  # IQR 32.5 > 25.0
    # Sub-millisecond groups fall back to the absolute floor, not the relative check.
    assert stable([0.4, 0.4, 0.9], POLICY) is True  # IQR 0.25 ≤ 0.5 ms floor
    assert stable([0.4, 0.4, 1.5], POLICY) is False  # IQR 0.55 > 0.5 ms floor


def test_distinguishable_requires_both_sides_stable() -> None:
    good = [100.0, 101.0, 102.0]
    noisy = [1.0, 50.0, 99.0]
    assert distinguishable(good, noisy, POLICY) is False


def test_distinguishable_rejects_when_delta_below_minimum() -> None:
    # Medians differ by 0.5 ms, below minimum_delta_ms=1.0.
    assert distinguishable([100.0, 100.0, 100.0], [99.5, 99.5, 99.5], POLICY) is False


def test_distinguishable_requires_delta_above_noise() -> None:
    # Medians differ by 2 ms, but the IQR noise floor (2 + 1 = 3) exceeds it.
    baseline = [98.0, 100.0, 102.0]
    candidate = [97.0, 98.0, 99.0]
    assert distinguishable(baseline, candidate, POLICY) is False


def test_distinguishable_accepts_clear_signal() -> None:
    baseline = [100.0, 100.0, 100.0]
    candidate = [20.0, 20.0, 20.0]
    assert distinguishable(baseline, candidate, POLICY) is True
