# Bybit Trading Bot: Implementation Plan

## 1. Introduction & Goals

This document outlines the implementation plan for a Python-based trading bot that listens for webhook signals from TradingView and executes trades on Bybit (Mainnet Live). The bot will focus on trading perpetual futures contracts.

**Core Goals:**

1.  Receive and parse trade signals (JSON format) from TradingView webhooks.
2.  Process each signal asynchronously.
3.  Interact with the Bybit API (v5) for:
    *   Fetching instrument details (max leverage, precision).
    *   Setting maximum leverage for the trading pair.
    *   Calculating order quantity based on a configurable Value at Risk (VaR).
    *   Placing limit orders with specified entry, stop-loss, and take-profit levels.
4.  Utilize API keys from the `.env` file for Bybit Mainnet Live.
5.  Provide robust logging and error handling.

## 2. Prerequisites

*   Python 3.9+
*   Bybit Mainnet Live account with API keys generated (ensure "Contract - Orders & Positions" permissions).
*   TradingView account capable of sending webhook alerts.
*   Basic understanding of FastAPI, `ccxt`, and asynchronous programming in Python.

## 3. Project Structure

We'll enhance the existing `bybit_bot` structure.

```
bybit_bot/
├── pinescript_indicator/
│   └── ict_2022_mentorship.pine
├── src/
│   ├── __init__.py
│   ├── main.py                   # FastAPI application, webhook endpoint
│   ├── config.py                 # Loads .env and config.json
│   ├── bybit_service.py          # Wrapper for Bybit API interactions (using ccxt)
│   ├── signal_processor.py       # Logic for processing parsed signals
│   ├── models.py                 # Pydantic models for webhook payload and config
│   └── logger_setup.py           # Logging configuration
├── venv/
├── .env                          # Stores API keys and other secrets (already present)
├── .gitignore                    # (already present)
├── requirements.txt              # Python dependencies (will be updated)
├── config.json                   # Bot configuration (VaR, default settings)
└── IMPLEMENTATION_PLAN.md        # This file
```

## 4. Configuration

### 4.1. Environment Variables (`.env`)

The existing `.env` file will be used. We'll specifically need:

*   `MAINNET_LIVE_BYBIT_API_KEY`
*   `MAINNET_LIVE_BYBIT_API_SECRET`

These will be loaded by the `src/config.py` module.

### 4.2. Application Configuration (`config.json`)

