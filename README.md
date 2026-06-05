# BTC Demo Trading AI Agent

AI-assisted trading agent untuk **belajar & demo/paper trading** BTC-USDT di OKX.
**NFA.**

## Disclaimer

⚠️ **Sistem ini dibuat untuk belajar & demo/paper trading saja**. Bukan nasihat finansial. Default-nya tidak melakukan live trading. Jangan pernah aktifkan eksekusi uang nyata tanpa audit menyeluruh dan pemahaman penuh atas risikonya.

## Cara Kerja Singkat

1. **Scheduler** mengambil ticker & candle dari OKX, simpan ke SQLite.
2. **Strategy** (Downtrend Pullback Short) mencari setup tiap 15 menit.
3. **Risk Manager** deterministik memvalidasi (gerbang utama).
4. **AI Reviewer** (OpenRouter) hanya memberi opini — TIDAK bisa override risk manager.
5. **Sinyal** dikirim ke Telegram, butuh approval manual sebelum eksekusi (default).

## Arsitektur Singkat

```
Scheduler (APScheduler)
├─ Market Data Worker (setiap 30s, 1m, 15m, 1H)
│  └─ SQLite: candles
├─ Strategy Engine (tiap 15m)
│  ├─ Indicator Engine
│  └─ Risk Manager (deterministic)
│     ├─ ALLOWED → AI Reviewer (OpenRouter)
│     └─ DENIED → STOP
└─ Telegram Notifications
   └─ Manual Approval (/approve_<id>, /reject_<id>)
```

## Prinsip Keputusan (Urutan Prioritas)

1. **Strategy** menghasilkan kandidat setup.
2. **Risk Manager deterministic** adalah gerbang utama. Kalau `allowed = false`, trade langsung ditolak.
3. **AI Reviewer** hanya dipanggil **setelah** risk manager meloloskan. AI **tidak bisa** meng-override risk manager.
4. **Manual approval** lewat Telegram wajib sebelum order benar-benar dieksekusi (default).
5. Eksekusi mengikuti mode env: `DRY_RUN` → `PAPER_TRADE` → `OKX_DEMO_TRADING`, dengan `EXECUTION_ENABLED=false` sebagai pengaman default.

## Struktur Folder

```
btc-demo-agent/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── okx_client.py
│   ├── market_data.py
│   ├── indicators.py
│   ├── strategy.py
│   ├── risk_manager.py
│   ├── ai_reviewer.py
│   ├── executor.py
│   ├── journal.py
│   ├── telegram_bot.py
│   └── scheduler.py
├── data/
│   └── trading.db        (dibuat otomatis saat pertama run)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Quick Start

### 1. Setup Lokal (Development)

```bash
# Clone atau buka folder project
cd btc-demo-agent

# Buat virtual environment
python -m venv .venv
source .venv/bin/activate   # di Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy .env.example ke .env
cp .env.example .env

# Edit .env dengan token Anda
nano .env
```

### 2. Jalankan FastAPI Lokal

```bash
uvicorn app.main:app --reload --port 8000
```

Buka browser: `http://localhost:8000/docs` → Swagger UI untuk test endpoint.

### 3. Setup VPS (Ubuntu)

```bash
# Update & install Docker
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-plugin git

# Enable Docker
sudo systemctl enable --now docker

# Clone repo
git clone <repo-anda> btc-demo-agent && cd btc-demo-agent

# Copy & isi .env
cp .env.example .env
nano .env

# Build & run
docker compose build
docker compose up -d

# Cek logs
docker compose logs -f agent
```

## Environment Variables (.env)

