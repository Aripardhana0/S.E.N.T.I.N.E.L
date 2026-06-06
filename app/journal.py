"""Data access layer for trade_plans, trades, daily_stats, and logs."""
import json
import logging
from datetime import datetime, timezone

from app.database import get_conn
from app.performance import setup_identity

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

def list_logs(limit: int = 80) -> list:
    limit = max(1, min(int(limit), 300))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

def delete_log(log_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM logs WHERE id=?", (log_id,)).fetchone()
        if not row:
            return {"ok": False, "deleted": 0, "message": "Log not found."}
        conn.execute("DELETE FROM logs WHERE id=?", (log_id,))
        return {"ok": True, "deleted": 1, "log": dict(row)}

def save_trade_plan(setup: dict, risk: dict, ai: dict, status: str) -> int:
    setup_type, setup_key = setup_identity(setup)
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO trade_plans
               (created_at, symbol, side, entry, stop_loss, take_profit,
                risk_reward, risk_amount, position_size, status,
                risk_allowed, risk_reason, ai_verdict, ai_reason,
                ai_confidence, ai_risk_notes, setup_key, setup_type,
                learning_decision, learning_notes, risk_multiplier,
                adaptive_min_rr, raw_payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _now(), setup["symbol"], setup["side"], setup["entry"],
                setup["stop_loss"], setup["take_profit"], risk["risk_reward"],
                risk["risk_amount"], risk["position_size"], status,
                1 if risk["allowed"] else 0, risk["reason"],
                ai.get("verdict"), ai.get("reason"), ai.get("confidence"),
                ai.get("risk_notes"), setup_key, setup_type,
                risk.get("learning_decision"), risk.get("learning_notes"),
                risk.get("risk_multiplier"), risk.get("adaptive_min_rr"),
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
    """Store the exchange order id and queue start time."""
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
    setup_type, setup_key = setup_identity(setup)
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO trades
               (trade_plan_id, opened_at, symbol, side, entry,
                stop_loss, take_profit, size,
                status, mode, okx_order_id, binance_order_id,
                setup_key, setup_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade_plan_id, _now(), setup["symbol"], setup["side"],
                setup["entry"], setup.get("stop_loss"), setup.get("take_profit"),
                size, "open", mode,
                None,
                order_id if mode == "BINANCE_DEMO" else None,
                setup_key, setup_type,
            ),
        )
        # Increment the daily trade counter.
        _bump_daily_trades_conn(conn)
        return cur.lastrowid

def list_trades(limit: int = 20) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_trade(trade_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return dict(row) if row else None

def list_open_trades() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                t.*,
                tp.stop_loss AS plan_stop_loss,
                tp.take_profit AS plan_take_profit
            FROM trades t
            LEFT JOIN trade_plans tp ON tp.id = t.trade_plan_id
            WHERE t.status = 'open'
              AND t.closed_at IS NULL
            ORDER BY t.id ASC
            """
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if item.get("stop_loss") is None:
            item["stop_loss"] = item.get("plan_stop_loss")
        if item.get("take_profit") is None:
            item["take_profit"] = item.get("plan_take_profit")
        result.append(item)
    return result

def close_trade(trade_id: int, exit_price: float | None = None,
                pnl: float | None = None, exit_reason: str = "manual",
                close_order_id: str | None = None) -> dict | None:
    """Close trade manually and record realized PnL for learning analytics."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not row:
            return None
        trade = dict(row)
        if trade.get("closed_at"):
            raise ValueError("Trade is already closed.")

        if pnl is None:
            if exit_price is None:
                raise ValueError("Provide exit_price or pnl.")
            entry = float(trade["entry"])
            size = float(trade["size"])
            if trade["side"] == "short":
                pnl = (entry - float(exit_price)) * size
            else:
                pnl = (float(exit_price) - entry) * size
        elif exit_price is None:
            exit_price = trade.get("exit")

        pnl = round(float(pnl), 8)
        status = "closed_win" if pnl > 0 else "closed_loss" if pnl < 0 else "closed_flat"
        closed_at = _now()
        conn.execute(
            """
            UPDATE trades
            SET closed_at=?, exit=?, pnl=?, status=?,
                exit_reason=?, close_order_id=?
            WHERE id=?
            """,
            (closed_at, exit_price, pnl, status, exit_reason, close_order_id, trade_id),
        )
        _apply_daily_close(conn, pnl)
        updated = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return dict(updated)

def update_trade_levels(
    trade_id: int,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not row:
            return None
        trade = dict(row)
        if trade.get("closed_at"):
            raise ValueError("Trade is already closed.")

        entry = float(trade["entry"])
        side = str(trade["side"]).lower()
        stop_loss = float(stop_loss if stop_loss is not None else trade["stop_loss"])
        take_profit = float(take_profit if take_profit is not None else trade["take_profit"])

        if side == "short" and not (stop_loss > entry > take_profit):
            raise ValueError("Short setup requires: SL > entry > TP.")
        if side == "long" and not (stop_loss < entry < take_profit):
            raise ValueError("Long setup requires: SL < entry < TP.")

        conn.execute(
            "UPDATE trades SET stop_loss=?, take_profit=? WHERE id=?",
            (stop_loss, take_profit, trade_id),
        )
        updated = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return dict(updated)

def clear_local_journal(
    include_candles: bool = False,
    tables: list[str] | None = None,
) -> dict:
    """Clear local trading journal data.

    By default candles are kept so indicators still have history after reset.
    This does not close exchange positions; callers should cancel/close exchange
    exposure first when needed.
    """
    allowed_tables = {
        "trade_plans",
        "trades",
        "daily_stats",
        "daily_reviews",
        "logs",
        "candles",
    }
    if tables is None:
        selected_tables = ["trade_plans", "trades", "daily_stats", "daily_reviews", "logs"]
        if include_candles:
            selected_tables.append("candles")
    else:
        selected_tables = []
        for table in tables:
            table = table.strip()
            if table not in allowed_tables:
                raise ValueError(f"Table {table} cannot be cleared.")
            if table not in selected_tables:
                selected_tables.append(table)
    if not selected_tables:
        raise ValueError("Select at least one data group to clear.")
    with get_conn() as conn:
        counts = {}
        for table in selected_tables:
            row = conn.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()
            counts[table] = int(row["total"] or 0)
            conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))
        conn.execute(
            "INSERT INTO logs (created_at, level, message) VALUES (?,?,?)",
            (
                _now(),
                "WARNING",
                f"Local data cleared: {', '.join(selected_tables)}",
            ),
        )
    return {"ok": True, "cleared": counts, "tables": selected_tables}

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
        _bump_daily_trades_conn(conn)

def _bump_daily_trades_conn(conn):
    day = _today()
    conn.execute("INSERT OR IGNORE INTO daily_stats (day) VALUES (?)", (day,))
    conn.execute(
        "UPDATE daily_stats SET trades_count = trades_count + 1 WHERE day=?",
        (day,),
    )

def _apply_daily_close(conn, pnl: float):
    day = _today()
    conn.execute("INSERT OR IGNORE INTO daily_stats (day) VALUES (?)", (day,))
    conn.execute(
        "UPDATE daily_stats SET realized_pnl = realized_pnl + ? WHERE day=?",
        (pnl, day),
    )
    if pnl < 0:
        conn.execute(
            "UPDATE daily_stats SET consecutive_loss = consecutive_loss + 1 WHERE day=?",
            (day,),
        )
    elif pnl > 0:
        conn.execute(
            "UPDATE daily_stats SET consecutive_loss = 0 WHERE day=?",
            (day,),
        )
