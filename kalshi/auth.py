# kalshi/auth.py
import datetime
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature

def load_private_key_from_file(file_path: str) -> rsa.RSAPrivateKey:
    """Loads an RSA private key from a PEM file."""
    with open(file_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )
    return private_key

def sign_pss_text(private_key: rsa.RSAPrivateKey, text: str) -> str:
    """Signs text using RSA-PSS and SHA-256, returning base64 encoded signature."""
    message = text.encode('utf-8')
    try:
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    except InvalidSignature as e:
        raise ValueError("RSA sign PSS failed") from e

def get_auth_headers(api_key_id: str, private_key: rsa.RSAPrivateKey, method: str, path: str) -> dict:
    """Generates the required Kalshi authentication headers."""
    current_time_milliseconds = int(datetime.datetime.now().timestamp() * 1000)
    timestamp_str = str(current_time_milliseconds)

    # Strip query parameters from path before signing[cite: 5]
    path_without_query = path.split('?')[0]
    msg_string = timestamp_str + method.upper() + path_without_query
    sig = sign_pss_text(private_key, msg_string)

    return {
        'KALSHI-ACCESS-KEY': api_key_id,
        'KALSHI-ACCESS-SIGNATURE': sig,
        'KALSHI-ACCESS-TIMESTAMP': timestamp_str
    }
