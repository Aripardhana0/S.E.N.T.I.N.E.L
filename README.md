# BTC Demo Trading AI Agent - Auto

AI-assisted trading agent for BTCUSDT demo/paper trading on Binance Demo USD-M
Futures. The `auto` branch adds automatic LIMIT entry, deterministic market
guard, pending queue cancellation during unsafe markets, periodic fill sync, and
TP/SL exit tracking. This is not financial advice.

## Default Safety

The default mode stays conservative:

```ini
DRY_RUN=true
PAPER_TRADE=true
EXECUTION_ENABLED=false
AUTO_ENTRY=true
ENTRY_ORDER_TYPE=LIMIT
GUARD_ENABLED=true
```

Do not use live API keys without a full audit. The intended credentials for this
branch are Binance Demo Futures credentials from `demo.binance.com`, not live
account keys.

## How It Works

1. The scheduler fetches Binance ticker and candles, then stores them in SQLite.
2. The strategy checks for setups every 15 minutes.
3. Market Guard blocks entries when market conditions are unsafe.
4. The deterministic Risk Manager is the main execution gate.
5. Learning Guard checks setup performance from historical closed trades.
6. AI Reviewer is called only after guard and risk checks pass.
7. If AI does not return `reject` and `AUTO_ENTRY=true`, the system places a
   LIMIT order.
8. Market Guard runs every 60 seconds and cancels pending queues during unsafe
   market conditions.
9. Sync fills runs every 60 seconds and marks orders as `FILLED`.
10. Position Manager monitors open trades, closes them when TP/SL is touched,
    and records `pnl`, `closed_at`, and win/loss results.

Priority order: Market Guard, Learning Guard, and Risk Manager always sit above AI.

## Environment

```ini
APP_ENV=demo
DRY_RUN=true
PAPER_TRADE=true
EXECUTION_ENABLED=false

AUTO_ENTRY=true
GUARD_ENABLED=true
GUARD_ATR_SPIKE=1.8
GUARD_VOL_SPIKE=3.0
GUARD_RANGE_ATR=2.5
GUARD_MOVE_PCT=1.5

BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_DEMO_TRADING=true
BINANCE_BASE_URL=https://demo-fapi.binance.com
PRICE_PRECISION=1
QTY_PRECISION=3

OPENROUTER_API_KEY=
OPENROUTER_MODEL=openrouter/free

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

DASHBOARD_AUTH_ENABLED=true
DASHBOARD_USERNAME=arip
DASHBOARD_PASSWORD=
DASHBOARD_PASSWORD_HASH=
DASHBOARD_SESSION_SECRET=

SYMBOL=BTCUSDT
TIMEFRAME_SIGNAL=15m
TIMEFRAME_TREND=1h
STRATEGY_PROFILE=balanced

INITIAL_EQUITY=5
MAX_RISK_PER_TRADE=0.01
MAX_DAILY_LOSS=0.03
MAX_TRADES_PER_DAY=3
MAX_CONSECUTIVE_LOSS=2
MAX_LEVERAGE=2
MIN_RR=1.5

LEARNING_ENABLED=true
LEARNING_LOOKBACK_DAYS=30
LEARNING_MIN_TRADES=6
LEARNING_BLOCK_WINRATE=0.35
LEARNING_REDUCE_WINRATE=0.45
LEARNING_BLOCK_LOSS_STREAK=3
LEARNING_RISK_MULTIPLIER=0.5
LEARNING_RR_BUFFER=0.25
```

## Strategy Profiles

`STRATEGY_PROFILE` controls how selective the entry engine is before Market
Guard, Risk Manager, Learning Guard, and AI review.

- `conservative`: closest to the original strict filters. Fewer entries.
- `balanced`: scoring-based entries for demo data collection. Default.
- `exploratory`: looser scoring for demo-only sampling. More entries, more noise.

The strategy now scores trend pullbacks, volatility breakouts, and controlled
range reversion setups. Every generated plan stores `strategy_profile`,
`setup_score`, and a numeric entry reason inside the raw payload so later
performance review can compare setup quality.

For demo data collection, `ENTRY_ORDER_TYPE=MARKET` can be used to fill entries
immediately after a setup passes all guards. Keep `ENTRY_ORDER_TYPE=LIMIT` when
you want price-confirmed pullback fills instead of immediate entries.

## Learning Guard

Learning Guard is not an ML model and does not train the AI. It reads trades that
are already `closed` and have `pnl`, then applies deterministic rules:

- At least `LEARNING_MIN_TRADES` closed trades are required before winrate
  blocking becomes active.
- A setup is blocked when winrate <= `LEARNING_BLOCK_WINRATE`.
- A setup is blocked when loss streak >= `LEARNING_BLOCK_LOSS_STREAK`.
- If winrate < `LEARNING_REDUCE_WINRATE`, risk is reduced to
  `LEARNING_RISK_MULTIPLIER` and minimum RR is raised by `LEARNING_RR_BUFFER`.
- Risk is never increased automatically above `MAX_RISK_PER_TRADE`.

To generate learning data, trades must close and have PnL. If auto-close has not
closed a trade yet, record it manually through the API:

```bash
curl -X POST "http://127.0.0.1:8000/trades/1/close?exit_price=62000"
```

