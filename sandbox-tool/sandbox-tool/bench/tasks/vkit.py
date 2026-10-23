"""Tiny shared helpers for the task verifiers. Trusted code: it is NOT part of the sandbox.

A verifier judges the FILE the model wrote, never what the model said about it.
Usage of every verifier:  python -I verify.py <path-to-output-file>
Last line is always:      VERIFY: PASS (n/n)   or   VERIFY: FAIL (k/n)
"""
import contextlib
import importlib.util
import io
import os
import signal
import subprocess
import sys
import tempfile


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout("took longer than 10 seconds")


if hasattr(signal, "SIGALRM"):
    signal.signal(signal.SIGALRM, _alarm)


class Checker:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.results = []
        self.mod = None
        self.loaded = False

    def check(self, name, fn):
        """Run fn(); an exception (AssertionError included) is a FAIL with its message."""
        try:
            if hasattr(signal, "alarm"):
                signal.alarm(10)
            detail = fn()
            self.results.append((True, name, detail or ""))
        except BaseException as e:  # noqa: BLE001  (SystemExit from model code counts as a fail)
            self.results.append((False, name, f"{type(e).__name__}: {e}"[:220]))
        finally:
            if hasattr(signal, "alarm"):
                signal.alarm(0)

    def load(self, label="file imports without error"):
        """Import the output file (stdout hidden). Later checks use self.mod; skipped if this failed."""
        if not os.path.isfile(self.path):
            self.results.append((False, "output file exists", f"not found: {self.path}"))
            return None

        def go():
            spec = importlib.util.spec_from_file_location("model_output_under_test", self.path)
            mod = importlib.util.module_from_spec(spec)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                spec.loader.exec_module(mod)
            self.mod = mod
            self.import_output = buf.getvalue()
        self.check(label, go)
        self.loaded = self.mod is not None
        return self.mod

    def need_mod(self, name, fn):
        """A check that needs the import to have worked."""
        if not self.loaded:
            self.results.append((False, name, "skipped: the file does not import"))
        else:
            self.check(name, fn)

    def quiet(self, fn, *a, **k):
        """Call fn with stdout captured; returns (result, printed_text)."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = fn(*a, **k)
        return out, buf.getvalue()

    def run_script(self, cwd=None, args=(), timeout=10):
        """Run the output file as `python -I file` in cwd. Returns (exit_code, stdout, stderr)."""
        try:
            p = subprocess.run([sys.executable, "-I", self.path, *args], cwd=cwd or tempfile.gettempdir(),
                               capture_output=True, text=True, timeout=timeout)
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            raise AssertionError(f"script did not finish within {timeout}s")

    def finish(self):
        for ok, name, detail in self.results:
            print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if detail and not ok else ""))
        good = sum(1 for r in self.results if r[0])
        print(f"VERIFY: {'PASS' if good == len(self.results) else 'FAIL'} ({good}/{len(self.results)})")
        sys.exit(0 if good == len(self.results) else 1)


def header(argv):
    """Standard start of a verifier: returns a Checker for argv[1]."""
    if len(argv) < 2:
        print("usage: python -I verify.py <output file>\nVERIFY: FAIL (0/1)")
        sys.exit(2)
    return Checker(argv[1])
