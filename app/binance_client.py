"""Client for Binance USD-M Futures Testnet/Demo."""
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import httpx

from app.config import config

logger = logging.getLogger("binance_client")


class BinanceClient:
    def __init__(self):
        self.base_url = config.BINANCE_BASE_URL
        self.timeout = httpx.Timeout(10.0)

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": config.BINANCE_API_KEY}

    def _signed_query(self, params: dict) -> str:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query = urlencode(params)
        signature = hmac.new(
            config.BINANCE_API_SECRET.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={signature}"

    def round_price(self, price: float) -> float:
        return round(float(price), config.PRICE_PRECISION)

    def round_qty(self, qty: float) -> float:
        return round(float(qty), config.QTY_PRECISION)

    def get_ticker(self, symbol: str) -> dict | None:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.base_url}/fapi/v1/ticker/price",
                    params={"symbol": symbol},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("get_ticker failed: %s", exc)
            return None

    def get_candles(self, symbol: str, interval: str = "15m", limit: int = 200) -> list:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.base_url}/fapi/v1/klines",
                    params={"symbol": symbol, "interval": interval, "limit": limit},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("get_candles failed (%s %s): %s", symbol, interval, exc)
            return []

    def get_balance(self) -> list | None:
        if not config.has_binance_credentials():
            return None
        query = self._signed_query({})
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.base_url}/fapi/v2/balance?{query}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("get_balance failed: %s", exc)
            return None

    def set_leverage(self, symbol: str, leverage: int) -> dict | None:
        if not config.has_binance_credentials():
            return None
        query = self._signed_query({"symbol": symbol, "leverage": int(leverage)})
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/fapi/v1/leverage?{query}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("set_leverage failed: %s", exc)
            return None

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        reduce_only: bool = False,
    ) -> dict | None:
        if not config.has_binance_credentials():
            logger.warning("Binance credentials are empty; order canceled.")
            return None
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": self.round_qty(quantity),
            "price": self.round_price(price),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        query = self._signed_query(params)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/fapi/v1/order?{query}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("place_limit_order failed: %s", exc)
            return None

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        reduce_only: bool = False,
    ) -> dict | None:
        if not config.has_binance_credentials():
            logger.warning("Binance credentials are empty; market order canceled.")
            return None
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": self.round_qty(quantity),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        query = self._signed_query(params)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/fapi/v1/order?{query}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("place_market_order failed: %s", exc)
            return None

    def get_order(self, symbol: str, order_id: str | int) -> dict | None:
        if not config.has_binance_credentials():
            return None
        query = self._signed_query({"symbol": symbol, "orderId": order_id})
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.base_url}/fapi/v1/order?{query}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("get_order failed: %s", exc)
            return None

    def get_open_orders(self, symbol: str) -> list:
        if not config.has_binance_credentials():
            return []
        query = self._signed_query({"symbol": symbol})
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.base_url}/fapi/v1/openOrders?{query}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("get_open_orders failed: %s", exc)
            return []

    def get_position_risk(self, symbol: str | None = None) -> list:
        if not config.has_binance_credentials():
            return []
        params = {}
        if symbol:
            params["symbol"] = symbol
        query = self._signed_query(params)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.base_url}/fapi/v2/positionRisk?{query}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, list) else [data]
        except Exception as exc:
            logger.error("get_position_risk failed: %s", exc)
            return []

    def cancel_order(self, symbol: str, order_id: str | int) -> dict | None:
        if not config.has_binance_credentials():
            return None
        query = self._signed_query({"symbol": symbol, "orderId": order_id})
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.delete(
                    f"{self.base_url}/fapi/v1/order?{query}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("cancel_order failed: %s", exc)
            return None

    def cancel_all_open_orders(self, symbol: str) -> dict | None:
        if not config.has_binance_credentials():
            return None
        query = self._signed_query({"symbol": symbol})
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.delete(
                    f"{self.base_url}/fapi/v1/allOpenOrders?{query}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("cancel_all_open_orders failed: %s", exc)
            return None


binance_client = BinanceClient()
