"""Technical indicator calculations using pandas and the ta library."""
import logging

import pandas as pd
from ta.trend import ADXIndicator, EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

logger = logging.getLogger("indicators")

PROFILE_RULES = {
    "conservative": {
        "near_ema_atr": 0.65,
        "body_atr": 0.18,
        "adx": 16,
        "volume_ratio": 0.75,
        "pullback_score": 4.2,
        "breakout_window": 20,
        "breakout_body_atr": 0.30,
        "breakout_adx": 18,
        "breakout_volume_ratio": 1.15,
        "breakout_score": 3.2,
        "range_score": 3.0,
    },
    "balanced": {
        "near_ema_atr": 0.90,
        "body_atr": 0.12,
        "adx": 13,
        "volume_ratio": 0.60,
        "pullback_score": 3.45,
        "breakout_window": 14,
        "breakout_body_atr": 0.22,
        "breakout_adx": 14,
        "breakout_volume_ratio": 0.85,
        "breakout_score": 2.65,
        "range_score": 2.75,
    },
    "exploratory": {
        "near_ema_atr": 1.20,
        "body_atr": 0.08,
        "adx": 10,
        "volume_ratio": 0.45,
        "pullback_score": 3.00,
        "breakout_window": 10,
        "breakout_body_atr": 0.16,
        "breakout_adx": 10,
        "breakout_volume_ratio": 0.65,
        "breakout_score": 2.25,
        "range_score": 2.40,
    },
}


def strategy_profile_rules(profile: str | None) -> dict:
    """Return threshold rules for a strategy profile."""
    key = str(profile or "balanced").strip().lower()
    return PROFILE_RULES.get(key, PROFILE_RULES["balanced"])


