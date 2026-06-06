"""Rule-based performance analytics and learning guard.

This module does not train a model. It reads closed trade history, calculates
simple statistics, and returns deterministic rules for the risk manager.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import config
from app.database import get_conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _since_iso(days: int | None = None) -> str:
    lookback = config.LEARNING_LOOKBACK_DAYS if days is None else days
    return (datetime.now(timezone.utc) - timedelta(days=lookback)).isoformat()


def _pct(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round((float(part) / float(total)) * 100, 2)


def setup_identity(setup: dict) -> tuple[str, str]:
    """Return stable setup_type and setup_key for analytics grouping."""
    setup_type = setup.get("setup_type") or "unknown_setup"
    symbol = setup.get("symbol", config.SYMBOL)
    side = setup.get("side", "unknown")
    return setup_type, f"{symbol}:{side}:{setup_type}"


def learning_rules() -> list[str]:
    return [
        (
            f"Need at least {config.LEARNING_MIN_TRADES} closed trades before "
            "winrate blocking is active."
        ),
        (
            f"Block setup if winrate <= {config.LEARNING_BLOCK_WINRATE:.0%} "
            f"or loss streak >= {config.LEARNING_BLOCK_LOSS_STREAK}."
        ),
        (
            f"If winrate < {config.LEARNING_REDUCE_WINRATE:.0%}, reduce risk to "
            f"{config.LEARNING_RISK_MULTIPLIER:.0%} and require RR +"
            f"{config.LEARNING_RR_BUFFER:g}."
        ),
        "Never increase risk above MAX_RISK_PER_TRADE automatically.",
    ]


def _loss_streak(conn, setup_key: str) -> int:
    rows = conn.execute(
        """
        SELECT t.pnl
        FROM trades t
        LEFT JOIN trade_plans tp ON tp.id = t.trade_plan_id
        WHERE t.closed_at IS NOT NULL
          AND t.pnl IS NOT NULL
          AND COALESCE(tp.setup_key, t.setup_key, 'legacy') = ?
        ORDER BY t.closed_at DESC
        LIMIT 30
        """,
        (setup_key,),
    ).fetchall()
    streak = 0
    for row in rows:
        pnl = float(row["pnl"] or 0)
        if pnl < 0:
            streak += 1
            continue
        break
    return streak


def _decision_from_stats(total: int, winrate: float, loss_streak: int) -> str:
    if loss_streak >= config.LEARNING_BLOCK_LOSS_STREAK:
        return "blocked_loss_streak"
    if total < config.LEARNING_MIN_TRADES:
        return "collecting"
    if winrate <= config.LEARNING_BLOCK_WINRATE * 100:
        return "blocked_low_winrate"
    if winrate < config.LEARNING_REDUCE_WINRATE * 100:
        return "reduced_risk"
    return "allowed"


def setup_stats(setup_key: str | None = None, limit: int = 20) -> list[dict]:
    since = _since_iso()
    where = [
        "t.closed_at IS NOT NULL",
        "t.pnl IS NOT NULL",
        "t.closed_at >= ?",
    ]
    params: list = [since]
    if setup_key:
        where.append("COALESCE(tp.setup_key, t.setup_key, 'legacy') = ?")
        params.append(setup_key)

    where_sql = " AND ".join(where)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                COALESCE(tp.setup_key, t.setup_key, 'legacy') AS setup_key,
                COALESCE(tp.setup_type, t.setup_type, 'legacy') AS setup_type,
                COUNT(t.id) AS total,
                SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN t.pnl < 0 THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN t.pnl = 0 THEN 1 ELSE 0 END) AS flats,
                SUM(t.pnl) AS net_pnl,
                AVG(t.pnl) AS avg_pnl,
                MAX(t.closed_at) AS last_closed
            FROM trades t
            LEFT JOIN trade_plans tp ON tp.id = t.trade_plan_id
            WHERE {where_sql}
            GROUP BY
                COALESCE(tp.setup_key, t.setup_key, 'legacy'),
                COALESCE(tp.setup_type, t.setup_type, 'legacy')
            ORDER BY total DESC, net_pnl DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            total = int(item["total"] or 0)
            wins = int(item["wins"] or 0)
            item["winrate"] = _pct(wins, total)
            item["loss_streak"] = _loss_streak(conn, item["setup_key"])
            item["decision"] = _decision_from_stats(
                total, item["winrate"], item["loss_streak"]
            )
            item["net_pnl"] = round(float(item["net_pnl"] or 0), 8)
            item["avg_pnl"] = round(float(item["avg_pnl"] or 0), 8)
            result.append(item)
        return result


def closed_trade_summary(days: int | None = None) -> dict:
    since = _since_iso(days)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(id) AS total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN pnl = 0 THEN 1 ELSE 0 END) AS flats,
                SUM(pnl) AS net_pnl,
                AVG(pnl) AS avg_pnl
            FROM trades
            WHERE closed_at IS NOT NULL
              AND pnl IS NOT NULL
              AND closed_at >= ?
            """,
            (since,),
        ).fetchone()
    data = dict(row) if row else {}
    total = int(data.get("total") or 0)
    wins = int(data.get("wins") or 0)
    return {
        "total": total,
        "wins": wins,
        "losses": int(data.get("losses") or 0),
        "flats": int(data.get("flats") or 0),
        "winrate": _pct(wins, total),
        "net_pnl": round(float(data.get("net_pnl") or 0), 8),
        "avg_pnl": round(float(data.get("avg_pnl") or 0), 8),
        "lookback_days": config.LEARNING_LOOKBACK_DAYS if days is None else days,
    }