Or write PnL directly:

```bash
curl -X POST "http://127.0.0.1:8000/trades/1/close?pnl=0.12"
```

## Quick Start

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose logs -f agent
```

First safe mode: keep `DRY_RUN=true` and `EXECUTION_ENABLED=false`.

For real order placement on Binance Futures Testnet/Demo:

```ini
DRY_RUN=false
PAPER_TRADE=false
EXECUTION_ENABLED=true
BINANCE_DEMO_TRADING=true
AUTO_ENTRY=true
GUARD_ENABLED=true
```

## API Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/` | GET | App info and mode |
| `/login` | GET/POST | Dashboard login page and login action |
| `/logout` | POST | Clear the dashboard session |
| `/health` | GET | Health check |
| `/status` | GET | Mode, symbol, guard, and daily stats |
| `/account` | GET | Balance/equity, open risk, queued risk, and win/loss amounts |
| `/settings` | GET | Runtime mode and switch snapshot |
| `/settings/mode` | POST | Change mode: `DRY_RUN`, `PAPER`, `BINANCE_DEMO`, `DISABLED` |
| `/settings/toggle` | POST | Change runtime switches such as `AUTO_ENTRY` or `GUARD_ENABLED` |
| `/settings/env` | GET/POST | Read and update all `.env` fields from the dashboard |
| `/last-signal` | GET | Last signal |
| `/trade-plans` | GET | Trade plan list |
| `/trades` | GET | Trade list |
| `/trades/{id}/close` | POST | Manually close a trade and record PnL |
| `/trades/{id}/close-now` | POST | Close an open position using market/ticker price |
| `/trades/{id}/levels` | POST | Update TP/SL for an open position |
| `/performance` | GET | Winrate, setup performance, and daily evaluation |
| `/market-guard` | GET | Current market guard evaluation |
| `/queue` | GET | Active queue list |
| `/queue/{id}/cancel` | POST | Cancel one queued item |
| `/cancel-all` | POST | Panic button to cancel all queued items |
| `/sync-fills` | POST | Force order/fill sync |
| `/admin/clear-local-data` | POST | Clear selected local journal data with `CLEAR_LOCAL_DATA` confirmation |
| `/positions` | GET | Local open positions |
| `/logs` | GET | Latest local logs |
| `/logs/{id}` | DELETE | Delete one local log |
| `/approve/{id}` | POST | Legacy manual approval for DRY_RUN/PAPER |
| `/reject/{id}` | POST | Reject a trade plan |

## Telegram Commands

| Command | Description |
| --- | --- |
| `/status` | Mode, guard, queue, learning, and last signal summary |
| `/market` | Price, trend, RSI/ATR, and market guard |
| `/positions` | Local open positions and Binance Demo positions when active |
| `/account` | Balance/equity, open risk, queued risk, and win/loss amounts |
| `/mode dry|paper|demo|stop` | Change runtime mode and save it to `.env` |
| `/entry short ENTRY SL TP` | Create a manual short entry from Telegram |
| `/entry long ENTRY SL TP` | Create a manual long entry from Telegram |
| `/force_entry short ENTRY SL TP` | Create a manual entry that bypasses Market Guard, while risk is still checked |
| `/close TRADE_ID` | Close an open position |
| `/set_tpsl TRADE_ID SL TP` | Update SL/TP for an open position |
| `/balance` | Binance Demo/Testnet balance |
| `/daily_report` | Daily summary |

Examples:

```text
/entry short 62500 63000 61500
/entry long 62500 62000 63500
account
market
close 3
set tpsl 3 62000 63500
```

Manual entries still pass through the risk manager. `/force_entry` bypasses the
market guard and is not canceled by the guard job, but it does not bypass risk.

Dashboard runtime controls change the running process mode and write changes
back to `.env`. In Docker, `docker-compose.yml` mounts `./.env:/app/.env` so
those changes are persisted on the host.

The dashboard is protected by a simple login using an `HttpOnly` session cookie.
The default username is `arip`; the default password follows the operator
credential requested for this deployment. For production, set
`DASHBOARD_PASSWORD` or `DASHBOARD_PASSWORD_HASH`, and also set
`DASHBOARD_SESSION_SECRET` in `.env`.

The settings menu can edit every `.env` field. Secrets such as API keys and
tokens can be replaced, but existing values are not displayed in the dashboard.
Local data can be cleared per group: `trade_plans`, `trades`, `daily_stats`,
`daily_reviews`, `logs`, and `candles`. This does not close any real open
Binance position. The settings menu also shows `saving/saved/failed` status for
`.env` saves and provides local logs that can be deleted one by one.

## Database

The `auto` branch adds non-destructive columns:

```text
trade_plans.binance_order_id
trade_plans.queued_at
trade_plans.ai_risk_notes
trade_plans.setup_key
trade_plans.setup_type
trade_plans.learning_decision
trade_plans.learning_notes
trade_plans.risk_multiplier
trade_plans.adaptive_min_rr
trades.binance_order_id
trades.setup_key
trades.setup_type
trades.stop_loss
trades.take_profit
trades.exit_reason
trades.close_order_id
daily_reviews
```

Migration runs on startup after `init_db()`.
