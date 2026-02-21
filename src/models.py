from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Direction(Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class PositionStatus(Enum):
    OPEN = "open"
    PARTIAL_CLOSED = "partial_closed"
    CLOSED = "closed"


@dataclass(frozen=True)
class ScoreResult:
    """Immutable score from a single analyzer."""
    value: float          # 0-100
    direction: Direction
    confidence: float     # 0-1
    reason: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class CompositeSignal:
    """Immutable combined signal from all analyzers."""
    sentiment_score: ScoreResult
    whale_score: ScoreResult
    technical_score: ScoreResult
    conviction: float      # 0-1 combined
    direction: Direction
    pair: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class TradeOrder:
    """Immutable order instruction."""
    pair: str
    direction: Direction
    size_pct: float        # % of wallet
    leverage: int
    conviction: float
    entry_price: float
    stop_loss: float
    tp_levels: tuple       # ((pct, target_price), ...)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Position:
    """Mutable position state (only object that changes in place)."""
    id: str
    pair: str
    direction: Direction
    entry_price: float
    size: float
    remaining_size: float
    leverage: int
    conviction: float
    stop_loss: float
    trailing_stop: float
    tp_levels: list
    status: PositionStatus
    opened_at: datetime
    closed_at: Optional[datetime] = None
    realized_pnl: float = 0.0
    exit_reason: str = ""


@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable market data at a point in time."""
    pair: str
    price: float
    bid: float
    ask: float
    volume_24h: float
    high_24h: float
    low_24h: float
    change_24h_pct: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class FearGreedData:
    """Immutable Fear & Greed Index data."""
    value: int             # 0-100
    classification: str    # "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    timestamp: datetime


@dataclass(frozen=True)
class WhaleTransaction:
    """Immutable whale transaction record."""
    tx_hash: str
    from_addr: str
    to_addr: str
    value_usd: float
    token: str
    is_exchange_inflow: bool
    is_exchange_outflow: bool
    timestamp: datetime
