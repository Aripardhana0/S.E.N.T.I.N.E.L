"""Trade executor helpers.

The auto branch uses order_queue for Binance auto entries. execute_plan remains
for legacy approval/manual endpoints and DRY_RUN/PAPER modes.
"""
import logging

from app import journal
from app.config import config

logger = logging.getLogger("executor")


def current_mode() -> str:
    """Effective execution mode based on env flags."""
    if config.DRY_RUN:
        return "DRY_RUN"
    if config.BINANCE_DEMO_TRADING and config.EXECUTION_ENABLED:
        return "BINANCE_DEMO"
    if config.PAPER_TRADE:
        return "PAPER"
    return "DISABLED"


def execute_plan(plan_id: int) -> dict:
    """Legacy manual execution for DRY_RUN/PAPER; Binance uses order_queue."""
    plan = journal.get_trade_plan(plan_id)
    if not plan:
        return {"ok": False, "message": "Trade plan not found."}
    if not plan["risk_allowed"]:
        journal.update_trade_plan_status(plan_id, "rejected_risk")
        return {"ok": False, "message": "Risk manager rejected the plan; execution skipped."}
    if config.REQUIRE_MANUAL_APPROVAL and plan["status"] != "approved":
        return {"ok": False, "message": "Manual approval is still required."}

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
        journal.log_event("INFO", f"DRY_RUN simulated plan {plan_id}.")
        return {"ok": True, "message": "DRY_RUN: simulation saved.", "mode": mode}

    if mode == "PAPER":
        journal.save_trade(plan_id, setup, plan["position_size"], "PAPER", None)
        journal.update_trade_plan_status(plan_id, "executed_paper")
        journal.log_event("INFO", f"PAPER trade plan {plan_id}.")
        return {"ok": True, "message": "PAPER trade saved.", "mode": mode}

    if mode == "BINANCE_DEMO":
        return {
            "ok": False,
            "message": "Use /queue or order_queue for Binance LIMIT orders.",
            "mode": mode,
        }

    return {"ok": False, "message": "Execution is disabled (mode DISABLED)."}
