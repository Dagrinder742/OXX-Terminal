import json
import logging
import os
import threading

from keyrings.cryptfile.cryptfile import CryptFileKeyring

SERVICE_NAME = "OKX_Terminal_Suite"

# Every keyring read costs ~1.5 s on a phone (measured), so all three values live in ONE entry:
# a load is then 1 read instead of 3.  The old per-field entries are still read once to migrate
# an existing install, and are left untouched (see purge_legacy_entries).
BLOB_NAME = "credentials_v2"
FIELDS = ("api_key", "secret_key", "passphrase")

_KEY_LOCK = threading.Lock()


def _key_path() -> str:
    return os.path.expanduser("~/.local/share/python_keyring/okx_tuid_master.key")


class EncryptedVault:
    """Manages cross-platform encrypted keyring storage using AES-GCM encryption.

    Security note: the master key file sits next to the encrypted file, so this protects against
    casual exposure (git, logs, screenshots, copied files) -- not against anything that can read
    your home folder as your user.  File permissions are what protect the master key.
    """

    @staticmethod
    def _read_master_key() -> str:
        key_path = _key_path()
        key_dir = os.path.dirname(key_path)
        os.makedirs(key_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(key_dir, 0o700)
        except OSError as e:
            logging.warning(f"Could not restrict permissions on {key_dir}: {e}")

        with _KEY_LOCK:
            try:
                # 0600 from the first byte (no window where it is readable by others), and O_EXCL
                # so two threads/processes can never both create it with different keys.
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(os.urandom(32).hex())
            with open(key_path, "r", encoding="utf-8") as f:
                master_key = f.read().strip()

        if not master_key:
            # Fail closed: an empty key would silently encrypt/decrypt with the wrong key.
            raise RuntimeError(f"Vault master key file is empty: {key_path}")

        try:
            os.chmod(key_path, 0o600)
        except OSError as e:
            logging.warning(f"Could not secure file permissions on {key_path}: {e}")
        return master_key

    @classmethod
    def _get_configured_keyring(cls) -> CryptFileKeyring:
        kr = CryptFileKeyring()
        # Bind the master key locally to avoid headless prompt locks while maintaining encryption
        kr.keyring_key = cls._read_master_key()
        return kr

    @classmethod
    def save_credentials(cls, api_key: str, secret_key: str, passphrase: str) -> None:
        kr = cls._get_configured_keyring()
        blob = json.dumps({"api_key": api_key, "secret_key": secret_key, "passphrase": passphrase})
        kr.set_password(SERVICE_NAME, BLOB_NAME, blob)
        # Read it back: a save that silently didn't stick is worse than an error.
        if kr.get_password(SERVICE_NAME, BLOB_NAME) != blob:
            raise RuntimeError("Vault write could not be verified; credentials were not saved.")

    @classmethod
    def load_credentials(cls) -> dict:
        kr = cls._get_configured_keyring()

        blob = kr.get_password(SERVICE_NAME, BLOB_NAME)
        if blob:
            try:
                data = json.loads(blob)
                return {name: data.get(name) for name in FIELDS}
            except (ValueError, AttributeError) as e:
                logging.error(f"Vault entry {BLOB_NAME} is unreadable ({type(e).__name__}); trying old format.")

        # Old format (three separate entries): read it, then migrate once.
        creds = {name: kr.get_password(SERVICE_NAME, name) for name in FIELDS}
        if all(creds.values()):
            cls._migrate(kr, creds)
        return creds

    @staticmethod
    def _migrate(kr, creds: dict) -> None:
        """Copies old-format credentials into the single entry.  Never raises: a failed migration
        must not stop the app from starting with the credentials it just read."""
        try:
            blob = json.dumps({name: creds[name] for name in FIELDS})
            kr.set_password(SERVICE_NAME, BLOB_NAME, blob)
            if kr.get_password(SERVICE_NAME, BLOB_NAME) == blob:
                logging.info("Vault migrated to single-entry format (old entries left in place).")
            else:
                logging.warning("Vault migration could not be verified; will retry next start.")
        except Exception as e:
            logging.warning(f"Vault migration skipped: {type(e).__name__}: {e}")

    @classmethod
    def purge_legacy_entries(cls) -> int:
        """Deletes the old per-field entries.  Run once you have confirmed the app starts with the
        new format.  Returns how many were removed."""
        kr = cls._get_configured_keyring()
        if not kr.get_password(SERVICE_NAME, BLOB_NAME):
            raise RuntimeError("No single-entry credentials found; refusing to delete the old entries.")
        removed = 0
        for name in FIELDS:
            try:
                kr.delete_password(SERVICE_NAME, name)
                removed += 1
            except Exception as e:
                logging.info(f"Old vault entry {name} not removed: {type(e).__name__}")
        return removed
