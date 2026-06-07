"""DETERMINISTIC risk manager.
AI is not allowed to override decisions made here."""
import logging
from datetime import datetime, timezone

from app import performance
from app.config import config
from app.journal import get_today_stats

logger = logging.getLogger("risk_manager")

def evaluate(setup: dict, equity: float | None = None) -> dict:
    """Return the risk decision in a standard format."""
    equity = config.INITIAL_EQUITY if equity is None else equity

    learning = performance.evaluate_setup_gate(setup)
    setup_type, setup_key = performance.setup_identity(setup)

    def deny(reason: str) -> dict:
        return {
            "allowed": False, "reason": reason,
            "risk_amount": 0.0, "position_size": 0.0, "risk_reward": 0.0,
            "setup_key": setup_key,
            "setup_type": setup_type,
            "learning_decision": learning.get("decision"),
            "learning_notes": learning.get("reason"),
            "risk_multiplier": learning.get("risk_multiplier", 1.0),
            "adaptive_min_rr": learning.get("min_rr", config.MIN_RR),
        }

    if learning["blocked"]:
        return deny(f"Learning guard block: {learning['reason']}")

    # 1. Stop loss and take profit are required.
    if not setup.get("stop_loss") or not setup.get("take_profit"):
        return deny("Stop loss / take profit is invalid.")

    entry = float(setup["entry"])
    stop = float(setup["stop_loss"])
    tp = float(setup["take_profit"])
    risk_per_unit = abs(stop - entry)
    
    if risk_per_unit <= 0:
        return deny("Risk per unit is invalid.")

    # 2. Check minimum RR.
    adaptive_min_rr = max(config.MIN_RR, float(learning.get("min_rr", config.MIN_RR)))
    if setup.get("risk_reward", 0) < adaptive_min_rr:
        return deny(f"RR {setup.get('risk_reward')} < adaptive minimum {adaptive_min_rr}.")

    # 3. Calculate position size and risk amount.
    risk_multiplier = min(1.0, max(0.0, float(learning.get("risk_multiplier", 1.0))))
    risk_amount = equity * config.MAX_RISK_PER_TRADE * risk_multiplier
    position_size = risk_amount / risk_per_unit
    
    # 4. Check daily loss limit.
    stats = get_today_stats()
    if stats["realized_pnl"] < -equity * config.MAX_DAILY_LOSS:
        return deny(f"Daily loss {stats['realized_pnl']} >= limit.")

    # 5. Check max trades per day.
    if stats["trades_count"] >= config.MAX_TRADES_PER_DAY:
        return deny("Max trades per day has been reached.")
    
    if stats["consecutive_loss"] >= config.MAX_CONSECUTIVE_LOSS:
        return deny("Consecutive loss limit reached; pause entries.")
    
    # 6. Check leverage limit.
    max_position = equity * config.MAX_LEVERAGE / entry
    if position_size > max_position:
        # Reduce position size to fit the leverage limit.
        position_size = round(max_position, 8)

    if position_size < 0.0001:
        return deny("Position size is too small after leverage adjustment.")

    return {
        "allowed": True,
        "reason": "OK",
        "risk_amount": round(risk_amount, 2),
        "position_size": round(position_size, 8),
        "risk_reward": setup.get("risk_reward", 0),
        "setup_key": setup_key,
        "setup_type": setup_type,
        "learning_decision": learning.get("decision"),
        "learning_notes": learning.get("reason"),
        "risk_multiplier": risk_multiplier,
        "adaptive_min_rr": adaptive_min_rr,
    }
