# BTC Demo Trading AI Agent - Auto

AI-assisted trading agent untuk belajar dan demo/paper trading BTCUSDT di
Binance Demo USD-M Futures. Branch `auto` menambahkan auto entry LIMIT order,
market guard deterministik, cancel semua antrian pending saat market buruk, dan
sync fill berkala. Bukan nasihat finansial.

## Pengaman Default

Default tetap aman:

```ini
DRY_RUN=true
PAPER_TRADE=true
EXECUTION_ENABLED=false
AUTO_ENTRY=true
GUARD_ENABLED=true
```

Jangan gunakan API live tanpa audit penuh. Kredensial yang dimaksud di branch ini
adalah Binance Demo Futures dari `demo.binance.com`, bukan akun live.

## Cara Kerja

1. Scheduler mengambil ticker dan candle Binance, lalu menyimpan ke SQLite.
2. Strategy mencari setup setiap 15 menit.
3. Market Guard mengecek kondisi buruk sebelum entry.
4. Risk Manager deterministik menjadi gerbang utama.
5. Learning Guard mengecek performa setup dari closed trade historis.
6. AI Reviewer hanya dipanggil setelah guard dan risk lolos.
7. Jika AI tidak `reject` dan `AUTO_ENTRY=true`, sistem memasang LIMIT order.
8. Market Guard berjalan tiap 60 detik dan membatalkan semua antrian pending saat
   kondisi market buruk.
9. Sync fills berjalan tiap 60 detik untuk menandai order `FILLED`.

Urutan prioritas: Market Guard, Learning Guard, dan Risk Manager selalu di atas AI.

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

SYMBOL=BTCUSDT
TIMEFRAME_SIGNAL=15m
TIMEFRAME_TREND=1h

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

## Learning Guard

Learning Guard bukan model ML dan tidak melatih AI. Sistem ini membaca trade yang
sudah `closed` dan punya `pnl`, lalu memakai aturan deterministik:

- Minimal `LEARNING_MIN_TRADES` closed trade sebelum blok winrate aktif.
- Setup diblok jika winrate <= `LEARNING_BLOCK_WINRATE`.
- Setup diblok jika loss streak >= `LEARNING_BLOCK_LOSS_STREAK`.
- Jika winrate < `LEARNING_REDUCE_WINRATE`, risk dikurangi ke
  `LEARNING_RISK_MULTIPLIER` dan minimum RR dinaikkan sebesar
  `LEARNING_RR_BUFFER`.
- Risk tidak pernah dinaikkan otomatis melebihi `MAX_RISK_PER_TRADE`.

Untuk membuat data pembelajaran, trade harus ditutup dan punya PnL. Kalau belum
ada auto close, catat manual lewat API:

```bash
curl -X POST "http://127.0.0.1:8000/trades/1/close?exit_price=62000"
```

Atau langsung isi PnL:

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

Mode aman pertama: biarkan `DRY_RUN=true` dan `EXECUTION_ENABLED=false`.

Untuk order nyata di Binance Futures Testnet:

```ini
DRY_RUN=false
PAPER_TRADE=false
EXECUTION_ENABLED=true
BINANCE_DEMO_TRADING=true
AUTO_ENTRY=true
GUARD_ENABLED=true
```

## API Endpoints

| Endpoint | Metode | Deskripsi |
| --- | --- | --- |
| `/` | GET | Info app dan mode |
| `/health` | GET | Health check |
| `/status` | GET | Mode, symbol, guard, dan stats |
| `/last-signal` | GET | Sinyal terakhir |
| `/trade-plans` | GET | Daftar trade plan |
| `/trades` | GET | Daftar trade |
| `/trades/{id}/close` | POST | Tutup trade manual dan catat PnL |
| `/performance` | GET | Winrate, setup performance, daily evaluation |
| `/market-guard` | GET | Evaluasi market guard saat ini |
| `/queue` | GET | Daftar antrian aktif |
| `/cancel-all` | POST | Panic button cancel semua antrian |
| `/sync-fills` | POST | Paksa sync status order |
| `/approve/{id}` | POST | Approval manual legacy untuk DRY_RUN/PAPER |
| `/reject/{id}` | POST | Reject trade plan |

## Database

Branch `auto` menambah kolom non-destruktif:

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
daily_reviews
```

Migrasi berjalan saat startup setelah `init_db()`.
