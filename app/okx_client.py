"""Client tipis untuk OKX REST API.
- Market data publik tidak butuh kredensial.
- Order (demo) butuh kredensial + header x-simulated-trading: 1.
Semua error ditangani agar tidak meng-crash aplikasi."""
import hmac
import base64
import hashlib
import json
import logging
from datetime import datetime, timezone

import httpx

from app.config import config

logger = logging.getLogger("okx_client")

class OKXClient:
    def __init__(self):
        self.base_url = config.OKX_BASE_URL
        self.timeout = httpx.Timeout(10.0)

    # ---------- util signing ----------
    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def _sign(self, ts: str, method: str, path: str, body: str) -> str:
        msg = f"{ts}{method}{path}{body}"
        mac = hmac.new(
            config.OKX_API_SECRET.encode(), msg.encode(), hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()

    def _auth_headers(self, method: str, path: str, body: str = "") -> dict:
        ts = self._timestamp()
        headers = {
            "OK-ACCESS-KEY": config.OKX_API_KEY,
            "OK-ACCESS-SIGN": self._sign(ts, method, path, body),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": config.OKX_API_PASSPHRASE,
            "Content-Type": "application/json",
        }
        # Header WAJIB untuk demo trading OKX.
        if config.OKX_DEMO_TRADING:
            headers["x-simulated-trading"] = "1"
        return headers

    # ---------- market data publik ----------
    def get_ticker(self, symbol: str) -> dict | None:
        path = f"/api/v5/market/ticker?instId={symbol}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(self.base_url + path)
                r.raise_for_status()
                data = r.json().get("data", [])
                return data[0] if data else None
        except Exception as e:
            logger.error("get_ticker gagal: %s", e)
            return None

    def get_candles(self, symbol: str, bar: str = "15m", limit: int = 200) -> list:
        """Kembalikan list candle [ts, o, h, l, c, vol]. List kosong jika gagal."""
        path = f"/api/v5/market/candles?instId={symbol}&bar={bar}&limit={limit}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(self.base_url + path)
                r.raise_for_status()
                rows = r.json().get("data", [])
                # OKX mengembalikan urutan terbaru -> terlama; balik agar kronologis.
                return list(reversed(rows))
        except Exception as e:
            logger.error("get_candles gagal (%s %s): %s", symbol, bar, e)
            return []

    def get_balance(self) -> dict | None:
        if not config.has_okx_credentials():
            return None
        path = "/api/v5/account/balance"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(
                    self.base_url + path, headers=self._auth_headers("GET", path)
                )
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.error("get_balance gagal: %s", e)
            return None

    # ---------- order (demo) ----------
    def place_order(self, symbol: str, side: str, size: float,
                    ord_type: str = "market") -> dict | None:
        """Kirim order ke OKX (demo bila OKX_DEMO_TRADING=true).
        side: 'buy' atau 'sell'. Untuk SHORT pakai 'sell'."""
        if not config.has_okx_credentials():
            logger.warning("Kredensial OKX kosong, order dibatalkan.")
            return None
        path = "/api/v5/trade/order"
        payload = {
            "instId": symbol,
            "tdMode": "isolated",
            "side": side,
            "ordType": ord_type,
            "sz": str(size),
        }
        body = json.dumps(payload)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(
                    self.base_url + path,
                    headers=self._auth_headers("POST", path, body),
                    content=body,
                )
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.error("place_order gagal: %s", e)
            return None

okx_client = OKXClient()
