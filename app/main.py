"""Entry point FastAPI. Menyalakan DB, scheduler, dan (opsional) Telegram bot."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.config import config
from app.database import init_db
from app import journal
from app.executor import execute_plan, current_mode
from app.scheduler import start_scheduler, scheduler
from app import telegram_bot
from app import market_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

_tg_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    # Ambil candle awal agar indikator cepat siap.
    for tf in ("1m", "15m", "1H"):
        market_data.fetch_and_store_candles(tf)
    start_scheduler()

    global _tg_app
    _tg_app = telegram_bot.build_application()
    if _tg_app is not None:
        await _tg_app.initialize()
        await _tg_app.start()
        await _tg_app.updater.start_polling()
        logger.info("Telegram bot polling started.")

    logger.info("App started in mode=%s", current_mode())
    yield

    # Shutdown
    if scheduler.running:
        scheduler.shutdown(wait=False)
    if _tg_app is not None:
        await _tg_app.updater.stop()
        await _tg_app.stop()
        await _tg_app.shutdown()

app = FastAPI(title="BTC Demo Trading AI Agent", lifespan=lifespan)

@app.get("/")
def root():
    return {"name": "BTC Demo Trading AI Agent", "mode": current_mode()}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/status")
def status():
    stats = journal.get_today_stats()
    return {
        "mode": current_mode(),
        "symbol": config.SYMBOL,
        "execution_enabled": config.EXECUTION_ENABLED,
        "require_manual_approval": config.REQUIRE_MANUAL_APPROVAL,
        "today": stats,
    }

@app.get("/last-signal")
def last_signal():
    return journal.get_last_signal() or {"message": "belum ada sinyal"}

@app.get("/trade-plans")
def trade_plans():
    return journal.list_trade_plans()

@app.get("/trades")
def trades():
    return journal.list_trades()

@app.post("/approve/{trade_plan_id}")
def approve(trade_plan_id: int):
    plan = journal.get_trade_plan(trade_plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Trade plan tidak ditemukan.")
    journal.update_trade_plan_status(trade_plan_id, "approved")
    return execute_plan(trade_plan_id)

@app.post("/reject/{trade_plan_id}")
def reject(trade_plan_id: int):
    plan = journal.get_trade_plan(trade_plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Trade plan tidak ditemukan.")
    journal.update_trade_plan_status(trade_plan_id, "rejected_manual")
    return {"ok": True, "message": f"Trade plan {trade_plan_id} ditolak."}
