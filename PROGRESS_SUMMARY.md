# Project Progress Summary & Next Steps

**Last Updated:** May 13, 2025

## Current Status

Order placement for entry orders with bundled Stop Loss (SL) and Take Profit (TP) is largely functional. Significant effort has been made to refine signal validation logic to prevent placing orders for stale setups where the price has already moved beyond the hypothetical TP or where the SL would be invalid relative to the current market price. `OrderExecutor.check_order_status` has been made more robust. TP price journaling to the database and CSV has been improved.

### Key Accomplishments (Since Last Update):

*   **Signal Invalidation Enhancements (`src/analysis_engine.py`):**
    *   Implemented **Local 5m Validation**: When a 5m entry signal is found, it now checks if its hypothetical TP was breached by subsequent 5m candles within its initial fetched data window. Debug logs added for this step.
    *   Implemented **Stage 2 Validation (15m Close)**: Signals passing local validation are checked against the latest 15m closing price for the symbol.
    *   Implemented **Final Validation (Fresh 5m Data)**: Before a signal is finalized, fresh 5m data (from the signal's 5m timestamp up to a recent window or current time) is fetched to perform a more definitive check if the hypothetical TP was breached. This helps invalidate older signals more accurately.
*   **Pre-Order Placement Validation (`src/main.py`):**
    *   Before attempting to place any limit entry order, `main.py` now fetches the current ticker price.
    *   It validates if the signal's SL price is valid relative to the current market price (e.g., SL for a buy must be below current market).
    *   Signals failing this check are logged as "STALE/INVALID" and order placement is skipped, preventing many API errors.
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

1.  **Monitor Order Fill Status Updates (`main.py`):**
    *   Closely observe if orders that are known to be filled (e.g., BTC, ETH) are now correctly transitioning from `PENDING_ENTRY` to `ENTRY_FILLED` in the database, now that `check_order_status` is more robust and `main.py` handles `closed` status.
    *   Ensure the `place_sl_tp_orders_for_signal` function is triggered correctly after `ENTRY_FILLED`.
2.  **Cancellation of Stale `PENDING_ENTRY` Orders (`main.py`):**
    *   Implement logic in `main.py`'s main loop to iterate through signals in `PENDING_ENTRY` status.
    *   For each, fetch current market price and compare against its stored entry, SL, and `hypothetical_tp_price`.
    *   If (TP hit) OR (SL hit/invalidated based on current market) OR (entry too far from current market), then:
        *   Call `order_executor.cancel_order()`.
        *   Update `StateManager` to an appropriate `CANCELLED_STALE_...` status.
3.  **Address `KeyError` for DOGEUSDT Sell (If Persists):**
    *   If the pre-order validation and removal of `orderFilter` don't fully resolve the `KeyError` for some order types (like the DOGEUSDT sell), analyze the verbose `ccxt` logs again for the exact Bybit error message. It might involve specific parameter requirements for sell-side SL/TP or other conditions.

## Future Modules/Refinements (Post SL/TP & Stale Order Cancellation):

*   Implement Position/SL/TP Monitoring (`main.py` loop for `POSITION_OPEN` signals to see if active SL/TP orders are hit).
*   Add Telegram/Discord notifications (`SignalAlerter`).
*   Address remaining Pandas `FutureWarning`s (low priority).
*   Add unit tests.