from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class MeasurementPolicy:
    minimum_repetitions: int = 3
    maximum_relative_spread: float = 0.25
    minimum_delta_ms: float = 1.0

    def __post_init__(self) -> None:
        import math

        if (
            self.minimum_repetitions < 3
            or not math.isfinite(self.maximum_relative_spread)
            or not 0 < self.maximum_relative_spread <= 1
            or not math.isfinite(self.minimum_delta_ms)
            or self.minimum_delta_ms <= 0
        ):
            raise ValueError("invalid measurement policy")


def stable(values: list[float], policy: MeasurementPolicy) -> bool:
    if len(values) < policy.minimum_repetitions:
        return False
    center = median(values)
    return center > 0 and (max(values) - min(values)) / center <= policy.maximum_relative_spread


def distinguishable(
    baseline: list[float], candidate: list[float], policy: MeasurementPolicy
) -> bool:
    if not stable(baseline, policy) or not stable(candidate, policy):
        return False
    noise = max(baseline) - min(baseline) + max(candidate) - min(candidate)
    return median(baseline) - median(candidate) > max(policy.minimum_delta_ms, noise)
