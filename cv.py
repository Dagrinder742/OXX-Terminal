#!/usr/bin/env python3
"""
cv.py - one helper for both Windows (PowerShell) and Termux.

Run from ANY folder:
  python cv.py cv [path]         bandit + pip-audit (+ package updates on Termux)
  python cv.py cv --skip-update  same, without the Termux package updates
  python cv.py git ["message"]   git add -A, commit, push in the current repo

Put bandit.yaml in the same folder as this file; it is found automatically.
"""
import argparse
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BANDIT_CONFIG = HERE / "bandit.yaml"
DEFAULT_MESSAGE = "Architectural Work To The Core Files"
YELLOW, RED, GREEN, RESET = "\033[33m", "\033[31m", "\033[32m", "\033[0m"

logging.basicConfig(level=logging.INFO, format="%(message)s")


def say(msg, color=YELLOW):
    print(f"{color}[+] {msg}{RESET}")


def run(cmd, cwd=None, quiet_warnings=False):
    """Run a command (a list, never a shell string). Returns the exit code."""
    env = dict(os.environ)
    if quiet_warnings:
        env["PYTHONWARNINGS"] = "ignore"
    try:
        return subprocess.run(cmd, cwd=cwd, env=env).returncode
    except OSError as e:
        logging.warning(f"Could not run {cmd[0]}: {e}")
        return 127


def capture(cmd, cwd=None):
    """Like run(), but returns (exit code, stdout text)."""
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return done.returncode, done.stdout.strip()
    except OSError as e:
        logging.warning(f"Could not run {cmd[0]}: {e}")
        return 127, ""


def have_module(name):
    return importlib.util.find_spec(name) is not None


def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "") or shutil.which("pkg") is not None


# --------------------------------------------------------------------------- #
def cmd_cv(args):
    target = Path(args.path).resolve()
    if not target.is_dir():
        say(f"Not a folder: {target}", RED)
        return 2
    results = {}

    if is_termux() and not args.skip_update:
        say("RUNNING PACKAGE UPDATES...")
        # `or` runs the upgrade only if the update returned 0
        results["pkg"] = run(["pkg", "update", "-y"]) or run(["pkg", "upgrade", "-y"])

    say(f"RUNNING BANDIT in {target} ...")
    if have_module("bandit"):
        cmd = [sys.executable, "-m", "bandit"]
        if BANDIT_CONFIG.exists():
            cmd += ["-c", str(BANDIT_CONFIG)]
        else:
            say(f"No bandit.yaml next to cv.py ({BANDIT_CONFIG}), using defaults", RED)
        cmd += ["-r", ".", "--severity-level", "all",
                "--confidence-level", "all", "--ignore-nosec"]
        # cwd=target + "-r ." keeps paths relative so excludes match as intended
        results["bandit"] = run(cmd, cwd=target, quiet_warnings=True)
    else:
        say("bandit is not installed:  pip install bandit", RED)
        results["bandit"] = 127

    say("RUNNING PIP-AUDIT...")
    if have_module("pip_audit"):
        results["pip-audit"] = run([sys.executable, "-m", "pip_audit"],
                                   cwd=target, quiet_warnings=True)
    else:
        say("pip-audit is not installed:  pip install pip-audit", RED)
        results["pip-audit"] = 127

    print()
    for step, code in results.items():
        ok = code == 0
        say(f"{step:<10} exit {code:<4} {'OK' if ok else 'CHECK OUTPUT ABOVE'}",
            GREEN if ok else RED)
    return 0 if all(c == 0 for c in results.values()) else 1


def cmd_git(args):
    if not shutil.which("git"):
        say("git is not installed", RED)
        return 127
    code, _ = capture(["git", "rev-parse", "--is-inside-work-tree"])
    if code != 0:
        say("This folder is not inside a git repository", RED)
        return 2

    code, changes = capture(["git", "status", "--porcelain"])
    if code != 0:
        say("git status failed", RED)
        return code
    if not changes:
        say("Nothing to commit")
        return 0

    say("Changes about to be committed:")
    run(["git", "status", "--short"])
    for step in (["git", "add", "-A"],
                 ["git", "commit", "-m", args.message],
                 ["git", "push"]):
        code = run(step)
        if code != 0:                       # stop at the first failure
            say(f"'{' '.join(step[:2])}' failed (exit {code}), stopping", RED)
            return code
    say("Pushed", GREEN)
    return 0


def main():
    if os.name == "nt":
        os.system("")                       # lets Windows consoles show ANSI colors

    # Called through a link named run-git / run-cv? Pick the subcommand from the name.
    called_as = {"run-git": "git", "run-cv": "cv"}.get(Path(sys.argv[0]).stem.lower())
    if called_as:
        sys.argv.insert(1, called_as)

    ap = argparse.ArgumentParser(description="Cross-platform helper for Termux and Windows.")
    sub = ap.add_subparsers(dest="command", required=True)

    p_cv = sub.add_parser("cv", help="bandit + pip-audit (+ Termux package updates)")
    p_cv.add_argument("path", nargs="?", default=".", help="folder to scan (default: current)")
    p_cv.add_argument("--skip-update", action="store_true", help="skip Termux package updates")
    p_cv.set_defaults(func=cmd_cv)

    p_git = sub.add_parser("git", help="add -A, commit, push in the current repo")
    p_git.add_argument("message", nargs="?", default=DEFAULT_MESSAGE, help="commit message")
    p_git.set_defaults(func=cmd_git)

    args = ap.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        say("Interrupted", RED)
        return 130


if __name__ == "__main__":
    sys.exit(main())
