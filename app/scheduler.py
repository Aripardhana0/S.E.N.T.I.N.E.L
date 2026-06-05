"""APScheduler: menjadwalkan market data, strategi, dan daily report.
AI hanya dipanggil saat ada setup valid (di dalam run_strategy)."""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import config
from app import market_data, strategy, risk_manager, ai_reviewer, journal
from app.executor import execute_plan
from app import telegram_bot

logger = logging.getLogger("scheduler")

scheduler = AsyncIOScheduler(timezone="UTC")

def _job_ticker():
    market_data.fetch_ticker()

def _job_candle(tf: str):
    market_data.fetch_and_store_candles(tf)

async def run_strategy():
    """Jalankan strategi → risk manager → AI (jika lolos) → kirim sinyal."""
    try:
        setup = strategy.generate_signal()
        if not setup:
            return

        # Gerbang utama: risk manager deterministik.
        risk = risk_manager.evaluate(setup, equity=config.INITIAL_EQUITY)
        if not risk["allowed"]:
            journal.save_trade_plan(setup, risk, {}, "rejected_risk")
            journal.log_event("INFO", f"Setup ditolak risk: {risk['reason']}")
            return  # AI TIDAK dipanggil bila risk menolak.

        # AI hanya dipanggil setelah risk lolos.
        ai = ai_reviewer.review(setup, risk)

        status = "pending_approval" if config.REQUIRE_MANUAL_APPROVAL else "approved"
        plan_id = journal.save_trade_plan(setup, risk, ai, status)

        # Kirim sinyal ke Telegram.
        msg = telegram_bot.format_signal(setup, risk, ai, plan_id)
        await telegram_bot.send_message(msg)

        # Bila tidak butuh approval manual, langsung eksekusi.
        if not config.REQUIRE_MANUAL_APPROVAL:
            execute_plan(plan_id)
    except Exception as e:
        logger.exception("run_strategy error: %s", e)

async def _job_daily_report():
    stats = journal.get_today_stats()
    await telegram_bot.send_message(
        f"Daily Report ({stats['day']})\n"
        f"Trades: {stats['trades_count']} | PnL: {stats['realized_pnl']}"
    )

def start_scheduler():
    """Daftarkan semua job & start scheduler."""
    scheduler.add_job(_job_ticker, "interval", seconds=30, id="ticker",
                      max_instances=1, replace_existing=True)
    scheduler.add_job(lambda: _job_candle("1m"), "interval", minutes=1,
                      id="candle_1m", max_instances=1, replace_existing=True)
    scheduler.add_job(lambda: _job_candle("15m"), "interval", minutes=15,
                      id="candle_15m", max_instances=1, replace_existing=True)
    scheduler.add_job(lambda: _job_candle("1H"), "interval", hours=1,
                      id="candle_1h", max_instances=1, replace_existing=True)
    scheduler.add_job(run_strategy, "interval", minutes=15, id="strategy",
                      max_instances=1, replace_existing=True)
    scheduler.add_job(_job_daily_report, "cron", hour=23, minute=55,
                      id="daily_report", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started.")
