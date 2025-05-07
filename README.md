# Bybit Futures Trading Scanner & Bot

This project is a Python-based system to scan cryptocurrency futures markets on Bybit for trading setups based on the "5m/15m BOS/FVG/Fib Confluence - $1 Fixed Risk" strategy. It also includes plans for future extensions into an algorithmic trading bot.

**Strategy Document:** [Trading_Strategy_5m_15m_BOS_FVG_Fib_Confluence.md](Trading_Strategy_5m_15m_BOS_FVG_Fib_Confluence.md)
**Implementation Plan:** [Implementation_Plan_Crypto_Scanner_Bot.md](Implementation_Plan_Crypto_Scanner_Bot.md)
**Progress Summary:** [PROGRESS_SUMMARY.md](PROGRESS_SUMMARY.md)

## Current Features (Scanner Focus)

*   Connects to Bybit (testnet by default) via `ccxt`.
*   Loads configuration from `config.json` and API secrets from `.env`.
*   Comprehensive logging to console and file (`logs/bot.log`) using `loguru`.
*   **Data Ingestion:**
    *   Fetches and processes OHLCV data into Pandas DataFrames.
    *   Fetches and caches contract specifications (tick size, lot size, etc.).
*   **Analysis Engine (In Progress):**
    *   Detects Swing Highs and Swing Lows.
    *   Detects Break of Structure (BOS) events.

## Setup Instructions

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd bybit_bot
    ```

2.  **Python Version:**
    Ensure you have Python 3.9+ installed. You can check with `python --version` or `python3 --version`.

3.  **Create a Virtual Environment:**
    It's highly recommended to use a virtual environment to manage dependencies.
    ```bash
    python3 -m venv venv
    ```

4.  **Activate the Virtual Environment:**
    *   On macOS and Linux:
        ```bash
        source venv/bin/activate
        ```
    *   On Windows:
        ```bash
        .\venv\Scripts\activate
        ```
    Your terminal prompt should change to indicate the virtual environment is active (e.g., `(venv) ...`).

5.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

6.  **Configure API Keys:**
    *   Copy the example environment file:
        ```bash
        cp example.env .env
        ```
    *   Open the `.env` file in a text editor.
    *   Add your Bybit API key and secret. For initial development and testing, use **Testnet V5 API keys**.
        *   You can generate these from [Bybit Testnet](https://testnet.bybit.com) after logging in.
        *   Ensure the keys have appropriate permissions (Read-Only for scanner, trade permissions if you intend to develop bot features).
    *   The `.env` file should look like this (replace placeholders):
        ```env
        TESTNET_BYBIT_API_KEY="YOUR_TESTNET_API_KEY_HERE"
        TESTNET_BYBIT_API_SECRET="YOUR_TESTNET_API_SECRET_HERE"
        ```

7.  **Review Configuration (`config.json`):
    *   Open `config.json` and review the default settings.
    *   By default, it's set to use Bybit testnet (`"testnet": true`).
    *   It uses `TESTNET_BYBIT_API_KEY` and `TESTNET_BYBIT_API_SECRET` from your `.env` file.
    *   Adjust `coins_to_scan`, strategy parameters, etc., as needed for your testing.

## Running the Application

To run the main application (which currently performs a test data fetch and initial analysis steps):

```bash
python -m src.main
```

This command should be run from the project root directory (`bybit_bot`).

## Running Individual Module Tests

Each core module in the `src/` directory often contains an `if __name__ == '__main__':` block for direct testing of its functionality. You can run these similarly:

```bash
python -m src.config_manager
python -m src.logging_service # (May need config loaded if run standalone without context)
python -m src.data_ingestion
python -m src.analysis_engine
```

Make sure your virtual environment is active when running these commands.

## Development

(Details about development workflow, branching strategy, etc., can be added here later.)

## Next Steps

Refer to [PROGRESS_SUMMARY.md](PROGRESS_SUMMARY.md) for the latest development status and immediate next steps.