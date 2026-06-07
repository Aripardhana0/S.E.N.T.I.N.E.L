"""Telegram notifications and commands.
Sends signals and receives approve/reject plus status commands."""
import logging
import re

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
)

from app.config import config
from app import (
    accounting,
    journal,
    manual_entry,
    market_data,
    market_guard,
    order_queue,
    performance,
    position_manager,
    runtime_settings,
)
from app.executor import execute_plan, current_mode
from app.binance_client import binance_client
from app.indicators import add_indicators, trend_regime

logger = logging.getLogger("telegram_bot")

_application: Application | None = None

def format_signal(setup: dict, risk: dict, ai: dict, plan_id: int) -> str:
    bias = "Bullish" if setup.get("side") == "long" else "Bearish"
    return (
        f"BTC/USDT Demo Signal\n"
        f"Bias: {bias}\n"
        f"Setup: {setup.get('setup_type', '-')}\n"
        f"Reason: {setup.get('entry_reason', '-')}\n"
        f"Entry: {setup['entry']}\n"
        f"Stop Loss: {setup['stop_loss']}\n"
        f"Take Profit: {setup['take_profit']}\n"
        f"RR: {risk['risk_reward']}\n"
        f"RSI/ADX/VOL: {setup.get('rsi', '-')} / {setup.get('adx', '-')} / {setup.get('volume_ratio', '-')}\n"
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
    """Send a message to the configured chat."""
    if not config.has_telegram() or _application is None:
        logger.warning("Telegram is not configured; message skipped.")
        return
    try:
        await _application.bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID, text=text
        )
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)

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
        return "safe simulation, no exchange order is sent"
    if mode == "PAPER":
        return "local paper trading"
    if mode == "BINANCE_DEMO":
        return "demo exchange execution is active"
    return "execution is disabled"


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
        logger.exception("Failed to read market guard for /status: %s", exc)
        return "Market Guard: ERROR reading market data"

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
        logger.exception("Failed to read queue for /status: %s", exc)
        return "Queue: ERROR reading queue"
    live = sum(1 for row in active if row.get("status") == "queued")
    sim = sum(1 for row in active if row.get("status") == "queued_sim")
    return f"Queue: {len(active)} active ({live} exchange / {sim} simulated)"


def _format_learning_status() -> str:
    try:
        perf = performance.build_performance_dashboard()
    except Exception as exc:
        logger.exception("Failed to read performance for /status: %s", exc)
        return "Learning Guard: ERROR reading performance"

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
        return "Last plan: none yet"
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
    trend = trend_regime(trend_df)
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


def _format_account_status() -> str:
    data = accounting.summary()
    open_data = data["open"]
    queue = data["queue"]
    closed = data["closed_all"]
    today = data["closed_today"]
    return (
        "ACCOUNT\n"
        f"Mode: {data['mode']} | Source: {data['balance_source']}\n"
        f"Balance: {_fmt(data['balance'], 4)} USDT\n"
        f"Available: {_fmt(data['available'], 4)} USDT\n"
        f"Equity est: {_fmt(data['equity_estimate'], 4)} USDT\n\n"
        f"Open: {open_data['count']} position(s) | notional {_fmt(open_data['notional'], 4)} | "
        f"risk {_fmt(open_data['risk_amount'], 4)} | uPnL {_fmt(open_data['unrealized_pnl'], 4)}\n"
        f"Queue: {queue['count']} entry | planned risk {_fmt(queue['risk_amount'], 4)}\n\n"
        f"Closed all: win {closed['wins']} (+{_fmt(closed['gross_profit'], 4)}) | "
        f"loss {closed['losses']} (-{_fmt(closed['gross_loss'], 4)}) | net {_fmt(closed['net_pnl'], 4)}\n"
        f"Today: win {today['wins']} | loss {today['losses']} | net {_fmt(today['net_pnl'], 4)}"
    )


