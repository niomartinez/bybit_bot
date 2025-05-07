import os
import asyncio # Import asyncio
from src.config_manager import config_manager
from src.logging_service import logger_instance as logger # Renaming for convenience
from src.data_ingestion import DataIngestionModule # Import DataIngestionModule

async def main(): # Make main async
    logger.info("Crypto Scanner Bot starting...")
    logger.info(f"Successfully loaded configuration for exchange: {config_manager.get('cex_api.exchange_id')}")
    logger.info(f"Testnet mode: {config_manager.get('cex_api.testnet')}")
    logger.info(f"Active API URL: {config_manager.get('cex_api.active_api_url')}")

    # Initialize Data Ingestion Module
    data_module = DataIngestionModule(config_manager, logger)
    initialized = await data_module.initialize() # Call the new async initialize method

    if not initialized or not data_module.exchange: # Check initialization success
        logger.error("Failed to initialize Data Ingestion Module. Exiting.")
        return

    # Example: Fetch data for the first coin in the scan list
    coins_to_scan = config_manager.get("portfolio.coins_to_scan", [])
    exec_timeframe = config_manager.get("strategy_params.timeframes.execution", "5m")

    if coins_to_scan:
        first_coin = coins_to_scan[0]
        logger.info(f"Attempting to fetch initial OHLCV for {first_coin} ({exec_timeframe})...")
        ohlcv_data = await data_module.fetch_ohlcv(symbol=first_coin, timeframe=exec_timeframe, limit=5)
        if ohlcv_data is not None and not ohlcv_data.empty: # Check if DataFrame is not None and not empty
            logger.info(f"Successfully fetched {len(ohlcv_data)} candles for {first_coin}.")
            logger.debug(f"Last candle for {first_coin}:\n{ohlcv_data.tail(1)}") # Log actual data
        else:
            logger.warning(f"Could not fetch initial OHLCV for {first_coin}.")
    else:
        logger.warning("No coins configured to scan in portfolio.coins_to_scan")

    # TODO: Start scanner logic (will involve more async operations)

    # Close the exchange connection when done
    await data_module.close()
    logger.info("Crypto Scanner Bot finished.")

if __name__ == "__main__":
    asyncio.run(main()) # Run the async main function 