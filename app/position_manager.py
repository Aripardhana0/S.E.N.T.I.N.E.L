"""Entry fill simulation and TP/SL exit manager.

For DRY_RUN/PAPER, queued_sim plans are filled when price touches the limit
entry. For BINANCE_DEMO, order_queue records fills from Binance, then this
manager monitors the open trade and closes it with reduce-only MARKET order
when TP/SL is touched.
"""
import logging

from app import journal, market_data
from app.binance_client import binance_client
from app.config import config
from app.executor import current_mode

logger = logging.getLogger("position_manager")


def _last_price() -> float | None:
    ticker = market_data.fetch_ticker()
    if not ticker:
        return None
    try:
        return float(ticker["price"])
    except (KeyError, TypeError, ValueError):
        return None


def _plan_to_setup(plan: dict) -> dict:
    return {
        "symbol": plan["symbol"],
        "side": plan["side"],
        "setup_type": plan.get("setup_type") or "unknown_setup",
        "entry": plan["entry"],
        "stop_loss": plan["stop_loss"],
        "take_profit": plan["take_profit"],
    }


def _limit_touched(plan: dict, price: float) -> bool:
    entry = float(plan["entry"])
    side = str(plan["side"]).lower()
    if side == "short":
        return price >= entry
    return price <= entry


def _exit_hit(trade: dict, price: float) -> str | None:
    side = str(trade["side"]).lower()
    stop_loss = trade.get("stop_loss")
    take_profit = trade.get("take_profit")
    if stop_loss is None or take_profit is None:
        return None

    stop_loss = float(stop_loss)
    take_profit = float(take_profit)
    if side == "short":
        if price <= take_profit:
            return "tp"
        if price >= stop_loss:
            return "sl"
        return None

    if price >= take_profit:
        return "tp"
    if price <= stop_loss:
        return "sl"
    return None


def _close_side(trade: dict) -> str:
    return "BUY" if str(trade["side"]).lower() == "short" else "SELL"


def close_trade_now(trade_id: int, reason: str = "manual") -> dict:
    """Close an open trade at current ticker price.

    BINANCE_DEMO trades are closed with reduce-only MARKET order first; local
    simulated trades are closed in the journal only.
    """
    trade = journal.get_trade(trade_id)
    if not trade:
        return {"ok": False, "message": "Trade not found."}
    if trade.get("closed_at") or trade.get("status") != "open":
        return {"ok": False, "message": "Trade is not an open position."}

    price = _last_price()
    if price is None:
        return {"ok": False, "message": "Ticker is empty; cannot close."}

    close_order_id = None
    mode = current_mode()
    if trade.get("mode") == "BINANCE_DEMO" and mode == "BINANCE_DEMO":
        resp = binance_client.place_market_order(
            config.SYMBOL,
            _close_side(trade),
            trade["size"],
            reduce_only=True,
        )
        if not resp or "orderId" not in resp:
            return {"ok": False, "message": f"Close order failed: {resp}"}
        close_order_id = str(resp["orderId"])

    updated = journal.close_trade(
        trade_id,
        exit_price=price,
        exit_reason=reason,
        close_order_id=close_order_id,
    )
    journal.log_event("INFO", f"Trade {trade_id} closed manual @ {price}.")
    return {"ok": True, "trade": updated}


def sync_simulated_entries() -> dict:
    """Fill DRY_RUN/PAPER queued plans when the limit entry is touched."""
    mode = current_mode()
    if mode not in ("DRY_RUN", "PAPER"):
        return {"ok": True, "checked": 0, "filled": 0, "mode": mode}

    price = _last_price()
    if price is None:
        return {"ok": False, "checked": 0, "filled": 0, "message": "Ticker is empty."}

    active = journal.list_plans_by_status(["queued_sim"])
    filled = 0
    for plan in active:
        try:
            if not _limit_touched(plan, price):
                continue
            journal.save_trade(
                plan["id"],
                _plan_to_setup(plan),
                plan["position_size"],
                mode,
                plan.get("binance_order_id"),
            )
            journal.update_trade_plan_status(plan["id"], "filled_sim")
            journal.log_event("INFO", f"{mode}: plan {plan['id']} filled_sim @ {price}.")
            filled += 1
        except Exception as exc:
            logger.exception("Failed to fill simulated plan %s: %s", plan.get("id"), exc)
    return {"ok": True, "checked": len(active), "filled": filled, "price": price}


def sync_exits() -> dict:
    """Close open trades when TP/SL is touched and update realized PnL."""
    price = _last_price()
    if price is None:
        return {"ok": False, "checked": 0, "closed": 0, "message": "Ticker is empty."}

    mode = current_mode()
    open_trades = journal.list_open_trades()
    closed = 0
    events = []
    for trade in open_trades:
        reason = _exit_hit(trade, price)
        if not reason:
            continue

        close_order_id = None
        if trade.get("mode") == "BINANCE_DEMO" and mode == "BINANCE_DEMO":
            resp = binance_client.place_market_order(
                config.SYMBOL,
                _close_side(trade),
                trade["size"],
                reduce_only=True,
            )
            if not resp or "orderId" not in resp:
                logger.error("Close %s trade %s failed: %s", reason, trade["id"], resp)
                continue
            close_order_id = str(resp["orderId"])

        updated = journal.close_trade(
            trade["id"],
            exit_price=price,
            exit_reason=reason,
            close_order_id=close_order_id,
        )
        if updated:
            closed += 1
            events.append(
                {
                    "trade_id": trade["id"],
                    "reason": reason,
                    "exit": price,
                    "pnl": updated.get("pnl"),
                }
            )
            journal.log_event(
                "INFO",
                f"Trade {trade['id']} closed_{reason} @ {price}, pnl={updated.get('pnl')}.",
            )
    return {"ok": True, "checked": len(open_trades), "closed": closed, "events": events}


def local_open_positions() -> list:
    price = _last_price()
    positions = []
    for trade in journal.list_open_trades():
        unrealized = None
        if price is not None:
            entry = float(trade["entry"])
            size = float(trade["size"])
            if str(trade["side"]).lower() == "short":
                unrealized = (entry - price) * size
            else:
                unrealized = (price - entry) * size
        trade = dict(trade)
        trade["mark_price"] = price
        trade["unrealized_pnl"] = round(unrealized, 8) if unrealized is not None else None
        positions.append(trade)
    return positions
