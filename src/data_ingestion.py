import ccxt.async_support as ccxt # Use async version of ccxt
import pandas as pd
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import time # For retry delay
import asyncio # For sleep

class DataIngestionModule:
    def __init__(self, config_manager, logger_object):
        self.config_manager = config_manager
        self.logger = logger_object.bind(name="DataIngestionModule")
        self.cex_api_config = self.config_manager.get_cex_api_config()
        self.exchange = None # Initialize to None
        self.contract_specs_cache: Dict[str, Dict[str, Any]] = {}
        self.markets_loaded = False # Flag to indicate if markets were attempted to load

    async def initialize(self):
        """Asynchronously initializes the exchange client."""
        exchange_id = self.cex_api_config.get('exchange_id')
        api_key = self.cex_api_config.get('api_key')
        api_secret = self.cex_api_config.get('api_secret')

        if not exchange_id or not api_key or not api_secret:
            self.logger.error("Exchange ID, API Key, or API Secret is missing in configuration.")
            return False

        try:
            exchange_class = getattr(ccxt, exchange_id)
            active_url = self.cex_api_config.get('active_api_url') 
            if not active_url:
                 self.logger.error("Active API URL is missing in configuration. Cannot initialize exchange.")
                 return False
                 
            exchange_params = {
                'apiKey': api_key,
                'secret': api_secret,
                'urls': { # Explicitly set the API URL dictionary
                    'api': {
                        'public': active_url,
                        'private': active_url,
                    }
                }, 
                'options': {
                    'defaultType': 'future' # Keep this to hint other methods
                },
                'verbose': False  # <--- ADD THIS FOR CCXT HTTP LOGGING
            }

            self.logger.info(f"Initializing {exchange_id} exchange. Target URL: {active_url}")
            self.exchange = exchange_class(exchange_params)
            
            # Do NOT call load_markets() here for demo account due to fetch_currencies incompatibility
            self.logger.info(f"{exchange_id} client initialized. Markets will be fetched on demand.")
            self.markets_loaded = False # Mark as not loaded
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
                # fetch_ohlcv should work with defaultType hint even if load_markets wasn't fully run
                ohlcv_raw = await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
                
                if not ohlcv_raw:
                    self.logger.warning(f"No OHLCV data returned for {symbol} on {timeframe}.")
                    return None

                df = pd.DataFrame(ohlcv_raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                df.set_index('timestamp', inplace=True)
                
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)

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
                return None 
            except ccxt.ExchangeError as e:
                self.logger.error(f"Exchange error fetching OHLCV for {symbol}: {e}")
                return None 
            except Exception as e:
                self.logger.exception(f"Unexpected error fetching OHLCV for {symbol}: {e}")
                return None
        return None

    async def get_contract_specs(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetches and parses instrument info directly for the given symbol."""
        if not self.exchange:
            self.logger.error("Exchange not initialized. Call initialize() first.")
            return None

        if symbol in self.contract_specs_cache:
            self.logger.debug(f"Returning cached contract specs for {symbol}.")
            return self.contract_specs_cache[symbol]

        try:
            self.logger.info(f"Fetching instruments info for symbol: {symbol}...")
            # Use fetch_instruments_info (maps to /v5/market/instruments-info)
            # Requires category parameter for Bybit V5
            params = {
                'category': 'linear', # Assuming we only trade linear contracts (USDT perps)
                'symbol': symbol
            }
            # Try the implicit method name corresponding to the API endpoint
            # instrument_info_list = await self.exchange.fetch_instruments_info(params=params)
            response = None # Initialize before try
            try:
                self.logger.debug(f"Calling public_get_v5_market_instruments_info for {symbol}...")
                response = await self.exchange.public_get_v5_market_instruments_info(params=params)
                self.logger.debug(f"Received response from public_get_v5_market_instruments_info for {symbol}: {response}")
            except KeyError as ke:
                self.logger.error(f"Caught KeyError during public_get_v5_market_instruments_info call for {symbol}: {ke}", exc_info=True)
                return None
            except ccxt.ExchangeError as e:
                self.logger.error(f"ExchangeError fetching instrument info for {symbol}: {e}")
                return None
            except Exception as e:
                self.logger.exception(f"Unexpected error during API call for instrument info for {symbol}: {e}")
                return None
            
            # If API call succeeded, now validate the response structure and retCode
            if response is None:
                 self.logger.error(f"API call for instrument info for {symbol} returned None unexpectedly.")
                 return None

            # The response structure for this endpoint contains a 'result' object, and inside it, a 'list'
            # {'retCode': 0, 'retMsg': 'OK', 'result': {'category': 'linear', 'list': [...]}, ...}
            instrument_info_list = response.get('result', {}).get('list', [])

            # Example Response Structure (for one instrument in the list):
            # {
            #     'symbol': 'BTCUSDT',
            #     'contractType': 'LinearPerpetual',
            #     'status': 'Trading',
            #     'baseCoin': 'BTC',
            #     'quoteCoin': 'USDT',
            #     'launchTime': '1585526400000',
            #     'deliveryTime': '0',
            #     'deliveryFeeRate': '',
            #     'priceScale': '2', # Corresponds to tickSize precision
            #     'leverageFilter': { 'minLeverage': '1', 'maxLeverage': '100.00', 'leverageStep': '0.01' },
            #     'priceFilter': { 'minPrice': '0.50', 'maxPrice': '999999.00', 'tickSize': '0.50' },
            #     'lotSizeFilter': { 'maxOrderQty': '100.000', 'minOrderQty': '0.001', 'qtyStep': '0.001', 'postOnlyMaxOrderQty': '1000.000' },
            #     'unifiedMarginTrade': True,
            #     'fundingInterval': 480,
            #     'settleCoin': 'USDT'
            # }
            
            if not instrument_info_list or not isinstance(instrument_info_list, list) or len(instrument_info_list) == 0:
                 self.logger.error(f"Instruments info list is empty or invalid for symbol {symbol}.")
                 return None
            
            # Find the specific instrument from the list (usually fetch_instruments_info returns a list even if one symbol is queried)
            market_info = None
            for item in instrument_info_list:
                if item.get('symbol') == symbol:
                    market_info = item
                    break
            
            if not market_info:
                self.logger.error(f"Instruments info for symbol {symbol} not found in the response list.")
                return None

            # Parse the info into the format RiskManagementModule expects
            lot_size_filter = market_info.get('lotSizeFilter', {})
            price_filter = market_info.get('priceFilter', {})
            
            specs = {
                'symbol': market_info.get('symbol'),
                'active': market_info.get('status') == 'Trading',
                'type': market_info.get('contractType', '').lower(), # e.g., linearperpetual -> swap/future?
                'linear': market_info.get('settleCoin') == market_info.get('quoteCoin'), # Heuristic
                'inverse': market_info.get('settleCoin') == market_info.get('baseCoin'), # Heuristic
                'settle': market_info.get('settleCoin'),
                'quote': market_info.get('quoteCoin'),
                'base': market_info.get('baseCoin'),
                
                # Precision/Steps
                'tick_size': float(price_filter.get('tickSize', 0)) if price_filter.get('tickSize') else None,
                'lot_size': float(lot_size_filter.get('qtyStep', 0)) if lot_size_filter.get('qtyStep') else None, # This is quantity_step
                'price_precision': int(market_info.get('priceScale', 2)), # Usually available directly
                # amount_precision might need to be derived from qtyStep
                
                # Contract Size (Assume 1 for linear perpetuals if not explicitly provided)
                'contract_size': market_info.get('contractSize', 1.0), # Defaulting to 1.0
                                
                # Limits
                'min_amount': float(lot_size_filter.get('minOrderQty', 0)) if lot_size_filter.get('minOrderQty') else None,
                'max_amount': float(lot_size_filter.get('maxOrderQty', 0)) if lot_size_filter.get('maxOrderQty') else None,
                'min_price': float(price_filter.get('minPrice', 0)) if price_filter.get('minPrice') else None,
                'max_price': float(price_filter.get('maxPrice', 0)) if price_filter.get('maxPrice') else None,
                # min/max cost not directly available here, might need calculation or other endpoints
                
                # Other useful info
                'leverage_filter': market_info.get('leverageFilter'),
                'funding_interval_minutes': market_info.get('fundingInterval'),
                # Fees might need fetchTradingFees endpoint
                'taker_fee_rate': None, # Placeholder
                'maker_fee_rate': None, # Placeholder
            }

            # Remap type for consistency if needed (e.g., 'linearperpetual' -> 'swap')
            if 'perpetual' in specs['type']:
                specs['type'] = 'swap'
            
            # Derive amount precision from lot_size (qtyStep)
            if specs['lot_size'] is not None and specs['lot_size'] > 0:
                 lot_size_str = f"{specs['lot_size']:.10f}".rstrip('0')
                 if '.' in lot_size_str:
                     specs['amount_precision'] = len(lot_size_str.split('.')[1])
                 else:
                     specs['amount_precision'] = 0
            else:
                specs['amount_precision'] = None

            # Validate critical specs needed by RiskManagementModule
            if specs['tick_size'] is None or specs['lot_size'] is None or specs['min_amount'] is None:
                self.logger.error(f"Critical specs (tick_size, lot_size/qtyStep, min_amount/minOrderQty) missing in fetched instrument info for {symbol}: {market_info}")
                return None
            
            self.contract_specs_cache[symbol] = specs
            self.logger.info(f"Fetched and cached contract specs for {symbol} via instruments-info.")
            return specs

        except ccxt.ExchangeError as e: # This might be redundant now but kept as fallback
            self.logger.error(f"Exchange error fetching instrument info for {symbol}: {e}")
            return None
        except Exception as e: # General fallback for parsing errors etc.
            self.logger.exception(f"Unexpected error processing instrument info for {symbol}: {e}")
            return None

    async def close(self):
        if self.exchange:
            self.logger.info(f"Closing connection to {self.exchange.id}.")
            # Need to handle potential exceptions during close
            try:
                await self.exchange.close()
                self.logger.info(f"Connection to {self.exchange.id} closed.")
            except Exception as e:
                 self.logger.error(f"Error closing exchange connection: {e}", exc_info=True)
            finally:
                 self.exchange = None # Ensure it's reset even if close fails

# Example usage (for testing)
# The test needs adjustment as load_markets is no longer called in initialize
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
            # Test get_contract_specs directly now
            specs = await data_module.get_contract_specs(coin)
            if specs:
                main_logger.info(f"Contract Specs for {coin}: Tick Size: {specs.get('tick_size')}, Lot Size (Qty Step): {specs.get('lot_size')}, Min Amount: {specs.get('min_amount')}")
                main_logger.debug(f"Full Specs: {specs}")
            else:
                main_logger.warning(f"Could not get contract specs for {coin}.")
                continue # Skip fetching OHLCV if specs failed
            
            await asyncio.sleep(0.5) # Add delay between symbols

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
            await asyncio.sleep(1.0) # Avoid potential rate limits

        await data_module.close()
        main_logger.info("DataIngestionModule test finished.")

    # Ensure logs directory exists for the main logger
    log_config = config_manager.get_logging_config()
    log_file_path = Path(log_config.get("log_file", "logs/bot.log"))
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    
    asyncio.run(test_data_ingestion()) 