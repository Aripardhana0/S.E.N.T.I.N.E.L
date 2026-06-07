"""Manual entry helper used by Telegram commands."""
from __future__ import annotations

from app import accounting, journal, market_guard, order_queue, risk_manager
from app.config import config


def _risk_reward(side: str, entry: float, stop_loss: float, take_profit: float) -> float:
    risk = abs(stop_loss - entry)
    reward = abs(entry - take_profit)
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def build_setup(side: str, entry: float, stop_loss: float, take_profit: float) -> dict:
    side = side.lower().strip()
    if side not in ("short", "long"):
        raise ValueError("Side must be short or long.")

    if side == "short" and not (stop_loss > entry > take_profit):
        raise ValueError("Short format requires: SL > entry > TP.")
    if side == "long" and not (stop_loss < entry < take_profit):
        raise ValueError("Long format requires: SL < entry < TP.")

    return {
        "symbol": config.SYMBOL,
        "side": side,
        "setup_type": "manual_telegram",
        "entry": float(entry),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "risk_reward": _risk_reward(side, entry, stop_loss, take_profit),
    }


def create_entry(
    side: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    respect_guard: bool = True,
) -> dict:
    setup = build_setup(side, entry, stop_loss, take_profit)
    if not respect_guard:
        setup["setup_type"] = "manual_telegram_force"

    if respect_guard and config.GUARD_ENABLED:
        guard = market_guard.evaluate_market()
        if guard["bad"]:
            return {
                "ok": False,
                "message": "Market guard block: " + "; ".join(guard["reasons"]),
                "guard": guard,
                "setup": setup,
            }

    account = accounting.summary()
    equity = float(account.get("equity_estimate") or config.INITIAL_EQUITY)
    risk = risk_manager.evaluate(setup, equity=equity)
    if not risk["allowed"]:
        plan_id = journal.save_trade_plan(setup, risk, {}, "rejected_risk")
        return {
            "ok": False,
            "message": f"Risk reject plan #{plan_id}: {risk['reason']}",
            "plan_id": plan_id,
            "setup": setup,
            "risk": risk,
        }

    ai = {
        "verdict": "manual",
        "reason": "Manual Telegram entry; AI reviewer skipped.",
        "confidence": "manual",
        "risk_notes": "",
    }
    plan_id = journal.save_trade_plan(setup, risk, ai, "approved")
    result = order_queue.enqueue_entry(plan_id)
    return {
        "ok": bool(result.get("ok")),
        "message": result.get("message", "-"),
        "plan_id": plan_id,
        "setup": setup,
        "risk": risk,
        "queue": result,
    }
