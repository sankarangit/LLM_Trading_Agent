"""Market fills with adverse spread/slippage and adverse tick rounding."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
from .types import ExecutionConfig


@dataclass(frozen=True)
class Fill:
    reference_price: float
    price: float
    size: float
    direction: int
    commission: float
    spread_cost: float
    slippage_cost: float
    rounding_cost: float

    @property
    def total_cost(self):
        return self.commission + self.spread_cost + self.slippage_cost + self.rounding_cost


def validate_execution(c: ExecutionConfig):
    for name in ("commission_bps_per_side", "slippage_bps_per_side", "spread_bps"):
        x = getattr(c, name)
        if not math.isfinite(x) or x < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    if (c.spread_bps/2 + c.slippage_bps_per_side) >= 10000:
        raise ValueError("execution friction must not create nonpositive fills")
    if any(not math.isfinite(x) or x <= 0 for x in (c.minimum_tick, c.quantity_increment)):
        raise ValueError("positive tick and quantity increment required")
    if c.ambiguity_policy not in {"stop_first", "reject"}:
        raise ValueError("ambiguity_policy must be stop_first or reject")


def costed_fill(reference_price: float, size: float, direction: int,
                c: ExecutionConfig) -> Fill:
    validate_execution(c)
    if direction not in (-1, 1) or reference_price <= 0 or size <= 0 or not all(
            math.isfinite(x) for x in (reference_price, size)):
        raise ValueError("invalid fill input")
    ref, tick = Decimal(str(reference_price)), Decimal(str(c.minimum_tick))
    spread = ref * Decimal(str(c.spread_bps)) / Decimal(20000)
    slip = ref * Decimal(str(c.slippage_bps_per_side)) / Decimal(10000)
    adverse = ref + direction * (spread + slip)
    price = (adverse / tick).to_integral_value(rounding=ROUND_CEILING if direction == 1 else ROUND_FLOOR) * tick
    if price <= 0:
        raise ValueError("tick/cost combination creates nonpositive fill")
    rounding = abs(price - adverse)
    return Fill(reference_price, float(price), size, direction,
                float(price) * size * c.commission_bps_per_side / 10000,
                float(spread) * size, float(slip) * size, float(rounding) * size)


def floor_quantity(value: float, increment: float) -> float:
    return float((Decimal(str(max(0, value))) / Decimal(str(increment))).to_integral_value(
        rounding=ROUND_FLOOR) * Decimal(str(increment)))
