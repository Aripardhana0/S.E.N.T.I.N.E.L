"""Strategy: Downtrend Pullback Short.
Jalankan tiap 15m dari scheduler. Output setup dict jika valid."""
import logging

from app.config import config
from app.market_data import load_candles_df
from app.indicators import add_indicators, is_downtrend, is_pullback_short_setup

logger = logging.getLogger("strategy")

def generate_signal() -> dict | None:
    """Jalankan strategi. Hanya buat setup short saat downtrend + pullback."""
    df_trend = add_indicators(load_candles_df(config.TIMEFRAME_TREND, limit=200))
    df_signal = add_indicators(load_candles_df(config.TIMEFRAME_SIGNAL, limit=200))

    # No-Trade Filter: data kurang.
    if df_trend is None or df_signal is None or len(df_trend) < 50 or len(df_signal) < 20:
        logger.debug("Skip: data belum cukup (trend atau signal).")
        return None

    # Cek downtrend di timeframe 1h.
    if not is_downtrend(df_trend):
        logger.debug("Skip: tidak downtrend di 1h.")
        return None

    # Cek setup pullback short di 15m.
    atr = float(df_signal.iloc[-1].get("atr14", 0))
    if not is_pullback_short_setup(df_signal, atr):
        logger.debug("Skip: tidak ada pullback setup di 15m.")
        return None

    # Setup valid: hitung entry, SL, TP.
    last = df_signal.iloc[-1]
    entry = float(last["close"])
    
    # SL = harga tertinggi candle terakhir + sedikit buffer (ATR * 0.2).
    stop_loss = float(last["high"]) + atr * 0.2
    
    # TP = entry - (SL - entry) * MIN_RR.
    risk_per_unit = stop_loss - entry
    take_profit = entry - risk_per_unit * config.MIN_RR

    # Validasi SL < entry (karena short) dan TP < entry.
    if stop_loss <= entry or take_profit >= entry:
        logger.info("Skip: SL/TP tidak valid.")
        return None

    risk_reward = round((entry - take_profit) / risk_per_unit, 2)

    setup = {
        "symbol": config.SYMBOL,
        "side": "short",
        "setup_type": "downtrend_pullback",
        "timeframe_signal": config.TIMEFRAME_SIGNAL,
        "timeframe_trend": config.TIMEFRAME_TREND,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": risk_reward,
        "atr": round(atr, 2),
        "rsi": round(float(last["rsi14"]), 2),
    }
    logger.info("Setup ditemukan: %s", setup)
    return setup