def _num(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if pd.isna(number) else number

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add indicator columns and return a new dataframe.
    Requires at least ~50 rows for EMA50 to be valid."""
    if df is None or df.empty or len(df) < 50:
        return df
    
    df = df.copy()
    df["ema20"] = EMAIndicator(close=df["close"], window=20).ema_indicator()
    df["ema50"] = EMAIndicator(close=df["close"], window=50).ema_indicator()
    df["ema200"] = EMAIndicator(close=df["close"], window=200).ema_indicator()
    macd = MACD(close=df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()
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
    """Bearish trend when EMA20(1h) < EMA50(1h) on the last candle."""
    if df is None or df.empty:
        return False
    last = df.iloc[-1]
    return last.get("ema20", 0) < last.get("ema50", 0) and last["close"] < last.get("ema50", 0)

def is_uptrend(df: pd.DataFrame) -> bool:
    """Bullish trend when EMA20(1h) > EMA50(1h) and price is above EMA50."""
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


def _volume_ratio(row) -> float:
    vol_ma = _num(row.get("vol_ma20"), 0.0)
    if vol_ma <= 0:
        return 0.0
    return _num(row.get("volume"), 0.0) / vol_ma


def pullback_setup_score(df: pd.DataFrame, atr: float, side: str,
                         profile: str | None = "balanced") -> dict:
    """Score a trend pullback setup instead of requiring every filter to be perfect."""
    rules = strategy_profile_rules(profile)
    if df is None or df.empty or len(df) < 50 or atr <= 0:
        return {"ok": False, "score": 0.0, "min_score": rules["pullback_score"], "reason": "not enough data"}

    last = df.iloc[-1]
    close = _num(last.get("close"))
    open_price = _num(last.get("open"))
    ema20 = _num(last.get("ema20"))
    ema50 = _num(last.get("ema50"))
    rsi = _num(last.get("rsi14"), 50.0)
    adx = _num(last.get("adx14"))
    macd_hist = _num(last.get("macd_hist"))
    body = _candle_body(last)
    vol_ratio = _volume_ratio(last)
    near_distance = min(abs(close - ema20), abs(close - ema50))
    near_ema = near_distance <= atr * rules["near_ema_atr"]

    is_long = side == "long"
    candle_ok = close > open_price if is_long else close < open_price
    trend_bias = ema20 >= ema50 if is_long else ema20 <= ema50
    price_bias = close >= ema50 if is_long else close <= ema50
    momentum_ok = (close >= ema20 or macd_hist > 0) if is_long else (close <= ema20 or macd_hist < 0)
    macd_ok = macd_hist > 0 if is_long else macd_hist < 0
    rsi_ideal = 40 <= rsi <= 66 if is_long else 34 <= rsi <= 60
    rsi_wide = 34 <= rsi <= 72 if is_long else 28 <= rsi <= 66

    score = 0.0
    notes = []
    if trend_bias:
        score += 0.9
        notes.append("EMA trend aligned")
    if price_bias:
        score += 0.6
        notes.append("price on trend side")
    if near_ema:
        score += 1.05
        notes.append(f"pullback distance {near_distance / atr:.2f} ATR")
    if candle_ok:
        score += 0.8
        notes.append("confirmation candle")
    elif momentum_ok:
        score += 0.35
        notes.append("momentum confirmation")
    if rsi_ideal:
        score += 0.7
        notes.append(f"RSI {rsi:.1f} healthy")
    elif rsi_wide:
        score += 0.35
        notes.append(f"RSI {rsi:.1f} acceptable")
    if body >= atr * rules["body_atr"]:
        score += 0.45
        notes.append(f"body {body / atr:.2f} ATR")
    if adx >= rules["adx"]:
        score += 0.45
        notes.append(f"ADX {adx:.1f}")
    if vol_ratio >= rules["volume_ratio"]:
        score += 0.35
        notes.append(f"volume x{vol_ratio:.2f}")
    if macd_ok:
        score += 0.4
        notes.append("MACD momentum")

    ok = near_ema and momentum_ok and rsi_wide and score >= rules["pullback_score"]
    return {
        "ok": ok,
        "score": round(score, 2),
        "min_score": rules["pullback_score"],
        "reason": "; ".join(notes) or "filters not aligned",
    }

def is_pullback_short_setup(df: pd.DataFrame, atr: float) -> bool:
    """15m short setup:
    - price pulls back near EMA20 or EMA50
    - last candle is bearish (close < open)
    - RSI < 60 (not overbought)
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

    # Check EMA pullback distance and ensure the candle body is meaningful.
    near_ema = (abs(close - ema20) <= atr * 0.65) or (abs(close - ema50) <= atr * 0.65)
    bearish_candle = close < open_price
    rsi_valid = 32 <= rsi <= 58
    body_valid = _candle_body(last) >= atr * 0.18
    trend_strength = adx >= 16
    volume_valid = not vol_ma or volume >= vol_ma * 0.75
    
    return near_ema and bearish_candle and rsi_valid and body_valid and trend_strength and volume_valid

def is_pullback_long_setup(df: pd.DataFrame, atr: float) -> bool:
    """15m long setup:
    - price pulls back near EMA20/EMA50
    - last candle is bullish
    - RSI is healthy, not overbought
    - ADX and volume are sufficient
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


def volatility_breakout_score(df: pd.DataFrame, atr: float,
                              profile: str | None = "balanced") -> dict:
    """Score a volatility breakout using profile-specific confirmation rules."""
    rules = strategy_profile_rules(profile)
    window = int(rules["breakout_window"])
    if df is None or df.empty or len(df) < window + 40 or atr <= 0:
        return {"ok": False, "side": None, "score": 0.0, "min_score": rules["breakout_score"], "reason": "not enough data"}

    prev = df.iloc[-(window + 1):-1]
    last = df.iloc[-1]
    prev_high = float(prev["high"].max())
    prev_low = float(prev["low"].min())
    close = _num(last.get("close"))
    body = _candle_body(last)
    adx = _num(last.get("adx14"))
    macd_hist = _num(last.get("macd_hist"))
    vol_ratio = _volume_ratio(last)

    side = "long" if close > prev_high else "short" if close < prev_low else None
    if not side:
        return {"ok": False, "side": None, "score": 0.0, "min_score": rules["breakout_score"], "reason": f"inside {window}-candle range"}

    score = 1.1
    notes = [f"{side} break of {window}-candle range"]
    if body >= atr * rules["breakout_body_atr"]:
        score += 0.65
        notes.append(f"body {body / atr:.2f} ATR")
    if adx >= rules["breakout_adx"]:
        score += 0.55
        notes.append(f"ADX {adx:.1f}")
    if vol_ratio >= rules["breakout_volume_ratio"]:
        score += 0.65
        notes.append(f"volume x{vol_ratio:.2f}")
    if (side == "long" and macd_hist > 0) or (side == "short" and macd_hist < 0):
        score += 0.45
        notes.append("MACD confirms")

    return {
        "ok": score >= rules["breakout_score"],
        "side": side,
        "score": round(score, 2),
        "min_score": rules["breakout_score"],
        "reason": "; ".join(notes),
    }


def range_reversion_score(df: pd.DataFrame, atr: float,
                          profile: str | None = "balanced") -> dict:
    """Score a controlled mean-reversion setup for non-trending markets."""
    rules = strategy_profile_rules(profile)
    if df is None or df.empty or len(df) < 60 or atr <= 0:
        return {"ok": False, "side": None, "score": 0.0, "min_score": rules["range_score"], "reason": "not enough data"}

    last = df.iloc[-1]
    close = _num(last.get("close"))
    open_price = _num(last.get("open"))
    ema20 = _num(last.get("ema20"))
    ema50 = _num(last.get("ema50"))
    rsi = _num(last.get("rsi14"), 50.0)
    adx = _num(last.get("adx14"))
    macd_hist = _num(last.get("macd_hist"))
    vol_ratio = _volume_ratio(last)
    body = _candle_body(last)

    score = 0.0
    notes = []
    side = None
    if close <= ema20 and rsi <= 39:
        side = "long"
        score += 1.05
        notes.append(f"range long RSI {rsi:.1f}")
        if close >= open_price:
            score += 0.65
            notes.append("bullish response candle")
        if macd_hist > 0:
            score += 0.45
            notes.append("MACD turning up")
    elif close >= ema20 and rsi >= 61:
        side = "short"
        score += 1.05
        notes.append(f"range short RSI {rsi:.1f}")
        if close <= open_price:
            score += 0.65
            notes.append("bearish response candle")
        if macd_hist < 0:
            score += 0.45
            notes.append("MACD turning down")

    if not side:
        return {"ok": False, "side": None, "score": 0.0, "min_score": rules["range_score"], "reason": "range extremes not reached"}

    if abs(close - ema50) <= atr * 1.4:
        score += 0.5
        notes.append("not overextended from EMA50")
    if adx <= max(24, rules["adx"] + 7):
        score += 0.35
        notes.append(f"range ADX {adx:.1f}")
    if body >= atr * rules["body_atr"]:
        score += 0.25
        notes.append(f"body {body / atr:.2f} ATR")
    if vol_ratio >= rules["volume_ratio"] * 0.75:
        score += 0.25
        notes.append(f"volume x{vol_ratio:.2f}")

    return {
        "ok": score >= rules["range_score"],
        "side": side,
        "score": round(score, 2),
        "min_score": rules["range_score"],
        "reason": "; ".join(notes),
    }
