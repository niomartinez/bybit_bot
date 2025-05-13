# Project Progress Summary & Next Steps

**Last Updated:** May 13, 2025

## Current Status

Order placement for entry orders with bundled Stop Loss (SL) and Take Profit (TP) is largely functional. Significant effort has been made to refine signal validation logic to prevent placing orders for stale setups. Logic for cancelling stale `PENDING_ENTRY` orders based on current market price vs. SL/TP/Entry has been implemented. The handling of very old, untraceable pending orders (`historical_notfound`) has been refined.

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
    *   `main.py` updated to handle `closed` status from `check_order_status` as a fill, and to appropriately update DB status for new error/not-found states.
    *   `main.py` signal processing loop now more robustly skips reprocessing signals that are already `PENDING_ENTRY` or in other non-actionable states.
    *   Refined `place_sl_tp_orders_for_signal` in `main.py` to fetch updated signal details (with filled price/qty) from DB after setting status to `ENTRY_FILLED`, before proceeding to place SL/TP orders. Added error handling for this step.
*   **API Parameter Correction (`src/order_executor.py`):**
    *   Removed potentially problematic `orderFilter: 'tpslOrder'` from `default_params` in `place_limit_entry_order` for derivative orders with bundled SL/TP.
*   **Log Level Adjustment for `historical_notfound` (`src/main.py`):**
    *   Changed log level for `historical_notfound` status (when checking `PENDING_ENTRY` orders) from `ERROR` to `WARNING` to reduce noise for expected scenarios with very old orders.
*   **Database Schema Fix for `error_message` (`src/state_manager.py`):**
    *   Resolved "no such column: error_message" by ensuring the `error_message` column is added to `tracked_signals` via `add_column_if_not_exists` in `_init_db`. DB updates including error messages now succeed.

### Debugging Journey Summary:

*   Addressed `KeyError: '"retCode"'` during order placement.
*   Refined multi-stage signal invalidation in `AnalysisEngine`.
*   Corrected `AttributeError` in `AnalysisEngine`.
*   Fixed "no such column: error_message" database error.
*   Adjusted logging for `historical_notfound` scenarios.

## Immediate Next Steps & Focus Areas:

1.  **Testing and Monitoring (Ongoing Priority):**
    *   Continue thorough testing of the **stale order cancellation logic** in various scenarios (TP hit market, SL hit market, market moved away).
    *   Monitor order fill status updates (`PENDING_ENTRY` -> `ENTRY_FILLED` -> `POSITION_OPEN`) to ensure correct transitions.
    *   Verify that the `place_sl_tp_orders_for_signal` function is triggered reliably after `ENTRY_FILLED` and uses the correct filled price/qty.
    *   Test the **duplicate entry prevention** logic by restarting the bot during different signal states.
2.  **Implement Position/SL/TP Monitoring (Critical):**
    *   Develop the loop in `main.py` for `POSITION_OPEN` signals to actively monitor if their corresponding SL or TP orders (managed by the exchange) are hit.
    *   This involves periodically checking the status of the `sl_order_id` and `tp_order_id` stored in `StateManager`.
    *   Upon SL/TP fill, update the signal status in `StateManager` to `CLOSED_SL` or `CLOSED_TP`, log the closure, and alert.
    *   If one is hit (e.g., TP), attempt to cancel the other (e.g., SL).
3.  **Configuration Cleanup:**
    *   Review and remove invalid/placeholder symbols from `portfolio.coins_to_scan` in `config.json` (e.g., `PLUMUSDT`, `FARTCOINUSDT`) to prevent API errors during data fetching.
4.  **Address Pandas `FutureWarning`s:**
    *   Investigate and refactor code in `src/analysis_engine.py` (and potentially other places) causing `FutureWarning: Setting an item of incompatible dtype is deprecated...` to ensure future compatibility with Pandas. This typically involves explicit type casting (e.g., `pd.to_datetime()`) before assigning to DataFrame columns of a specific `dtype`.

## Future Modules/Refinements (Post Critical Next Steps):

*   Add Telegram/Discord notifications (`SignalAlerter` for fills, errors, and closures).
*   Add comprehensive unit tests for all critical modules.
*   Further explore and refine error handling and retry mechanisms, especially for API interactions.
*   Performance review and optimization if scanning a very large number of coins.