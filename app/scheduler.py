"""APScheduler jobs: market data, auto entry, market guard, and sync fills."""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import (
    accounting,
    ai_reviewer,
    journal,
    market_data,
    market_guard,
    order_queue,
    performance,
    position_manager,
    risk_manager,
    strategy,
    telegram_bot,
)
from app.config import config

logger = logging.getLogger("scheduler")

scheduler = AsyncIOScheduler(timezone="UTC")


def _job_ticker():
    market_data.fetch_ticker()


def _job_candle(tf: str):
    market_data.fetch_and_store_candles(tf)


async def run_strategy():
    """Strategy -> Market Guard -> Risk -> AI -> AUTO ENTRY."""
    try:
        setup = strategy.generate_signal()
        if not setup:
            return

        if config.GUARD_ENABLED:
            guard = market_guard.evaluate_market()
            if guard["bad"]:
                journal.log_event("INFO", f"Skip entry, bad market: {guard['reasons']}")
                return

        account = accounting.summary()
        equity = float(account.get("equity_estimate") or config.INITIAL_EQUITY)
        risk = risk_manager.evaluate(setup, equity=equity)
        if not risk["allowed"]:
            journal.save_trade_plan(setup, risk, {}, "rejected_risk")
            journal.log_event("INFO", f"Setup rejected by risk: {risk['reason']}")
            return

        ai = ai_reviewer.review(setup, risk)

        if config.AUTO_ENTRY:
            if ai.get("verdict") == "reject":
                journal.save_trade_plan(setup, risk, ai, "rejected_ai")
                journal.log_event("INFO", "Auto entry canceled: AI reject.")
                return
            plan_id = journal.save_trade_plan(setup, risk, ai, "approved")
            result = order_queue.enqueue_entry(plan_id)
            msg = telegram_bot.format_signal(setup, risk, ai, plan_id)
            await telegram_bot.send_message(
                msg + f"\n\nAUTO ENTRY: {result['message']}"
            )
        else:
            plan_id = journal.save_trade_plan(setup, risk, ai, "pending_approval")
            await telegram_bot.send_message(
                telegram_bot.format_signal(setup, risk, ai, plan_id)
            )
    except Exception as exc:
        logger.exception("run_strategy error: %s", exc)
        journal.log_event("ERROR", f"run_strategy error: {exc.__class__.__name__}: {exc}")


async def _job_market_guard():
    """Every 60 seconds: cancel pending queue items when the market is unsafe."""
    if not config.GUARD_ENABLED:
        return
    try:
        guard = market_guard.evaluate_market()
        if not guard["bad"]:
            return
        res = order_queue.cancel_all_pending(reason="; ".join(guard["reasons"]))
        if res["canceled"] > 0:
            await telegram_bot.send_message(
                f"Unsafe market -> canceled {res['canceled']} queue item(s).\n"
                f"Reason: {', '.join(guard['reasons'])}\n"
                f"Metrics: {guard['metrics']}"
            )
    except Exception as exc:
        logger.exception("market_guard job error: %s", exc)
        journal.log_event("ERROR", f"market_guard job error: {exc.__class__.__name__}: {exc}")


async def _job_sync_fills():
    """Every 60 seconds: check entry fills and TP/SL for open trades."""
    try:
        exchange_res = order_queue.sync_fills()
        sim_res = position_manager.sync_simulated_entries()
        exit_res = position_manager.sync_exits()
        filled = int(exchange_res.get("filled", 0)) + int(sim_res.get("filled", 0))
        if filled:
            await telegram_bot.send_message(f"{filled} queue item(s) filled.")
        if exit_res.get("closed"):
            lines = [
                f"{event['trade_id']} {event['reason'].upper()} exit={event['exit']} pnl={event['pnl']}"
                for event in exit_res.get("events", [])
            ]
            await telegram_bot.send_message("TP/SL closed:\n" + "\n".join(lines))
    except Exception as exc:
        logger.exception("sync_fills job error: %s", exc)
        journal.log_event("ERROR", f"sync_fills job error: {exc.__class__.__name__}: {exc}")


async def _job_daily_report():
    stats = journal.get_today_stats()
    evaluation = performance.build_daily_evaluation(stats["day"], persist=True)
    recommendations = "\n".join(f"- {item}" for item in evaluation["recommendations"])
    await telegram_bot.send_message(
        f"Daily Report ({stats['day']})\n"
        f"Trades: {stats['trades_count']} | PnL: {stats['realized_pnl']}\n"
        f"Closed: {evaluation['closed_trades']} | Winrate: {evaluation['winrate']}%\n"
        f"Review:\n{recommendations}"
    )


def start_scheduler():
    scheduler.add_job(_job_ticker, "interval", seconds=30, id="ticker",
                      max_instances=1, replace_existing=True)
    scheduler.add_job(lambda: _job_candle("1m"), "interval", minutes=1,
                      id="candle_1m", max_instances=1, replace_existing=True)
    scheduler.add_job(lambda: _job_candle("15m"), "interval", minutes=15,
                      id="candle_15m", max_instances=1, replace_existing=True)
    scheduler.add_job(lambda: _job_candle("1h"), "interval", hours=1,
                      id="candle_1h", max_instances=1, replace_existing=True)
    scheduler.add_job(run_strategy, "interval", minutes=15, id="strategy",
                      max_instances=1, replace_existing=True)
    scheduler.add_job(_job_market_guard, "interval", seconds=60, id="market_guard",
                      max_instances=1, replace_existing=True)
    scheduler.add_job(_job_sync_fills, "interval", seconds=60, id="sync_fills",
                      max_instances=1, replace_existing=True)
    scheduler.add_job(_job_daily_report, "cron", hour=23, minute=55,
                      id="daily_report", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler branch auto started.")
