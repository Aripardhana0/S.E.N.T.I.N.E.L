"""Trade Executor. Mendukung mode DRY_RUN, PAPER_TRADE, OKX_DEMO_TRADING.
Mengikuti pengaman: EXECUTION_ENABLED & REQUIRE_MANUAL_APPROVAL."""
import logging

from app.config import config
from app.okx_client import okx_client
from app import journal

logger = logging.getLogger("executor")

def current_mode() -> str:
    if config.DRY_RUN:
        return "DRY_RUN"
    if config.OKX_DEMO_TRADING and config.EXECUTION_ENABLED:
        return "OKX_DEMO"
    if config.PAPER_TRADE:
        return "PAPER"
    return "DISABLED"

def execute_plan(plan_id: int) -> dict:
    """Eksekusi trade plan yang sudah disetujui.
    Selalu cek ulang status risk & approval sebelum kirim order."""
    plan = journal.get_trade_plan(plan_id)
    if not plan:
        return {"ok": False, "message": "Trade plan tidak ditemukan."}

    # Re-check pengaman deterministik.
    if not plan["risk_allowed"]:
        journal.update_trade_plan_status(plan_id, "rejected_risk")
        return {"ok": False, "message": "Risk manager menolak, tidak dieksekusi."}

    if config.REQUIRE_MANUAL_APPROVAL and plan["status"] != "approved":
        return {"ok": False, "message": "Belum di-approve manual."}

    setup = {
        "symbol": plan["symbol"], "side": plan["side"],
        "entry": plan["entry"], "stop_loss": plan["stop_loss"],
        "take_profit": plan["take_profit"],
    }
    size = plan["position_size"]
    mode = current_mode()

    # DRY_RUN: tidak kirim order, hanya catat simulasi.
    if mode == "DRY_RUN":
        journal.save_trade(plan_id, setup, size, "DRY_RUN", None)
        journal.update_trade_plan_status(plan_id, "executed_dry_run")
        journal.log_event("INFO", f"DRY_RUN simulasi plan {plan_id}.")
        return {"ok": True, "message": "DRY_RUN: simulasi tersimpan.", "mode": mode}

    # PAPER: catat sebagai paper trade tanpa kirim ke exchange.
    if mode == "PAPER":
        journal.save_trade(plan_id, setup, size, "PAPER", None)
        journal.update_trade_plan_status(plan_id, "executed_paper")
        journal.log_event("INFO", f"PAPER trade plan {plan_id}.")
        return {"ok": True, "message": "PAPER trade tersimpan.", "mode": mode}

    # OKX_DEMO: kirim order ke OKX demo trading.
    if mode == "OKX_DEMO":
        if not config.has_okx_credentials():
            return {"ok": False, "message": "Kredensial OKX belum lengkap."}
        okx_side = "sell" if setup["side"] == "short" else "buy"
        resp = okx_client.place_order(setup["symbol"], okx_side, size)
        if not resp or resp.get("code") not in ("0", 0):
            journal.log_event("ERROR", f"Order OKX gagal plan {plan_id}: {resp}")
            return {"ok": False, "message": f"Order gagal: {resp}"}
        order_id = resp["data"][0].get("ordId")
        journal.save_trade(plan_id, setup, size, "OKX_DEMO", order_id)
        journal.update_trade_plan_status(plan_id, "executed_okx_demo")
        journal.log_event("INFO", f"Order OKX demo terkirim plan {plan_id}.")
        return {"ok": True, "message": f"Order demo terkirim (ordId={order_id}).",
                "mode": mode}

    return {"ok": False, "message": "Eksekusi dinonaktifkan (mode DISABLED)."}
