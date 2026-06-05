"""Inisialisasi koneksi SQLite + pembuatan tabel.
Koneksi dibuat per-operasi agar aman dipakai dari thread scheduler & FastAPI."""
import os
import sqlite3
import logging
from contextlib import contextmanager

from app.config import config

logger = logging.getLogger("database")

@contextmanager
def get_conn():
    """Context manager untuk koneksi SQLite. Selalu commit/rollback & close."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Buat semua tabel jika belum ada."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                UNIQUE(symbol, timeframe, timestamp)
            );

            CREATE TABLE IF NOT EXISTS trade_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                symbol TEXT, side TEXT,
                entry REAL, stop_loss REAL, take_profit REAL,
                risk_reward REAL, risk_amount REAL, position_size REAL,
                status TEXT,
                risk_allowed INTEGER, risk_reason TEXT,
                ai_verdict TEXT, ai_reason TEXT, ai_confidence TEXT,
                raw_payload TEXT
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_plan_id INTEGER,
                opened_at TEXT, closed_at TEXT,
                symbol TEXT, side TEXT,
                entry REAL, exit REAL, size REAL, pnl REAL,
                status TEXT, mode TEXT, okx_order_id TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT UNIQUE,
                trades_count INTEGER DEFAULT 0,
                realized_pnl REAL DEFAULT 0,
                consecutive_loss INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                level TEXT,
                message TEXT
            );
            """
        )
    logger.info("Database siap di %s", config.DB_PATH)
