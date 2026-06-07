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
    is_uptrend,
    pullback_setup_score,
    range_reversion_score,
    trend_regime,
    volatility_breakout_score,
)

logger = logging.getLogger("strategy")


def _volume_ratio(row) -> float:
    vol_ma = float(row.get("vol_ma20", 0) or 0)
    if vol_ma <= 0:
        return 0.0
    return round(float(row.get("volume", 0) or 0) / vol_ma, 2)


def _profile() -> str:
    return str(getattr(config, "STRATEGY_PROFILE", "balanced") or "balanced").lower()


def _score_reason(base: str, score: dict) -> str:
    return (
        f"{base} Score {score.get('score', 0)}/"
        f"{score.get('min_score', '-')}: {score.get('reason', '-')}"
    )


def _build_setup(side: str, setup_type: str, entry: float, stop_loss: float,
                 take_profit: float, last, regime: str, reason: str,
                 score: dict | None = None) -> dict | None:
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
        "strategy_profile": _profile(),
        "setup_score": score.get("score") if score else None,
        "setup_min_score": score.get("min_score") if score else None,
        "entry_reason": reason,
    }


def _trend_pullback(df_trend, df_signal, regime: str) -> dict | None:
    last = df_signal.iloc[-1]
    entry = float(last["close"])
    atr = float(last.get("atr14", 0) or 0)
    if atr <= 0:
        return None

    profile = _profile()
    long_score = pullback_setup_score(df_signal, atr, "long", profile)
    if regime == "uptrend" and long_score["ok"]:
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
            _score_reason("1h uptrend pullback long.", long_score),
            long_score,
        )

    short_score = pullback_setup_score(df_signal, atr, "short", profile)
    if regime == "downtrend" and short_score["ok"]:
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
            _score_reason("1h downtrend pullback short.", short_score),
            short_score,
        )
    return None


def _volatility_setup(df_trend, df_signal, regime: str) -> dict | None:
    last = df_signal.iloc[-1]
    entry = float(last["close"])
    atr = float(last.get("atr14", 0) or 0)
    if atr <= 0:
        return None
    score = volatility_breakout_score(df_signal, atr, _profile())
    side = score.get("side")
    if not side or not score.get("ok"):
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
            _score_reason("15m volatility breakout long.", score),
            score,
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
        _score_reason("15m volatility breakout short.", score),
        score,
    )


def _range_reversion_setup(df_signal, regime: str) -> dict | None:
    if regime != "range":
        return None
    last = df_signal.iloc[-1]
    entry = float(last["close"])
    atr = float(last.get("atr14", 0) or 0)
    if atr <= 0:
        return None

    score = range_reversion_score(df_signal, atr, _profile())
    side = score.get("side")
    if not side or not score.get("ok"):
        return None

    if side == "long":
        stop_loss = min(float(last["low"]), entry - atr * 0.75)
        risk = entry - stop_loss
        take_profit = entry + risk * config.MIN_RR
        return _build_setup(
            "long",
            "range_reversion_long",
            entry,
            stop_loss,
            take_profit,
            last,
            regime,
            _score_reason("Range reversion long.", score),
            score,
        )

    stop_loss = max(float(last["high"]), entry + atr * 0.75)
    risk = stop_loss - entry
    take_profit = entry - risk * config.MIN_RR
    return _build_setup(
        "short",
        "range_reversion_short",
        entry,
        stop_loss,
        take_profit,
        last,
        regime,
        _score_reason("Range reversion short.", score),
        score,
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

    setup = _range_reversion_setup(df_signal, regime)
    if setup:
        logger.info("Range reversion setup found: %s", setup)
        return setup

    logger.debug("Skip: no scored setup found. regime=%s profile=%s", regime, _profile())
    return None