Create `config.json` in the root directory:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8000
  },
  "bybit_api": {
    "category": "linear", // For USDT perpetuals
    "default_time_in_force": "GTC", // Good Till Cancelled for limit orders
    "max_leverage_cap": null // Optional: e.g., 20 to cap leverage below exchange max. null means use exchange max.
  },
  "risk_management": {
    "var_type": "fixed_amount", // Options: "fixed_amount" or "portfolio_percentage"
    "var_value": 1.0,           // If "fixed_amount": e.g., 1.0 (for 1 USDT)
                                // If "portfolio_percentage": e.g., 0.01 (for 1% of USDT balance)
    "portfolio_currency": "USDT" // Currency to check for portfolio percentage VaR
  },
  "logging": {
    "level": "INFO",           // DEBUG, INFO, WARNING, ERROR, CRITICAL
    "file": "logs/trading_bot.log",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  }
}
```
*(Ensure a `logs/` directory is created or handled by the logger setup).*

### 4.3. Python Dependencies (`requirements.txt`)

Update or create `requirements.txt` with:

```
fastapi
uvicorn[standard]
python-dotenv
ccxt
pydantic
requests
# Add any other necessary libraries as development progresses
```

Install with: `pip install -r requirements.txt`

## 5. Core Components

### 5.1. `src/config.py`

*   Loads API keys from `.env`.
*   Loads settings from `config.json`.
*   Provides easy access to configuration values throughout the application.
*   Uses Pydantic models for validating and typing `config.json` structure.

### 5.2. `src/logger_setup.py`

*   Configures a global logger based on settings in `config.json`.
*   Outputs logs to both console and a file.

### 5.3. `src/models.py`

*   Defines Pydantic models for:
    *   Incoming webhook payload (e.g., `TradingViewSignal`).
    *   Configuration structure (`BotConfig`, nested models for API, risk, etc.).

    Example `TradingViewSignal`:
    ```python
    from pydantic import BaseModel, Field
    from typing import Literal

    class TradingViewSignal(BaseModel):
        symbol: str
        side: Literal['long', 'short']
        entry: float
        stop_loss: float
        take_profit: float
        trigger_time: str
        max_lag: int = 20
        order_type: str = "limit"
    ```

### 5.4. `src/bybit_service.py`

*   Initializes the `ccxt` Bybit exchange object for Mainnet Live using API keys from `config.py`.
*   Handles Bybit-specific API calls:
    *   `normalize_symbol(tv_symbol: str) -> str`: Converts "XXXUSDT.P" to "XXXUSDT".
    *   `get_instrument_info(symbol: str) -> dict`: Fetches market data for a symbol, including leverage tiers, min/max order quantity, quantity step, tick size.
    *   `set_leverage(symbol: str, leverage: int)`: Sets leverage for the given symbol.
    *   `get_usdt_balance() -> float`: Fetches the USDT balance from the CONTRACT or UNIFIED account.
    *   `place_limit_order(symbol: str, side: str, qty: float, price: float, sl: float, tp: float) -> dict`: Places the limit order with SL/TP.
    *   Wraps API calls with error handling and logging.

### 5.5. `src/signal_processor.py`

*   Contains the core logic to process a validated signal.
*   `async process_signal(signal: TradingViewSignal)`:
    1.  Normalize symbol (e.g., "SOLUSDT.P" -> "SOLUSDT").
    2.  Fetch instrument information using `BybitService`.
    3.  Determine max leverage from instrument info. Apply `max_leverage_cap` from config if set.
    4.  Set leverage for the symbol using `BybitService`.
    5.  Calculate VaR:
        *   If `var_type` is "fixed_amount", VaR is `var_value`.
        *   If `var_type` is "portfolio_percentage", fetch USDT balance using `BybitService` and calculate `VaR = balance * var_value`.
    6.  Calculate order quantity:
        *   `price_diff_per_contract = abs(signal.entry - signal.stop_loss)`
        *   `raw_qty = var_amount / price_diff_per_contract`
        *   Adjust `raw_qty` based on `minOrderQty` and `qtyStep` from instrument info.
           `qty = floor(raw_qty / qty_step) * qty_step`. Ensure `qty >= min_order_qty`.
    7.  Convert signal side ("long", "short") to Bybit API side ("Buy", "Sell").
    8.  Place the limit order using `BybitService` with entry, SL, TP, and calculated quantity.
    9.  Log success or failure.

### 5.6. `src/main.py` (FastAPI Application)

*   Initializes FastAPI app.
*   Initializes `BybitService` and other services.
*   Defines the webhook endpoint (e.g., `/webhook/tradingview`):
    *   Accepts POST requests.
    *   Uses the `TradingViewSignal` Pydantic model to validate the incoming JSON payload.
    *   Handles requests asynchronously.
    *   For each valid signal, calls `signal_processor.process_signal(signal)` asynchronously (e.g., using `asyncio.create_task` or simply `await` if sequential processing per request is acceptable and FastAPI handles concurrency between requests).
    *   Returns an appropriate HTTP response (e.g., 200 OK on successful receipt, 400 on validation error).

## 6. Detailed Workflow (Single Webhook Event)

1.  TradingView alert triggers and sends a JSON payload to the bot's webhook endpoint (e.g., `http://<your_bot_ip_or_domain>:<port>/webhook/tradingview`).
2.  **`main.py` (FastAPI):**
    *   Receives the POST request.
    *   Validates the JSON payload against the `TradingViewSignal` Pydantic model. If invalid, returns a 400 error.
    *   Logs the received signal.
    *   Asynchronously calls `signal_processor.process_signal()` with the validated signal data.
    *   Returns a 200 OK response to TradingView immediately to acknowledge receipt.
