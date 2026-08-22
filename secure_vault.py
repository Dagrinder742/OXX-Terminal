import os
import logging
from keyrings.cryptfile.cryptfile import CryptFileKeyring

SERVICE_NAME = "OKX_Terminal_Suite"

class EncryptedVault:
    """Manages cross-platform encrypted keyring storage using AES-GCM encryption."""

    @staticmethod
    def _get_configured_keyring() -> CryptFileKeyring:
        kr = CryptFileKeyring()
        # Bind the master key locally to avoid headless prompt locks while maintaining encryption
        key_path = os.path.expanduser("~/.local/share/python_keyring/okx_tuid_master.key")
        os.makedirs(os.path.dirname(key_path), exist_ok=True)

        if os.path.exists(key_path):
            with open(key_path, "r", encoding="utf-8") as f:
                kr.keyring_key = f.read().strip()
        else:
            # Generate a secure internal master key on first initialization
            master_key = os.urandom(32).hex()
            with open(key_path, "w", encoding="utf-8") as f:
                f.write(master_key)
            kr.keyring_key = master_key

        # Always ensure permissions are locked down securely
        try:
            os.chmod(key_path, 0o600)
        except Exception as e:
            logging.warning(f"Could not secure file permissions on {key_path}: {e}")

        return kr

    @classmethod
    def save_credentials(cls, api_key: str, secret_key: str, passphrase: str) -> None:
        kr = cls._get_configured_keyring()
        kr.set_password(SERVICE_NAME, "api_key", api_key)
        kr.set_password(SERVICE_NAME, "secret_key", secret_key)
        kr.set_password(SERVICE_NAME, "passphrase", passphrase)

    @classmethod
    def load_credentials(cls) -> dict:
        kr = cls._get_configured_keyring()
        return {
            "api_key": kr.get_password(SERVICE_NAME, "api_key"),
            "secret_key": kr.get_password(SERVICE_NAME, "secret_key"),
            "passphrase": kr.get_password(SERVICE_NAME, "passphrase")
        }