def ai_verdict_summary(day: str | None = None) -> list[dict]:
    params: list = []
    where = "1=1"
    if day:
        where = "created_at LIKE ?"
        params.append(f"{day}%")
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE(ai_verdict, 'none') AS verdict, COUNT(*) AS total
            FROM trade_plans
            WHERE {where}
            GROUP BY verdict
            ORDER BY total DESC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def evaluate_setup_gate(setup: dict) -> dict:
    setup_type, setup_key = setup_identity(setup)
    base = {
        "enabled": config.LEARNING_ENABLED,
        "setup_key": setup_key,
        "setup_type": setup_type,
        "blocked": False,
        "decision": "collecting",
        "reason": "Learning guard collecting closed trade data.",
        "risk_multiplier": 1.0,
        "min_rr": config.MIN_RR,
        "sample_size": 0,
        "wins": 0,
        "losses": 0,
        "winrate": 0.0,
        "loss_streak": 0,
    }
    if not config.LEARNING_ENABLED:
        base["decision"] = "disabled"
        base["reason"] = "Learning guard disabled."
        return base

    stats = setup_stats(setup_key=setup_key, limit=1)
    if not stats:
        return base

    stat = stats[0]
    total = int(stat["total"] or 0)
    wins = int(stat["wins"] or 0)
    losses = int(stat["losses"] or 0)
    winrate = float(stat["winrate"] or 0)
    loss_streak = int(stat["loss_streak"] or 0)
    base.update(
        {
            "sample_size": total,
            "wins": wins,
            "losses": losses,
            "winrate": winrate,
            "loss_streak": loss_streak,
            "reason": "Enough history for rule check."
            if total >= config.LEARNING_MIN_TRADES
            else "Sample still below minimum; entry not blocked by winrate.",
        }
    )

    if loss_streak >= config.LEARNING_BLOCK_LOSS_STREAK:
        base.update(
            {
                "blocked": True,
                "decision": "blocked_loss_streak",
                "reason": (
                    f"Setup loss streak {loss_streak} >= "
                    f"{config.LEARNING_BLOCK_LOSS_STREAK}."
                ),
            }
        )
        return base

    if total >= config.LEARNING_MIN_TRADES:
        if winrate <= config.LEARNING_BLOCK_WINRATE * 100:
            base.update(
                {
                    "blocked": True,
                    "decision": "blocked_low_winrate",
                    "reason": (
                        f"Setup winrate {winrate:.2f}% <= "
                        f"{config.LEARNING_BLOCK_WINRATE:.0%}."
                    ),
                }
            )
            return base

        if winrate < config.LEARNING_REDUCE_WINRATE * 100:
            base.update(
                {
                    "decision": "reduced_risk",
                    "risk_multiplier": config.LEARNING_RISK_MULTIPLIER,
                    "min_rr": round(config.MIN_RR + config.LEARNING_RR_BUFFER, 4),
                    "reason": (
                        f"Setup winrate {winrate:.2f}% < "
                        f"{config.LEARNING_REDUCE_WINRATE:.0%}; risk reduced."
                    ),
                }
            )
            return base

        base.update(
            {
                "decision": "allowed",
                "reason": f"Setup winrate {winrate:.2f}% passes learning guard.",
            }
        )
    return base