```ini
# Mode aplikasi
APP_ENV=demo
DRY_RUN=true                    # Tidak kirim order, simulasi saja
PAPER_TRADE=true                # Catat trade tanpa kirim ke exchange
EXECUTION_ENABLED=false         # WAJIB false untuk keamanan default
REQUIRE_MANUAL_APPROVAL=true    # Perlu approval manual sebelum eksekusi

# OKX API (opsional untuk market data publik; wajib untuk demo order)
OKX_API_KEY=
OKX_API_SECRET=
OKX_API_PASSPHRASE=
OKX_DEMO_TRADING=true           # Selalu gunakan demo, bukan live

# OpenRouter AI
OPENROUTER_API_KEY=             # https://openrouter.ai
OPENROUTER_MODEL=openrouter/free

# Telegram Bot
TELEGRAM_BOT_TOKEN=             # @BotFather → newbot
TELEGRAM_CHAT_ID=               # Chat ID dari bot (https://api.telegram.org/bot<TOKEN>/getUpdates)

# Strategy
SYMBOL=BTC-USDT
TIMEFRAME_SIGNAL=15m
TIMEFRAME_TREND=1H

# Risk Management
INITIAL_EQUITY=5                # Modal awal (USD)
MAX_RISK_PER_TRADE=0.01         # 1% per trade
MAX_DAILY_LOSS=0.03             # 3% stop loss harian
MAX_TRADES_PER_DAY=3
MAX_CONSECUTIVE_LOSS=2
MAX_LEVERAGE=2
MIN_RR=1.5                      # Risk Reward minimum
```

## API Endpoints

| Endpoint | Metode | Deskripsi |
|----------|--------|-----------|
| `/` | GET | Root (info app) |
| `/health` | GET | Health check |
| `/status` | GET | Status mode & stats harian |
| `/last-signal` | GET | Sinyal terakhir |
| `/trade-plans` | GET | List semua trade plan |
| `/trades` | GET | List semua trades |
| `/approve/{id}` | POST | Approve trade plan & eksekusi |
| `/reject/{id}` | POST | Reject trade plan |

### Contoh Curl

```bash
# Cek status
curl http://localhost:8000/status

# List trade plans
curl http://localhost:8000/trade-plans

# Approve plan #1
curl -X POST http://localhost:8000/approve/1

# Reject plan #1
curl -X POST http://localhost:8000/reject/1
```

## Testing (DRY_RUN)

1. **Pastikan `.env` sudah dikonfigurasi** dengan minimal `OPENROUTER_API_KEY`.
2. **Set mode DRY_RUN**:
   ```ini
   DRY_RUN=true
   EXECUTION_ENABLED=false
   ```
3. **Jalankan aplikasi** dan tunggu setup (15 menit pertama kali ambil data).
4. **Test endpoint**:
   ```bash
   curl http://localhost:8000/status
   curl http://localhost:8000/trade-plans
   ```
5. **Approve sinyal** via API atau Telegram (jika bot aktif).

## Mengaktifkan Telegram Bot

1. Chat dengan **@BotFather** di Telegram → `/newbot` → ikuti instruksi.
2. Dapat `TELEGRAM_BOT_TOKEN` (simpan di `.env`).
3. Chat dengan bot Anda, kirim pesan random.
4. Cek `TELEGRAM_CHAT_ID` di: `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Masukkan `TELEGRAM_CHAT_ID` ke `.env`.

### Telegram Commands

```
/status           → Status mode & trades hari ini
/balance          → Balance OKX (atau equity awal)
/last_signal      → Sinyal terakhir
/daily_report     → Report hari ini
/approve_<id>     → Approve trade plan
/reject_<id>      → Reject trade plan
```

## Mengaktifkan OKX Demo Mode (BERTAHAP)

⚠️ **Jangan pernah langsung enable live trading tanpa testing!**

1. **Buat akun OKX** (jika belum) → https://www.okx.com
2. **Setup Demo Trading** di OKX dashboard → dapatkan API key (untuk demo).
3. **Isi kredensial di `.env`**:
   ```ini
   OKX_API_KEY=<your_demo_key>
   OKX_API_SECRET=<your_demo_secret>
   OKX_API_PASSPHRASE=<your_demo_passphrase>
   OKX_DEMO_TRADING=true
   ```
4. **Ubah mode secara bertahap**:
   ```ini
   DRY_RUN=false
   PAPER_TRADE=false
   EXECUTION_ENABLED=true
   REQUIRE_MANUAL_APPROVAL=true    # ← SELALU aktif untuk keamanan
   ```
5. **Restart aplikasi** dan monitor logs.

## Fitur Keamanan

✅ **Risk Manager Deterministic** — AI tidak bisa override.
✅ **EXECUTION_ENABLED=false** — Default pengaman.
✅ **REQUIRE_MANUAL_APPROVAL=true** — Approval manual wajib.
✅ **DRY_RUN mode** — Test tanpa order nyata.
✅ **PAPER_TRADE mode** — Track trade tanpa ke exchange.
✅ **OKX_DEMO_TRADING=true** — Selalu ke demo, bukan live.
✅ **Max daily loss limit** — Stop jika loss > batas.
✅ **Max consecutive loss** — Berhenti setelah N loss berturut-turut.
✅ **Leverage limit** — Batas maksimal leverage.

## Logs & Debugging

### Local
```bash
# Terminal akan menampilkan logs real-time
uvicorn app.main:app --reload --port 8000
```

### Docker
```bash
# Lihat logs container
docker compose logs -f agent

