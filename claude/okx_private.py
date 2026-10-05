import hmac
import hashlib
import base64
import json
import requests
import logging
from datetime import datetime, timezone
from secure_vault import EncryptedVault


class OKXPrivateClient:
    """Handles authenticated REST requests to OKX for order execution.

    Every public method returns the exchange's JSON dict.  Network / signing / credential
    problems never raise: they come back as {"code": "500"|"1", "msg": ...} so a bad
    request can't crash the UI.
    """

    BASE_URL = "https://us.okx.com"

    @staticmethod
    def _get_timestamp() -> str:
        # ISO 8601 UTC with real milliseconds, e.g. 2026-10-04T22:45:08.364Z
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    @classmethod
    def _sign(cls, timestamp: str, method: str, request_path: str, body: str, secret_key: str) -> str:
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(
            secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    @classmethod
    def _request(cls, method: str, path: str, payload: dict = None, timeout: int = 10) -> dict:
        """Signs and sends one request. `path` includes any query string (it is part of the signature)."""
        try:
            creds = EncryptedVault.load_credentials()
            api_key = creds.get("api_key")
            secret_key = creds.get("secret_key")
            passphrase = creds.get("passphrase")
            if not api_key or not secret_key or not passphrase:
                return {"code": "1", "msg": "Missing credentials in secure vault."}

            body_str = json.dumps(payload) if payload is not None else ""
            timestamp = cls._get_timestamp()
            signature = cls._sign(timestamp, method, path, body_str, secret_key)
            headers = {
                "OK-ACCESS-KEY": api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
            }

            if method.upper() == "POST":
                response = requests.post(cls.BASE_URL + path, headers=headers, data=body_str, timeout=timeout)
            else:
                response = requests.get(cls.BASE_URL + path, headers=headers, timeout=timeout)
            return response.json()
        except Exception as e:
            logging.error(f"API {method} {path} critical failure: {e}", exc_info=True)
            return {"code": "500", "msg": str(e)}

    @classmethod
    def place_order(cls, inst_id: str, side: str, order_type: str, sz: str, px: str = None, tp_trigger_px: str = None, sl_trigger_px: str = None) -> dict:
        payload = {
            "instId": inst_id,
            "tdMode": "cash",
            "side": side,
            "ordType": order_type,
            "sz": str(sz)
        }

        if order_type == "market":
            # Spot market orders: without tgtCcy a BUY's `sz` is read as QUOTE currency
            # (USDT).  The UI's Amount field is in BASE units, so say so explicitly.
            payload["tgtCcy"] = "base_ccy"

        if order_type == "limit" and px:
            payload["px"] = str(px)

        # Attach Advanced TP/SL if provided.
        # NOTE: unverified against the current OKX docs -- newer API versions may expect these
        # inside "attachAlgoOrds".  Confirm with the smallest possible order before relying on it.
        if tp_trigger_px:
            payload["tpTriggerPx"] = str(tp_trigger_px)
            payload["tpOrdPx"] = "-1"  # Market order execution upon TP trigger
        if sl_trigger_px:
            payload["slTriggerPx"] = str(sl_trigger_px)
            payload["slOrdPx"] = "-1"  # Market order execution upon SL trigger

        return cls._request("POST", "/api/v5/trade/order", payload)

    @classmethod
    def get_pending_orders(cls) -> dict:
        return cls._request("GET", "/api/v5/trade/orders-pending")

    @classmethod
    def get_positions(cls) -> dict:
        return cls._request("GET", "/api/v5/account/positions")

    @classmethod
    def get_account_balance(cls) -> dict:
        return cls._request("GET", "/api/v5/account/balance")

    @classmethod
    def get_fill_history(cls, inst_id=None, limit=20):
        """Retrieves recent trade fill history from OKX (last 3 days)."""
        # Always include instType=SPOT for stability on US endpoints
        path = f"/api/v5/trade/fills?instType=SPOT&limit={limit}"
        if inst_id:
            path += f"&instId={inst_id}"
        return cls._request("GET", path)

    @classmethod
    def get_trade_fee(cls, inst_type: str = "SPOT") -> dict:
        """Queries the exact maker/taker fee rates for the authenticated account."""
        return cls._request("GET", f"/api/v5/account/trade-fee?instType={inst_type}")
