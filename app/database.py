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
                ai_risk_notes TEXT,
                setup_key TEXT, setup_type TEXT,
                learning_decision TEXT, learning_notes TEXT,
                risk_multiplier REAL, adaptive_min_rr REAL,
                binance_order_id TEXT, queued_at TEXT,
                raw_payload TEXT
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_plan_id INTEGER,
                opened_at TEXT, closed_at TEXT,
                symbol TEXT, side TEXT,
                entry REAL, exit REAL, size REAL, pnl REAL,
                status TEXT, mode TEXT, okx_order_id TEXT, binance_order_id TEXT,
                setup_key TEXT, setup_type TEXT
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

            CREATE TABLE IF NOT EXISTS daily_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT UNIQUE,
                created_at TEXT,
                summary TEXT,
                metrics_json TEXT,
                recommendations_json TEXT
            );
            """
        )
    logger.info("Database siap di %s", config.DB_PATH)

def migrate_brach_auto():
    """Migrasi non-destruktif untuk branch auto."""
    with get_conn() as conn:
        cols = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(trade_plans)").fetchall()
        ]
        if "binance_order_id" not in cols:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN binance_order_id TEXT")
        if "queued_at" not in cols:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN queued_at TEXT")
        if "ai_risk_notes" not in cols:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN ai_risk_notes TEXT")
        if "setup_key" not in cols:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN setup_key TEXT")
        if "setup_type" not in cols:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN setup_type TEXT")
        if "learning_decision" not in cols:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN learning_decision TEXT")
        if "learning_notes" not in cols:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN learning_notes TEXT")
        if "risk_multiplier" not in cols:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN risk_multiplier REAL")
        if "adaptive_min_rr" not in cols:
            conn.execute("ALTER TABLE trade_plans ADD COLUMN adaptive_min_rr REAL")

        trade_cols = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(trades)").fetchall()
        ]
        if "binance_order_id" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN binance_order_id TEXT")
        if "setup_key" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN setup_key TEXT")
        if "setup_type" not in trade_cols:
            conn.execute("ALTER TABLE trades ADD COLUMN setup_type TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT UNIQUE,
                created_at TEXT,
                summary TEXT,
                metrics_json TEXT,
                recommendations_json TEXT
            )
            """
        )
    logger.info("Migrasi branch auto selesai.")
