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

    # --- OKX ---
    OKX_API_KEY = os.getenv("OKX_API_KEY", "")
    OKX_API_SECRET = os.getenv("OKX_API_SECRET", "")
    OKX_API_PASSPHRASE = os.getenv("OKX_API_PASSPHRASE", "")
    OKX_DEMO_TRADING = _get_bool("OKX_DEMO_TRADING", True)
    OKX_BASE_URL = "https://www.okx.com"

    # --- OpenRouter ---
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Market / strategy ---
    SYMBOL = os.getenv("SYMBOL", "BTC-USDT")
    TIMEFRAME_SIGNAL = os.getenv("TIMEFRAME_SIGNAL", "15m")
    TIMEFRAME_TREND = os.getenv("TIMEFRAME_TREND", "1H")

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

    def has_okx_credentials(self) -> bool:
        return all([self.OKX_API_KEY, self.OKX_API_SECRET, self.OKX_API_PASSPHRASE])

    def has_telegram(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)

    def has_openrouter(self) -> bool:
        return bool(self.OPENROUTER_API_KEY)

config = Config()
