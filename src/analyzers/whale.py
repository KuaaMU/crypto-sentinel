import logging
from datetime import datetime, timezone

from src.models import ScoreResult, Direction, WhaleTransaction

logger = logging.getLogger(__name__)


def analyze_whale_activity(
    whale_txs: list[WhaleTransaction],
    orderbook_data: dict[str, dict],
) -> ScoreResult:
    """Analyze whale transactions and orderbook imbalance.

    Logic:
    - Net exchange outflow → bullish (whales accumulating)
    - Net exchange inflow → bearish (whales selling)
    - Orderbook bid > ask → bullish (buy wall)
    - Orderbook ask > bid → bearish (sell wall)
    """
    # --- Whale transaction analysis ---
    inflow_usd = sum(tx.value_usd for tx in whale_txs if tx.is_exchange_inflow)
    outflow_usd = sum(tx.value_usd for tx in whale_txs if tx.is_exchange_outflow)
    net_flow = outflow_usd - inflow_usd  # positive = bullish (more leaving exchanges)

    if (inflow_usd + outflow_usd) > 0:
        flow_ratio = net_flow / (inflow_usd + outflow_usd)  # -1 to +1
    else:
        flow_ratio = 0

    # Convert to 0-100 score (50 = neutral)
    whale_flow_score = 50 + (flow_ratio * 40)  # range: 10-90

    # --- Orderbook imbalance analysis ---
    imbalance_scores = []
    for pair, ob in orderbook_data.items():
        imbalance = ob.get("imbalance", 0)  # -1 to +1
        imbalance_scores.append(imbalance)

    avg_imbalance = sum(imbalance_scores) / len(imbalance_scores) if imbalance_scores else 0
    orderbook_score = 50 + (avg_imbalance * 30)  # range: 20-80

    # --- Combined whale score ---
    # Whale flow is more important (60%) than orderbook (40%)
    if whale_txs:
        final_score = whale_flow_score * 0.6 + orderbook_score * 0.4
    else:
        # No whale data available, rely only on orderbook
        final_score = orderbook_score

    final_score = max(0, min(100, final_score))

    # Direction
    if final_score > 60:
        direction = Direction.LONG
    elif final_score < 40:
        direction = Direction.SHORT
    else:
        direction = Direction.NEUTRAL

    confidence = abs(final_score - 50) / 50

    # Build reason
    reasons = []
    if whale_txs:
        reasons.append(f"Whale inflow ${inflow_usd/1e6:.1f}M, outflow ${outflow_usd/1e6:.1f}M")
    else:
        reasons.append("No whale tx data")
    reasons.append(f"Orderbook imbalance: {avg_imbalance:+.3f}")

    return ScoreResult(
        value=round(final_score, 1),
        direction=direction,
        confidence=round(confidence, 3),
        reason=" | ".join(reasons),
        timestamp=datetime.now(tz=timezone.utc),
    )
