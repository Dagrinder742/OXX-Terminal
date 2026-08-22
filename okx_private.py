import time
import hmac
import hashlib
import base64
import json
import requests
from secure_vault import EncryptedVault

class OKXPrivateClient:
    """Handles authenticated REST requests to OKX for order execution."""

    BASE_URL = "https://us.okx.com"

    @staticmethod
    def _get_timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S.320Z", time.gmtime())

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
    def place_order(cls, inst_id: str, side: str, order_type: str, sz: str, px: str = None) -> dict:
        creds = EncryptedVault.load_credentials()
        api_key = creds.get("api_key")
        secret_key = creds.get("secret_key")
        passphrase = creds.get("passphrase")

        if not api_key or not secret_key or not passphrase:
            return {"code": "1", "msg": "Missing credentials in secure vault."}

        endpoint = "/api/v5/trade/order"

        payload = {
            "instId": inst_id,
            "tdMode": "cash",
            "side": side,
            "ordType": order_type,
            "sz": str(sz)
        }

        if order_type == "limit" and px:
            payload["px"] = str(px)

        body_str = json.dumps(payload)
        timestamp = cls._get_timestamp()
        signature = cls._sign(timestamp, "POST", endpoint, body_str, secret_key)

        headers = {
            "OK-ACCESS-KEY": api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(cls.BASE_URL + endpoint, headers=headers, data=body_str, timeout=10)
            return response.json()
        except Exception as e:
            return {"code": "500", "msg": str(e)}

    @classmethod
    def get_account_balance(cls) -> dict:
        creds = EncryptedVault.load_credentials()
        api_key = creds.get("api_key")
        secret_key = creds.get("secret_key")
        passphrase = creds.get("passphrase")

        if not api_key:
            return {"code": "1", "msg": "Missing credentials."}

        endpoint = "/api/v5/account/balance"
        timestamp = cls._get_timestamp()
        signature = cls._sign(timestamp, "GET", endpoint, "", secret_key)

        headers = {
            "OK-ACCESS-KEY": api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(cls.BASE_URL + endpoint, headers=headers, timeout=10)
            return response.json()
        except Exception as e:
            return {"code": "500", "msg": str(e)}
