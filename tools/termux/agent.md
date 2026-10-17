# Agent Architecture & Sandbox Specification
**Project Root / Sandbox Directory:** `/data/data/com.termux/files/home/OKX-Terminal/tools`[span_0](start_span)[span_0](end_span)
**Core Engine:** Local `llama-server` running `Qwen/Qwen2.5-Coder-3B-Instruct-GGUF` via a local OpenAI-compatible API endpoint (`http://localhost:8080/v1/chat/completions`)[span_1](start_span)[span_1](end_span).

---

## 1. Security & Execution Policy (`sandbox_tool.py`)
* **No Shell Execution:** Commands are executed strictly via argument lists (`argv`), completely neutralizing command injection, backticks, or variable expansion.
* **Strict Chaining Blockers:** Explicitly blocks shell tokens (`|`, `&&`, `;`, `>`, `<`, etc.) to prevent pipes, redirects, or multi-command chaining in a single turn[span_2](start_span)[span_2](end_span).
* **Path Boundary Enforcer:** Every path is resolved using `os.path.realpath` to guarantee it cannot escape the sandbox root (no `../` escapes or symlink exploits allowed).
* **Flag Validation Engine:** Long flags and short flag clusters are filtered against a strict allowlist. Dangerous or destructive short flags (e.g., recursive forcing) are explicitly blocked.

---

## 2. Whitelisted Terminal Commands
The agent has read-only/introspection access to a minimal, safe set of standard Unix utilities:
* `ls` (directory listing with safe flags)[span_3](start_span)[span_3](end_span)
* `cat` (file viewing)[span_4](start_span)[span_4](end_span)
* `grep` (pattern searching, with isolated patterns)[span_5](start_span)[span_5](end_span)
* `sed` (stream editing, running under restricted sandbox profiles)[span_6](start_span)[span_6](end_span)
* `head` / `tail` (file boundary inspection)[span_7](start_span)[span_7](end_span)
* `wc` (word, line, and byte counting)[span_8](start_span)[span_8](end_span)

---

## 3. Custom Built-In Agent Tools
Beyond standard CLI commands, custom Python functions are intercepted and executed safely within the runner:
* **`write_file <path> <content>`**: Creates or overwrites files inside the sandbox directory, automatically handling newline formatting (`\n`) for multi-line scripts[span_9](start_span)[span_9](end_span).
* **`patch_file <path> <search_string> <replace_string>`**: Performs precise, unique search-and-replace text modifications on existing files without rewriting entire modules[span_10](start_span)[span_10](end_span).

---

## 4. State Tracking & Audit Trail
* **`file_index.txt`**: Automatically logs every file created or modified by the agent with corresponding action tags (e.g., `created`, `patched`), maintaining a clean historical index of all code generated[span_11](start_span)[span_11](end_span).

---

## 5. Agent Reasoning Loop
* **Context Preservation:** Chat history (`msgs`) explicitly appends real tool execution outputs as user messages on each turn, ensuring the model sees true execution feedback and avoids hallucinating file structures.
* **Failure Guardrails:** Tracks consecutive failures or duplicate commands and automatically aborts to prevent infinite loops.

