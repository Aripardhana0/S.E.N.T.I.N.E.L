"""Notifikasi & command Telegram.
Mengirim sinyal dan menerima approve/reject + command status."""
import logging

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
)

from app.config import config
from app import (
    journal,
    manual_entry,
    market_data,
    market_guard,
    order_queue,
    performance,
    position_manager,
)
from app.executor import execute_plan, current_mode
from app.binance_client import binance_client
from app.indicators import add_indicators, is_downtrend

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

# ---------- formatting helpers ----------
def _onoff(value: bool) -> str:
    return "ON" if value else "OFF"


def _fmt(value, digits: int = 4) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def _runtime_hint(mode: str) -> str:
    if mode == "DRY_RUN":
        return "simulasi aman, tidak kirim order exchange"
    if mode == "PAPER":
        return "paper trade lokal"
    if mode == "BINANCE_DEMO":
        return "order demo exchange aktif"
    return "eksekusi mati"


def _short_reason(text: str | None, limit: int = 120) -> str:
    if not text:
        return "-"
    clean = " ".join(str(text).split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "..."


def _format_guard_status() -> str:
    if not config.GUARD_ENABLED:
        return "Market Guard: OFF"
    try:
        guard = market_guard.evaluate_market()
    except Exception as exc:
        logger.exception("Gagal membaca market guard untuk /status: %s", exc)
        return "Market Guard: ERROR membaca data market"

    label = "BLOCK" if guard.get("bad") else "CLEAR"
    metrics = guard.get("metrics") or {}
    lines = [
        f"Market Guard: {label}",
        (
            "Metrics: "
            f"ATR {_fmt(metrics.get('atr_ratio'), 2)} | "
            f"VOL {_fmt(metrics.get('vol_ratio'), 2)} | "
            f"RANGE {_fmt(metrics.get('range_ratio'), 2)} | "
            f"MOVE {_fmt(metrics.get('move_pct'), 2)}%"
        ),
    ]
    reasons = guard.get("reasons") or []
    if reasons:
        lines.append("Reason: " + _short_reason("; ".join(reasons)))
    return "\n".join(lines)


def _format_queue_status() -> str:
    try:
        active = order_queue.list_active_queue()
    except Exception as exc:
        logger.exception("Gagal membaca queue untuk /status: %s", exc)
        return "Queue: ERROR membaca antrian"
    live = sum(1 for row in active if row.get("status") == "queued")
    sim = sum(1 for row in active if row.get("status") == "queued_sim")
    return f"Queue: {len(active)} aktif ({live} exchange / {sim} simulasi)"


def _format_learning_status() -> str:
    try:
        perf = performance.build_performance_dashboard()
    except Exception as exc:
        logger.exception("Gagal membaca performance untuk /status: %s", exc)
        return "Learning Guard: ERROR membaca performa"

    summary = perf.get("closed_summary") or {}
    setups = perf.get("setups") or []
    daily = perf.get("daily") or {}
    weak = None
    if setups:
        weak = sorted(
            setups,
            key=lambda row: (
                float(row.get("winrate") or 0),
                -int(row.get("loss_streak") or 0),
            ),
        )[0]

    lines = [
        f"Learning Guard: {_onoff(perf.get('learning_enabled', False))}",
        (
            "Closed sample: "
            f"{summary.get('total', 0)} | "
            f"Winrate {_fmt(summary.get('winrate'), 2)}% | "
            f"Net PnL {_fmt(summary.get('net_pnl'), 8)}"
        ),
    ]
    if weak:
        lines.append(
            "Weak setup: "
            f"{weak.get('setup_type', '-')} | "
            f"{_fmt(weak.get('winrate'), 2)}% | "
            f"{weak.get('decision', 'collecting')}"
        )
    recommendations = daily.get("recommendations") or []
    if recommendations:
        lines.append("Daily note: " + _short_reason(recommendations[0]))
    return "\n".join(lines)


def _format_last_signal() -> str:
    last = journal.get_last_signal()
    if not last:
        return "Last plan: belum ada"
    return (
        "Last plan: "
        f"#{last.get('id')} {last.get('side', '-')} "
        f"entry {_fmt(last.get('entry'), 2)} | "
        f"AI {last.get('ai_verdict') or '-'} | "
        f"{last.get('status') or '-'}"
    )


def _format_market_status() -> str:
    ticker = market_data.fetch_ticker()
    price = _fmt(ticker.get("price"), 2) if ticker else "-"
    trend_df = add_indicators(market_data.load_candles_df(config.TIMEFRAME_TREND, 200))
    signal_df = add_indicators(market_data.load_candles_df(config.TIMEFRAME_SIGNAL, 200))
    trend = "bearish" if is_downtrend(trend_df) else "not bearish"
    rsi = "-"
    atr = "-"
    if signal_df is not None and not signal_df.empty:
        last = signal_df.iloc[-1]
        rsi = _fmt(last.get("rsi14"), 2)
        atr = _fmt(last.get("atr14"), 2)
    return (
        f"MARKET {config.SYMBOL}\n"
        f"Price: {price}\n"
        f"Trend {config.TIMEFRAME_TREND}: {trend}\n"
        f"Signal {config.TIMEFRAME_SIGNAL}: RSI {rsi} | ATR {atr}\n\n"
        f"{_format_guard_status()}"
    )


def _format_positions_status() -> str:
    local = position_manager.local_open_positions()
    lines = ["POSITIONS"]
    if not local:
        lines.append("Local open trades: none")
    else:
        lines.append(f"Local open trades: {len(local)}")
        for trade in local[:8]:
            lines.append(
                f"#{trade['id']} {trade['side']} entry {_fmt(trade['entry'], 2)} "
                f"mark {_fmt(trade.get('mark_price'), 2)} "
                f"TP {_fmt(trade.get('take_profit'), 2)} "
                f"SL {_fmt(trade.get('stop_loss'), 2)} "
                f"uPnL {_fmt(trade.get('unrealized_pnl'), 8)}"
            )

    if current_mode() == "BINANCE_DEMO":
        exchange = [
            row for row in binance_client.get_position_risk(config.SYMBOL)
            if abs(float(row.get("positionAmt", 0) or 0)) > 0
        ]
        if not exchange:
            lines.append("\nExchange position: none")
        else:
            lines.append("\nExchange position:")
            for row in exchange:
                lines.append(
                    f"{row.get('symbol')} amt {row.get('positionAmt')} "
                    f"entry {row.get('entryPrice')} "
                    f"mark {row.get('markPrice')} "
                    f"uPnL {row.get('unRealizedProfit')}"
                )
    return "\n".join(lines)


def _entry_help() -> str:
    return (
        "Format:\n"
        "/entry short ENTRY SL TP\n"
        "/entry long ENTRY SL TP\n\n"
        "Contoh short:\n"
        "/entry short 62500 63000 61500\n\n"
        "Contoh long:\n"
        "/entry long 62500 62000 63500\n\n"
        "Manual entry tetap dicek risk manager dan market guard.\n"
        "/force_entry melewati market guard dan tidak ikut cancel guard."
    )


# ---------- command handlers ----------
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = journal.get_today_stats()
    mode = current_mode()
    message = (
        "SENTINEL STATUS\n"
        f"Mode: {mode} - {_runtime_hint(mode)}\n"
        f"Symbol: {config.SYMBOL}\n"
        f"Execution: {_onoff(config.EXECUTION_ENABLED)} | "
        f"Auto Entry: {_onoff(config.AUTO_ENTRY)} | "
        f"Manual Approval: {_onoff(config.REQUIRE_MANUAL_APPROVAL)}\n\n"
        f"{_format_guard_status()}\n\n"
        f"Today: {stats['trades_count']} trade | "
        f"PnL {_fmt(stats['realized_pnl'], 8)} | "
        f"Loss streak {stats['consecutive_loss']}\n"
        f"{_format_queue_status()}\n\n"
        f"{_format_learning_status()}\n\n"
        f"{_format_last_signal()}"
    )
    await update.message.reply_text(message)


async def cmd_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_format_market_status())


