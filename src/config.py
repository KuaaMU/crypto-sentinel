import urllib.request
import yaml
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any


def _detect_proxy() -> str:
    """Auto-detect system proxy (Clash/V2Ray etc). Env var PROXY_URL overrides."""
    explicit = os.getenv("PROXY_URL", "")
    if explicit:
        return explicit
    proxies = urllib.request.getproxies()
    return proxies.get("https", proxies.get("http", ""))


@dataclass(frozen=True)
class ExchangeConfig:
    name: str
    sandbox: bool
    pairs: tuple
    api_key: str
    api_secret: str
    api_passphrase: str
    proxy: str


@dataclass(frozen=True)
class TradingConfig:
    base_leverage: int
    max_leverage: int
    max_positions: int
    max_position_pct: float
    daily_loss_limit: float
    entry_conviction_threshold: float
    exit_conviction_threshold: float
    max_hold_minutes: int


@dataclass(frozen=True)
class ScoringWeights:
    sentiment: float
    whale: float
    technical: float


@dataclass(frozen=True)
class ExitConfig:
    partial_tp_levels: tuple
    trailing_atr_multiplier: float
    trailing_atr_period: int


@dataclass(frozen=True)
class CollectorConfig:
    interval_seconds: int
    fear_greed_url: str
    coingecko_base: str
    etherscan_base: str
    min_whale_tx_usd: float
    etherscan_api_key: str
    crypto_news_api_key: str
    proxy: str


@dataclass(frozen=True)
class AppConfig:
    exchange: ExchangeConfig
    trading: TradingConfig
    scoring: ScoringWeights
    exit_strategy: ExitConfig
    collectors: CollectorConfig
    trading_mode: str


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load configuration from YAML file and environment variables."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_file, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    exchange_raw = raw["exchange"]
    trading_raw = raw["trading"]
    scoring_raw = raw["scoring_weights"]
    exit_raw = raw["exit_strategy"]
    coll_raw = raw["collectors"]

    tp_levels = tuple(
        (lv["pct"], lv["target"]) for lv in exit_raw["partial_tp_levels"]
    )

    proxy = _detect_proxy()

    return AppConfig(
        exchange=ExchangeConfig(
            name=exchange_raw["name"],
            sandbox=exchange_raw.get("sandbox", True),
            pairs=tuple(exchange_raw["pairs"]),
            api_key=os.getenv("OKX_API_KEY", ""),
            api_secret=os.getenv("OKX_API_SECRET", ""),
            api_passphrase=os.getenv("OKX_API_PASSPHRASE", ""),
            proxy=proxy,
        ),
        trading=TradingConfig(
            base_leverage=trading_raw["base_leverage"],
            max_leverage=trading_raw["max_leverage"],
            max_positions=trading_raw["max_positions"],
            max_position_pct=trading_raw["max_position_pct"],
            daily_loss_limit=trading_raw["daily_loss_limit"],
            entry_conviction_threshold=trading_raw["entry_conviction_threshold"],
            exit_conviction_threshold=trading_raw["exit_conviction_threshold"],
            max_hold_minutes=trading_raw["max_hold_minutes"],
        ),
        scoring=ScoringWeights(
            sentiment=scoring_raw["sentiment"],
            whale=scoring_raw["whale"],
            technical=scoring_raw["technical"],
        ),
        exit_strategy=ExitConfig(
            partial_tp_levels=tp_levels,
            trailing_atr_multiplier=exit_raw["trailing_atr_multiplier"],
            trailing_atr_period=exit_raw["trailing_atr_period"],
        ),
        collectors=CollectorConfig(
            interval_seconds=coll_raw["interval_seconds"],
            fear_greed_url=coll_raw["fear_greed_url"],
            coingecko_base=coll_raw["coingecko_base"],
            etherscan_base=coll_raw["etherscan_base"],
            min_whale_tx_usd=coll_raw["min_whale_tx_usd"],
            etherscan_api_key=os.getenv("ETHERSCAN_API_KEY", ""),
            crypto_news_api_key=os.getenv("CRYPTO_NEWS_API_KEY", ""),
            proxy=proxy,
        ),
        trading_mode=os.getenv("TRADING_MODE", "paper"),
    )
