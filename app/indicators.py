"""Perhitungan indikator teknikal pakai pandas + library ta."""
import logging

import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

logger = logging.getLogger("indicators")

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan kolom indikator. Mengembalikan df baru.
    Butuh minimal ~50 baris agar EMA50 valid."""
    if df is None or df.empty or len(df) < 50:
        return df
    
    df = df.copy()
    df["ema20"] = EMAIndicator(close=df["close"], window=20).ema_indicator()
    df["ema50"] = EMAIndicator(close=df["close"], window=50).ema_indicator()
    df["rsi14"] = RSIIndicator(close=df["close"], window=14).rsi()
    df["atr"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()
    return df

def is_downtrend(df: pd.DataFrame) -> bool:
    """Trend bearish bila EMA20(1H) < EMA50(1H) di candle terakhir."""
    if df is None or df.empty:
        return False
    last = df.iloc[-1]
    return last.get("ema20", 0) < last.get("ema50", 0)

def is_pullback_short_setup(df: pd.DataFrame, atr: float) -> bool:
    """Setup short di 15m:
    - harga pullback mendekati EMA20 atau EMA50
    - candle terakhir bearish (close < open)
    - RSI < 60 (tidak overbought)
    """
    if df is None or df.empty or len(df) < 20:
        return False
    
    last = df.iloc[-1]
    ema20 = last.get("ema20", 0)
    ema50 = last.get("ema50", 0)
    close = last["close"]
    open_price = last["open"]
    rsi = last.get("rsi14", 50)
    
    # Cek pullback ke EMA (dalam jarak ATR).
    near_ema = (abs(close - ema20) <= atr * 0.5) or (abs(close - ema50) <= atr * 0.5)
    bearish_candle = close < open_price
    rsi_valid = rsi < 60
    
    return near_ema and bearish_candle and rsi_valid
