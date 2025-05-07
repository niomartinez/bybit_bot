import ccxt.async_support as ccxt # Use async version of ccxt
import pandas as pd
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import time # For retry delay

class DataIngestionModule:
    def __init__(self, config_manager, logger_object):
        self.config_manager = config_manager
        self.logger = logger_object.bind(name="DataIngestionModule")
        self.cex_api_config = self.config_manager.get_cex_api_config()
        self.exchange = None # Initialize to None
        self.contract_specs_cache: Dict[str, Dict[str, Any]] = {}
        # self._initialize_exchange() # Call this in an async context if needed, or make it synchronous

    async def initialize(self):
        """Asynchronously initializes the exchange client and loads markets."""
        exchange_id = self.cex_api_config.get('exchange_id')
        api_key = self.cex_api_config.get('api_key')
        api_secret = self.cex_api_config.get('api_secret')
        is_testnet = self.cex_api_config.get('testnet', False)

        if not exchange_id or not api_key or not api_secret:
            self.logger.error("Exchange ID, API Key, or API Secret is missing in configuration.")
            return False

        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange_params = {
                'apiKey': api_key,
                'secret': api_secret,
            }
            
            if is_testnet:
                exchange_params['options'] = {'defaultType': 'future', 'testnet': True}

            self.logger.info(f"Initializing {exchange_id} exchange. Testnet: {is_testnet}")
            self.exchange = exchange_class(exchange_params)
            
            self.logger.info(f"Loading markets for {exchange_id}...")
            await self.exchange.load_markets()
            self.logger.info(f"Markets loaded. {exchange_id} client initialized. API URL: {self.exchange.urls['api']}")
            return True
        except AttributeError:
            self.logger.error(f"Exchange '{exchange_id}' is not supported by ccxt.")
            self.exchange = None
            return False
        except Exception as e:
            self.logger.exception(f"Failed to initialize {exchange_id} exchange: {e}")
            self.exchange = None
            return False

    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: int = None, limit: int = None) -> Optional[pd.DataFrame]:
        if not self.exchange:
            self.logger.error("Exchange not initialized. Call initialize() first. Cannot fetch OHLCV.")
            return None
        
        retries = self.cex_api_config.get("rate_limit_retry_attempts", 3)
        delay = self.cex_api_config.get("rate_limit_retry_delay_seconds", 60)

        for attempt in range(retries):
            try:
                self.logger.info(f"Fetching OHLCV for {symbol} on {timeframe} (Attempt {attempt + 1}/{retries})...")
                ohlcv_raw = await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
                
                if not ohlcv_raw:
                    self.logger.warning(f"No OHLCV data returned for {symbol} on {timeframe}.")
                    return None

                df = pd.DataFrame(ohlcv_raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                df.set_index('timestamp', inplace=True)
                
                # Ensure numeric types for OHLCV columns
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True) # Drop rows where essential OHLC is NaN

                self.logger.info(f"Successfully fetched and processed {len(df)} candles for {symbol} on {timeframe}.")
                return df
            
            except ccxt.RateLimitExceeded as e:
                self.logger.warning(f"Rate limit exceeded for {symbol} ({timeframe}). Attempt {attempt + 1}/{retries}. Retrying in {delay}s... Error: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(f"Failed to fetch OHLCV for {symbol} after {retries} attempts due to rate limiting.")
                    return None
            except ccxt.NetworkError as e:
                self.logger.error(f"Network error fetching OHLCV for {symbol}: {e}")
                return None # No retry on general network error for now, could be more nuanced
            except ccxt.ExchangeError as e:
                self.logger.error(f"Exchange error fetching OHLCV for {symbol}: {e}")
                return None # No retry on general exchange error
            except Exception as e:
                self.logger.exception(f"Unexpected error fetching OHLCV for {symbol}: {e}")
                return None
        return None

    async def get_contract_specs(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.exchange or not self.exchange.markets:
            self.logger.error("Exchange not initialized or markets not loaded. Call initialize() first.")
            return None

        if symbol in self.contract_specs_cache:
            self.logger.debug(f"Returning cached contract specs for {symbol}.")
            return self.contract_specs_cache[symbol]

        try:
            market = self.exchange.market(symbol)
            if not market:
                self.logger.warning(f"Market details not found for symbol: {symbol}")
                return None

            # Relevant information based on Implementation Plan & general use
            specs = {
                'symbol': symbol,
                'active': market.get('active'),
                'type': market.get('type'), # spot, future, swap
                'linear': market.get('linear'),
                'inverse': market.get('inverse'),
                'settle': market.get('settle'), # e.g., 'USDT', 'BTC'
                'quote': market.get('quote'), # e.g., 'USDT'
                'base': market.get('base'), # e.g., 'BTC'
                
                # Precision
                'price_precision': market.get('precision', {}).get('price'), # Number of decimal places for price
                'amount_precision': market.get('precision', {}).get('amount'), # Number of decimal places for amount/qty
                'cost_precision': market.get('precision', {}).get('cost'),
                
                # Tick size (minimum price increment)
                'tick_size': market.get('info', {}).get('tickDirection') == 'buy' and market.get('info', {}).get('priceFilter', {}).get('tickSize') or market.get('precision', {}).get('price'), # Heuristic for tickSize, might need exchange specific logic
                                                                                                # A more reliable way is often from market['info'] if available and consistent
                                                                                                # For Bybit V5, look at market['info']['priceFilter']['tickSize'] for linear contracts.
                                                                                                
                # Contract/Lot Size
                'contract_size': market.get('contractSize'), # Value of 1 contract in base currency (for futures)
                'lot_size': market.get('info', {}).get('lotSizeFilter', {}).get('qtyStep'), # For Bybit V5 linear, this is qtyStep
                
                # Limits
                'min_amount': market.get('limits', {}).get('amount', {}).get('min'),
                'max_amount': market.get('limits', {}).get('amount', {}).get('max'),
                'min_cost': market.get('limits', {}).get('cost', {}).get('min'),
                'max_cost': market.get('limits', {}).get('cost', {}).get('max'),
                'min_price': market.get('limits', {}).get('price', {}).get('min'),
                'max_price': market.get('limits', {}).get('price', {}).get('max'),
                
                # Bybit specific for futures (example, may vary with API version and contract type)
                'leverage_tiers': market.get('info', {}).get('leverageFilter', {}).get('leveragebrackets'), # For V5
                'contract_multiplier': market.get('info', {}).get('contractMultiplier'), # Often 1 for linear USDT contracts
                'taker_fee_rate': market.get('taker'),
                'maker_fee_rate': market.get('maker'),
            }
            
            # Refine tick_size for Bybit V5 specifically for linear contracts
            if self.cex_api_config.get('exchange_id') == 'bybit' and market.get('linear'):
                price_filter = market.get('info', {}).get('priceFilter', {})
                if price_filter and 'tickSize' in price_filter:
                    specs['tick_size'] = float(price_filter['tickSize'])
            
            # Refine lot_size (qtyStep) for Bybit V5
            if self.cex_api_config.get('exchange_id') == 'bybit':
                lot_size_filter = market.get('info', {}).get('lotSizeFilter', {})
                if lot_size_filter and 'qtyStep' in lot_size_filter:
                     specs['lot_size'] = float(lot_size_filter['qtyStep'])
                if lot_size_filter and 'minOrderQty' in lot_size_filter:
                     specs['min_amount'] = float(lot_size_filter['minOrderQty'])
                if lot_size_filter and 'maxOrderQty' in lot_size_filter:
                    specs['max_amount'] = float(lot_size_filter['maxOrderQty'])

            self.contract_specs_cache[symbol] = specs
            self.logger.info(f"Fetched and cached contract specs for {symbol}.")
            # self.logger.debug(f"Specs for {symbol}: {specs}")
            return specs

        except ccxt.ExchangeError as e:
            self.logger.error(f"Exchange error fetching contract specs for {symbol}: {e}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error fetching contract specs for {symbol}: {e}")
            return None

    async def close(self):
        if self.exchange:
            self.logger.info(f"Closing connection to {self.exchange.id}.")
            await self.exchange.close()
            self.logger.info(f"Connection to {self.exchange.id} closed.")
            self.exchange = None # Ensure it's reset

# Example usage (for testing)
if __name__ == '__main__':
    import asyncio
    from .config_manager import config_manager 
    from .logging_service import logger_instance as main_logger

    async def test_data_ingestion():
        main_logger.info("Starting DataIngestionModule test...")
        data_module = DataIngestionModule(config_manager, main_logger)
        initialized = await data_module.initialize()
        
        if not initialized or not data_module.exchange:
            main_logger.error("Failed to initialize DataIngestionModule for testing. Exiting.")
            return

        coins_to_scan = config_manager.get("portfolio.coins_to_scan", [])
        exec_timeframe = config_manager.get("strategy_params.timeframes.execution", "5m")
        context_timeframe = config_manager.get("strategy_params.timeframes.contextual", "15m")

        if not coins_to_scan:
            main_logger.warning("No coins configured to scan in portfolio.coins_to_scan")
            await data_module.close()
            return

        for coin in coins_to_scan:
            main_logger.info(f"--- Testing for {coin} ---")
            specs = await data_module.get_contract_specs(coin)
            if specs:
                main_logger.info(f"Contract Specs for {coin}: Tick Size: {specs.get('tick_size')}, Lot Size (Qty Step): {specs.get('lot_size')}, Min Amount: {specs.get('min_amount')}")
            else:
                main_logger.warning(f"Could not get contract specs for {coin}.")

            main_logger.info(f"Attempting to fetch OHLCV for {coin} ({exec_timeframe}, limit 5)...")
            ohlcv_5m = await data_module.fetch_ohlcv(symbol=coin, timeframe=exec_timeframe, limit=5)
            if ohlcv_5m is not None and not ohlcv_5m.empty:
                main_logger.info(f"Fetched 5m data for {coin}. Shape: {ohlcv_5m.shape}")
                main_logger.info(f"Last 5m candle:\n{ohlcv_5m.tail(1)}")
            else:
                main_logger.warning(f"No 5m OHLCV data fetched for {coin} or DataFrame is empty.")

            main_logger.info(f"Attempting to fetch OHLCV for {coin} ({context_timeframe}, limit 3)...")
            ohlcv_15m = await data_module.fetch_ohlcv(symbol=coin, timeframe=context_timeframe, limit=3)
            if ohlcv_15m is not None and not ohlcv_15m.empty:
                main_logger.info(f"Fetched 15m data for {coin}. Shape: {ohlcv_15m.shape}")
                main_logger.info(f"Last 15m candle:\n{ohlcv_15m.tail(1)}")
            else:
                main_logger.warning(f"No 15m OHLCV data fetched for {coin} or DataFrame is empty.")
            main_logger.info(f"--- Finished testing for {coin} ---")

        await data_module.close()
        main_logger.info("DataIngestionModule test finished.")

    asyncio.run(test_data_ingestion()) 