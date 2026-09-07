# Global Refactor: Migrate from USD to USDT Quote

This plan outlines the steps to migrate the entire OXX Terminal (Python and C++) from USD-quoted pairs to USDT-quoted pairs, following OKX delisting schedules.

## User Review Required

> [!IMPORTANT]
> - All `-USD` instrument IDs will be renamed to `-USDT`.
> - `USDT-USD` will be renamed to `USDC-USDT` to avoid identity pairs and maintain a liquidity anchor.
> - The logic that appends `-USD` to ticker searches will be updated to append `-USDT`.

## Proposed Changes

### Core Python Application

#### [MODIFY] [main.py](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/main.py)
- Update default `instrument_id` from `BTC-USD` to `BTC-USDT`.
- Update watchlist pairs: replace `-USD` with `-USDT`.
- Rename `USDT-USD` to `USDC-USDT`.
- Update search normalization logic to append `-USDT`.

#### [MODIFY] [agent.py](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/agent.py)
- Update all tool default arguments from `BTC-USD` to `BTC-USDT`.
- Update internal symbol cleaner to append `-USDT`.
- Update test prompt and comments.

#### [MODIFY] [api_client.py](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/api_client.py)
- Update default `instrument_id`.

#### [MODIFY] [chart_renderer.py](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/chart_renderer.py)
- Update default `inst_id`.

---

### C++ Translation Layer

#### [MODIFY] [main.cpp](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/CPP/main.cpp)
- Update `focus_pair` and `symbols` vector.

#### [MODIFY] [OKXPublicClient.hpp](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/CPP/OKXPublicClient.hpp)
- Update default constructor argument.

#### [MODIFY] [UIComponents.cpp](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/CPP/UIComponents.cpp)
- Update hardcoded UI strings.

---

### Testing & Support Scripts

#### [MODIFY] [test_liquid_main.py](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/test_liquid_main.py)
#### [MODIFY] [test_termux_happy.py](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/test_termux_happy.py)
- Synchronize with `main.py` changes.

#### [MODIFY] [test_reactive_scaling.py](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/test_reactive_scaling.py)
- Update dynamic watchlist generation to use `-USDT`.

---

### Documentation & Memory

#### [MODIFY] [README.md](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/README.md)
#### [MODIFY] [oxx-terminal.md](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/oxx-terminal.md)
#### [MODIFY] [agent.md](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/agent.md)
- Update examples and architecture notes.

#### [MODIFY] [agent_memory.json](file:///C:/Users/krayz/AndroidStudioProjects/OXXTerminal/app/src/main/Python/agent_memory.json)
- Migrate existing history entries to `BTC-USDT`.

## Verification Plan

### Automated Tests
- I will run the `agent.py` to ensure it can still fetch ticker data using the new `BTC-USDT` default.
- I will check the `main.py` search logic by simulating a search for "BTC" and verifying it resolves to `BTC-USDT`.

### Manual Verification
- The user should verify that the TUI loads with `BTC-USDT` as the default instrument and that the watchlist displays `-USDT` pairs correctly.
- The user should verify the `USDC-USDT` liquidity anchor is functional in the Market Hub.