def _entry_help() -> str:
    return (
        "Format:\n"
        "/entry short ENTRY SL TP\n"
        "/entry long ENTRY SL TP\n\n"
        "Short example:\n"
        "/entry short 62500 63000 61500\n\n"
        "Long example:\n"
        "/entry long 62500 62000 63500\n\n"
        "Manual entry is still checked by the risk manager and market guard.\n"
        "/force_entry bypasses the market guard and is not canceled by the guard job."
    )


def _help_text() -> str:
    return (
        "I can help through normal chat:\n"
        "- status / market / account / positions\n"
        "- entry short 62500 63000 61500\n"
        "- entry long 62500 62000 63500\n"
        "- close 3\n"
        "- set tpsl 3 62000 63500\n"
        "- mode dry | paper | demo | stop\n\n"
        "Slash commands also work: /status /market /positions /account /entry /force_entry."
    )


def _numbers(text: str) -> list[float]:
    return [float(item) for item in re.findall(r"-?\d+(?:\.\d+)?", text)]


def _entry_result_message(result: dict) -> str:
    setup = result.get("setup", {})
    risk = result.get("risk", {})
    return (
        f"Manual entry plan #{result.get('plan_id', '-')}\n"
        f"Status: {'OK' if result.get('ok') else 'BLOCKED'}\n"
        f"Message: {result.get('message')}\n"
        f"Side: {setup.get('side')} | Entry: {_fmt(setup.get('entry'), 2)}\n"
        f"SL: {_fmt(setup.get('stop_loss'), 2)} | TP: {_fmt(setup.get('take_profit'), 2)}\n"
        f"RR: {_fmt(setup.get('risk_reward'), 2)} | Size: {_fmt(risk.get('position_size'), 8)}\n"
        f"Mode: {current_mode()}"
    )


# ---------- command handlers ----------
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = journal.get_today_stats()
    mode = current_mode()
    message = (
        "SENTINEL STATUS\n"
        f"Mode: {mode} - {_runtime_hint(mode)}\n"
        f"Symbol: {config.SYMBOL} | Strategy: {config.STRATEGY_PROFILE}\n"
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


async def cmd_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_format_account_status())


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_help_text())


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            f"Current mode: {current_mode()}\nType: /mode dry | paper | demo | stop"
        )
        return
    try:
        settings = runtime_settings.set_mode(ctx.args[0])
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(f"Mode changed to {settings['mode']}.")


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
        await update.message.reply_text(f"Invalid input: {exc}\n\n{_entry_help()}")
        return
    except Exception as exc:
        logger.exception("Manual entry failed: %s", exc)
        await update.message.reply_text(f"Manual entry error: {exc}")
        return

    await update.message.reply_text(_entry_result_message(result))


async def cmd_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_entry(update, ctx, respect_guard=True)


async def cmd_force_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_entry(update, ctx, respect_guard=False)


async def cmd_close(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Format: /close <trade_id>")
        return
    try:
        trade_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Trade id must be numeric.")
        return
    result = position_manager.close_trade_now(trade_id, reason="telegram")
    if not result.get("ok"):
        await update.message.reply_text(result.get("message", "Close failed."))
        return
    trade = result["trade"]
    await update.message.reply_text(
        f"Trade #{trade_id} closed @ {_fmt(trade.get('exit'), 2)} | "
        f"PnL {_fmt(trade.get('pnl'), 4)} | {trade.get('status')}"
    )


async def cmd_set_tpsl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) != 3:
        await update.message.reply_text("Format: /set_tpsl <trade_id> <SL> <TP>")
        return
    try:
        trade_id = int(ctx.args[0])
        stop_loss = float(ctx.args[1])
        take_profit = float(ctx.args[2])
        trade = journal.update_trade_levels(trade_id, stop_loss, take_profit)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    if not trade:
        await update.message.reply_text("Trade not found.")
        return
    await update.message.reply_text(
        f"TP/SL for trade #{trade_id} updated: SL {_fmt(stop_loss, 2)} | TP {_fmt(take_profit, 2)}"
    )

async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bal = binance_client.get_balance()
    if not bal:
        await update.message.reply_text(
            f"Balance is unavailable. Initial equity from config: {config.INITIAL_EQUITY}"
        )
        return
    await update.message.reply_text(f"Balance Binance Futures Testnet: {bal}")


