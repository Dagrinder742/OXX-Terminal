"""check_vault.py -- READ-ONLY audit of where your API credentials live and whether they are protected.

Prints sizes, file names and PASS/FAIL lines.  It NEVER prints a stored value.
Run it from the project folder:   python check_vault.py

What it checks
  1. The decisive test: can your CURRENT credentials be recovered from each file by decoding alone
     (as-is, base64, base64url, hex, and inside nested base64/JSON layers) -- i.e. WITHOUT the key?
  2. A lock test: the real master key opens the vault, a WRONG key is refused.
  3. File permissions on the key folder and files.
  4. Which of your other scripts use the keyring (they may depend on the old per-field entries).

Note: "readable text after one base64 decode" alone does NOT mean unencrypted -- some encrypted
formats wrap ciphertext in a text envelope.  That is shown as information only; test 1 decides.
"""
import base64
import configparser
import glob
import json
import os
import re
import stat
import string
import sys

KEY_DIR = os.path.expanduser("~/.local/share/python_keyring")
SERVICE = "OKX_Terminal_Suite"
BLOB = "credentials_v2"
# The live vault and its key.  These are NEVER leftovers; deleting them destroys your credentials.
LIVE_FILES = {"cryptfile_pass.cfg", "okx_tuid_master.key"}
PRINTABLE = set(string.printable)


def mode(path):
    return oct(stat.S_IMODE(os.stat(path).st_mode))


def ini_values(path):
    cp = configparser.RawConfigParser()
    cp.optionxform = str
    try:
        cp.read(path, encoding="utf-8")
    except configparser.Error:
        return []
    return [(sec, key, "".join(val.split())) for sec in cp.sections() for key, val in cp.items(sec) if val.strip()]


