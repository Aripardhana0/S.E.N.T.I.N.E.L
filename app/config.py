"""Konfigurasi terpusat. Semua nilai diambil dari environment (.env).
Tidak ada secret yang di-hardcode di sini."""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("config")

def _get_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "on")

def _get_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        logger.warning("Nilai %s tidak valid, pakai default %s", key, default)
        return float(default)

def _get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        logger.warning("Nilai %s tidak valid, pakai default %s", key, default)
        return int(default)

class Config:
    # --- Mode aplikasi ---
    APP_ENV = os.getenv("APP_ENV", "demo")
    DRY_RUN = _get_bool("DRY_RUN", True)
    PAPER_TRADE = _get_bool("PAPER_TRADE", True)
    EXECUTION_ENABLED = _get_bool("EXECUTION_ENABLED", False)
    REQUIRE_MANUAL_APPROVAL = _get_bool("REQUIRE_MANUAL_APPROVAL", True)

    # --- Auto entry & Market Guard ---
    AUTO_ENTRY = _get_bool("AUTO_ENTRY", True)
    GUARD_ENABLED = _get_bool("GUARD_ENABLED", True)
    GUARD_ATR_SPIKE = _get_float("GUARD_ATR_SPIKE", 1.8)
    GUARD_VOL_SPIKE = _get_float("GUARD_VOL_SPIKE", 3.0)
    GUARD_RANGE_ATR = _get_float("GUARD_RANGE_ATR", 2.5)
    GUARD_MOVE_PCT = _get_float("GUARD_MOVE_PCT", 1.5)

    # --- Binance Futures Testnet ---
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
    BINANCE_DEMO_TRADING = _get_bool("BINANCE_DEMO_TRADING", True)
    BINANCE_BASE_URL = os.getenv(
        "BINANCE_BASE_URL", "https://testnet.binancefuture.com"
    )
    PRICE_PRECISION = _get_int("PRICE_PRECISION", 1)
    QTY_PRECISION = _get_int("QTY_PRECISION", 3)

    # --- OpenRouter ---
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Market / strategy ---
    SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
    TIMEFRAME_SIGNAL = os.getenv("TIMEFRAME_SIGNAL", "15m")
    TIMEFRAME_TREND = os.getenv("TIMEFRAME_TREND", "1h")

    # --- Risk ---
    INITIAL_EQUITY = _get_float("INITIAL_EQUITY", 5)
    MAX_RISK_PER_TRADE = _get_float("MAX_RISK_PER_TRADE", 0.01)
    MAX_DAILY_LOSS = _get_float("MAX_DAILY_LOSS", 0.03)
    MAX_TRADES_PER_DAY = _get_int("MAX_TRADES_PER_DAY", 3)
    MAX_CONSECUTIVE_LOSS = _get_int("MAX_CONSECUTIVE_LOSS", 2)
    MAX_LEVERAGE = _get_int("MAX_LEVERAGE", 2)
    MIN_RR = _get_float("MIN_RR", 1.5)

    # --- Database ---
    DB_PATH = os.getenv("DB_PATH", "data/trading.db")

    def has_binance_credentials(self) -> bool:
        return all([self.BINANCE_API_KEY, self.BINANCE_API_SECRET])

    def has_telegram(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)

    def has_openrouter(self) -> bool:
        return bool(self.OPENROUTER_API_KEY)

config = Config()
