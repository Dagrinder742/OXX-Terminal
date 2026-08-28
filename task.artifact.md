# Tasks: Account Trade History Integration

- `[x]` Update Private API Client (`okx_private.py`)
    - `[x]` Implement `get_fill_history` method
- `[x]` Wire TUI Hydration (`main.py`)
    - `[x]` Implement `hydrate_fill_history`
    - `[x]` Trigger hydration in `_start_terminal_services`
    - `[x]` Refresh history display on boot
- `[x]` Verification
    - `[x]` Created `test_fill_history.py` scratch script
    - `[x]` Logic verified against API schema
