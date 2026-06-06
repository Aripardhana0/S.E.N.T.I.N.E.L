"""Deterministic Market Guard for blocking entries and canceling queues."""
import logging

from app.config import config
from app.indicators import add_indicators
from app.market_data import load_candles_df

logger = logging.getLogger("market_guard")


def evaluate_market() -> dict:
    """Return the current market status: bad, reasons, metrics."""
    df = add_indicators(load_candles_df(config.TIMEFRAME_SIGNAL, limit=200))
    reasons: list[str] = []

    if df is None or df.empty or len(df) < 50:
        return {"bad": True, "reasons": ["Not enough candle data."], "metrics": {}}
    if df["atr14"].isna().iloc[-1]:
        return {"bad": True, "reasons": ["Indicators are not ready yet."], "metrics": {}}

    last = df.iloc[-1]
    prev = df.iloc[-2]
    atr = float(last["atr14"])

    atr_ma = float(df["atr14"].tail(20).mean())
    atr_ratio = atr / atr_ma if atr_ma else 0.0
    if atr_ratio >= config.GUARD_ATR_SPIKE:
        reasons.append(f"ATR spike x{atr_ratio:.2f} (>= {config.GUARD_ATR_SPIKE}).")

    vol = float(last["volume"])
    vol_ma = float(last["vol_ma20"]) if last["vol_ma20"] == last["vol_ma20"] else 0.0
    vol_ratio = vol / vol_ma if vol_ma else 0.0
    if vol_ratio >= config.GUARD_VOL_SPIKE:
        reasons.append(f"Volume spike x{vol_ratio:.2f} (>= {config.GUARD_VOL_SPIKE}).")

    candle_range = float(last["high"]) - float(last["low"])
    range_ratio = candle_range / atr if atr else 0.0
    if range_ratio >= config.GUARD_RANGE_ATR:
        reasons.append(f"Range {range_ratio:.2f}x ATR (>= {config.GUARD_RANGE_ATR}).")

    prev_close = float(prev["close"]) or 1.0
    move_pct = abs(float(last["close"]) - prev_close) / prev_close * 100
    if move_pct >= config.GUARD_MOVE_PCT:
        reasons.append(f"Price spike {move_pct:.2f}% (>= {config.GUARD_MOVE_PCT}%).")

    metrics = {
        "atr_ratio": round(atr_ratio, 2),
        "vol_ratio": round(vol_ratio, 2),
        "range_ratio": round(range_ratio, 2),
        "move_pct": round(move_pct, 2),
    }
    bad = bool(reasons)
    if bad:
        logger.warning("Bad market: %s | %s", reasons, metrics)
    return {"bad": bad, "reasons": reasons, "metrics": metrics}
