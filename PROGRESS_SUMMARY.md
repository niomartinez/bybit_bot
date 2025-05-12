# Project Progress Summary & Next Steps

**Last Updated:** May 13, 2025

## Current Status

Order placement for entry orders with bundled Stop Loss (SL) and Take Profit (TP) is largely functional. Significant effort has been made to refine signal validation logic to prevent placing orders for stale setups where the price has already moved beyond the hypothetical TP or where the SL would be invalid relative to the current market price. `OrderExecutor.check_order_status` has been made more robust. TP price journaling to the database and CSV has been improved. **Logic for cancelling stale `PENDING_ENTRY` orders based on current market price vs. SL/TP/Entry has been implemented.**

### Key Accomplishments (Since Last Update):

*   **Signal Invalidation Enhancements (`src/analysis_engine.py`):**
    *   Implemented **Local 5m Validation**: When a 5m entry signal is found, it now checks if its hypothetical TP was breached by subsequent 5m candles within its initial fetched data window. Debug logs added for this step.
    *   Implemented **Stage 2 Validation (15m Close)**: Signals passing local validation are checked against the latest 15m closing price for the symbol.
    *   Implemented **Final Validation (Fresh 5m Data)**: Before a signal is finalized, fresh 5m data (from the signal's 5m timestamp up to a recent window or current time) is fetched to perform a more definitive check if the hypothetical TP was breached. This helps invalidate older signals more accurately.
*   **Pre-Order Placement Validation (`src/main.py`):**
    *   Before attempting to place any limit entry order, `main.py` now fetches the current ticker price.
    *   It validates if the signal's SL price is valid relative to the current market price (e.g., SL for a buy must be below current market).
    *   Signals failing this check are logged as "STALE/INVALID" and order placement is skipped, preventing many API errors.
*   **Stale `PENDING_ENTRY` Order Cancellation (`src/main.py`):**
    *   Implemented logic within the `PENDING_ENTRY` monitoring loop.
    *   For orders still 'open' via API, fetches current market price.
    *   Compares market price against stored entry, SL, and hypothetical TP.
    *   If market price indicates SL/TP hit or entry is too far away (based on `staleness_entry_deviation_percent` config), attempts to cancel the order via `order_executor.cancel_order()`.
    *   Updates `StateManager` to appropriate `CANCELLED_STALE_...` status.
*   **TP Journaling Improvements:**
    *   **`src/state_manager.py`**:
        *   Added `hypothetical_tp_price REAL` and `actual_tp_ordered REAL` columns to the `tracked_signals` table schema.
        *   `add_signal_entry` now stores the `hypothetical_tp_price` (from `AnalysisEngine`) and the `actual_tp_ordered` (TP price sent with bundled entry order, from `OrderExecutor` response via `main.py`).
    *   **`src/journaling.py`**:
        *   Added `HypotheticalTPPrice` to CSV headers and logs the corresponding value.
    *   **`src/main.py`**:
        *   Corrected logic to pass the actual TP price (from order response when bundled, or calculated `tp_price_f` when separate) to `StateManager` for storage in relevant TP price columns.
*   **Order Status Handling (`src/order_executor.py` & `src/main.py`):**
    *   `OrderExecutor.check_order_status` refactored to try `fetchOpenOrders`, then `fetchClosedOrders`, then `fetch_order` as a fallback. It now returns more descriptive statuses like `historical_notfound` if Bybit's "last 500 orders" limit is hit by `fetch_order`.
    *   `StateManager.update_signal_status` now whitelists `error_message` for storage.
    *   `main.py` updated to handle `closed` status from `check_order_status` as a fill, and to appropriately update DB status for new error/not-found states like `historical_notfound` (to `CANCELLED_STALE_NOT_FOUND`) and other errors (to `CHECK_STATUS_FAILED`).
    *   `main.py` signal processing loop now more robustly skips reprocessing signals that are already `PENDING_ENTRY` or in other non-actionable states (including `UNKNOWN_API_STATUS`).
    *   Refined `place_sl_tp_orders_for_signal` in `main.py` to fetch updated signal details (with filled price/qty) from DB after setting status to `ENTRY_FILLED`, before proceeding to place SL/TP orders. Added error handling for this step.
*   **API Parameter Correction (`src/order_executor.py`):**
    *   Removed potentially problematic `orderFilter: 'tpslOrder'` from `default_params` in `place_limit_entry_order` for derivative orders with bundled SL/TP.

### Debugging Journey Summary:

*   Addressed `KeyError: '"retCode"'` during order placement by:
    *   Ensuring `verbose: True` in `DataIngestionModule` to get raw Bybit API responses.
    *   Identifying that Bybit rejected orders due to SL prices being invalid relative to the *current market price* at the time of submission (because signals were stale).
    *   Removing the `orderFilter` parameter for derivative limit orders with SL/TP.
    *   Implementing the pre-order validation in `main.py` to catch these stale SL conditions proactively.
*   Refined multi-stage signal invalidation in `AnalysisEngine` to better handle old signals by fetching fresh 5m data up to the current scan time for a final validity check against hypothetical TP.
*   Corrected `AttributeError` in `AnalysisEngine` due to method indentation.

## Immediate Next Steps:

1.  **Testing and Monitoring:**
    *   Thoroughly test the **stale order cancellation logic** in various scenarios (TP hit market, SL hit market, market moved away).
    *   Monitor order fill status updates (`PENDING_ENTRY` -> `ENTRY_FILLED` -> `POSITION_OPEN`) to ensure correct transitions.
    *   Verify that the `place_sl_tp_orders_for_signal` function is triggered reliably after `ENTRY_FILLED` and uses the correct filled price/qty.
    *   Test the **duplicate entry prevention** logic by restarting the bot during different signal states.

## Future Modules/Refinements (Post SL/TP & Stale Order Cancellation Testing):

*   Implement Position/SL/TP Monitoring (`main.py` loop for `POSITION_OPEN` signals to see if active SL/TP orders are hit).
*   Add Telegram/Discord notifications (`SignalAlerter`).
*   Address remaining Pandas `FutureWarning`s (low priority).
*   Add unit tests.