async def cmd_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_format_positions_status())


async def _handle_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                        respect_guard: bool = True):
    if len(ctx.args) != 4:
        await update.message.reply_text(_entry_help())
        return
    try:
        side = ctx.args[0]
        entry = float(ctx.args[1])
        stop_loss = float(ctx.args[2])
        take_profit = float(ctx.args[3])
        result = manual_entry.create_entry(
            side, entry, stop_loss, take_profit, respect_guard=respect_guard
        )
    except ValueError as exc:
        await update.message.reply_text(f"Input tidak valid: {exc}\n\n{_entry_help()}")
        return
    except Exception as exc:
        logger.exception("Manual entry gagal: %s", exc)
        await update.message.reply_text(f"Manual entry error: {exc}")
        return

    setup = result.get("setup", {})
    risk = result.get("risk", {})
    await update.message.reply_text(
        f"Manual entry plan #{result.get('plan_id', '-')}\n"
        f"Status: {'OK' if result.get('ok') else 'BLOCKED'}\n"
        f"Message: {result.get('message')}\n"
        f"Side: {setup.get('side')} | Entry: {_fmt(setup.get('entry'), 2)}\n"
        f"SL: {_fmt(setup.get('stop_loss'), 2)} | TP: {_fmt(setup.get('take_profit'), 2)}\n"
        f"RR: {_fmt(setup.get('risk_reward'), 2)} | Size: {_fmt(risk.get('position_size'), 8)}\n"
        f"Mode: {current_mode()}"
    )


async def cmd_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_entry(update, ctx, respect_guard=True)


async def cmd_force_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_entry(update, ctx, respect_guard=False)

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
    if plan_id is None and ctx.args:
        try:
            plan_id = int(ctx.args[0])
        except ValueError:
            plan_id = None
    if plan_id is None:
        await update.message.reply_text("Format: /approve_<id> atau /approve <id>")
        return
    journal.update_trade_plan_status(plan_id, "approved")
    result = execute_plan(plan_id)
    await update.message.reply_text(result["message"])

async def cmd_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    plan_id = _parse_id(update.message.text, "/reject_")
    if plan_id is None and ctx.args:
        try:
            plan_id = int(ctx.args[0])
        except ValueError:
            plan_id = None
    if plan_id is None:
        await update.message.reply_text("Format: /reject_<id> atau /reject <id>")
        return
    journal.update_trade_plan_status(plan_id, "rejected_manual")
    await update.message.reply_text(f"Trade plan {plan_id} ditolak.")


async def cmd_inline_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if text.startswith("/approve_"):
        await cmd_approve(update, ctx)
    elif text.startswith("/reject_"):
        await cmd_reject(update, ctx)


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
    app.add_handler(CommandHandler("market", cmd_market))
    app.add_handler(CommandHandler(["positions", "position"], cmd_positions))
    app.add_handler(CommandHandler("entry", cmd_entry))
    app.add_handler(CommandHandler("force_entry", cmd_force_entry))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("last_signal", cmd_last_signal))
    app.add_handler(CommandHandler("daily_report", cmd_daily_report))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(MessageHandler(filters.Regex(r"^/(approve|reject)_\d+"), cmd_inline_decision))
    _application = app
    return app
