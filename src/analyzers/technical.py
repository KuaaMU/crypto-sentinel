import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.models import ScoreResult, Direction

logger = logging.getLogger(__name__)


def _calculate_rsi(closes: pd.Series, period: int = 14) -> float:
    """Calculate RSI from close prices."""
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else 50.0


def _calculate_ema(closes: pd.Series, period: int) -> float:
    """Calculate EMA value."""
    ema = closes.ewm(span=period, adjust=False).mean()
    return float(ema.iloc[-1]) if not ema.empty else 0.0


def analyze_technical(
    ohlcv_data: list,  # [[timestamp, open, high, low, close, volume], ...]
    pair: str,
) -> ScoreResult:
    """Analyze technical indicators: RSI + EMA trend + volume.

    Scoring:
    - RSI < 30: Oversold → bullish (score += 20-30)
    - RSI 30-45: Mild bullish (score += 5-15)
    - RSI 45-55: Neutral
    - RSI 55-70: Mild bearish (score -= 5-15)
    - RSI > 70: Overbought → bearish (score -= 20-30)

    - EMA 8 > 21 > 55: Strong uptrend (score += 20)
    - EMA 8 < 21 < 55: Strong downtrend (score -= 20)

    - Volume > 1.5x avg: Confirmation (amplify signal)
    """
    if not ohlcv_data or len(ohlcv_data) < 60:
        return ScoreResult(
            value=50, direction=Direction.NEUTRAL, confidence=0,
            reason=f"{pair}: Insufficient data ({len(ohlcv_data)} candles)",
            timestamp=datetime.now(tz=timezone.utc),
        )

    df = pd.DataFrame(ohlcv_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    closes = df["close"]
    volumes = df["volume"]

    # --- RSI ---
    rsi = _calculate_rsi(closes, 14)
    if rsi < 30:
        rsi_score = 80 + (30 - rsi)  # 80-110 capped later
        rsi_reason = f"RSI {rsi:.0f} oversold"
    elif rsi < 45:
        rsi_score = 55 + (45 - rsi)
        rsi_reason = f"RSI {rsi:.0f} mild bullish"
    elif rsi <= 55:
        rsi_score = 50
        rsi_reason = f"RSI {rsi:.0f} neutral"
    elif rsi <= 70:
        rsi_score = 45 - (rsi - 55)
        rsi_reason = f"RSI {rsi:.0f} mild bearish"
    else:
        rsi_score = 20 - (rsi - 70)
        rsi_reason = f"RSI {rsi:.0f} overbought"

    # --- EMA trend ---
    ema8 = _calculate_ema(closes, 8)
    ema21 = _calculate_ema(closes, 21)
    ema55 = _calculate_ema(closes, 55)
    current_price = float(closes.iloc[-1])

    if ema8 > ema21 > ema55 and current_price > ema8:
        ema_score = 75
        ema_reason = "Strong uptrend (8>21>55)"
    elif ema8 > ema21:
        ema_score = 60
        ema_reason = "Mild uptrend (8>21)"
    elif ema8 < ema21 < ema55 and current_price < ema8:
        ema_score = 25
        ema_reason = "Strong downtrend (8<21<55)"
    elif ema8 < ema21:
        ema_score = 40
        ema_reason = "Mild downtrend (8<21)"
    else:
        ema_score = 50
        ema_reason = "EMA neutral"

    # --- Volume ---
    vol_mean = float(volumes.rolling(20).mean().iloc[-1]) if len(volumes) >= 20 else float(volumes.mean())
    current_vol = float(volumes.iloc[-1])
    vol_ratio = current_vol / vol_mean if vol_mean > 0 else 1.0

    # Volume amplifies the signal direction
    vol_multiplier = min(vol_ratio / 1.5, 1.5)  # cap at 1.5x

    # --- Combined ---
    raw_score = rsi_score * 0.40 + ema_score * 0.35 + 50 * 0.25
    # Amplify by volume (move away from 50)
    if vol_ratio > 1.5:
        raw_score = 50 + (raw_score - 50) * vol_multiplier

    final_score = max(0, min(100, raw_score))

    if final_score > 60:
        direction = Direction.LONG
    elif final_score < 40:
        direction = Direction.SHORT
    else:
        direction = Direction.NEUTRAL

    confidence = abs(final_score - 50) / 50
    reason = f"{pair}: {rsi_reason} | {ema_reason} | Vol {vol_ratio:.1f}x"

    return ScoreResult(
        value=round(final_score, 1),
        direction=direction,
        confidence=round(confidence, 3),
        reason=reason,
        timestamp=datetime.now(tz=timezone.utc),
    )
