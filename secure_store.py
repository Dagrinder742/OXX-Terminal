import keyring
import logging

SERVICE_NAME = "OKX_Terminal_Suite"

class SecureCredentialStore:
    @staticmethod
    def save_credentials(api_key: str, secret_key: str, passphrase: str) -> None:
        """Stores credentials securely in the OS native credential vault."""
        keyring.set_password(SERVICE_NAME, "api_key", api_key)
        keyring.set_password(SERVICE_NAME, "secret_key", secret_key)
        keyring.set_password(SERVICE_NAME, "passphrase", passphrase)
        print("[SECURE] Credentials successfully stored in OS Vault.")

    @staticmethod
    def load_credentials() -> dict:
        """Retrieves credentials from the OS vault dynamically at runtime."""
        return {
            "api_key": keyring.get_password(SERVICE_NAME, "api_key"),
            "secret_key": keyring.get_password(SERVICE_NAME, "secret_key"),
            "passphrase": keyring.get_password(SERVICE_NAME, "passphrase")
        }

    @staticmethod
    def clear_credentials() -> None:
        """Wipes credentials from the OS vault."""
        try:
            keyring.delete_password(SERVICE_NAME, "api_key")
            keyring.delete_password(SERVICE_NAME, "secret_key")
            keyring.delete_password(SERVICE_NAME, "passphrase")
            print("[SECURE] Credentials wiped from system vault.")
        except Exception as e:  # keyring can throw various exceptions if a key isn't found
            logging.warning(f"Could not clear credentials from OS vault: {e}")
