"""Order Queue + Cancel Manager for Binance auto entry."""
import logging

from app import journal
from app.binance_client import binance_client
from app.config import config
from app.executor import current_mode

logger = logging.getLogger("order_queue")

ACTIVE_STATUSES = ("queued", "queued_sim")


def _plan_to_setup(plan: dict) -> dict:
    return {
        "symbol": plan["symbol"],
        "side": plan["side"],
        "entry": plan["entry"],
        "stop_loss": plan["stop_loss"],
        "take_profit": plan["take_profit"],
        "setup_type": plan.get("setup_type"),
    }


def _entry_order_type() -> str:
    order_type = str(getattr(config, "ENTRY_ORDER_TYPE", "LIMIT") or "LIMIT").upper()
    return "MARKET" if order_type == "MARKET" else "LIMIT"


def _binance_error(default: str = "Unknown Binance error.") -> str:
    return binance_client.last_error or default


def enqueue_entry(plan_id: int) -> dict:
    """Place or simulate an entry for a plan that passed guard, risk, and AI checks."""
    plan = journal.get_trade_plan(plan_id)
    if not plan:
        journal.log_event("ERROR", f"Queue failed for plan {plan_id}: Plan not found.")
        return {"ok": False, "message": "Plan not found."}
    if not plan["risk_allowed"]:
        journal.update_trade_plan_status(plan_id, "rejected_risk")
        journal.log_event("ERROR", f"Queue failed for plan {plan_id}: Risk rejected the plan.")
        return {"ok": False, "message": "Risk rejected the plan; it was not queued."}

    symbol = config.SYMBOL
    side = "SELL" if plan["side"] == "short" else "BUY"
    qty = binance_client.round_qty(plan["position_size"])
    price = binance_client.round_price(plan["entry"])
    mode = current_mode()
    order_type = _entry_order_type()

    if qty <= 0:
        journal.update_trade_plan_status(plan_id, "queue_failed")
        journal.log_event(
            "ERROR",
            f"Queue failed for plan {plan_id}: Position quantity rounded to zero "
            f"(position_size={plan['position_size']}, qty_precision={config.QTY_PRECISION}).",
        )
        return {"ok": False, "message": "Position quantity rounded to zero; increase equity/risk or precision."}

    if mode in ("DRY_RUN", "PAPER"):
        if order_type == "MARKET":
            journal.save_trade(plan_id, _plan_to_setup(plan), plan["position_size"], mode, f"SIM-{plan_id}")
            journal.set_order_id(plan_id, f"SIM-{plan_id}")
            journal.update_trade_plan_status(plan_id, "filled_sim")
            journal.log_event("INFO", f"{mode}: simulated market entry filled for plan {plan_id}.")
            return {
                "ok": True,
                "message": f"{mode}: simulated market entry filled.",
                "mode": mode,
                "order_type": order_type,
            }
        journal.set_order_id(plan_id, f"SIM-{plan_id}")
        journal.update_trade_plan_status(plan_id, "queued_sim")
        journal.log_event("INFO", f"{mode}: simulated queue for plan {plan_id}.")
        return {
            "ok": True,
            "message": f"{mode}: simulated limit queue created.",
            "mode": mode,
            "order_type": order_type,
        }

    if mode == "BINANCE_DEMO":
        if not config.has_binance_credentials():
            message = "Binance credentials are incomplete."
            journal.update_trade_plan_status(plan_id, "queue_failed")
            journal.log_event("ERROR", f"Queue failed for plan {plan_id}: {message}")
            return {"ok": False, "message": message}
        leverage_resp = binance_client.set_leverage(symbol, config.MAX_LEVERAGE)
        if not leverage_resp:
            journal.log_event(
                "ERROR",
                f"Set leverage failed for plan {plan_id}: {_binance_error()}",
            )
        if order_type == "MARKET":
            resp = binance_client.place_market_order(symbol, side, qty)
            if not resp or "orderId" not in resp:
                journal.update_trade_plan_status(plan_id, "queue_failed")
                reason = _binance_error(f"Unexpected response: {resp}")
                journal.log_event("ERROR", f"Market entry failed for plan {plan_id}: {reason}")
                return {"ok": False, "message": f"Market entry failed: {reason}"}
            journal.set_order_id(plan_id, str(resp["orderId"]))
            journal.save_trade(plan_id, _plan_to_setup(plan), qty, "BINANCE_DEMO", str(resp["orderId"]))
            journal.update_trade_plan_status(plan_id, "filled")
            journal.log_event("INFO", f"Binance market entry filled for plan {plan_id}.")
            return {
                "ok": True,
                "message": f"Market entry filled (orderId={resp['orderId']}).",
                "mode": mode,
                "order_type": order_type,
            }
        resp = binance_client.place_limit_order(symbol, side, qty, price)
        if not resp or "orderId" not in resp:
            journal.update_trade_plan_status(plan_id, "queue_failed")
            reason = _binance_error(f"Unexpected response: {resp}")
            journal.log_event("ERROR", f"Queue failed for plan {plan_id}: {reason}")
            return {"ok": False, "message": f"Queue failed: {reason}"}
        journal.set_order_id(plan_id, str(resp["orderId"]))
        journal.update_trade_plan_status(plan_id, "queued")
        journal.log_event("INFO", f"Binance queue placed for plan {plan_id}.")
        return {
            "ok": True,
            "message": f"Queue placed (orderId={resp['orderId']}).",
            "mode": mode,
            "order_type": order_type,
        }

    journal.log_event("ERROR", f"Queue failed for plan {plan_id}: Execution is disabled (mode DISABLED).")
    return {"ok": False, "message": "Execution is disabled (mode DISABLED)."}


