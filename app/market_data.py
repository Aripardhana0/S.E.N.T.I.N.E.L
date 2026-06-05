"""Worker market data: ambil ticker & klines dari Binance, simpan ke SQLite."""
import logging

import pandas as pd

from app.config import config
from app.database import get_conn
from app.binance_client import binance_client

logger = logging.getLogger("market_data")

def fetch_and_store_candles(timeframe: str, limit: int = 200):
    """Ambil klines Binance dan simpan ke tabel candles (idempotent)."""
    rows = binance_client.get_candles(config.SYMBOL, interval=timeframe, limit=limit)
    if not rows:
        logger.warning("Tidak ada candle %s (API mungkin gagal).", timeframe)
        return 0
    saved = 0
    with get_conn() as conn:
        cur = conn.cursor()
        for c in rows:
            try:
                # Binance kline: [openTime, open, high, low, close, volume, ...]
                cur.execute(
                    """INSERT OR IGNORE INTO candles
                       (symbol, timeframe, timestamp, open, high, low, close, volume)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        config.SYMBOL, timeframe, int(c[0]),
                        float(c[1]), float(c[2]), float(c[3]),
                        float(c[4]), float(c[5]),
                    ),
                )
                saved += cur.rowcount
            except (ValueError, IndexError) as e:
                logger.error("Candle rusak dilewati: %s", e)
    logger.info("Candle %s tersimpan: %s baris baru.", timeframe, saved)
    return saved

def fetch_ticker():
    """Ambil ticker terbaru (harga real-time)."""
    t = binance_client.get_ticker(config.SYMBOL)
    if t:
        logger.debug("Ticker %s = %s", config.SYMBOL, t.get("price"))
    return t

def load_candles_df(timeframe: str, limit: int = 200) -> pd.DataFrame:
    """Baca candle dari DB menjadi DataFrame kronologis."""
    with get_conn() as conn:
        df = pd.read_sql_query(
            """SELECT timestamp, open, high, low, close, volume
               FROM candles WHERE symbol=? AND timeframe=?
               ORDER BY timestamp ASC""",
            conn, params=(config.SYMBOL, timeframe),
        )
    if not df.empty:
        df = df.tail(limit).reset_index(drop=True)
    return df
