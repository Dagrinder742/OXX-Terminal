# OXX Terminal: C++ Translation Roadmap

This document outlines the architectural mapping for translating the Python TUI production environment into high-performance C++.

## Core Files to Translate

### 1. The Math & Logic (Accountant & Strategy)
*   **Source:** `accountant.py` 
    *   **Target:** `Accountant.hpp` / `Accountant.cpp` [COMPLETED]
    *   **Status:** Math verified in PowerShell.
*   **Source:** `strategy_engine.py`
    *   **Target:** `StrategyEngine.hpp` / `StrategyEngine.cpp` [COMPLETED]
    *   **Status:** Logic ported; ready for CMake build.

### 2. Connectivity & Security
*   **Source:** `auth.py` & `okx_private.py`
    *   **Target:** `SecurityUtils.hpp` / `Auth.cpp` / `OKXPrivateClient.hpp`
    *   **Role:** HMAC-SHA256 signing logic and authenticated REST requests.
    *   **C++ Hardening:** Manual memory zeroing and high-performance authenticated requests via `cpp-httplib`. [COMPLETED]
*   **Source:** `api_client.py`
    *   **Target:** `OKXPublicClient.hpp` / `OKXPublicClient.cpp`
    *   **Role:** Low-latency WebSocket stream management for Tickers, Books, and Trades.
*   **Source:** `secure_vault.py` & `secure_store.py`
    *   **Target:** `Security.hpp` / `Security.cpp`
    *   **Role:** OS-level encrypted credential storage (utilizing `libsecret` or `Windows Data Protection API`).

### 3. Visuals & Orchestration
*   **Source:** `chart_renderer.py`
    *   **Target:** `ChartRenderer.hpp` / `ChartRenderer.cpp`
    *   **Role:** ASCII candlestick rendering (using a C++ equivalent to `plotext` or custom matrix logic).
*   **Source:** `main.py`
    *   **Target:** `main.cpp`
    *   **Role:** Application entry point and TUI orchestration (leveraging **FTXUI** for component management).

---

## Technical Dependencies for C++
*   **TUI Framework:** `FTXUI`
*   **Networking:** `IXWebSocket` (for WS) / `cURL` or `cpp-httplib` (for REST).
*   **JSON:** `nlohmann/json`
*   **Crypto:** `OpenSSL` (for HMAC signing).

## Ground Rules for Execution
1.  **Strict Parity:** Logic must be verified line-by-line against the Python "Single Source of Truth."
2.  **No Python Mutation:** Active `.py` files must remain untouched during translation.
3.  **Bifurcated Testing:** Each C++ module must pass a "Math Identity" test against its Python counterpart before integration.

---

## 4. Build System & Workflow (CMake)
To maintain the "Snowman Standard" across Windows and Termux, we utilize **CMake** as our universal build orchestrator.

### Standard Build Workflow (PowerShell / Termux)
1.  **Enter the build environment:**
    ```powershell
    cd C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/CPP
    mkdir build -Force
    cd build
    ```
2.  **Configure & Build:**
    ```powershell
    cmake ..
    cmake --build .
    ```

### Running Executables (Windows/VS Specific)
When using the Visual Studio compiler, CMake creates a `Debug/` subfolder. Your verified outlets are:
*   **Accountant Test**: `./bin/Debug/test_accountant.exe`
*   **Strategy Test**: `./bin/Debug/test_strategy.exe`

---

## 5. Learner's Log: Technical Hurdles & Fixes

### 1. The "Debug" Folder Quirk
**Problem:** Executables were not found in `./bin/`.
**Teaching:** Visual Studio (MSVC) is a multi-config generator. It isolates different build types. On Linux/Termux, they land directly in `bin/`, but on Windows, you must look inside `bin/Debug/`.

### 2. The 'localtime' Safety Warning
**Problem:** Compiler threw `warning C4996` about unsafe C functions.
**Teaching:** Standard C functions like `localtime` are considered "legacy" by Microsoft. We use `-D_CRT_SECURE_NO_WARNINGS` in `CMakeLists.txt` to suppress these and maintain cross-platform code parity.

### 3. Header Guards (`#ifndef OXX_...`)
**Teaching:** Every `.hpp` file starts with a "Guard." This prevents the compiler from getting confused if the same file is included multiple times in a complex project.

