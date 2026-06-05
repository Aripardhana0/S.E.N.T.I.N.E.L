"""Notifikasi & command Telegram.
Mengirim sinyal dan menerima approve/reject + command status."""
import logging

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
)

from app.config import config
from app import journal
from app.executor import execute_plan, current_mode
from app.binance_client import binance_client

logger = logging.getLogger("telegram_bot")

_application: Application | None = None

def format_signal(setup: dict, risk: dict, ai: dict, plan_id: int) -> str:
    return (
        f"BTC/USDT Demo Signal\n"
        f"Bias: Bearish\n"
        f"Setup: Pullback Short\n"
        f"Entry: {setup['entry']}\n"
        f"Stop Loss: {setup['stop_loss']}\n"
        f"Take Profit: {setup['take_profit']}\n"
        f"RR: {risk['risk_reward']}\n"
        f"Risk: {config.MAX_RISK_PER_TRADE * 100:.0f}%\n"
        f"Mode: {current_mode()}\n\n"
        f"Risk Manager:\n"
        f"Allowed: {risk['allowed']}\n"
        f"Reason: {risk['reason']}\n\n"
        f"AI Review:\n"
        f"Verdict: {ai.get('verdict')}\n"
        f"Reason: {ai.get('reason')}\n\n"
        f"Commands:\n"
        f"/approve_{plan_id}\n"
        f"/reject_{plan_id}"
    )

async def send_message(text: str):
    """Kirim pesan ke chat yang dikonfigurasi."""
    if not config.has_telegram() or _application is None:
        logger.warning("Telegram tidak dikonfigurasi, pesan dilewati.")
        return
    try:
        await _application.bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID, text=text
        )
    except Exception as e:
        logger.error("Gagal kirim Telegram: %s", e)

# ---------- command handlers ----------
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = journal.get_today_stats()
    await update.message.reply_text(
        f"Status: OK\nMode: {current_mode()}\n"
        f"Trades hari ini: {stats['trades_count']}\n"
        f"PnL hari ini: {stats['realized_pnl']}"
    )

async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bal = binance_client.get_balance()
    if not bal:
        await update.message.reply_text(
            f"Balance tidak tersedia. Equity awal (config): {config.INITIAL_EQUITY}"
        )
        return
    await update.message.reply_text(f"Balance Binance Futures Testnet: {bal}")

async def cmd_last_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sig = journal.get_last_signal()
    await update.message.reply_text(str(sig) if sig else "Belum ada sinyal.")

async def cmd_daily_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = journal.get_today_stats()
    await update.message.reply_text(
        f"Daily Report ({stats['day']})\n"
        f"Trades: {stats['trades_count']}\n"
        f"PnL: {stats['realized_pnl']}\n"
        f"Consecutive loss: {stats['consecutive_loss']}"
    )

async def cmd_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Format command: /approve_123
    plan_id = _parse_id(update.message.text, "/approve_")
    if plan_id is None:
        await update.message.reply_text("Format: /approve_<id>")
        return
    journal.update_trade_plan_status(plan_id, "approved")
    result = execute_plan(plan_id)
    await update.message.reply_text(result["message"])

async def cmd_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    plan_id = _parse_id(update.message.text, "/reject_")
    if plan_id is None:
        await update.message.reply_text("Format: /reject_<id>")
        return
    journal.update_trade_plan_status(plan_id, "rejected_manual")
    await update.message.reply_text(f"Trade plan {plan_id} ditolak.")

def _parse_id(text: str, prefix: str) -> int | None:
    try:
        return int(text.strip().split(prefix, 1)[1])
    except (IndexError, ValueError):
        return None

def build_application() -> Application | None:
    """Bangun aplikasi Telegram. Return None bila tidak dikonfigurasi."""
    global _application
    if not config.has_telegram():
        logger.warning("TELEGRAM_BOT_TOKEN/CHAT_ID kosong, bot tidak aktif.")
        return None
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("last_signal", cmd_last_signal))
    app.add_handler(CommandHandler("daily_report", cmd_daily_report))
    # approve_/reject_ pakai prefix → tangkap lewat MessageHandler regex sederhana.
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    _application = app
    return app
