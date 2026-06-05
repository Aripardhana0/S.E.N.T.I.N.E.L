"""Order Queue + Cancel Manager untuk auto entry Binance."""
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


def enqueue_entry(plan_id: int) -> dict:
    """Pasang LIMIT order untuk plan yang sudah lolos guard, risk, dan AI."""
    plan = journal.get_trade_plan(plan_id)
    if not plan:
        return {"ok": False, "message": "Plan tidak ditemukan."}
    if not plan["risk_allowed"]:
        journal.update_trade_plan_status(plan_id, "rejected_risk")
        return {"ok": False, "message": "Risk menolak, tidak diantrikan."}

    symbol = config.SYMBOL
    side = "SELL" if plan["side"] == "short" else "BUY"
    qty = binance_client.round_qty(plan["position_size"])
    price = binance_client.round_price(plan["entry"])
    mode = current_mode()

    if mode in ("DRY_RUN", "PAPER"):
        journal.set_order_id(plan_id, f"SIM-{plan_id}")
        journal.update_trade_plan_status(plan_id, "queued_sim")
        journal.log_event("INFO", f"{mode}: antrian simulasi plan {plan_id}.")
        return {"ok": True, "message": f"{mode}: antrian simulasi dibuat.", "mode": mode}

    if mode == "BINANCE_DEMO":
        if not config.has_binance_credentials():
            return {"ok": False, "message": "Kredensial Binance belum lengkap."}
        binance_client.set_leverage(symbol, config.MAX_LEVERAGE)
        resp = binance_client.place_limit_order(symbol, side, qty, price)
        if not resp or "orderId" not in resp:
            journal.update_trade_plan_status(plan_id, "queue_failed")
            journal.log_event("ERROR", f"Antri gagal plan {plan_id}: {resp}")
            return {"ok": False, "message": f"Antri gagal: {resp}"}
        journal.set_order_id(plan_id, str(resp["orderId"]))
        journal.update_trade_plan_status(plan_id, "queued")
        journal.log_event("INFO", f"Antrian Binance terpasang plan {plan_id}.")
        return {
            "ok": True,
            "message": f"Antrian terpasang (orderId={resp['orderId']}).",
            "mode": mode,
        }

    return {"ok": False, "message": "Eksekusi dinonaktifkan (mode DISABLED)."}


def cancel_all_pending(reason: str = "market guard") -> dict:
    """Batalkan semua antrian yang belum terisi."""
    active = journal.list_plans_by_status(list(ACTIVE_STATUSES))
    mode = current_mode()

    if mode == "BINANCE_DEMO" and active:
        binance_client.cancel_all_open_orders(config.SYMBOL)

    canceled = 0
    for plan in active:
        journal.update_trade_plan_status(plan["id"], "canceled_market_guard")
        journal.log_event("INFO", f"Plan {plan['id']} dibatalkan ({reason}).")
        canceled += 1
    if canceled:
        logger.warning("Cancel %s antrian. Alasan: %s", canceled, reason)
    return {"ok": True, "canceled": canceled, "reason": reason}


def sync_fills() -> dict:
    """Cek status antrian Binance dan catat trade saat FILLED."""
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
            journal.log_event("INFO", f"Antrian plan {plan['id']} FILLED.")
            filled += 1
        elif status in ("CANCELED", "EXPIRED", "REJECTED"):
            journal.update_trade_plan_status(plan["id"], f"closed_{status.lower()}")
    return {"ok": True, "filled": filled, "checked": len(active)}


def list_active_queue() -> list:
    return journal.list_plans_by_status(list(ACTIVE_STATUSES))
