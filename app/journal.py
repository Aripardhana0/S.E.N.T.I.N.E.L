"""Lapisan akses data: simpan/baca trade_plans, trades, daily_stats, logs."""
import json
import logging
from datetime import datetime, timezone

from app.database import get_conn

logger = logging.getLogger("journal")

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def log_event(level: str, message: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO logs (created_at, level, message) VALUES (?,?,?)",
            (_now(), level, message),
        )

def save_trade_plan(setup: dict, risk: dict, ai: dict, status: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO trade_plans
               (created_at, symbol, side, entry, stop_loss, take_profit,
                risk_reward, risk_amount, position_size, status,
                risk_allowed, risk_reason, ai_verdict, ai_reason,
                ai_confidence, raw_payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _now(), setup["symbol"], setup["side"], setup["entry"],
                setup["stop_loss"], setup["take_profit"], risk["risk_reward"],
                risk["risk_amount"], risk["position_size"], status,
                1 if risk["allowed"] else 0, risk["reason"],
                ai.get("verdict"), ai.get("reason"), ai.get("confidence"),
                json.dumps({"setup": setup, "risk": risk, "ai": ai}),
            ),
        )
        return cur.lastrowid

def update_trade_plan_status(plan_id: int, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE trade_plans SET status=? WHERE id=?", (status, plan_id)
        )

def set_order_id(plan_id: int, order_id: str):
    """Simpan id order exchange dan waktu mulai antre."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE trade_plans SET binance_order_id=?, queued_at=? WHERE id=?",
            (order_id, _now(), plan_id),
        )

def get_trade_plan(plan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM trade_plans WHERE id=?", (plan_id,)
        ).fetchone()
        return dict(row) if row else None

def list_trade_plans(limit: int = 20) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_plans ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

def list_plans_by_status(statuses: list) -> list:
    if not statuses:
        return []
    placeholders = ",".join(["?"] * len(statuses))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM trade_plans WHERE status IN ({placeholders}) "
            "ORDER BY id DESC",
            statuses,
        ).fetchall()
        return [dict(r) for r in rows]

def get_last_signal() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM trade_plans ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

def save_trade(trade_plan_id: int, setup: dict, size: float,
               mode: str, order_id: str | None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO trades
               (trade_plan_id, opened_at, symbol, side, entry, size,
                status, mode, okx_order_id, binance_order_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                trade_plan_id, _now(), setup["symbol"], setup["side"],
                setup["entry"], size, "open", mode,
                None,
                order_id if mode == "BINANCE_DEMO" else None,
            ),
        )
        # Naikkan counter trade harian.
        _bump_daily_trades()
        return cur.lastrowid

def list_trades(limit: int = 20) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_today_stats() -> dict:
    day = _today()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_stats WHERE day=?", (day,)
        ).fetchone()
        if row:
            return dict(row)
        conn.execute("INSERT INTO daily_stats (day) VALUES (?)", (day,))
    return {"day": day, "trades_count": 0, "realized_pnl": 0.0,
            "consecutive_loss": 0}

def _bump_daily_trades():
    day = _today()
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO daily_stats (day) VALUES (?)", (day,))
        conn.execute(
            "UPDATE daily_stats SET trades_count = trades_count + 1 WHERE day=?",
            (day,),
        )