3.  **`signal_processor.process_signal()`:**
    *   **Symbol Normalization:** Converts `signal.symbol` (e.g., "SOLUSDT.P") to "SOLUSDT".
    *   **Fetch Instrument Info:** Calls `bybit_service.get_instrument_info()` for the normalized symbol. This provides:
        *   `leverageFilter.maxLeverage`
        *   `lotSizeFilter.minOrderQty`, `lotSizeFilter.qtyStep`
        *   `priceFilter.tickSize` (for potential price adjustments, though entry price is given)
    *   **Set Leverage:**
        *   Determines the target leverage (exchange max or config cap).
        *   Calls `bybit_service.set_leverage()` for the symbol and side.
    *   **Calculate VaR:**
        *   Retrieves `var_type` and `var_value` from `config.json`.
        *   If `var_type == "portfolio_percentage"`:
            *   Calls `bybit_service.get_usdt_balance()`.
            *   `var_amount = balance * var_value`.
        *   Else (`var_type == "fixed_amount"`):
            *   `var_amount = var_value`.
        *   Logs the calculated VaR amount.
    *   **Calculate Order Quantity (`qty`):**
        *   `price_difference = abs(signal.entry - signal.stop_loss)`
        *   If `price_difference == 0`, log an error and abort (to prevent division by zero).
        *   `target_qty_raw = var_amount / price_difference`
        *   `qty_step = instrument_info['lotSizeFilter']['qtyStep']`
        *   `min_qty = instrument_info['lotSizeFilter']['minOrderQty']`
        *   `adjusted_qty = floor(target_qty_raw / float(qty_step)) * float(qty_step)` (ensure types are float for division).
        *   If `adjusted_qty < float(min_qty)`, log a warning/error (VaR might be too small for min order size) and decide whether to proceed with `min_qty` (risking more than VaR) or abort. For now, let's assume we abort or log and don't trade if `adjusted_qty` is too low.
        *   Logs the calculated `adjusted_qty`.
    *   **Prepare Order Details:**
        *   `order_side = "Buy"` if `signal.side == "long"`, else `"Sell"`.
    *   **Place Order:** Calls `bybit_service.place_limit_order()` with:
        *   `symbol`: normalized symbol
        *   `category`: from `config.json` (e.g., "linear")
        *   `side`: `order_side`
        *   `orderType`: "Limit"
        *   `qty`: `adjusted_qty` (as a string, respecting Bybit's format)
        *   `price`: `signal.entry` (as a string)
        *   `takeProfit`: `signal.take_profit` (as a string)
        *   `stopLoss`: `signal.stop_loss` (as a string)
        *   `timeInForce`: from `config.json` (e.g., "GTC")
        *   (Optionally `orderLinkId` for custom tracking)
    *   Logs the outcome of the order placement (success with order ID, or failure with error message).

## 7. Error Handling & Logging

*   **Logging:**
    *   Implement structured logging using `logger_setup.py`.
    *   Log key events: webhook receipt, signal parsing, VaR calculation, quantity calculation, API requests/responses (or summaries), errors.
    *   Log to both console (for development) and a rotating log file (for production).
*   **Error Handling:**
    *   Use `try-except` blocks for API calls in `bybit_service.py` and critical sections in `signal_processor.py`.
    *   Handle `ccxt` specific exceptions (e.g., `NetworkError`, `ExchangeError`, `InsufficientFunds`).
    *   Handle validation errors from Pydantic gracefully in `main.py`.
    *   Log errors with stack traces for easier debugging.
    *   If an error occurs during signal processing, ensure it doesn't crash the entire bot. The specific signal processing might fail, but the webhook server should remain operational.

## 8. Testing (Brief Outline)

*   **Unit Tests:** For `config.py`, `signal_parser.py` logic (VaR, qty calculation), `bybit_service.py` (mocking `ccxt` calls).
*   **Integration Tests:** Test the webhook endpoint with mock TradingView payloads and potentially a mock Bybit API or use the Bybit testnet (though the user specified Mainnet Live for final implementation, testnet is crucial for dev).
*   **Manual Testing:** Send test webhooks (e.g., using Postman or `curl`) to the running application.

## 9. Deployment (Brief Outline)

*   The FastAPI application can be run using Uvicorn: `uvicorn src.main:app --host 0.0.0.0 --port 8000`.
*   For external access from TradingView:
    *   **Local Development:** Use `ngrok` to expose the local webhook endpoint.
    *   **Production:** Deploy on a VPS, cloud platform (AWS, GCP, Azure), or a serverless function environment that supports long-running processes if needed, or ensure FastAPI can handle the load.
*   Consider containerization with Docker for easier deployment and dependency management.
*   Ensure the server running the bot has a stable internet connection and is secure.