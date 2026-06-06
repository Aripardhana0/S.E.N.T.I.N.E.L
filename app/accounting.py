"""Account and PnL summaries for dashboard and Telegram."""
from __future__ import annotations

from app import journal, position_manager
from app.binance_client import binance_client
from app.config import config
from app.database import get_conn
from app.executor import current_mode


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _balance_from_binance() -> dict:
    balances = binance_client.get_balance() or []
    for row in balances:
        if row.get("asset") == "USDT":
            return {
                "source": "binance_demo",
                "balance": _num(row.get("balance")),
                "available": _num(row.get("availableBalance")),
                "cross_wallet": _num(row.get("crossWalletBalance")),
            }
    return {"source": "local", "balance": None, "available": None, "cross_wallet": None}


def _closed_totals(day: str | None = None) -> dict:
    where = ["closed_at IS NOT NULL", "pnl IS NOT NULL"]
    params: list = []
    if day:
        where.append("closed_at LIKE ?")
        params.append(f"{day}%")
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(id) AS closed,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) AS gross_profit,
                SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END) AS gross_loss,
                SUM(pnl) AS net_pnl
            FROM trades
            WHERE {" AND ".join(where)}
            """,
            params,
        ).fetchone()
    data = dict(row) if row else {}
    return {
        "closed": int(data.get("closed") or 0),
        "wins": int(data.get("wins") or 0),
        "losses": int(data.get("losses") or 0),
        "gross_profit": round(_num(data.get("gross_profit")), 8),
        "gross_loss": round(_num(data.get("gross_loss")), 8),
        "net_pnl": round(_num(data.get("net_pnl")), 8),
    }


def _queued_risk() -> dict:
    active = journal.list_plans_by_status(["queued", "queued_sim"])
    risk = sum(_num(row.get("risk_amount")) for row in active)
    size_value = sum(_num(row.get("entry")) * _num(row.get("position_size")) for row in active)
    return {
        "count": len(active),
        "risk_amount": round(risk, 8),
        "notional": round(size_value, 8),
    }


def summary() -> dict:
    today = journal.get_today_stats()
    closed_all = _closed_totals()
    closed_today = _closed_totals(today["day"])
    open_positions = position_manager.local_open_positions()
    open_notional = sum(_num(row.get("entry")) * _num(row.get("size")) for row in open_positions)
    open_risk = sum(
        abs(_num(row.get("entry")) - _num(row.get("stop_loss"))) * _num(row.get("size"))
        for row in open_positions
    )
    unrealized = sum(_num(row.get("unrealized_pnl")) for row in open_positions)

    balance = _balance_from_binance() if current_mode() == "BINANCE_DEMO" else {
        "source": "local",
        "balance": None,
        "available": None,
        "cross_wallet": None,
    }
    base_balance = (
        _num(balance["balance"], config.INITIAL_EQUITY)
        if balance.get("balance") is not None
        else config.INITIAL_EQUITY + closed_all["net_pnl"]
    )
    equity_estimate = base_balance + unrealized

    return {
        "mode": current_mode(),
        "symbol": config.SYMBOL,
        "initial_equity": config.INITIAL_EQUITY,
        "balance": round(base_balance, 8),
        "available": round(
            _num(balance.get("available"), base_balance) if balance.get("available") is not None else base_balance,
            8,
        ),
        "equity_estimate": round(equity_estimate, 8),
        "balance_source": balance["source"],
        "open": {
            "count": len(open_positions),
            "notional": round(open_notional, 8),
            "risk_amount": round(open_risk, 8),
            "unrealized_pnl": round(unrealized, 8),
        },
        "queue": _queued_risk(),
        "closed_all": closed_all,
        "closed_today": closed_today,
        "today": today,
    }
