import base64
import datetime
import hmac

class OKXAuth:
    """Handles official OKX v5 REST API authentication and header signing."""
    def __init__(self, api_key: str, secret_key: str, passphrase: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase

    def _get_timestamp(self) -> str:
        """Generates ISO 8601 UTC timestamp with millisecond precision required by OKX."""
        now = datetime.datetime.now(datetime.timezone.utc)
        return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def sign_request(self, method: str, request_path: str, body: str = "") -> dict:
        """
        Computes the HMAC-SHA256 signature and returns the required authentication headers.
        """
        timestamp = self._get_timestamp()

        # Pre-hash string: timestamp + method (UPPERCASE) + requestPath + body
        message = timestamp + method.upper() + request_path + body

        # Compute HMAC-SHA256 signature and encode as Base64
        mac = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            digestmod="sha256"
        )
        signature = base64.b64encode(mac.digest()).decode("utf-8")

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

        return headers

