"""Tests for secure_vault.py with the real keyring REPLACED by an in-memory fake and HOME pointed at a
temp folder -- nothing here touches your real vault, key file or account.

Run:  python test_secure_vault.py
Proves the vault's own logic (one read per load, migration, permissions, fail-closed key file).
Does NOT prove the real CryptFileKeyring behaves like the fake -- see the timing check in the notes.
"""
import json
import logging
import os
import stat
import sys
import tempfile
import threading
import types

STORE = {}
class FakeKR:
    reads = writes = 0
    fail_set = False
    def __init__(self): self.keyring_key = None
    def get_password(self, s, k): FakeKR.reads += 1; return STORE.get((s, k))
    def set_password(self, s, k, v):
        if FakeKR.fail_set: raise OSError("disk full")
        FakeKR.writes += 1; STORE[(s, k)] = v
    def delete_password(self, s, k):
        if (s, k) not in STORE: raise KeyError("no such entry")
        del STORE[(s, k)]

for name in ("keyrings", "keyrings.cryptfile", "keyrings.cryptfile.cryptfile"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["keyrings.cryptfile.cryptfile"].CryptFileKeyring = FakeKR

import secure_vault as SV                                     # noqa: E402
V, S = SV.EncryptedVault, SV.SERVICE_NAME
CREDS = {"api_key": "KEY-123", "secret_key": "SECRET-456", "passphrase": "PASS-789"}

PASSED, FAILED = 0, []
def check(name, cond, detail=""):
    global PASSED
    if cond: PASSED += 1; print(f"  ok    {name}")
    else: FAILED.append(name); print(f"  FAIL  {name}  {detail}")

def fresh():
    STORE.clear(); FakeKR.reads = FakeKR.writes = 0; FakeKR.fail_set = False
    home = tempfile.mkdtemp(); os.environ["HOME"] = home
    return home

# capture every log record so we can prove secrets are never logged
records = []
class _H(logging.Handler):
    def emit(self, r): records.append(r.getMessage())
logging.getLogger().addHandler(_H()); logging.getLogger().setLevel(logging.DEBUG)

print("master key file")
home = fresh()
kr = V._get_configured_keyring()
kp = os.path.join(home, ".local/share/python_keyring/okx_tuid_master.key")
check("created on first use with 64 hex chars", os.path.exists(kp) and len(open(kp).read()) == 64)
check("key file is 0600", stat.S_IMODE(os.stat(kp).st_mode) == 0o600, oct(os.stat(kp).st_mode))
check("key folder is 0700", stat.S_IMODE(os.stat(os.path.dirname(kp)).st_mode) == 0o700)
check("keyring is given exactly the file's key", kr.keyring_key == open(kp).read().strip())
check("an existing key is reused, never regenerated", V._get_configured_keyring().keyring_key == kr.keyring_key)
open(kp, "w").write("")
try: V._get_configured_keyring(); ok = False
except RuntimeError: ok = True
check("an EMPTY key file fails closed instead of using a blank key", ok)

home = fresh(); keys = []
def grab(): keys.append(V._get_configured_keyring().keyring_key)
ths = [threading.Thread(target=grab) for _ in range(12)]
[t.start() for t in ths]; [t.join() for t in ths]
check("12 threads racing on first start all get the SAME key", len(keys) == 12 and len(set(keys)) == 1, set(keys))

print("save / load (new format)")
fresh()
V.save_credentials(**CREDS)
check("round trip", V.load_credentials() == CREDS)
FakeKR.reads = 0; V.load_credentials()
check("a load costs exactly ONE keyring read (was 3)", FakeKR.reads == 1, FakeKR.reads)
check("stored as one entry", (S, SV.BLOB_NAME) in STORE and not any(k[1] in SV.FIELDS for k in STORE))
FakeKR.fail_set = False
orig = FakeKR.get_password
FakeKR.get_password = lambda self, s, k: "something else" if k == SV.BLOB_NAME else orig(self, s, k)
try: V.save_credentials(**CREDS); ok = False
except RuntimeError: ok = True
FakeKR.get_password = orig
check("a save that does not read back correctly raises", ok)

print("migration from the old 3-entry format")
fresh()
for k, v in CREDS.items(): STORE[(S, k)] = v
FakeKR.reads = 0
check("old install loads correctly", V.load_credentials() == CREDS)
check("... and was migrated to the single entry", json.loads(STORE[(S, SV.BLOB_NAME)]) == CREDS)
check("... old entries are left in place (rollback-safe)", all((S, k) in STORE for k in SV.FIELDS))
FakeKR.reads = 0; V.load_credentials()
check("second load is one read", FakeKR.reads == 1, FakeKR.reads)
fresh(); STORE[(S, "api_key")] = "K"; STORE[(S, "secret_key")] = "S"
res = V.load_credentials()
check("partial old data returns what exists and does NOT migrate", res["passphrase"] is None and (S, SV.BLOB_NAME) not in STORE, res)
fresh()
check("empty vault returns all None", V.load_credentials() == {k: None for k in SV.FIELDS})
fresh()
for k, v in CREDS.items(): STORE[(S, k)] = v
FakeKR.fail_set = True
check("a failing migration still returns the credentials", V.load_credentials() == CREDS)
fresh(); STORE[(S, SV.BLOB_NAME)] = "{not json"
for k, v in CREDS.items(): STORE[(S, k)] = v
check("a corrupt single entry falls back to the old entries", V.load_credentials() == CREDS)

print("purge old entries")
fresh()
for k, v in CREDS.items(): STORE[(S, k)] = v
try: V.purge_legacy_entries(); ok = False
except RuntimeError: ok = True
check("refuses to delete old entries before the new one exists", ok and all((S, k) in STORE for k in SV.FIELDS))
V.load_credentials()
check("after migration it removes all 3", V.purge_legacy_entries() == 3 and V.load_credentials() == CREDS)

print("logging")
secrets = list(CREDS.values())
check("no secret value appears in any log line", not any(s in line for s in secrets for line in records), [l for l in records if any(s in l for s in secrets)])

print(f"\n{PASSED} passed, {len(FAILED)} failed")
if FAILED: print("FAILED:", *FAILED, sep="\n  - "); sys.exit(1)
