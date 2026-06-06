"""Trade executor helpers.

Branch auto memakai order_queue untuk LIMIT order Binance. execute_plan tetap ada
untuk endpoint approval/manual lama dan mode DRY_RUN/PAPER.
"""
import logging

from app import journal
from app.config import config

logger = logging.getLogger("executor")


def current_mode() -> str:
    """Mode eksekusi efektif berdasarkan flag env."""
    if config.DRY_RUN:
        return "DRY_RUN"
    if config.BINANCE_DEMO_TRADING and config.EXECUTION_ENABLED:
        return "BINANCE_DEMO"
    if config.PAPER_TRADE:
        return "PAPER"
    return "DISABLED"


def execute_plan(plan_id: int) -> dict:
    """Eksekusi manual lama untuk DRY_RUN/PAPER; Binance lewat order_queue."""
    plan = journal.get_trade_plan(plan_id)
    if not plan:
        return {"ok": False, "message": "Trade plan tidak ditemukan."}
    if not plan["risk_allowed"]:
        journal.update_trade_plan_status(plan_id, "rejected_risk")
        return {"ok": False, "message": "Risk manager menolak, tidak dieksekusi."}
    if config.REQUIRE_MANUAL_APPROVAL and plan["status"] != "approved":
        return {"ok": False, "message": "Belum di-approve manual."}

    setup = {
        "symbol": plan["symbol"],
        "side": plan["side"],
        "entry": plan["entry"],
        "stop_loss": plan["stop_loss"],
        "take_profit": plan["take_profit"],
        "setup_type": plan.get("setup_type"),
    }
    mode = current_mode()

    if mode == "DRY_RUN":
        journal.save_trade(plan_id, setup, plan["position_size"], "DRY_RUN", None)
        journal.update_trade_plan_status(plan_id, "executed_dry_run")
        journal.log_event("INFO", f"DRY_RUN simulasi plan {plan_id}.")
        return {"ok": True, "message": "DRY_RUN: simulasi tersimpan.", "mode": mode}

    if mode == "PAPER":
        journal.save_trade(plan_id, setup, plan["position_size"], "PAPER", None)
        journal.update_trade_plan_status(plan_id, "executed_paper")
        journal.log_event("INFO", f"PAPER trade plan {plan_id}.")
        return {"ok": True, "message": "PAPER trade tersimpan.", "mode": mode}

    if mode == "BINANCE_DEMO":
        return {
            "ok": False,
            "message": "Gunakan /queue atau order_queue untuk LIMIT order Binance.",
            "mode": mode,
        }

    return {"ok": False, "message": "Eksekusi dinonaktifkan (mode DISABLED)."}