# Lihat database (SQLite)
sqlite3 data/trading.db
SELECT * FROM trade_plans;
```

## Struktur Database

### Tabel: `candles`
```
id, symbol, timeframe, timestamp, open, high, low, close, volume
```

### Tabel: `trade_plans`
```
id, created_at, symbol, side, entry, stop_loss, take_profit,
risk_reward, risk_amount, position_size, status,
risk_allowed, risk_reason, ai_verdict, ai_reason, ai_confidence, raw_payload
```

### Tabel: `trades`
```
id, trade_plan_id, opened_at, closed_at, symbol, side,
entry, exit, size, pnl, status, mode, okx_order_id
```

### Tabel: `daily_stats`
```
id, day, trades_count, realized_pnl, consecutive_loss
```

### Tabel: `logs`
```
id, created_at, level, message
```

## Troubleshooting

### ❌ API OKX Error
- Pastikan kredensial OKX sudah benar.
- Untuk demo, gunakan **OKX_DEMO_TRADING=true**.
- Cek koneksi internet.

### ❌ AI Review Tidak Berjalan
- Verifikasi `OPENROUTER_API_KEY` sudah benar.
- Cek balance OpenRouter (ada credit?).
- Fallback default: `watch` (tidak crash).

### ❌ Telegram Bot Tidak Kirim Pesan
- Pastikan `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` benar.
- Bot harus sudah aktif (chat dengannya terlebih dahulu).
- Cek logs: `docker compose logs -f agent | grep telegram`.

### ❌ Database Locked
- Stop container & hapus lock file (jarang terjadi).
- SQLite dengan timeout 30s sudah handling concurrency.

## Development Notes

- **Tech Stack**: FastAPI + APScheduler + SQLite + OpenRouter + Telegram.
- **Python Version**: 3.11+
- **Concurrency**: Async untuk scheduler & FastAPI, SQLite dengan timeout.
- **No external dependencies**: Redis, PostgreSQL, model lokal → minimal footprint.

## Production Deployment (VPS)

```bash
# 1. SSH ke VPS
ssh user@vps-ip

# 2. Clone repo
git clone <repo> btc-demo-agent && cd btc-demo-agent

# 3. Atur .env dengan kredensial production
cp .env.example .env
nano .env

# 4. Build & run
docker compose build
docker compose up -d

# 5. Monitor
docker compose logs -f agent

# 6. Atur restart otomatis
sudo systemctl enable docker
docker compose up -d  # dengan restart: unless-stopped
```

## Support & Kontribusi

- 📖 Baca kode & dokumentasi terlebih dahulu.
- 🐛 Report bug via issue.
- 🚀 PR untuk improvement selalu welcome.

---

**Made for Learning & Demo Trading. Not Financial Advice.**