def cancel_all_pending(reason: str = "market guard") -> dict:
    """Cancel all queue items that have not been filled yet."""
    active = journal.list_plans_by_status(list(ACTIVE_STATUSES))
    mode = current_mode()

    canceled = 0
    skipped = 0
    for plan in active:
        if plan.get("setup_type") == "manual_telegram_force":
            journal.log_event(
                "INFO",
                f"Plan {plan['id']} was not canceled by the guard because it is a force entry.",
            )
            skipped += 1
            continue
        if mode == "BINANCE_DEMO" and plan.get("binance_order_id"):
            binance_client.cancel_order(config.SYMBOL, plan["binance_order_id"])
        journal.update_trade_plan_status(plan["id"], "canceled_market_guard")
        journal.log_event("INFO", f"Plan {plan['id']} canceled ({reason}).")
        canceled += 1
    if canceled:
        logger.warning("Canceled %s queue item(s). Reason: %s", canceled, reason)
    return {"ok": True, "canceled": canceled, "skipped_force": skipped, "reason": reason}


def cancel_plan(plan_id: int, reason: str = "manual") -> dict:
    plan = journal.get_trade_plan(plan_id)
    if not plan:
        return {"ok": False, "message": "Plan not found."}
    if plan.get("status") not in ACTIVE_STATUSES:
        return {"ok": False, "message": f"Plan status {plan.get('status')} is not an active queue item."}
    mode = current_mode()
    if mode == "BINANCE_DEMO" and plan.get("binance_order_id"):
        binance_client.cancel_order(config.SYMBOL, plan["binance_order_id"])
    journal.update_trade_plan_status(plan_id, "canceled_manual")
    journal.log_event("INFO", f"Plan {plan_id} canceled ({reason}).")
    return {"ok": True, "canceled": 1, "plan_id": plan_id}


def sync_fills() -> dict:
    """Check Binance queue status and record trades when FILLED."""
    if current_mode() != "BINANCE_DEMO":
        return {"ok": True, "filled": 0, "checked": 0}

    active = journal.list_plans_by_status(["queued"])
    filled = 0
    for plan in active:
        order_id = plan.get("binance_order_id")
        if not order_id:
            continue
        order = binance_client.get_order(config.SYMBOL, order_id)
        if not order:
            continue
        status = order.get("status")
        if status == "FILLED":
            journal.save_trade(
                plan["id"], _plan_to_setup(plan), plan["position_size"],
                "BINANCE_DEMO", str(order_id)
            )
            journal.update_trade_plan_status(plan["id"], "filled")
            journal.log_event("INFO", f"Queue plan {plan['id']} FILLED.")
            filled += 1
        elif status in ("CANCELED", "EXPIRED", "REJECTED"):
            journal.update_trade_plan_status(plan["id"], f"closed_{status.lower()}")
    return {"ok": True, "filled": filled, "checked": len(active)}


def list_active_queue() -> list:
    return journal.list_plans_by_status(list(ACTIVE_STATUSES))
