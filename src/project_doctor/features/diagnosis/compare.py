from dataclasses import dataclass
from statistics import median


def _quantile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated quantile over an already-sorted list (numpy ``linear`` style)."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    pos = (n - 1) * p
    lo = int(pos)
    hi = lo + 1
    if hi >= n:
        return sorted_values[n - 1]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _iqr(values: list[float]) -> float:
    """Robust dispersion: interquartile range (Q3 − Q1), insensitive to extremes.

    The max−min range is the least robust dispersion statistic and never converges;
    a single cold-cache outlier can fail an otherwise-stable group. The IQR tracks
    the middle 50% and is the natural companion to the median used elsewhere.
    """
    ordered = sorted(values)
    return _quantile(ordered, 0.75) - _quantile(ordered, 0.25)


@dataclass(frozen=True)
class MeasurementPolicy:
    minimum_repetitions: int = 3
    maximum_relative_spread: float = 0.25
    minimum_delta_ms: float = 1.0
    # Sub-millisecond floor: a relative spread check is undefined/over-strict at
    # sub-ms scales (0.4ms median with 0.3ms dispersion is 75%, yet the absolute
    # jitter is irrelevant to a multi-ms effect). Bound dispersion absolutely below.
    minimum_absolute_spread_ms: float = 0.5

    def __post_init__(self) -> None:
        import math

        if (
            self.minimum_repetitions < 3
            or not math.isfinite(self.maximum_relative_spread)
            or not 0 < self.maximum_relative_spread <= 1
            or not math.isfinite(self.minimum_delta_ms)
            or self.minimum_delta_ms <= 0
            or not math.isfinite(self.minimum_absolute_spread_ms)
            or self.minimum_absolute_spread_ms < 0
        ):
            raise ValueError("invalid measurement policy")


def stable(values: list[float], policy: MeasurementPolicy) -> bool:
    if len(values) < policy.minimum_repetitions:
        return False
    center = median(values)
    if center <= 0:
        return False
    tolerance = max(policy.maximum_relative_spread * center, policy.minimum_absolute_spread_ms)
    return _iqr(values) <= tolerance


def distinguishable(
    baseline: list[float], candidate: list[float], policy: MeasurementPolicy
) -> bool:
    if not stable(baseline, policy) or not stable(candidate, policy):
        return False
    noise = _iqr(baseline) + _iqr(candidate)
    return median(baseline) - median(candidate) > max(policy.minimum_delta_ms, noise)
