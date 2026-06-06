"""Multi-regime strategy.

The strategy is still deterministic: it looks for higher-quality trend
pullbacks in both directions and moderate volatility breakouts. Risk manager,
market guard, learning guard, and AI reviewer still run after this module.
"""
import logging

from app.config import config
from app.market_data import load_candles_df
from app.indicators import (
    add_indicators,
    is_downtrend,
    is_pullback_long_setup,
    is_pullback_short_setup,
    is_uptrend,
    trend_regime,
    volatility_breakout,
)

logger = logging.getLogger("strategy")


def _volume_ratio(row) -> float:
    vol_ma = float(row.get("vol_ma20", 0) or 0)
    if vol_ma <= 0:
        return 0.0
    return round(float(row.get("volume", 0) or 0) / vol_ma, 2)


def _build_setup(side: str, setup_type: str, entry: float, stop_loss: float,
                 take_profit: float, last, regime: str, reason: str) -> dict | None:
    if side == "short" and not (stop_loss > entry > take_profit):
        logger.info("Skip %s: invalid short SL/TP.", setup_type)
        return None
    if side == "long" and not (stop_loss < entry < take_profit):
        logger.info("Skip %s: invalid long SL/TP.", setup_type)
        return None

    risk_per_unit = abs(stop_loss - entry)
    if risk_per_unit <= 0:
        return None
    risk_reward = round(abs(entry - take_profit) / risk_per_unit, 2)
    return {
        "symbol": config.SYMBOL,
        "side": side,
        "setup_type": setup_type,
        "timeframe_signal": config.TIMEFRAME_SIGNAL,
        "timeframe_trend": config.TIMEFRAME_TREND,
        "entry": round(float(entry), config.PRICE_PRECISION),
        "stop_loss": round(float(stop_loss), config.PRICE_PRECISION),
        "take_profit": round(float(take_profit), config.PRICE_PRECISION),
        "risk_reward": risk_reward,
        "atr": round(float(last.get("atr14", 0) or 0), 2),
        "rsi": round(float(last.get("rsi14", 0) or 0), 2),
        "adx": round(float(last.get("adx14", 0) or 0), 2),
        "volume_ratio": _volume_ratio(last),
        "trend_regime": regime,
        "entry_reason": reason,
    }


def _trend_pullback(df_trend, df_signal, regime: str) -> dict | None:
    last = df_signal.iloc[-1]
    entry = float(last["close"])
    atr = float(last.get("atr14", 0) or 0)
    if atr <= 0:
        return None

    if regime == "uptrend" and is_pullback_long_setup(df_signal, atr):
        stop_loss = float(last["low"]) - atr * 0.25
        risk = entry - stop_loss
        take_profit = entry + risk * config.MIN_RR
        return _build_setup(
            "long",
            "uptrend_pullback_long",
            entry,
            stop_loss,
            take_profit,
            last,
            regime,
            "1h uptrend, 15m pullback to EMA, bullish confirmation candle.",
        )

    if regime == "downtrend" and is_pullback_short_setup(df_signal, atr):
        stop_loss = float(last["high"]) + atr * 0.25
        risk = stop_loss - entry
        take_profit = entry - risk * config.MIN_RR
        return _build_setup(
            "short",
            "downtrend_pullback_short",
            entry,
            stop_loss,
            take_profit,
            last,
            regime,
            "1h downtrend, 15m pullback to EMA, bearish confirmation candle.",
        )
    return None


def _volatility_setup(df_trend, df_signal, regime: str) -> dict | None:
    last = df_signal.iloc[-1]
    entry = float(last["close"])
    atr = float(last.get("atr14", 0) or 0)
    if atr <= 0:
        return None
    side = volatility_breakout(df_signal, atr)
    if not side:
        return None
    if side == "long" and is_downtrend(df_trend):
        return None
    if side == "short" and is_uptrend(df_trend):
        return None

    if side == "long":
        stop_loss = min(float(last["low"]), entry - atr * 0.85)
        risk = entry - stop_loss
        take_profit = entry + risk * max(config.MIN_RR, 1.7)
        return _build_setup(
            "long",
            "volatility_breakout_long",
            entry,
            stop_loss,
            take_profit,
            last,
            regime,
            "15m range breakout up with volume, body, and ADX confirmation.",
        )

    stop_loss = max(float(last["high"]), entry + atr * 0.85)
    risk = stop_loss - entry
    take_profit = entry - risk * max(config.MIN_RR, 1.7)
    return _build_setup(
        "short",
        "volatility_breakout_short",
        entry,
        stop_loss,
        take_profit,
        last,
        regime,
        "15m range breakout down with volume, body, and ADX confirmation.",
    )


def generate_signal() -> dict | None:
    """Generate one setup if the current market passes deterministic filters."""
    df_trend = add_indicators(load_candles_df(config.TIMEFRAME_TREND, limit=220))
    df_signal = add_indicators(load_candles_df(config.TIMEFRAME_SIGNAL, limit=220))

    if df_trend is None or df_signal is None or len(df_trend) < 80 or len(df_signal) < 80:
        logger.debug("Skip: not enough trend or signal data.")
        return None

    regime = trend_regime(df_trend)
    setup = _trend_pullback(df_trend, df_signal, regime)
    if setup:
        logger.info("Setup found: %s", setup)
        return setup

    setup = _volatility_setup(df_trend, df_signal, regime)
    if setup:
        logger.info("Volatility setup found: %s", setup)
        return setup

    logger.debug("Skip: no strong setup found. regime=%s", regime)
    return None