### 4. OpenSSL Configuration (Windows)
**Problem:** CMake could not find the OpenSSL library automatically.
**Verified Fix:** 
1.  Install via winget: `winget install ShiningLight.OpenSSL.Dev`
2.  Point CMake to the installation root during configuration:
    ```powershell
    cmake .. -DOPENSSL_ROOT_DIR="C:/Program Files/OpenSSL-Win64"
    ```

### 5. Type Safety & 'Loss of Data' Warnings
**Problem:** `warning C4267` regarding `size_t` (64-bit) to `int` (32-bit) conversion in OpenSSL functions.
**Verified Fix (The Snowman Middleware Standard):** 
1.  **Validation**: Implement strict `if` checks to ensure 64-bit lengths do not exceed 32-bit limits (`INT_MAX`) before any conversion occurs.
2.  **Chunking**: For large data transfers (like Base64 encoding), we utilize a "Middleware" loop that processes data in 1MB chunks. This ensures no data is lost regardless of how large the total payload is, as each individual call only receives a small, safe value.
3.  **Explicit Intent**: Use `static_cast<int>(...)` only *after* validation is complete to signal to the compiler and future auditors that the conversion is mathematically guaranteed to be safe.

### 6. CMake Policies (CMP0135)
**Problem:** Warning about `DOWNLOAD_EXTRACT_TIMESTAMP` for external content.
**Teaching:** CMake uses "Policies" to manage breaking changes between versions. `CMP0135` ensures that downloaded files get a fresh timestamp. We explicitly set this to `NEW` in `CMakeLists.txt` to ensure reliable, ghost-free builds when fetching external libraries like JSON.

---

## 6. Bifurcated Python "Happy Sides" Standard [IN PROGRESS]
Before final consolidation into C++, we have successfully prototyped two distinct Python standards for environment-specific scaling:

### The PowerShell Happy Side (`test_liquid_main.py`)
*   **Target:** High-resolution desktop monitors.
*   **Specs:** 300ms debounce, 80-candle history, dynamic full-width matrix resolution.

### The Termux Happy Side (`test_termux_happy.py`)
*   **Target:** High-efficiency mobile hardware.
*   **Specs:** 500ms debounce (extra CPU breathing room), 50-candle history (reduced buffer payload), aggressive vertical Hub stacking.

---

## 7. C++ Translation Status: Phase 3 Consolidation
We have successfully ported the core logic modules and are moving toward TUI consolidation in `main.cpp`.

*   **Accountant Module**: Verified Math [COMPLETED]
*   **Strategy Engine**: Verified Logic [COMPLETED]
*   **Security & Auth**: OpenSSL Signed requests verified [COMPLETED]
*   **JSON/HTTP Core**: Build system integrated [COMPLETED]
*   **TUI Framework**: FTXUI added to build path [IN PROGRESS]

===================================================================================================
PERSONAL NOTES I FIND HELPFUL IN AGENT DISCUSSIONS (AGENT MAY ADD TO THIS OR EDIT)
===================================================================================================
Python vs. C++ Security (The "Snowman" Standard):
---------------------------------------------------------------------------------------------------
1. The Python Challenge: In Python, when you use an API Key string, that string might hang around 
in your computer's RAM (Memory) for minutes or even hours after you're done with it because of 
"Garbage Collection." A specialized memory-scraping virus could theoretically find it.

2. The C++ Hardening: In C++, we have manual control. We can write code that says: "Use this API 
Key to sign the order, and the very next millisecond, overwrite those specific bytes in RAM with 
zeros." This is called Zeroing Memory, and it's the gold standard for institutional trading desks 
to ensure sensitive keys never leave a "trace" in memory.

3. losing data is always a bad thing. In a trading environment, losing even a single byte of a 
signature or an order ID means the request fails or, worse, it executes incorrectly.
In this specific case (API signatures), it’s not serious because we know our signatures are always 
very short (64 characters). But in a general sense, it's a "Code Smell" that professional 
engineers try to eliminate.
How to solve it for good (The Senior Engineer Approach):
Instead of trying to force a 64-bit number into a 32-bit function, we can process the data in 
chunks.
If you have a massive piece of data (larger than 2.1 billion characters), you don't pour it all into 
the 32-bit function at once. Instead, you write a loop that sends it in 1-megabyte chunks. This 
ensures that every function only ever receives a small number that it can safely handle.