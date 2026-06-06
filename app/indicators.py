"""Perhitungan indikator teknikal pakai pandas + library ta."""
import logging

import pandas as pd
from ta.trend import ADXIndicator, EMAIndicator
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
    df["ema200"] = EMAIndicator(close=df["close"], window=200).ema_indicator()
    df["adx14"] = ADXIndicator(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).adx()
    df["rsi14"] = RSIIndicator(close=df["close"], window=14).rsi()
    df["atr14"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()
    df["vol_ma20"] = df["volume"].rolling(window=20).mean()
    return df

def is_downtrend(df: pd.DataFrame) -> bool:
    """Trend bearish bila EMA20(1h) < EMA50(1h) di candle terakhir."""
    if df is None or df.empty:
        return False
    last = df.iloc[-1]
    return last.get("ema20", 0) < last.get("ema50", 0) and last["close"] < last.get("ema50", 0)

def is_uptrend(df: pd.DataFrame) -> bool:
    """Trend bullish bila EMA20(1h) > EMA50(1h) dan harga di atas EMA50."""
    if df is None or df.empty:
        return False
    last = df.iloc[-1]
    return last.get("ema20", 0) > last.get("ema50", 0) and last["close"] > last.get("ema50", 0)

def trend_regime(df: pd.DataFrame) -> str:
    if is_uptrend(df):
        return "uptrend"
    if is_downtrend(df):
        return "downtrend"
    return "range"

def _candle_body(row) -> float:
    return abs(float(row["close"]) - float(row["open"]))

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
    
    adx = last.get("adx14", 0)
    volume = last.get("volume", 0)
    vol_ma = last.get("vol_ma20", 0)

    # Cek pullback ke EMA (dalam jarak ATR) dan candle punya body cukup.
    near_ema = (abs(close - ema20) <= atr * 0.65) or (abs(close - ema50) <= atr * 0.65)
    bearish_candle = close < open_price
    rsi_valid = 32 <= rsi <= 58
    body_valid = _candle_body(last) >= atr * 0.18
    trend_strength = adx >= 16
    volume_valid = not vol_ma or volume >= vol_ma * 0.75
    
    return near_ema and bearish_candle and rsi_valid and body_valid and trend_strength and volume_valid

def is_pullback_long_setup(df: pd.DataFrame, atr: float) -> bool:
    """Setup long di 15m:
    - harga pullback mendekati EMA20/EMA50
    - candle terakhir bullish
    - RSI sehat, tidak overbought
    - ADX dan volume cukup
    """
    if df is None or df.empty or len(df) < 50:
        return False

    last = df.iloc[-1]
    ema20 = last.get("ema20", 0)
    ema50 = last.get("ema50", 0)
    close = last["close"]
    open_price = last["open"]
    rsi = last.get("rsi14", 50)
    adx = last.get("adx14", 0)
    volume = last.get("volume", 0)
    vol_ma = last.get("vol_ma20", 0)

    near_ema = (abs(close - ema20) <= atr * 0.65) or (abs(close - ema50) <= atr * 0.65)
    bullish_candle = close > open_price
    rsi_valid = 42 <= rsi <= 68
    body_valid = _candle_body(last) >= atr * 0.18
    trend_strength = adx >= 16
    volume_valid = not vol_ma or volume >= vol_ma * 0.75

    return near_ema and bullish_candle and rsi_valid and body_valid and trend_strength and volume_valid

def volatility_breakout(df: pd.DataFrame, atr: float) -> str | None:
    """Return long/short when price breaks a 20-candle range with confirmation."""
    if df is None or df.empty or len(df) < 60 or atr <= 0:
        return None
    prev = df.iloc[-21:-1]
    last = df.iloc[-1]
    prev_high = float(prev["high"].max())
    prev_low = float(prev["low"].min())
    close = float(last["close"])
    volume = float(last.get("volume", 0) or 0)
    vol_ma = float(last.get("vol_ma20", 0) or 0)
    body = _candle_body(last)
    adx = float(last.get("adx14", 0) or 0)

    confirmed = body >= atr * 0.3 and adx >= 18 and (not vol_ma or volume >= vol_ma * 1.15)
    if not confirmed:
        return None
    if close > prev_high:
        return "long"
    if close < prev_low:
        return "short"
    return None
