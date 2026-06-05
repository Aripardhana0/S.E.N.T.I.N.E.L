"""Entry point FastAPI. Menyalakan DB, scheduler, dan Telegram bila aktif."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import journal, market_data, market_guard, order_queue, performance, telegram_bot
from app.config import config
from app.database import init_db, migrate_brach_auto
from app.executor import current_mode, execute_plan
from app.scheduler import scheduler, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("main")

_tg_app = None
_DASHBOARD_PATH = Path(__file__).parent / "static" / "dashboard.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    migrate_brach_auto()
    for tf in ("1m", "15m", "1h"):
        market_data.fetch_and_store_candles(tf)
    start_scheduler()

    global _tg_app
    _tg_app = telegram_bot.build_application()
    if _tg_app is not None:
        try:
            await _tg_app.initialize()
            await _tg_app.start()
            await _tg_app.updater.start_polling()
            logger.info("Telegram bot polling started.")
        except Exception as exc:
            logger.error("Telegram bot disabled during startup: %s", exc.__class__.__name__)
            _tg_app = None

    logger.info("App started in mode=%s", current_mode())
    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)
    if _tg_app is not None:
        await _tg_app.updater.stop()
        await _tg_app.stop()
        await _tg_app.shutdown()


app = FastAPI(title="BTC Demo Trading AI Agent - Auto", lifespan=lifespan)


@app.middleware("http")
async def log_http_errors(request: Request, call_next):
    response = await call_next(request)
    if response.status_code >= 400:
        logger.warning(
            "HTTP %s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
        )
    return response


@app.get("/")
def root():
    return {"name": "BTC Demo Trading AI Agent", "mode": current_mode()}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(_DASHBOARD_PATH.read_text(encoding="utf-8"))


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
        "auto_entry": config.AUTO_ENTRY,
        "guard_enabled": config.GUARD_ENABLED,
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


@app.post("/trades/{trade_id}/close")
def close_trade(trade_id: int, exit_price: float | None = None,
                pnl: float | None = None):
    try:
        trade = journal.close_trade(trade_id, exit_price=exit_price, pnl=pnl)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not trade:
        raise HTTPException(status_code=404, detail="Trade tidak ditemukan.")
    return {"ok": True, "trade": trade}


@app.get("/performance")
def performance_status():
    return performance.build_performance_dashboard()


@app.get("/market-guard")
def market_guard_status():
    return market_guard.evaluate_market()


@app.get("/queue")
def queue():
    return order_queue.list_active_queue()


@app.post("/cancel-all")
def cancel_all():
    return order_queue.cancel_all_pending(reason="manual via API")


@app.post("/sync-fills")
def sync_fills_now():
    return order_queue.sync_fills()


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