def build_daily_evaluation(day: str | None = None, persist: bool = False) -> dict:
    day = day or _today()
    with get_conn() as conn:
        plan = conn.execute(
            """
            SELECT
                COUNT(id) AS total,
                SUM(CASE WHEN status LIKE 'rejected%' THEN 1 ELSE 0 END) AS rejected,
                SUM(CASE WHEN status IN ('queued', 'queued_sim') THEN 1 ELSE 0 END) AS queued,
                SUM(CASE WHEN status IN ('filled', 'filled_sim') THEN 1 ELSE 0 END) AS filled
            FROM trade_plans
            WHERE created_at LIKE ?
            """,
            (f"{day}%",),
        ).fetchone()
        trade = conn.execute(
            """
            SELECT
                COUNT(id) AS closed,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses,
                SUM(pnl) AS pnl
            FROM trades
            WHERE closed_at LIKE ?
              AND pnl IS NOT NULL
            """,
            (f"{day}%",),
        ).fetchone()

    plan_data = dict(plan) if plan else {}
    trade_data = dict(trade) if trade else {}
    closed = int(trade_data.get("closed") or 0)
    wins = int(trade_data.get("wins") or 0)
    rejected = int(plan_data.get("rejected") or 0)
    total_plans = int(plan_data.get("total") or 0)
    recommendations = []

    if closed == 0:
        recommendations.append("No closed trades yet; learning guard is still collecting outcomes.")
    if total_plans and _pct(rejected, total_plans) >= 60:
        recommendations.append("High rejection rate today; check market regime and strategy filters.")
    if closed >= 3 and _pct(wins, closed) < 40:
        recommendations.append("Weak day by winrate; keep auto-entry conservative tomorrow.")
    if not recommendations:
        recommendations.append("No critical issue from today's closed data.")

    evaluation = {
        "day": day,
        "plans_total": total_plans,
        "plans_rejected": rejected,
        "plans_queued": int(plan_data.get("queued") or 0),
        "plans_filled": int(plan_data.get("filled") or 0),
        "closed_trades": closed,
        "wins": wins,
        "losses": int(trade_data.get("losses") or 0),
        "winrate": _pct(wins, closed),
        "realized_pnl": round(float(trade_data.get("pnl") or 0), 8),
        "ai_verdicts": ai_verdict_summary(day),
        "recommendations": recommendations,
    }
    if persist:
        save_daily_evaluation(evaluation)
    return evaluation


def save_daily_evaluation(evaluation: dict) -> None:
    summary = (
        f"{evaluation['closed_trades']} closed trades, "
        f"{evaluation['winrate']}% winrate, pnl {evaluation['realized_pnl']}"
    )
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO daily_reviews
                (day, created_at, summary, metrics_json, recommendations_json)
            VALUES (?,?,?,?,?)
            """,
            (
                evaluation["day"],
                _now(),
                summary,
                json.dumps(evaluation),
                json.dumps(evaluation["recommendations"]),
            ),
        )


def _build_performance_dashboard() -> dict:
    return {
        "learning_enabled": config.LEARNING_ENABLED,
        "thresholds": {
            "min_trades": config.LEARNING_MIN_TRADES,
            "block_winrate": config.LEARNING_BLOCK_WINRATE,
            "reduce_winrate": config.LEARNING_REDUCE_WINRATE,
            "block_loss_streak": config.LEARNING_BLOCK_LOSS_STREAK,
            "risk_multiplier": config.LEARNING_RISK_MULTIPLIER,
            "rr_buffer": config.LEARNING_RR_BUFFER,
            "lookback_days": config.LEARNING_LOOKBACK_DAYS,
        },
        "rules": learning_rules(),
        "closed_summary": closed_trade_summary(),
        "setups": setup_stats(limit=12),
        "ai_verdicts": ai_verdict_summary(),
        "daily": build_daily_evaluation(),
    }


def build_performance_dashboard() -> dict:
    try:
        return _build_performance_dashboard()
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "no such column" not in message and "no such table" not in message:
            raise
        from app.database import init_db, migrate_brach_auto

        init_db()
        migrate_brach_auto()
        return _build_performance_dashboard()