def strings_in(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings_in(v)


def layers(chunk, max_items=3000):
    """Yields the chunk and everything reachable by base64-decoding or reading JSON string fields."""
    stack = [(chunk, 0)]
    seen = 0
    while stack and seen < max_items:
        data, depth = stack.pop()
        seen += 1
        yield data
        if depth >= 3:
            continue
        try:
            stack.append((base64.b64decode(b"".join(data.split()), validate=True), depth + 1))
        except Exception:
            pass
        try:
            obj = json.loads(data.decode("utf-8"))
        except Exception:
            obj = None
        if obj is not None:
            for s in strings_in(obj):
                stack.append((s.encode("utf-8"), depth + 1))


def needles(secret):
    raw = secret.encode("utf-8")
    return {"as-is": raw, "base64": base64.b64encode(raw), "base64url": base64.urlsafe_b64encode(raw),
            "hex": raw.hex().encode()}


def recoverable(path, secrets):
    """{field_name: sorted forms} for every current credential findable in the file without a key."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return {}
    chunks = [raw] + [v.encode("utf-8") for _, _, v in ini_values(path)]
    found = {}
    for chunk in chunks:
        for layer in layers(chunk):
            for name, secret in secrets.items():
                for form, needle in needles(secret).items():
                    if needle in layer:
                        found.setdefault(name, set()).add(form)
    return {k: sorted(v) for k, v in found.items()}


def text_like(path):
    """Info only: how many values decode (one base64 step) to readable text."""
    n = 0
    for _, _, v in ini_values(path):
        try:
            raw = base64.b64decode(v, validate=True)
        except Exception:
            continue
        if len(raw) >= 8 and sum(chr(b) in PRINTABLE for b in raw) / len(raw) >= 0.95:
            n += 1
    return n


def load_live_secrets():
    try:
        from secure_vault import EncryptedVault
        creds = EncryptedVault.load_credentials() or {}
    except Exception as e:
        print(f"   could not read your vault ({type(e).__name__}); cannot run the recovery test")
        return {}
    return {k: v for k, v in creds.items() if isinstance(v, str) and len(v) >= 8}


def audit_files():
    print("1) Can your CURRENT credentials be recovered from each file WITHOUT the key?")
    leftovers = []
    if not os.path.isdir(KEY_DIR):
        print(f"   folder not found: {KEY_DIR}")
        return leftovers
    secrets = load_live_secrets()
    if not secrets:
        return leftovers
    print(f"   (testing {', '.join(sorted(secrets))}; values are never printed)")
    for path in sorted(glob.glob(os.path.join(KEY_DIR, "*"))):
        if not os.path.isfile(path):
            continue
        name = os.path.basename(path)
        tag = "  [LIVE VAULT - keep]" if name in LIVE_FILES else ""
        print(f"  {name}  ({os.path.getsize(path)} bytes, mode {mode(path)}){tag}")
        found = recoverable(path, secrets)
        if found:
            fields = ", ".join(f"{k} ({'/'.join(v)})" for k, v in sorted(found.items()))
            print(f"    -> FAIL: recoverable without the key: {fields}")
            if name not in LIVE_FILES:
                leftovers.append(path)
        else:
            print("    -> PASS: none of your current credentials can be recovered from this file by decoding")
        n = text_like(path)
        if n:
            extra = "" if found else " (not your current credentials, or a text envelope around ciphertext)"
            print(f"       info: {n} value(s) decode to readable text{extra}")
            if not found and name not in LIVE_FILES:
                leftovers.append(path)
    return leftovers


def lock_test():
    print("2) Lock test (right key opens it, wrong key is refused)")
    try:
        from secure_vault import EncryptedVault
        from keyrings.cryptfile.cryptfile import CryptFileKeyring
    except Exception as e:
        print(f"   skipped: could not import the vault ({type(e).__name__})")
        return
    try:
        kr = EncryptedVault._get_configured_keyring()
        has_entry = bool(kr.get_password(SERVICE, BLOB))
        print(f"   right key opens the vault: {'yes' if has_entry else 'no single-entry credentials found (not migrated yet?)'}")
    except Exception as e:
        print(f"   right key: FAILED to open ({type(e).__name__})")
        return
    try:
        bad = CryptFileKeyring()
        bad.keyring_key = "definitely-not-the-key"
        value = bad.get_password(SERVICE, BLOB)
    except Exception as e:
        print(f"   -> PASS: a wrong key is rejected ({type(e).__name__})")
        return
    if value:
        print("   -> FAIL: a WRONG key still returned data, so the file is not protected by the key")
    else:
        print("   -> INCONCLUSIVE: a wrong key returned nothing (no exception, no data)")


def audit_permissions():
    print("3) Permissions")
    problems = 0
    if os.path.isdir(KEY_DIR):
        m = stat.S_IMODE(os.stat(KEY_DIR).st_mode)
        print(f"   folder {mode(KEY_DIR)}  {'ok' if m & 0o077 == 0 else 'WARNING: group/others can enter'}")
        problems += (m & 0o077) != 0
        for path in glob.glob(os.path.join(KEY_DIR, "*")):
            if os.path.isfile(path) and stat.S_IMODE(os.stat(path).st_mode) & 0o077:
                print(f"   WARNING: {os.path.basename(path)} is {mode(path)} (should be 0o600)")
                problems += 1
    if not problems:
        print("   all private to your user")


def scan_code():
    print("4) Scripts that use the keyring directly (they may rely on the OLD per-field entries)")
    pattern = re.compile(r"\bimport keyring\b|\bfrom keyring\b|\bkeyring\.(get|set|delete)_password")
    here = os.path.dirname(os.path.abspath(__file__))
    home = os.path.expanduser("~")
    paths = set(glob.glob(os.path.join(here, "*.py")) + glob.glob(os.path.join(home, "*.py")))
    paths |= set(glob.glob(os.path.join(home, "*", "*.py")) + glob.glob(os.path.join(here, "..", "*.py")))
    hits = {}
    for path in sorted(paths):
        base = os.path.basename(path)
        if base == "check_vault.py" or base.startswith("test_"):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                n = sum(1 for line in f if pattern.search(line))
        except OSError:
            continue
        if n:
            hits[os.path.normpath(path)] = n
    for path, n in hits.items():
        print(f"   {path.replace(home, '~')}  ({n} line{'s' if n != 1 else ''})")
    if not hits:
        print("   none found")


if __name__ == "__main__":
    leftovers = audit_files()
    lock_test()
    audit_permissions()
    scan_code()
    print()
    print("KEEP (do not delete): cryptfile_pass.cfg and okx_tuid_master.key are your live vault and its key.")
    if leftovers:
        print("POSSIBLE LEFTOVERS (this app does not read them):")
        for p in leftovers:
            print(f"   {p}")
        print("   Other scripts may still use them: check section 4 before deleting anything.")
    sys.exit(0)
