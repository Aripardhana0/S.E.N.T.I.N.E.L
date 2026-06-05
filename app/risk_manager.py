"""Risk Manager DETERMINISTIC. Inilah gerbang utama.
AI tidak boleh meng-override keputusan di sini."""
import logging
from datetime import datetime, timezone

from app import performance
from app.config import config
from app.journal import get_today_stats

logger = logging.getLogger("risk_manager")

def evaluate(setup: dict, equity: float | None = None) -> dict:
    """Kembalikan keputusan risk dalam format standar."""
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

    # 1. Validasi SL & TP wajib ada.
    if not setup.get("stop_loss") or not setup.get("take_profit"):
        return deny("Stop loss / take profit tidak valid.")

    entry = float(setup["entry"])
    stop = float(setup["stop_loss"])
    tp = float(setup["take_profit"])
    risk_per_unit = abs(stop - entry)
    
    if risk_per_unit <= 0:
        return deny("Risk per unit tidak valid.")

    # 2. Cek RR minimum.
    adaptive_min_rr = max(config.MIN_RR, float(learning.get("min_rr", config.MIN_RR)))
    if setup.get("risk_reward", 0) < adaptive_min_rr:
        return deny(f"RR {setup.get('risk_reward')} < adaptive minimum {adaptive_min_rr}.")

    # 3. Hitung posisi dan risk amount.
    risk_multiplier = min(1.0, max(0.0, float(learning.get("risk_multiplier", 1.0))))
    risk_amount = equity * config.MAX_RISK_PER_TRADE * risk_multiplier
    position_size = risk_amount / risk_per_unit
    
    # 4. Cek daily loss limit.
    stats = get_today_stats()
    if stats["realized_pnl"] < -equity * config.MAX_DAILY_LOSS:
        return deny(f"Daily loss {stats['realized_pnl']} >= limit.")

    # 5. Cek max trades per day.
    if stats["trades_count"] >= config.MAX_TRADES_PER_DAY:
        return deny("Sudah mencapai max trades per day.")
    
    if stats["consecutive_loss"] >= config.MAX_CONSECUTIVE_LOSS:
        return deny("Sudah loss berturut-turut, berhenti dulu.")
    
    # 6. Cek leverage limit.
    max_position = equity * config.MAX_LEVERAGE / entry
    if position_size > max_position:
        # Kecilkan posisi agar sesuai batas leverage.
        position_size = round(max_position, 8)

    if position_size < 0.0001:
        return deny("Posisi terlalu kecil setelah adjustment leverage.")

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
