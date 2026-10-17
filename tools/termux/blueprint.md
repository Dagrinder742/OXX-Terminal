Local 3B AI Agent Architecture: Design Specification & Roadmap
1. Executive Summary & Architecture Philosophy
Building an autonomous coding agent around a compact model (such as Qwen2.5-Coder-3B-Instruct-GGUF:Q4_K_M) on resource-constrained hardware (such as an 8GB PC or Termux mobile environment) requires a lean, deterministic approach.
Instead of hosting heavy, resource-intensive background HTTP servers, this architecture utilizes:
 * Single-turn CLI execution (llama-cli) via Python subprocesses.
 * Structured JSON state files (tasks.json) as an external working memory layer.
 * SQLite archival (agent_memory.db) to prevent prompt context bloat.
 * Strict sandboxing to allow modular file creation and code inspection while blocking destructive system commands.
2. Core System Components
┌────────────────────────────────────────────────────────┐
│               Main Core (architect_gemini.py)          │
└───────────┬────────────────────────┬───────────────────┘
            │                        │
            ▼                        ▼
┌───────────────────────┐  ┌─────────────────────────────┐
│ Active State Ledger   │  │ Long-Term SQLite Memory     │
│ (`tasks.json`)        │  │ (`agent_memory.db`)         │
│ • Current Active Task │  │ • Historical Error Logs     │
│ • Immediate Context   │  │ • Past Successful Modules   │
└───────────────────────┘  └─────────────────────────────┘
            │                        ▲
            └───────────┬────────────┘
                        │ (Rotation/Archival)
                        ▼
┌────────────────────────────────────────────────────────┐
│                Safe Terminal Sandbox                   │
│         (`safe_terminal.py` / Whitelisted Tools)       │
│  • ALLOWED: grep, sed, cat, python syntax checks       │
│  • BLOCKED: rm, mkdir, chmod, apt install, etc.        │
└────────────────────────────────────────────────────────┘

3. Workable Framework & Design Blueprint
A. The State Ledger (tasks.json)
 * Purpose: Acts as the short-term, volatile working memory for the active micro-task.
 * Design Rule: Kept strictly lean (under 1–2 KB) to fit smoothly within the 3B model's limited context window.
 * Lifecycle: Once a task is completed, its full execution log is flushed out of tasks.json and archived into SQLite.
B. The Memory Archive (agent_memory.db)
 * Purpose: Long-term storage using lightweight SQLite (import sqlite3).
 * Design Rule: Zero background daemons required. Stores past task solutions, stack traces, and pattern history.
 * Recall Mechanism: The agent can query specific keywords from this database when encountering recurring bugs, rather than holding all history in active memory.
C. The Safe Terminal Sandbox (safe_terminal.py)
 * Purpose: Gives the agent analytical tools (grep, sed, cat, syntax parsing) to check its work and inspect its source code without risking the host environment.
 * Security Boundaries:
   * Creation & Modular Imports (Yes): The agent is encouraged to write clean, importable Python modules that plug directly into the main core.
   * Destructive Actions (No): Commands like rm, mkdir, chmod, or system package installations (apt) are strictly blacklisted.
   * Dependency Management (Human-in-the-Loop): Missing Python packages (pip) trigger an explicit advisory prompt requiring human authorization rather than running autonomously.
4. Refinement Needs & Potential Pitfalls to Watch
 * Scoping Down Task Granularity (The 3B Constraint):
   * Challenge: Small models struggle with sweeping instructions (e.g., "Build an entire application"), leading to hallucinated placeholders or skipped logic.
   * Refinement: Break all objectives down into ultra-granular micro-tasks (e.g., "Write a 25-line helper function to parse X").
 * Context Drift and Prompt Bloat:
   * Challenge: Allowing historical logs to continuously accumulate inside the active workspace files will choke the model's token limits.
   * Refinement: Strict enforcement of the JSON-to-SQLite rotation pipeline.
 * Environment Blind Spots:
   * Challenge: A 3B model does not natively know which packages or Python versions are present in your local Termux/PC environment.
   * Refinement: Maintain a static local manifest file listing core installed libraries to feed into prompt context when generating code.

