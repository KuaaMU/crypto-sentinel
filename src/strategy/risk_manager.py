import logging

from src.config import TradingConfig
from src.models import CompositeSignal

logger = logging.getLogger(__name__)


def calculate_position_size(
    signal: CompositeSignal,
    wallet_balance: float,
    config: TradingConfig,
) -> tuple[float, int]:
    """Calculate position size and leverage based on conviction.

    Returns (position_size_usd, leverage).

    Rules:
    - conviction 0.65-0.75: small position (50% of max), base leverage
    - conviction 0.75-0.85: medium position (75% of max), base+1 leverage
    - conviction 0.85+: full position (100% of max), up to max leverage
    """
    max_position = wallet_balance * config.max_position_pct
    conviction = signal.conviction

    if conviction >= 0.85:
        size_pct = 1.0
        leverage = min(config.max_leverage, config.base_leverage + 3)
    elif conviction >= 0.75:
        size_pct = 0.75
        leverage = min(config.max_leverage, config.base_leverage + 1)
    else:
        size_pct = 0.50
        leverage = config.base_leverage

    position_size = max_position * size_pct

    logger.info(
        "Position sizing: conviction=%.3f → size=$%.2f (%.0f%% of max), leverage=%dx",
        conviction, position_size, size_pct * 100, leverage,
    )
    return position_size, leverage


def check_risk_limits(
    current_positions: int,
    daily_pnl_pct: float,
    config: TradingConfig,
) -> tuple[bool, str]:
    """Check if we're within risk limits.

    Returns (allowed, reason).
    """
    if current_positions >= config.max_positions:
        return False, f"Max positions reached ({current_positions}/{config.max_positions})"

    if daily_pnl_pct <= config.daily_loss_limit:
        return False, f"Daily loss limit hit ({daily_pnl_pct:.2%} <= {config.daily_loss_limit:.2%})"

    return True, "OK"
