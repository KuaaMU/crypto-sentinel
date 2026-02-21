import logging
from datetime import datetime, timezone

from src.models import ScoreResult, Direction, FearGreedData

logger = logging.getLogger(__name__)


def analyze_sentiment(
    fear_greed: FearGreedData | None,
    news_data: dict,
) -> ScoreResult:
    """Analyze market sentiment from Fear & Greed Index + news momentum.

    Scoring logic:
    - Fear & Greed < 25: Extreme Fear → contrarian bullish (score 70-90)
    - Fear & Greed 25-45: Fear → mild bullish (score 55-70)
    - Fear & Greed 45-55: Neutral (score 45-55)
    - Fear & Greed 55-75: Greed → mild bearish (score 30-45)
    - Fear & Greed > 75: Extreme Greed → contrarian bearish (score 10-30)

    News sentiment adds ±15 points.
    """
    # Base score from Fear & Greed (contrarian)
    if fear_greed is None:
        fg_score = 50.0
        fg_reason = "F&G unavailable"
    else:
        fg_value = fear_greed.value
        if fg_value < 25:
            # Extreme Fear → contrarian bullish
            fg_score = 90 - (fg_value * 0.8)  # 90 at 0, 70 at 25
            fg_reason = f"Extreme Fear ({fg_value}) → contrarian bullish"
        elif fg_value < 45:
            fg_score = 70 - (fg_value - 25) * 0.75  # 70 at 25, 55 at 45
            fg_reason = f"Fear ({fg_value}) → mild bullish"
        elif fg_value <= 55:
            fg_score = 55 - (fg_value - 45)  # 55 at 45, 45 at 55
            fg_reason = f"Neutral ({fg_value})"
        elif fg_value <= 75:
            fg_score = 45 - (fg_value - 55) * 0.75  # 45 at 55, 30 at 75
            fg_reason = f"Greed ({fg_value}) → mild bearish"
        else:
            fg_score = 30 - (fg_value - 75) * 0.8  # 30 at 75, 10 at 100
            fg_reason = f"Extreme Greed ({fg_value}) → contrarian bearish"

    # News momentum adjustment (±15)
    news_score = news_data.get("sentiment_score", 50)
    news_adjustment = (news_score - 50) * 0.3  # scale to ±15

    final_score = max(0, min(100, fg_score * 0.7 + (news_score * 0.3)))

    # Determine direction
    if final_score > 60:
        direction = Direction.LONG
    elif final_score < 40:
        direction = Direction.SHORT
    else:
        direction = Direction.NEUTRAL

    confidence = abs(final_score - 50) / 50  # 0 at neutral, 1 at extremes

    reason_parts = [fg_reason]
    if news_data.get("market_cap_change_24h"):
        reason_parts.append(f"Market 24h: {news_data['market_cap_change_24h']:+.1f}%")

    return ScoreResult(
        value=round(final_score, 1),
        direction=direction,
        confidence=round(confidence, 3),
        reason=" | ".join(reason_parts),
        timestamp=datetime.now(tz=timezone.utc),
    )