async def cmd_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    low = text.lower()
    try:
        if any(word in low for word in ("help", "menu")):
            await update.message.reply_text(_help_text())
            return
        if "status" in low:
            await cmd_status(update, ctx)
            return
        if any(word in low for word in ("market", "trend", "rsi")):
            await cmd_market(update, ctx)
            return
        if any(word in low for word in ("account", "balance", "equity")):
            await cmd_account(update, ctx)
            return
        if any(word in low for word in ("positions", "position", "open trade")):
            await cmd_positions(update, ctx)
            return
        if low.startswith("mode "):
            try:
                settings = runtime_settings.set_mode(low.split()[1])
                await update.message.reply_text(f"Mode changed to {settings['mode']}.")
            except (IndexError, ValueError) as exc:
                await update.message.reply_text(str(exc))
            return
        if low.startswith("close "):
            nums = _numbers(text)
            if nums:
                result = position_manager.close_trade_now(int(nums[0]), reason="telegram")
                if result.get("ok"):
                    trade = result["trade"]
                    await update.message.reply_text(
                        f"Trade #{int(nums[0])} closed @ {_fmt(trade.get('exit'), 2)} | "
                        f"PnL {_fmt(trade.get('pnl'), 4)} | {trade.get('status')}"
                    )
                else:
                    await update.message.reply_text(result.get("message", "Close failed."))
            return
        if low.startswith("set tpsl "):
            nums = _numbers(text)
            if len(nums) >= 3:
                try:
                    trade = journal.update_trade_levels(int(nums[0]), nums[1], nums[2])
                except ValueError as exc:
                    await update.message.reply_text(str(exc))
                    return
                if not trade:
                    await update.message.reply_text("Trade not found.")
                    return
                await update.message.reply_text(
                    f"TP/SL for trade #{int(nums[0])} updated: SL {_fmt(nums[1], 2)} | TP {_fmt(nums[2], 2)}"
                )
                return
        if low.startswith("entry ") or low.startswith("force entry "):
            force = low.startswith("force entry ")
            side = "long" if " long " in f" {low} " else "short" if " short " in f" {low} " else None
            nums = _numbers(text)
            if side and len(nums) >= 3:
                try:
                    result = manual_entry.create_entry(
                        side, nums[0], nums[1], nums[2], respect_guard=not force
                    )
                except ValueError as exc:
                    await update.message.reply_text(f"Invalid input: {exc}\n\n{_entry_help()}")
                    return
                await update.message.reply_text(_entry_result_message(result))
                return
        await update.message.reply_text(
            "I understood the message, but I am not sure which action you want. "
            "Try typing: status, market, account, positions, or help."
        )
    except Exception as exc:
        logger.exception("Chat handler error: %s", exc)
        await update.message.reply_text(f"An error occurred while processing the chat: {exc}")

async def cmd_last_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sig = journal.get_last_signal()
    await update.message.reply_text(str(sig) if sig else "No signal yet.")

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
        await update.message.reply_text("Format: /approve_<id> or /approve <id>")
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
        await update.message.reply_text("Format: /reject_<id> or /reject <id>")
        return
    journal.update_trade_plan_status(plan_id, "rejected_manual")
    await update.message.reply_text(f"Trade plan {plan_id} rejected.")


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
    """Build the Telegram application. Return None when it is not configured."""
    global _application
    if not config.has_telegram():
        logger.warning("TELEGRAM_BOT_TOKEN/CHAT_ID is empty; bot is inactive.")
        return None
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("market", cmd_market))
    app.add_handler(CommandHandler(["positions", "position"], cmd_positions))
    app.add_handler(CommandHandler("account", cmd_account))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("entry", cmd_entry))
    app.add_handler(CommandHandler("force_entry", cmd_force_entry))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("set_tpsl", cmd_set_tpsl))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("last_signal", cmd_last_signal))
    app.add_handler(CommandHandler("daily_report", cmd_daily_report))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(MessageHandler(filters.Regex(r"^/(approve|reject)_\d+"), cmd_inline_decision))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_chat))
    _application = app
    return app
