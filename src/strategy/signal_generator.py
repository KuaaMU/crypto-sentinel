import logging
from datetime import datetime, timezone

from src.models import (
    ScoreResult, CompositeSignal, Direction,
)
from src.config import ScoringWeights

logger = logging.getLogger(__name__)


def generate_signal(
    sentiment: ScoreResult,
    whale: ScoreResult,
    technical: ScoreResult,
    weights: ScoringWeights,
    pair: str,
) -> CompositeSignal:
    """Combine three dimension scores into a single conviction signal.

    Conviction = weighted average of scores, normalized to 0-1.
    Direction = majority vote of individual directions, weighted by confidence.
    """
    # Weighted conviction
    weighted_score = (
        sentiment.value * weights.sentiment
        + whale.value * weights.whale
        + technical.value * weights.technical
    )
    conviction = weighted_score / 100.0  # normalize to 0-1

    # Direction via weighted vote
    direction_votes = {Direction.LONG: 0.0, Direction.SHORT: 0.0, Direction.NEUTRAL: 0.0}
    for score, weight in [(sentiment, weights.sentiment), (whale, weights.whale), (technical, weights.technical)]:
        direction_votes[score.direction] += weight * score.confidence

    # Winner takes all
    best_direction = max(direction_votes, key=direction_votes.get)

    # If conviction is near 0.5, force neutral
    if 0.40 <= conviction <= 0.60:
        best_direction = Direction.NEUTRAL

    return CompositeSignal(
        sentiment_score=sentiment,
        whale_score=whale,
        technical_score=technical,
        conviction=round(conviction, 4),
        direction=best_direction,
        pair=pair,
        timestamp=datetime.now(tz=timezone.utc),
    )


def should_enter(signal: CompositeSignal, threshold: float) -> bool:
    """Determine if conviction is high enough to enter a trade."""
    return (
        signal.direction != Direction.NEUTRAL
        and signal.conviction >= threshold
    )
