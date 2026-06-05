# BTC Demo Trading AI Agent - Auto

AI-assisted trading agent untuk belajar dan demo/paper trading BTCUSDT di
Binance USD-M Futures Testnet. Branch `auto` menambahkan auto entry LIMIT order,
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
adalah Binance Futures Testnet, bukan akun live.

## Cara Kerja

1. Scheduler mengambil ticker dan candle Binance, lalu menyimpan ke SQLite.
2. Strategy mencari setup setiap 15 menit.
3. Market Guard mengecek kondisi buruk sebelum entry.
4. Risk Manager deterministik menjadi gerbang utama.
5. AI Reviewer hanya dipanggil setelah guard dan risk lolos.
6. Jika AI tidak `reject` dan `AUTO_ENTRY=true`, sistem memasang LIMIT order.
7. Market Guard berjalan tiap 60 detik dan membatalkan semua antrian pending saat
   kondisi market buruk.
8. Sync fills berjalan tiap 60 detik untuk menandai order `FILLED`.

Urutan prioritas: Market Guard dan Risk Manager selalu di atas AI.

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
BINANCE_BASE_URL=https://testnet.binancefuture.com
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
trades.binance_order_id
```

Migrasi berjalan saat startup setelah `init_db()`.
