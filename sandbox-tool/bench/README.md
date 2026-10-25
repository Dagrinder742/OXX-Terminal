# bench: task bank, capture, reports

Run from a checkout of the repository (`python bench/bench.py ...`). Needs only Python 3 and the standard library.
It finds `sandbox_tool.py` in `../src`, or in the installed package, or from `--tools <folder>` / `TOOLS=<folder>`.

```bash
python bench/test_bench.py        # must print ALL OK (fake model server, about a minute)
python bench/bench.py selftest    # must print ALL VERIFIERS BEHAVE (tests the checkers themselves)
python bench/bench.py list
python bench/bench.py run -t wordcount stack -n 3 --label first-try
python bench/bench.py run -t all -n 3 --live
```

Point it at your server first (`LLAMA_URL`, `BACKEND`, ... as in the main README). Every run uses a fresh empty
sandbox folder (plus the task's fixture files), so leftovers cannot help or hurt.

## What gets written

`bench/runs/<session>/<task>/run_<n>/` holds `run.log`, the file the model wrote, `verify.log`,
`transcript.json` (the whole conversation), `result.json` (verdict, checks passed, steps, commands used, seconds,
how it ended, generation speed, failed check names, and `claimed_false`: the tool accepted the model's DONE but
the verifier said FAIL) and `refused.log`. `meta.json` records the model name, hashes of the tool, the system
prompt and each task's prompt and verifier. When a run finishes you get one report file,
`bench/reports/<session>.txt`: summary table, your notes, then every run's log, file and verify log.

## Commands

| Command | |
|---|---|
| `run -t <tasks> -n N --label X --note "..."` | Run, judge, capture, write the report. `--live` echoes the agent's output. |
| `note "text" [--run task/3]` | Add a note to the latest session (or one run), even while a run is going. |
| `report [session] [--detail all\|fail\|none]` | Rebuild the report (picks up new notes). Edit `notes.md` files, never `report.txt`. |
| `show task/3 [session]` | Print one run: log, file, verify log. |
| `stats` | Pass rates per task for every session, with the tool and prompt hashes. |
| `export [-o file] [--no-system] [--max-per-task N]` | Verified passes as JSONL (chat messages). A seed for fine-tuning, not a training set. |
| `selftest [task]` | Every verifier must pass its `selftest/good*.py` and fail its `selftest/bad*.py`. |

## Keeping results honest

* A run is PASS only if the verifier printed `VERIFY: PASS`. A missing output file, a dead server, a blocked
  construct, a hang or a crash is recorded as FAIL with the reason.
* It refuses to start on a missing or empty prompt.
* The verifier will not execute a file that contains constructs the sandbox blocks. It does run the model's file
  **outside** the sandbox guard (timeout, CPU and file-size limits only), so it is not a sandbox: only run it
  against models you are willing to run code from.

## Adding a task

`bench/tasks/<name>/` needs `task.json` (`title`, `output`, `difficulty`, `max_steps`), `prompt.txt`, `verify.py`
(prints PASS/FAIL lines and a last line `VERIFY: PASS (n/n)`; copy `tasks/stack/verify.py`), optional `files/`
(copied into the sandbox before the run) and `selftest/` references. Write the verifier so a hard-coded answer
fails (see `csv_total`, which tests with different data).
