"""
Bybit API service for interacting with the Bybit exchange.
"""

import ccxt
import re
import time
import math
from typing import Dict, Any, Tuple, Optional, List, Union
from src.config import get_api_credentials, config, logger

class BybitService:
    """
    Service for interacting with the Bybit API.
    """
    
    def __init__(self):
        """Initialize the Bybit API service."""
        self.api_key, self.api_secret = get_api_credentials()
        self.exchange = self._initialize_exchange()
        self._load_markets()
        logger.info("BybitService initialized")
    
    def _initialize_exchange(self) -> ccxt.bybit:
        """
        Initialize the CCXT Bybit exchange object.
        
        Returns:
            ccxt.bybit: Initialized exchange object
        """
        try:
            exchange = ccxt.bybit({
                'apiKey': self.api_key,
                'secret': self.api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'linear',  # For USDT perpetuals on Bybit
                    'recvWindow': 5000,     # ms to wait for the exchange to respond
                    'adjustForTimeDifference': True,
                    # V5 API specific options - CRITICAL for unified account
                    'brokerId': 'ccxt',
                    'accountType': 'unified',  # Use unified trading account for V5
                    # Ensure we're using the latest API version
                    'version': 'v5',
                    # Request format - important for V5 API
                    'timeout': 30000,  # 30 seconds timeout
                    # Market loading options
                    'loadMarkets': True,
                    # V5 API specific settings
                    'unified': True,  # Enable unified account mode
                    'marginMode': 'cross',  # Use cross margin by default
                    # Ensure proper API endpoint
                    'sandBox': False,  # Set to True for testnet
                }
            })
            
            # Set additional options for V5 API
            exchange.options['unified'] = True
            exchange.options['accountType'] = 'unified'
            
            logger.info("Bybit exchange object created with V5 API unified account configuration")
            
            # Try to load markets for different types to ensure we get everything
            logger.info("Loading markets for V5 unified account...")
            
            # Load linear markets (perpetuals) first
            exchange.options['defaultType'] = 'linear'
            try:
                exchange.load_markets()
                linear_count = len([m for m in exchange.markets.values() if m.get('type') in ['swap', 'future']])
                logger.info(f"Loaded {linear_count} linear perpetual markets")
            except Exception as e:
                logger.warning(f"Failed to load linear markets: {e}")
            
            # Also load spot markets for completeness
            exchange.options['defaultType'] = 'spot'
            try:
                exchange.load_markets()
                spot_count = len([m for m in exchange.markets.values() if m.get('type') == 'spot'])
                logger.info(f"Loaded {spot_count} spot markets")
            except Exception as e:
                logger.warning(f"Failed to load spot markets: {e}")
            
            # Reset to linear as default for trading
            exchange.options['defaultType'] = 'linear'
            
            return exchange
        
        except ccxt.AuthenticationError as e:
            logger.error(f"Authentication error: {e}")
            raise
        except ccxt.NetworkError as e:
            logger.error(f"Network error: {e}")
            raise
        except Exception as e:
            logger.error(f"Error initializing Bybit exchange: {e}")
            raise
    
    def _load_markets(self):
        """Load markets and handle potential errors."""
        try:
            self.exchange.load_markets()
            logger.info("Connected to Bybit API successfully and loaded markets")
            
            # Show basic market statistics
            all_markets = list(self.exchange.markets.keys())
            total_markets = len(all_markets)
            
            # Count market types
            linear_markets = []
            spot_markets = []
            other_markets = []
            
            for market_id, market_info in self.exchange.markets.items():
                market_type = market_info.get('type', 'unknown')
                if market_type in ['swap', 'future']:
                    linear_markets.append(market_id)
                elif market_type == 'spot':
                    spot_markets.append(market_id)
                else:
                    other_markets.append(market_id)
            
            logger.info(f"Loaded {total_markets} total markets: {len(linear_markets)} linear/perpetual, {len(spot_markets)} spot, {len(other_markets)} other")
            
        except Exception as e:
            logger.error(f"Failed to load markets: {e}")
            raise
    
    def normalize_symbol(self, tv_symbol: str) -> str:
        """
        Normalize symbol from TradingView format (e.g., 'BTCUSDT.P') to Bybit format (e.g., 'BTCUSDT').
        
        Args:
            tv_symbol (str): Symbol in TradingView format
        
        Returns:
            str: Normalized symbol
        """
        # Remove .P suffix if present (indicating perpetual futures in TradingView)
        if tv_symbol.endswith('.P'):
            normalized = tv_symbol[:-2]
            logger.info(f"Normalized TradingView perpetual symbol: {tv_symbol} -> {normalized}")
            return normalized
        return tv_symbol
    
    def get_market_id(self, symbol: str, market_type: str = None) -> str:
        """
        Get the market ID from the symbol.
        
        Args:
            symbol (str): Symbol to get market ID for (e.g., 'BTCUSDT')
            market_type (str, optional): Type of market ('linear', 'inverse', 'spot'). 
                                         Defaults to config.bybit_api.category.
        
        Returns:
            str: Market ID for the symbol
        """
        # Use the provided market_type or default to the one in config
        market_type = market_type or config.bybit_api.category
        
        # Set market type in CCXT options
        self.exchange.options['defaultType'] = market_type
        
        # Reload markets with the new default type if needed
        if not hasattr(self, '_last_market_type') or self._last_market_type != market_type:
            logger.info(f"Switching market type to: {market_type}")
            self.exchange.load_markets()
            self._last_market_type = market_type
        
        # For linear/perpetual markets, prioritize the :USDT format (Bybit perpetual format)
        if market_type == 'linear':
            # Extract base asset from symbol (e.g., BTCUSDT -> BTC, SOLUSDT -> SOL)
            symbol_clean = symbol.replace('/', '').upper()
            
            # Try to extract base currency (remove common quote currencies)
            base_currency = None
            for quote in ['USDT', 'USDC', 'USD', 'BTC', 'ETH']:
                if symbol_clean.endswith(quote):
                    base_currency = symbol_clean[:-len(quote)]
                    break
            
            if base_currency:
                # Build perpetual market alternatives in priority order
                perpetual_alternatives = [
                    f"{base_currency}/USDT:USDT",    # Bybit USDT perpetual format (highest priority)
                    f"{base_currency}/USDC:USDC",    # Bybit USDC perpetual format
                    f"{base_currency}/USD:{base_currency}",  # Inverse perpetual format
                    symbol_clean,                     # Original format without slash
                    f"{base_currency}/USDT",         # Spot format (lowest priority for linear)
                ]
                
                logger.info(f"Searching for {symbol} linear perpetual in formats: {perpetual_alternatives}")
                
                # Check each alternative with verification
                for alt in perpetual_alternatives:
                    if alt in self.exchange.markets:
                        market = self.exchange.markets[alt]
                        market_info = market.get('info', {})
                        
                        # Verify this is actually a perpetual/linear market
                        is_linear_perpetual = (
                            market.get('type') in ['swap', 'future'] or
                            market_info.get('contractType') == 'LinearPerpetual' or
                            (market_info.get('quoteCoin') in ['USDT', 'USDC'] and 
                             market_info.get('status') == 'Trading' and
                             ':' in alt)  # Perpetuals have colon in CCXT format
                        )
                        
                        if is_linear_perpetual:
                            logger.info(f"✅ Found verified linear perpetual market for {symbol}: {alt}")
                            return alt
                        else:
                            logger.info(f"❌ Market '{alt}' is not a linear perpetual (type: {market.get('type')}, contractType: {market_info.get('contractType')})")
            
            # If no perpetual found with base currency extraction, try direct alternatives
            direct_alternatives = [
                symbol + ":USDT",           # Add :USDT suffix
                symbol.replace('USDT', '/USDT:USDT'),  # Convert BTCUSDT to BTC/USDT:USDT
                symbol,                      # Original format
            ]
            
            for alt in direct_alternatives:
                if alt in self.exchange.markets:
                    market = self.exchange.markets[alt]
                    market_info = market.get('info', {})
                    
                    is_linear_perpetual = (
                        market.get('type') in ['swap', 'future'] or
                        market_info.get('contractType') == 'LinearPerpetual'
                    )
                    
                    if is_linear_perpetual:
                        logger.info(f"✅ Found linear perpetual market for {symbol}: {alt}")
                        return alt
            
            logger.error(f"❌ Could not find linear perpetual market for {symbol}")
            
            # Debug: show what's available
            available_markets = list(self.exchange.markets.keys())
            if base_currency:
                matching_markets = [m for m in available_markets if base_currency in m.upper()]
                logger.error(f"Markets containing '{base_currency}': {matching_markets}")
            
            raise ValueError(f"Linear perpetual market for {symbol} not found")
        
        # Standard format checking for spot and other market types
        if symbol in self.exchange.markets:
            return symbol
        
        # Try common alternative formats
        alternatives = [
            symbol,                   # Original format (e.g., BTCUSDT)
            f"{symbol}:USDT",         # Some exchanges use this format
            f"{symbol}/USDT",         # Spot market format
            symbol.replace("USDT", "/USDT"),  # Convert BTCUSDT to BTC/USDT
        ]
        
        # If the symbol already contains a slash, add it as an alternative
        if "/" not in symbol:
            # Try to split at a common boundary (before USDT, USD, etc.)
            match = re.search(r"^(.+?)(USDT|USD|BTC|ETH)$", symbol)
            if match:
                base, quote = match.groups()
                alternatives.append(f"{base}/{quote}")
        
        # Check each alternative
        for alt in alternatives:
            if alt in self.exchange.markets:
                logger.info(f"Found market ID for {symbol} in {market_type} market: {alt}")
                return alt
        
        # If no match found and this is not linear, try linear as fallback
        if market_type != 'linear':
            try:
                logger.info(f"Trying to find {symbol} in linear market")
                return self.get_market_id(symbol, 'linear')
            except ValueError:
                pass
        
        # If still not found, log available symbols and raise an error
        logger.error(f"Symbol {symbol} not found in available {market_type} markets")
        
        # Log some available markets for debugging
        available_markets = list(self.exchange.markets.keys())
        # Filter markets that might be relevant to the symbol
        relevant_markets = [m for m in available_markets if symbol.replace('/', '').upper() in m.upper()]
        if relevant_markets:
            logger.info(f"Possibly relevant markets found: {relevant_markets[:5]}")
        else:
            logger.debug(f"Available markets (first 10): {available_markets[:10]}...")
        
        raise ValueError(f"Symbol {symbol} not found in available {market_type} markets")
    
    async def get_instrument_info(self, symbol: str) -> Dict[str, Any]:
        """
        Get instrument information for a symbol.
        
        Args:
            symbol (str): Symbol to get information for (e.g., 'BTCUSDT')
        
        Returns:
            Dict[str, Any]: Instrument information
        """
        try:
            # For perpetual futures, we should prioritize linear market type
            market_type = 'linear'  # Default to linear for .P symbols
            
            # Try to get the market ID for linear (futures) markets first
            try:
                market_id = self.get_market_id(symbol, 'linear')
                market_type = 'linear'
                logger.info(f"Found {symbol} in linear market as: {market_id}")
            except ValueError:
                # If not found in linear, try spot
                try:
                    market_id = self.get_market_id(symbol, 'spot')
                    market_type = 'spot'
                    logger.info(f"Found {symbol} in spot market as: {market_id}")
                except ValueError:
                    logger.error(f"Symbol {symbol} not found in either linear or spot markets")
                    raise
            
            # Get market info from CCXT
            instrument_info = self.exchange.markets[market_id].copy()
            instrument_info['market_type'] = market_type
            
            # For linear markets, fetch detailed instrument info from Bybit V5 API
            if market_type == 'linear':
                try:
                    logger.info(f"Fetching detailed instrument info from Bybit V5 API for {symbol}")
                    
                    # Use the normalized symbol (without .P) for Bybit API
                    bybit_symbol = symbol.replace('/', '')  # Ensure no slash
                    
                    # Call Bybit V5 instrument info API directly
                    params = {
                        'category': 'linear',
                        'symbol': bybit_symbol
                    }
                    
                    # Make direct API call to get instrument info
                    raw_response = await self._fetch_bybit_instrument_info(bybit_symbol)
                    
                    if raw_response and 'result' in raw_response and 'list' in raw_response['result']:
                        bybit_info = raw_response['result']['list'][0] if raw_response['result']['list'] else {}
                        
                        # Merge Bybit's detailed info with CCXT info
                        if 'info' not in instrument_info:
                            instrument_info['info'] = {}
                        
                        # Update with Bybit's raw instrument data
                        instrument_info['info'].update(bybit_info)
                        
                        # Extract and update leverage information
                        if 'leverageFilter' in bybit_info:
                            leverage_filter = bybit_info['leverageFilter']
                            if 'maxLeverage' in leverage_filter:
                                max_leverage = float(leverage_filter['maxLeverage'])
                                
                                # Update CCXT limits with proper leverage info
                                if 'limits' not in instrument_info:
                                    instrument_info['limits'] = {}
                                if 'leverage' not in instrument_info['limits']:
                                    instrument_info['limits']['leverage'] = {}
                                
                                instrument_info['limits']['leverage']['max'] = max_leverage
                                logger.info(f"Updated max leverage for {symbol}: {max_leverage}x")
                        
                        logger.info(f"Successfully merged Bybit V5 instrument info for {symbol}")
                    else:
                        logger.warning(f"No detailed instrument info returned from Bybit API for {symbol}")
                        
                except Exception as fetch_error:
                    logger.warning(f"Could not fetch detailed instrument info from Bybit V5 API: {fetch_error}")
                    # Continue with CCXT info even if Bybit API call fails
            
            logger.info(f"Retrieved instrument info for {symbol} (market type: {market_type})")
            return instrument_info
        
        except Exception as e:
            logger.error(f"Error getting instrument info for {symbol}: {e}")
            raise
    
    async def _fetch_bybit_instrument_info(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch instrument information directly from Bybit V5 API.
        
        Args:
            symbol (str): Symbol to fetch info for (e.g., 'BTCUSDT')
        
        Returns:
            Dict[str, Any]: Raw API response from Bybit
        """
        try:
            # Use CCXT's public API method to call Bybit V5 instrument info
            params = {
                'category': 'linear',
                'symbol': symbol
            }
            
            response = self.exchange.publicGetV5MarketInstrumentsInfo(params)
            logger.info(f"Fetched Bybit V5 instrument info for {symbol}")
            return response
            
        except Exception as e:
            logger.error(f"Error fetching Bybit V5 instrument info for {symbol}: {e}")
            return {}
    
    async def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """
        Set leverage for a symbol. Skip if the market doesn't support leverage.
        
        Args:
            symbol (str): Symbol to set leverage for (e.g., 'BTCUSDT')
            leverage (int): Leverage value
        
        Returns:
            Dict[str, Any]: Response from the API or None if not supported
        """
        try:
            # For perpetual futures, prioritize linear market
            market_id = None
            market_type = None
            
            # Try to get the market ID for linear (futures) market first
            try:
                market_id = self.get_market_id(symbol, 'linear')
                market_type = 'linear'
                logger.info(f"Setting leverage for {symbol} in linear market: {market_id}")
            except ValueError:
                # Try inverse as fallback
                try:
                    market_id = self.get_market_id(symbol, 'inverse')
                    market_type = 'inverse'
                    logger.info(f"Setting leverage for {symbol} in inverse market: {market_id}")
                except ValueError:
                    # If neither found, check if it's a spot market
                    try:
                        market_id = self.get_market_id(symbol, 'spot')
                        market_type = 'spot'
                        logger.warning(f"Symbol {symbol} is a spot market, leverage setting not applicable")
                        return {'success': False, 'message': f"Market {symbol} is spot and doesn't support leverage setting", 'leverageSet': False}
                    except ValueError:
                        logger.error(f"Symbol {symbol} not found in any market type")
                        return {'success': False, 'message': f"Symbol {symbol} not found", 'leverageSet': False}
            
            # Check if the market supports leverage
            if market_type not in ['linear', 'inverse']:
                logger.warning(f"Market {symbol} ({market_id}) type '{market_type}' doesn't support leverage setting. Skipping.")
                return {'success': False, 'message': f"Market {symbol} doesn't support leverage setting", 'leverageSet': False}
            
            # Prepare the symbol for Bybit API (ensure no slash and proper format)
            bybit_symbol = symbol.replace('/', '')  # Remove any '/' for Bybit API format
            
            # Set leverage using CCXT
            try:
                logger.info(f"Attempting to set leverage {leverage}x for {bybit_symbol} (market: {market_id}, type: {market_type})")
                
                # For V5 API, we need to specify category in params
                params = {
                    'category': market_type,
                }
                
                # Use the Bybit symbol format for the API call
                response = self.exchange.set_leverage(leverage, bybit_symbol, params=params)
                
                logger.info(f"Successfully set leverage for {symbol} to {leverage}x")
                return {'success': True, 'message': f"Set leverage to {leverage}x", 'leverageSet': True, 'response': response}
                
            except ccxt.NotSupported as e:
                logger.warning(f"Setting leverage not supported for {symbol}: {e}. This might be due to CCXT limitation.")
                
                # Try direct API call as fallback
                try:
                    logger.info(f"Trying direct Bybit API call for leverage setting")
                    leverage_response = await self._set_leverage_direct(bybit_symbol, leverage, market_type)
                    
                    if leverage_response.get('success', False):
                        logger.info(f"Successfully set leverage via direct API call for {symbol} to {leverage}x")
                        return leverage_response
                    else:
                        logger.warning(f"Direct API leverage setting also failed: {leverage_response.get('message', 'Unknown error')}")
                        return leverage_response
                        
                except Exception as direct_error:
                    logger.error(f"Direct API leverage setting failed: {direct_error}")
                    return {'success': False, 'message': f"Leverage setting not supported: {str(e)}", 'leverageSet': False}
                    
            except ccxt.ExchangeError as e:
                error_msg = str(e)
                logger.error(f"Exchange error setting leverage for {symbol}: {error_msg}")
                
                # Check for specific Bybit error codes
                if "110017" in error_msg:  # Reduce-only mode
                    return {'success': False, 'message': f"Cannot set leverage - position is in reduce-only mode", 'leverageSet': False}
                elif "110018" in error_msg:  # Position exists
                    logger.warning(f"Position exists for {symbol}, leverage change might not be allowed")
                    return {'success': False, 'message': f"Position exists - leverage cannot be changed", 'leverageSet': False}
                else:
                    return {'success': False, 'message': f"Exchange error: {error_msg}", 'leverageSet': False}
            
        except Exception as e:
            logger.error(f"Error setting leverage for {symbol}: {e}")
            return {'success': False, 'message': str(e), 'leverageSet': False}
    
    async def _set_leverage_direct(self, symbol: str, leverage: int, category: str) -> Dict[str, Any]:
        """
        Set leverage using direct Bybit V5 API call.
        
        Args:
            symbol (str): Symbol (e.g., 'BTCUSDT')
            leverage (int): Leverage value
            category (str): Market category ('linear' or 'inverse')
        
        Returns:
            Dict[str, Any]: Response from the API
        """
        try:
            # Use CCXT's private API method to call Bybit V5 set leverage
            params = {
                'category': category,
                'symbol': symbol,
                'buyLeverage': str(leverage),
                'sellLeverage': str(leverage)
            }
            
            # Use the correct CCXT method name for Bybit V5
            response = self.exchange.private_post_v5_position_set_leverage(params)
            
            if response.get('retCode') == 0:
                logger.info(f"Direct API leverage setting successful for {symbol}: {leverage}x")
                return {'success': True, 'message': f"Set leverage to {leverage}x", 'leverageSet': True, 'response': response}
            else:
                error_msg = response.get('retMsg', 'Unknown error')
                logger.error(f"Direct API leverage setting failed for {symbol}: {error_msg}")
                return {'success': False, 'message': f"API error: {error_msg}", 'leverageSet': False}
                
        except Exception as e:
            logger.error(f"Error in direct leverage API call for {symbol}: {e}")
            return {'success': False, 'message': f"Direct API call failed: {str(e)}", 'leverageSet': False}
    
    async def get_usdt_balance(self) -> float:
        """
        Get USDT balance from the account.
        
        Returns:
            float: USDT balance
        """
        try:
            # Define the portfolio currency from config
            portfolio_currency = config.risk_management.portfolio_currency
            
            # Fetch balances
            balance = self.exchange.fetch_balance()
            
            # Check if the portfolio currency exists in the balance
            if portfolio_currency not in balance:
                logger.error(f"{portfolio_currency} balance not found in account")
                raise ValueError(f"{portfolio_currency} balance not found in account")
            
            # Get free balance (available for trading)
            free_balance = balance[portfolio_currency]['free']
            logger.info(f"Retrieved {portfolio_currency} balance: {free_balance}")
            return free_balance
        
        except Exception as e:
            logger.error(f"Error getting {config.risk_management.portfolio_currency} balance: {e}")
            raise
    
    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        sl: float,
        tp: float,
        strategy_id: str = None,
        priority: int = 2
    ) -> Dict[str, Any]:
        """
        Place a limit order with stop loss and take profit.
        
        Args:
            symbol (str): Symbol to place order for (e.g., 'BTCUSDT')
            side (str): Order side ('Buy' or 'Sell')
            qty (float): Order quantity
            price (float): Order price
            sl (float): Stop loss price
            tp (float): Take profit price
            strategy_id (str): Strategy identifier for multi-strategy support
            priority (int): Order priority
        
        Returns:
            Dict[str, Any]: Order response or error details
        """
        try:
            # Use the same approach as get_instrument_info to find the correct market
            market_id = None
            market_type = None
            
            # Try to get the market ID first for linear (perpetual) markets
            try:
                market_id = self.get_market_id(symbol, 'linear')
                market_type = 'linear'
                logger.info(f"Using linear market for order: {symbol} -> {market_id}")
            except ValueError:
                # If not found in linear, try spot
                try:
                    market_id = self.get_market_id(symbol, 'spot')
                    market_type = 'spot'
                    logger.info(f"Using spot market for order: {symbol} -> {market_id}")
                except ValueError:
                    logger.error(f"Symbol {symbol} not found in either linear or spot markets")
                    return {
                        'success': False,
                        'message': f"Symbol {symbol} not found in available markets",
                        'error': 'symbol_not_found'
                    }
            
            # Multi-strategy support for linear markets (ONE-WAY MODE ONLY)
            if market_type == 'linear' and hasattr(config, 'multi_strategy') and config.multi_strategy and config.multi_strategy.enabled:
                logger.info(f"Multi-strategy mode enabled for {symbol} (one-way mode)")
                
                # Check existing positions and orders to determine current direction
                existing_positions = await self.get_existing_positions(symbol)
                existing_orders = await self.get_existing_orders(symbol)
                
                # Log existing positions/orders for debugging
                if existing_positions:
                    logger.info(f"Existing positions: {[{'side': p.get('side'), 'size': p.get('size'), 'contracts': p.get('contracts')} for p in existing_positions]}")
                if existing_orders:
                    logger.info(f"Existing orders: {[{'side': o.get('side'), 'amount': o.get('amount')} for o in existing_orders]}")
                
                # Check for direction conflicts
                direction_conflict = self.check_direction_conflict(side, existing_positions, existing_orders)
                if direction_conflict:
                    return {
                        'success': False,
                        'message': f"Direction conflict: Cannot place {side} order when existing {direction_conflict} position/orders exist. Reversing not allowed in one-way mode.",
                        'error': 'direction_conflict',
                        'existing_direction': direction_conflict,
                        'requested_direction': side
                    }
                
                # Check pyramiding limits for same direction
                if not self.check_pyramiding_limits(side, strategy_id, existing_orders, existing_positions):
                    return {
                        'success': False,
                        'message': f"Pyramiding limit reached for {symbol} {side} direction",
                        'error': 'pyramiding_limit_reached'
                    }
            
            # Use the exact market_id found - don't try to convert it
            order_symbol = market_id
            logger.info(f"Using exact market ID for order placement: {order_symbol}")
            
            # Verify market details
            market = self.exchange.markets[market_id]
            market_info = market.get('info', {})
            
            # Log market details for verification
            logger.info(f"Market details - Type: {market.get('type')}, ContractType: {market_info.get('contractType')}")
            
            # Format prices to strings with appropriate precision
            try:
                price_precision = market['precision']['price']
                amount_precision = market['precision']['amount']
                
                # Format prices as strings with proper precision
                if isinstance(price_precision, int):
                    price_str = format(price, f'.{price_precision}f')
                    sl_str = format(sl, f'.{price_precision}f')
                    tp_str = format(tp, f'.{price_precision}f')
                else:
                    price_str = str(price)
                    sl_str = str(sl)
                    tp_str = str(tp)
                
                # Process quantity according to market requirements
                lot_size_filter = self._get_lot_size_filter(market)
                qty_adjusted = self._adjust_quantity_for_market(qty, market, lot_size_filter)
                
                # Create both string and float versions
                if isinstance(amount_precision, int):
                    qty_str = format(qty_adjusted, f'.{amount_precision}f')
                else:
                    qty_str = str(qty_adjusted)
                    
            except (KeyError, TypeError):
                # If precision info not available, use string conversion
                price_str = str(price)
                sl_str = str(sl)
                tp_str = str(tp)
                qty_str = str(qty)
                qty_adjusted = qty
            
            # Generate unique order ID for tracking
            timestamp = int(time.time())
            symbol_clean = symbol.replace('/', '').replace(':', '')
            strategy_suffix = f"_{strategy_id}" if strategy_id else ""
            
            # Include priority in order ID for tracking
            priority_prefix = f"prio{priority}_" if priority != 2 else "tv_"
            order_id = f"{priority_prefix}{timestamp}_{symbol_clean}{strategy_suffix}"
            
            # Prepare parameters for Bybit V5 API
            # Using standard Bybit SL/TP attached to the main order for simplicity and reliability
            params = {
                'orderLinkId': order_id,
                'stopLoss': sl_str,
                'takeProfit': tp_str,
                'timeInForce': config.bybit_api.default_time_in_force,
            }
            
            logger.info(f"Using standard attached SL/TP for reliable order execution")
            
            # For Bybit V5 API, category is REQUIRED and must be explicit
            if market_type == 'linear':
                params['category'] = 'linear'  # USDT perpetuals
                params['positionIdx'] = 0  # Always use one-way mode (simplified approach)
                logger.info(f"Setting category=linear for perpetual futures (one-way mode)")
            elif market_type == 'inverse':
                params['category'] = 'inverse'  # Inverse perpetuals  
                params['positionIdx'] = 0  # Always use one-way mode
                logger.info(f"Setting category=inverse for inverse perpetuals (one-way mode)")
            elif market_type == 'spot':
                params['category'] = 'spot'    # Spot trading
                logger.info(f"Setting category=spot for spot trading")
            
            logger.info(f"Generated order ID: {order_id} (priority: {priority}, strategy: {strategy_id or 'default'})")
            logger.info(f"Final API params: {params}")
            
            # Place the order using the exact market ID found
            try:
                logger.info(f"Placing {side} limit order for {symbol} ({market_type}): {qty_str} @ {price_str} (SL: {sl_str}, TP: {tp_str})")
                logger.info(f"Using market_id: {market_id} with category: {params.get('category')}, strategy: {strategy_id or 'default'}")
                
                order = self.exchange.create_order(
                    symbol=order_symbol,  # Use the exact market_id found
                    type='limit',
                    side=side.lower(),  # ccxt uses lowercase side
                    amount=qty_adjusted,  # Use numeric value
                    price=price_str,
                    params=params
                )
                
                logger.info(f"✅ Placed {side} limit order for {symbol}: {qty_str} @ {price_str} (SL: {sl_str}, TP: {tp_str})")
                logger.info(f"Order placed in market: {order.get('symbol', 'Unknown')} with category: {params.get('category')}, strategy: {strategy_id or 'default'}")
                
                return {
                    'success': True,
                    'order': order,
                    'message': 'Order placed successfully with attached SL/TP',
                    'strategy_id': strategy_id,
                    'priority': priority,
                    'position_idx': params.get('positionIdx', 0)
                }
                
            except ccxt.InsufficientFunds as e:
                logger.warning(f"Insufficient funds to place order for {symbol}: {e}")
                return {
                    'success': False,
                    'message': f"Insufficient funds to place order: {str(e)}",
                    'error': 'insufficient_funds',
                    'order_details': {
                        'symbol': symbol,
                        'market_id': market_id,
                        'side': side,
                        'quantity': qty_str,
                        'price': price_str,
                        'stop_loss': sl_str,
                        'take_profit': tp_str,
                        'market_type': market_type
                    }
                }
                
            except ccxt.ExchangeError as e:
                error_message = str(e)
                logger.error(f"Exchange error for {symbol}: {error_message}")
                
                if "Qty invalid" in error_message:
                    # Try with a different quantity approach - some markets require whole numbers
                    try:
                        logger.warning(f"Qty invalid error for {symbol}. Trying with integer quantity.")
                        rounded_qty = math.floor(float(qty_adjusted))
                        
                        # Skip if the rounded quantity would be zero
                        if rounded_qty <= 0:
                            rounded_qty = 1
                        
                        logger.info(f"Retrying with integer quantity: {rounded_qty}")
                        
                        order = self.exchange.create_order(
                            symbol=order_symbol,
                            type='limit',
                            side=side.lower(),
                            amount=rounded_qty,
                            price=price_str,
                            params=params
                        )
                        
                        logger.info(f"✅ Placed {side} limit order for {symbol} with integer quantity: {rounded_qty} @ {price_str}")
                        logger.info(f"Order placed in market: {order.get('symbol', 'Unknown')}")
                        
                        return {
                            'success': True,
                            'order': order,
                            'message': 'Order placed successfully with integer quantity and attached SL/TP',
                            'strategy_id': strategy_id,
                            'priority': priority,
                            'position_idx': params.get('positionIdx', 0)
                        }
                    except Exception as retry_error:
                        logger.error(f"Error retrying with integer quantity: {retry_error}")
                        return {
                            'success': False,
                            'message': f"Failed to place order with integer quantity: {str(retry_error)}",
                            'error': 'order_placement_failed',
                            'order_details': {
                                'symbol': symbol,
                                'market_id': market_id,
                                'side': side,
                                'quantity': rounded_qty if 'rounded_qty' in locals() else qty_str,
                                'price': price_str,
                                'stop_loss': sl_str,
                                'take_profit': tp_str,
                                'market_type': market_type
                            }
                        }
                else:
                    # Handle other exchange errors
                    return {
                        'success': False,
                        'message': f"Exchange error: {error_message}",
                        'error': 'exchange_error',
                        'order_details': {
                            'symbol': symbol,
                            'market_id': market_id,
                            'side': side,
                            'quantity': qty_str,
                            'price': price_str,
                            'stop_loss': sl_str,
                            'take_profit': tp_str,
                            'market_type': market_type
                        }
                    }
        
        except Exception as e:
            logger.error(f"Error placing limit order for {symbol}: {e}")
            return {
                'success': False,
                'message': f"Error placing order: {str(e)}",
                'error': 'order_placement_failed',
                'order_details': {
                    'symbol': symbol,
                    'market_id': market_id if 'market_id' in locals() else 'unknown',
                    'side': side,
                    'quantity': qty_str if 'qty_str' in locals() else str(qty),
                    'price': price_str if 'price_str' in locals() else str(price),
                    'stop_loss': sl_str if 'sl_str' in locals() else str(sl),
                    'take_profit': tp_str if 'tp_str' in locals() else str(tp),
                    'market_type': market_type if 'market_type' in locals() else 'unknown'
                }
            }

    def _get_lot_size_filter(self, market_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract lot size filter from market info.
        
        Args:
            market_info (Dict[str, Any]): Market information
            
        Returns:
            Dict[str, Any]: Lot size filter information or empty dict if not found
        """
        try:
            if 'info' in market_info and isinstance(market_info['info'], dict):
                if 'lotSizeFilter' in market_info['info']:
                    return market_info['info']['lotSizeFilter']
            return {}
        except Exception as e:
            logger.error(f"Error extracting lot size filter: {e}")
            return {}
            
    def _adjust_quantity_for_market(self, qty: float, market_info: Dict[str, Any], lot_size_filter: Dict[str, Any]) -> float:
        """
        Adjust quantity based on market requirements and lot size filter.
        
        Args:
            qty (float): Original quantity
            market_info (Dict[str, Any]): Market information
            lot_size_filter (Dict[str, Any]): Lot size filter information
            
        Returns:
            float: Adjusted quantity
        """
        try:
            # Get min quantity and quantity step from lot size filter
            min_qty = float(lot_size_filter.get('minOrderQty', 0.0))
            qty_step = float(lot_size_filter.get('qtyStep', 0.0))
            
            # If both values are available, adjust properly
            if min_qty > 0 and qty_step > 0:
                # Round down to the nearest step
                steps = math.floor(qty / qty_step)
                adjusted_qty = steps * qty_step
                
                # Ensure it meets minimum
                if adjusted_qty < min_qty:
                    adjusted_qty = min_qty
                    
                logger.info(f"Adjusted quantity from {qty} to {adjusted_qty} based on min: {min_qty}, step: {qty_step}")
                return adjusted_qty
                
            # Some linear futures require integers for contract sizes
            if market_info.get('type') == 'linear' or market_info.get('market_type') == 'linear':
                # Check if minOrderQty is a whole number - indicates contract sizing
                if min_qty.is_integer() and min_qty >= 1.0:
                    # Use integer quantity for linear contracts that appear to use whole contract sizes
                    adjusted_qty = math.floor(qty)
                    if adjusted_qty < min_qty:
                        adjusted_qty = int(min_qty)
                    logger.info(f"Using integer quantity {adjusted_qty} for linear contract")
                    return adjusted_qty
            
            # Default: return original quantity if no adjustments needed
            return qty
            
        except Exception as e:
            logger.error(f"Error adjusting quantity: {e}")
            return qty
    
    # Removed debug_bybit_instruments method as it was specific to NEAR debugging
    
    async def get_position_mode(self, symbol: str) -> str:
        """
        Get the current position mode for a symbol.
        
        Args:
            symbol (str): Symbol to check position mode for
        
        Returns:
            str: Position mode ('one-way' or 'hedge')
        """
        try:
            # Use Bybit V5 API to get position mode
            # For unified trading account, we need to check the specific coin's position mode
            base_coin = symbol.replace('USDT', '').replace('/', '').replace(':', '').upper()
            
            params = {
                'category': 'linear',
                'coin': base_coin  # Just the base coin (e.g., 'NEAR', 'BTC')
            }
            
            # Use the correct CCXT method name for Bybit V5
            response = self.exchange.private_get_v5_position_switch_mode(params)
            
            if response.get('retCode') == 0:
                result = response.get('result', {})
                # Position mode: 0 = one-way, 3 = hedge
                mode = result.get('mode', 0)
                return 'hedge' if mode == 3 else 'one-way'
            else:
                logger.warning(f"Could not get position mode for {symbol}: {response.get('retMsg', 'Unknown error')}")
                return 'one-way'  # Default assumption
                
        except Exception as e:
            logger.error(f"Error getting position mode for {symbol}: {e}")
            return 'one-way'  # Default assumption
    
    async def set_position_mode(self, symbol: str, mode: str = 'hedge') -> Dict[str, Any]:
        """
        Set position mode for a symbol.
        
        Args:
            symbol (str): Symbol to set position mode for
            mode (str): 'hedge' or 'one-way'
        
        Returns:
            Dict[str, Any]: Result of the operation
        """
        try:
            # Convert mode to Bybit format
            bybit_mode = 3 if mode == 'hedge' else 0
            
            # Get base coin for the API call - need to be more careful about the format
            base_coin = symbol.replace('USDT', '').replace('/', '').replace(':', '').upper()
            
            # For some coins like NEAR, we might need to check if it's supported
            # Let's try different formats
            coin_alternatives = [
                base_coin,                    # NEAR
                f"{base_coin}USDT",          # NEARUSDT  
                symbol.replace('/', '').replace(':', '').upper()  # Full symbol
            ]
            
            logger.info(f"Attempting to set position mode for {symbol} ({base_coin}) to {mode} (mode={bybit_mode})")
            
            for coin_format in coin_alternatives:
                try:
                    params = {
                        'category': 'linear',
                        'coin': coin_format,
                        'mode': str(bybit_mode)
                    }
                    
                    logger.info(f"Trying coin format: {coin_format}")
                    
                    # Use the correct CCXT method name for Bybit V5
                    response = self.exchange.private_post_v5_position_switch_mode(params)
                    
                    if response.get('retCode') == 0:
                        logger.info(f"✅ Successfully set position mode for {symbol} to {mode} using coin format: {coin_format}")
                        return {'success': True, 'message': f'Position mode set to {mode}'}
                    else:
                        error_msg = response.get('retMsg', 'Unknown error')
                        logger.warning(f"Failed with coin format {coin_format}: {error_msg}")
                        
                        # If this coin format failed, try the next one
                        continue
                        
                except Exception as format_error:
                    logger.warning(f"Error with coin format {coin_format}: {format_error}")
                    continue
            
            # If all formats failed
            logger.error(f"Failed to set position mode for {symbol} with all coin formats: {coin_alternatives}")
            return {'success': False, 'message': f'Failed to set position mode: all coin formats failed'}
                
        except Exception as e:
            logger.error(f"Error setting position mode for {symbol}: {e}")
            return {'success': False, 'message': f'Error setting position mode: {str(e)}'}
    
    async def get_existing_positions(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get existing positions for a symbol.
        
        Args:
            symbol (str): Symbol to check positions for
        
        Returns:
            List[Dict[str, Any]]: List of existing positions
        """
        try:
            # Get the correct market ID
            market_id = self.get_market_id(symbol, 'linear')
            
            # Use CCXT to fetch positions
            positions = self.exchange.fetch_positions([market_id])
            
            # Log all positions for debugging
            logger.info(f"Raw positions response for {symbol} ({market_id}): {len(positions)} total")
            
            active_positions = []
            
            for pos in positions:
                pos_symbol = pos.get('symbol', '')
                pos_size = pos.get('size', 0)
                pos_contracts = pos.get('contracts', 0)  
                pos_side = pos.get('side', '')
                pos_info = pos.get('info', {})
                
                # Log each position for debugging
                logger.info(f"Position check - Symbol: {pos_symbol}, Size: {pos_size}, Contracts: {pos_contracts}, Side: {pos_side}")
                
                # Check multiple ways to determine if position is active
                is_active = False
                
                # Method 1: Check size
                if pos_size != 0:
                    is_active = True
                    logger.info(f"Position is active via size: {pos_size}")
                
                # Method 2: Check contracts
                if pos_contracts != 0:
                    is_active = True
                    logger.info(f"Position is active via contracts: {pos_contracts}")
                
                # Method 3: Check raw info from Bybit API
                if pos_info:
                    raw_size = pos_info.get('size', '0')
                    raw_side = pos_info.get('side', '')
                    
                    # Bybit sometimes returns string values
                    try:
                        if float(raw_size) != 0:
                            is_active = True
                            logger.info(f"Position is active via raw info size: {raw_size}")
                    except (ValueError, TypeError):
                        pass
                    
                    # Check if side is not 'None' or empty
                    if raw_side and raw_side.lower() not in ['none', '']:
                        logger.info(f"Position has side in raw info: {raw_side}")
                
                if is_active:
                    active_positions.append(pos)
                    logger.info(f"✅ Added active position: {pos_side} {pos_size} contracts for {pos_symbol}")
                else:
                    logger.info(f"❌ Skipped inactive position for {pos_symbol}")
            
            logger.info(f"Found {len(active_positions)} active positions for {symbol} out of {len(positions)} total")
            return active_positions
            
        except Exception as e:
            logger.error(f"Error getting positions for {symbol}: {e}")
            return []
    
    async def get_existing_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get existing open orders for a symbol.
        
        Args:
            symbol (str): Symbol to check orders for
        
        Returns:
            List[Dict[str, Any]]: List of existing orders
        """
        try:
            # Get the correct market ID
            market_id = self.get_market_id(symbol, 'linear')
            
            # Use CCXT to fetch open orders
            orders = self.exchange.fetch_open_orders(market_id)
            
            logger.info(f"Found {len(orders)} open orders for {symbol}")
            return orders
            
        except Exception as e:
            logger.error(f"Error getting orders for {symbol}: {e}")
            return []
    
    def determine_position_idx(self, side: str, strategy_id: str, existing_positions: List[Dict[str, Any]]) -> int:
        """
        Determine the appropriate positionIdx for hedge mode based on side and existing positions.
        
        Args:
            side (str): Order side ('Buy' or 'Sell')
            strategy_id (str): Strategy identifier
            existing_positions (List[Dict[str, Any]]): Existing positions
        
        Returns:
            int: Position index (0=one-way, 1=buy hedge, 2=sell hedge)
        """
        try:
            # If multi-strategy is not enabled or not in hedge mode, use one-way
            if (not hasattr(config, 'multi_strategy') or 
                not config.multi_strategy or 
                not config.multi_strategy.hedge_mode):
                return 0
            
            # In hedge mode, determine position index based on side
            if side.lower() == 'buy':
                return 1  # Buy side of hedge position
            else:
                return 2  # Sell side of hedge position
            
        except Exception as e:
            logger.error(f"Error determining position index: {e}")
            return 0  # Default to one-way mode
    
    def check_pyramiding_limits(self, side: str, strategy_id: str, existing_orders: List[Dict[str, Any]], existing_positions: List[Dict[str, Any]]) -> bool:
        """
        Check if pyramiding limits allow placing a new order.
        
        Args:
            side (str): Order side ('Buy' or 'Sell')
            strategy_id (str): Strategy identifier
            existing_orders (List[Dict[str, Any]]): Existing orders
            existing_positions (List[Dict[str, Any]]): Existing positions
        
        Returns:
            bool: True if pyramiding is allowed, False otherwise
        """
        try:
            # If multi-strategy is not enabled, allow the order
            if (not hasattr(config, 'multi_strategy') or 
                not config.multi_strategy or 
                not config.multi_strategy.allow_pyramiding):
                # Check if there's already a position in the same direction
                for pos in existing_positions:
                    pos_side = pos.get('side')
                    if ((side.lower() == 'buy' and pos_side == 'long') or
                        (side.lower() == 'sell' and pos_side == 'short')):
                        logger.warning(f"Pyramiding disabled: Position already exists in {side} direction")
                        return False
                return True
            
            # Count existing orders and positions in the same direction
            same_direction_count = 0
            
            # Count positions
            for pos in existing_positions:
                pos_side = pos.get('side')
                if ((side.lower() == 'buy' and pos_side == 'long') or
                    (side.lower() == 'sell' and pos_side == 'short')):
                    same_direction_count += 1
            
            # Count open orders
            for order in existing_orders:
                order_side = order.get('side')
                if order_side and order_side.lower() == side.lower():
                    same_direction_count += 1
            
            max_pyramiding = config.multi_strategy.max_pyramiding_orders
            
            if same_direction_count >= max_pyramiding:
                logger.warning(f"Pyramiding limit reached: {same_direction_count}/{max_pyramiding} orders/positions in {side} direction")
                return False
            
            logger.info(f"Pyramiding check passed: {same_direction_count}/{max_pyramiding} orders/positions in {side} direction")
            return True
            
        except Exception as e:
            logger.error(f"Error checking pyramiding limits: {e}")
            return True  # Default to allowing the order 

    def check_direction_conflict(self, requested_side: str, existing_positions: List[Dict[str, Any]], existing_orders: List[Dict[str, Any]]) -> Optional[str]:
        """
        Check if there's a direction conflict between requested order and existing positions/orders.
        In one-way mode, we don't allow reversing the position direction.
        
        Args:
            requested_side (str): Requested order side ('Buy' or 'Sell')
            existing_positions (List[Dict[str, Any]]): Existing positions
            existing_orders (List[Dict[str, Any]]): Existing orders
        
        Returns:
            Optional[str]: The conflicting direction if found, None if no conflict
        """
        try:
            requested_direction = 'long' if requested_side.lower() == 'buy' else 'short'
            
            # Check existing positions for opposite direction
            for pos in existing_positions:
                if pos.get('size', 0) != 0 or pos.get('contracts', 0) != 0:  # Active position
                    pos_side = pos.get('side', '').lower()
                    if pos_side:
                        if requested_direction == 'long' and pos_side == 'short':
                            logger.warning(f"Direction conflict: Requested {requested_direction} but existing {pos_side} position found")
                            return 'short'
                        elif requested_direction == 'short' and pos_side == 'long':
                            logger.warning(f"Direction conflict: Requested {requested_direction} but existing {pos_side} position found")
                            return 'long'
            
            # Check existing orders for opposite direction
            for order in existing_orders:
                order_side = order.get('side', '').lower()
                if order_side:
                    order_direction = 'long' if order_side == 'buy' else 'short'
                    if requested_direction != order_direction:
                        logger.warning(f"Direction conflict: Requested {requested_direction} but existing {order_direction} order found")
                        return order_direction
            
            # No conflict found
            logger.info(f"No direction conflict: Requested {requested_direction} direction is clear")
            return None
            
        except Exception as e:
            logger.error(f"Error checking direction conflict: {e}")
            # In case of error, be conservative and assume conflict
            return "unknown"
    
    async def check_priority_conflicts(self, symbol: str, requested_priority: int, requested_side: str) -> Dict[str, Any]:
        """
        Check for priority conflicts and determine what actions to take.
        
        Args:
            symbol (str): Symbol to check
            requested_priority (int): Priority of new signal (1 = high, 2 = low)
            requested_side (str): Side of new signal ('Buy' or 'Sell')
        
        Returns:
            Dict[str, Any]: Action plan with conflicts and orders to cancel
        """
        try:
            logger.info(f"🎯 Checking priority conflicts for {symbol}: requested priority {requested_priority} ({requested_side})")
            
            # Get existing orders and positions
            existing_orders = await self.get_existing_orders(symbol)
            existing_positions = await self.get_existing_positions(symbol)
            
            conflict_info = {
                'allow_order': True,
                'orders_to_cancel': [],
                'positions_to_close': [],
                'conflicts_found': [],
                'reason': '',
                'existing_priorities': {}
            }
            
            # Analyze existing orders by priority
            for order in existing_orders:
                order_link_id = order.get('clientOrderId', order.get('info', {}).get('orderLinkId', ''))
                order_side = order.get('side', '').title()
                order_amount = order.get('amount', 0)
                
                # Extract priority from order ID (format: tv_timestamp_symbol_strategy or prio1_timestamp_symbol_strategy)
                extracted_priority = self._extract_priority_from_order_id(order_link_id)
                
                logger.info(f"Existing order: {order_link_id} | Side: {order_side} | Amount: {order_amount} | Priority: {extracted_priority}")
                
                if extracted_priority not in conflict_info['existing_priorities']:
                    conflict_info['existing_priorities'][extracted_priority] = []
                
                conflict_info['existing_priorities'][extracted_priority].append({
                    'order_id': order.get('id'),
                    'order_link_id': order_link_id,
                    'side': order_side,
                    'amount': order_amount,
                    'order': order
                })
            
            # Analyze existing positions and determine if they need to be closed
            active_positions = []
            for position in existing_positions:
                pos_size = position.get('size', 0)
                pos_contracts = position.get('contracts', 0)
                pos_side = position.get('side', '').lower()
                
                if pos_size != 0 or pos_contracts != 0:  # Active position
                    # For now, assume all positions are Priority 2 unless we implement position tracking by priority
                    # This could be enhanced later by tracking position creation with order IDs
                    position_priority = 2  # Default assumption for existing positions
                    
                    active_positions.append({
                        'side': pos_side,
                        'size': pos_size,
                        'contracts': pos_contracts,
                        'priority': position_priority,
                        'position': position
                    })
                    
                    logger.info(f"Active position: {pos_side} | Size: {pos_size} | Contracts: {pos_contracts} | Assumed Priority: {position_priority}")
            
            # Priority conflict resolution logic
            if requested_priority == 1:
                # Priority 1: Always executes, cancel any Priority 2 orders and close Priority 2 positions
                if 2 in conflict_info['existing_priorities']:
                    logger.warning(f"Priority 1 signal received - will cancel all Priority 2 orders for {symbol}")
                    for p2_order in conflict_info['existing_priorities'][2]:
                        conflict_info['orders_to_cancel'].append(p2_order)
                        conflict_info['conflicts_found'].append(f"Priority 2 order {p2_order['order_link_id']} will be cancelled")
                
                # Close any active Priority 2 positions 
                requested_direction = 'long' if requested_side.lower() == 'buy' else 'short'
                for pos in active_positions:
                    if pos['priority'] == 2:  # Priority 2 position
                        # Close regardless of direction to allow Priority 1 full control
                        conflict_info['positions_to_close'].append(pos)
                        if pos['side'] != requested_direction:
                            conflict_info['conflicts_found'].append(f"Priority 2 {pos['side']} position will be closed for direction change")
                        else:
                            conflict_info['conflicts_found'].append(f"Priority 2 {pos['side']} position will be closed for Priority 1 override")
                
                # Also check for existing Priority 1 orders for direction conflicts or pyramiding
                if 1 in conflict_info['existing_priorities']:
                    same_direction_p1 = [o for o in conflict_info['existing_priorities'][1] if o['side'].lower() == requested_side.lower()]
                    opposite_direction_p1 = [o for o in conflict_info['existing_priorities'][1] if o['side'].lower() != requested_side.lower()]
                    
                    if opposite_direction_p1:
                        # Priority 1 wants opposite direction - cancel existing Priority 1 orders
                        logger.warning(f"Priority 1 direction conflict: cancelling existing Priority 1 {opposite_direction_p1[0]['side']} orders")
                        for p1_order in conflict_info['existing_priorities'][1]:
                            conflict_info['orders_to_cancel'].append(p1_order)
                            conflict_info['conflicts_found'].append(f"Priority 1 direction conflict - cancelling {p1_order['order_link_id']}")
                    elif same_direction_p1:
                        # Same direction Priority 1 - check pyramiding limits
                        if len(same_direction_p1) >= config.multi_strategy.max_pyramiding_orders:
                            conflict_info['allow_order'] = False
                            conflict_info['reason'] = f"Priority 1 pyramiding limit reached: {len(same_direction_p1)}/{config.multi_strategy.max_pyramiding_orders}"
                            logger.warning(conflict_info['reason'])
                
                if conflict_info['allow_order']:
                    order_count = len(conflict_info['orders_to_cancel'])
                    position_count = len(conflict_info['positions_to_close'])
                    conflict_info['reason'] = f"Priority 1 signal approved - cancelling {order_count} orders, closing {position_count} positions"
                
            elif requested_priority == 2:
                # Priority 2: Only execute if no Priority 1 exists
                if 1 in conflict_info['existing_priorities']:
                    conflict_info['allow_order'] = False
                    conflict_info['reason'] = f"Priority 2 blocked: Priority 1 orders exist for {symbol}"
                    logger.warning(conflict_info['reason'])
                    for p1_order in conflict_info['existing_priorities'][1]:
                        conflict_info['conflicts_found'].append(f"Blocked by Priority 1 order: {p1_order['order_link_id']}")
                else:
                    # No Priority 1, check Priority 2 pyramiding and direction conflicts
                    if 2 in conflict_info['existing_priorities']:
                        same_direction_p2 = [o for o in conflict_info['existing_priorities'][2] if o['side'].lower() == requested_side.lower()]
                        opposite_direction_p2 = [o for o in conflict_info['existing_priorities'][2] if o['side'].lower() != requested_side.lower()]
                        
                        if opposite_direction_p2:
                            conflict_info['allow_order'] = False
                            conflict_info['reason'] = f"Priority 2 direction conflict: existing {opposite_direction_p2[0]['side']} orders prevent {requested_side}"
                            logger.warning(conflict_info['reason'])
                        elif len(same_direction_p2) >= config.multi_strategy.max_pyramiding_orders:
                            conflict_info['allow_order'] = False
                            conflict_info['reason'] = f"Priority 2 pyramiding limit reached: {len(same_direction_p2)}/{config.multi_strategy.max_pyramiding_orders}"
                            logger.warning(conflict_info['reason'])
                        else:
                            conflict_info['reason'] = f"Priority 2 signal approved - no conflicts"
                    else:
                        conflict_info['reason'] = f"Priority 2 signal approved - no existing orders"
                    
                    # Check for active positions that might conflict (for direction changes)
                    if conflict_info['allow_order'] and active_positions:
                        requested_direction = 'long' if requested_side.lower() == 'buy' else 'short'
                        
                        for pos in active_positions:
                            if pos['side'] != requested_direction:
                                # Priority 2 cannot reverse positions
                                conflict_info['allow_order'] = False
                                conflict_info['reason'] = f"Priority 2 cannot reverse position from {pos['side']} to {requested_direction}"
                                logger.warning(conflict_info['reason'])
                                break
            
            logger.info(f"Priority conflict resolution: {conflict_info['reason']}")
            return conflict_info
            
        except Exception as e:
            logger.error(f"Error checking priority conflicts: {e}")
            return {
                'allow_order': False,
                'orders_to_cancel': [],
                'positions_to_close': [],
                'conflicts_found': [f"Error checking conflicts: {str(e)}"],
                'reason': f"Error in priority check: {str(e)}",
                'existing_priorities': {}
            }
    
    def _extract_priority_from_order_id(self, order_link_id: str) -> int:
        """
        Extract priority from order link ID.
        
        Args:
            order_link_id (str): Order link ID
        
        Returns:
            int: Extracted priority (1 or 2, defaults to 2)
        """
        try:
            if not order_link_id:
                return 2
            
            # Check for explicit priority prefixes
            if order_link_id.startswith('prio1_') or order_link_id.startswith('p1_'):
                return 1
            elif order_link_id.startswith('prio2_') or order_link_id.startswith('p2_'):
                return 2
            elif order_link_id.startswith('tv_'):
                # Default TradingView orders are priority 2 unless specified
                return 2
            else:
                # Unknown format, assume priority 2
                return 2
                
        except Exception as e:
            logger.warning(f"Error extracting priority from order ID '{order_link_id}': {e}")
            return 2
    
    async def cancel_orders_by_priority(self, orders_to_cancel: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Cancel a list of orders.
        
        Args:
            orders_to_cancel (List[Dict[str, Any]]): List of order info dicts to cancel
        
        Returns:
            Dict[str, Any]: Results of cancellation attempts
        """
        try:
            results = {
                'cancelled_orders': [],
                'failed_cancellations': [],
                'total_attempted': len(orders_to_cancel)
            }
            
            if not orders_to_cancel:
                return results
            
            logger.info(f"🗑️ Cancelling {len(orders_to_cancel)} lower priority orders...")
            
            for order_info in orders_to_cancel:
                try:
                    order_id = order_info['order_id']
                    order_link_id = order_info['order_link_id']
                    symbol = order_info['order'].get('symbol', 'Unknown')
                    
                    logger.info(f"Cancelling order: {order_link_id} (ID: {order_id})")
                    
                    # Cancel the order
                    cancel_result = self.exchange.cancel_order(order_id, symbol)
                    
                    results['cancelled_orders'].append({
                        'order_id': order_id,
                        'order_link_id': order_link_id,
                        'symbol': symbol,
                        'cancel_result': cancel_result
                    })
                    
                    logger.info(f"✅ Cancelled order: {order_link_id}")
                    
                except Exception as cancel_error:
                    error_msg = f"Failed to cancel order {order_info.get('order_link_id', 'Unknown')}: {str(cancel_error)}"
                    logger.error(error_msg)
                    results['failed_cancellations'].append({
                        'order_info': order_info,
                        'error': error_msg
                    })
            
            success_count = len(results['cancelled_orders'])
            total_count = len(orders_to_cancel)
            
            if success_count == total_count:
                logger.info(f"✅ Successfully cancelled all {success_count}/{total_count} orders")
            else:
                logger.warning(f"⚠️ Cancelled {success_count}/{total_count} orders, {len(results['failed_cancellations'])} failed")
            
            return results
            
        except Exception as e:
            logger.error(f"Error in bulk order cancellation: {e}")
            return {
                'cancelled_orders': [],
                'failed_cancellations': [{'error': f"Bulk cancellation error: {str(e)}"}],
                'total_attempted': len(orders_to_cancel)
            }
    
    async def close_all_positions(self, symbol: str, reason: str = "Priority override") -> Dict[str, Any]:
        """
        Close all active positions for a symbol using market orders.
        
        Args:
            symbol (str): Symbol to close positions for
            reason (str): Reason for closing positions
        
        Returns:
            Dict[str, Any]: Results of position closure attempts
        """
        try:
            results = {
                'closed_positions': [],
                'failed_closures': [],
                'total_attempted': 0
            }
            
            logger.info(f"🔄 Closing all positions for {symbol} - Reason: {reason}")
            
            # Get existing positions
            existing_positions = await self.get_existing_positions(symbol)
            
            if not existing_positions:
                logger.info(f"No active positions found for {symbol}")
                return results
            
            results['total_attempted'] = len(existing_positions)
            
            for position in existing_positions:
                try:
                    pos_size = position.get('size', 0)
                    pos_side = position.get('side', '').lower()
                    pos_contracts = position.get('contracts', 0)
                    
                    if pos_size == 0 and pos_contracts == 0:
                        logger.info(f"Position {pos_side} has zero size, skipping")
                        continue
                    
                    # Determine the opposite side for closing
                    close_side = 'sell' if pos_side == 'long' else 'buy'
                    close_quantity = abs(pos_size) if pos_size != 0 else abs(pos_contracts)
                    
                    logger.info(f"Closing {pos_side} position: {close_quantity} contracts via {close_side} market order")
                    
                    # Get the correct market ID
                    market_id = self.get_market_id(symbol, 'linear')
                    
                    # Place market order to close the position
                    params = {
                        'category': 'linear',
                        'positionIdx': 0,  # One-way mode
                        'reduceOnly': True  # This ensures we're closing, not opening new position
                    }
                    
                    close_order = self.exchange.create_order(
                        symbol=market_id,
                        type='market',
                        side=close_side,
                        amount=close_quantity,
                        params=params
                    )
                    
                    results['closed_positions'].append({
                        'original_side': pos_side,
                        'close_side': close_side,
                        'quantity': close_quantity,
                        'close_order': close_order,
                        'reason': reason
                    })
                    
                    logger.info(f"✅ Closed {pos_side} position: {close_quantity} contracts")
                    
                except Exception as close_error:
                    error_msg = f"Failed to close {position.get('side', 'unknown')} position: {str(close_error)}"
                    logger.error(error_msg)
                    results['failed_closures'].append({
                        'position': position,
                        'error': error_msg
                    })
            
            success_count = len(results['closed_positions'])
            total_count = results['total_attempted']
            
            if success_count == total_count:
                logger.info(f"✅ Successfully closed all {success_count}/{total_count} positions for {symbol}")
            else:
                logger.warning(f"⚠️ Closed {success_count}/{total_count} positions, {len(results['failed_closures'])} failed")
            
            return results
            
        except Exception as e:
            logger.error(f"Error closing positions for {symbol}: {e}")
            return {
                'closed_positions': [],
                'failed_closures': [{'error': f"Position closure error: {str(e)}"}],
                'total_attempted': 0
            }
    
    async def get_balance(self, currency="USDT"):
        """Get account balance for a specific currency."""
        try:
            # Get wallet balance using V5 unified account
            balance = self.exchange.fetch_balance({'type': 'unified'})
            return balance.get(currency, {}).get('free', 0.0)
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return 0.0
    
    async def get_all_positions(self):
        """Get all active positions."""
        try:
            positions = self.exchange.fetch_positions()
            active_positions = {}
            
            for position in positions:
                symbol = position.get('symbol', '')
                size = float(position.get('contracts', 0))
                
                if size != 0:  # Only include active positions
                    # Normalize symbol (e.g., BTC/USDT:USDT -> BTCUSDT)
                    normalized_symbol = symbol.replace('/USDT:USDT', '').replace('/USDC:USDC', '').replace('/', '')
                    active_positions[normalized_symbol] = {
                        'symbol': symbol,
                        'size': size,
                        'side': position.get('side'),
                        'contracts': position.get('contracts', 0),
                        'notional': position.get('notional', 0),
                        'unrealizedPnl': position.get('unrealizedPnl', 0),
                        'percentage': position.get('percentage', 0)
                    }
            
            return active_positions
            
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return {}
    
    async def get_trade_history(self, symbol, limit=50):
        """Get recent trade history for a symbol."""
        try:
            # Normalize symbol for market lookup
            normalized_symbol = self._normalize_symbol(symbol)
            market_id = self._find_market_id(normalized_symbol)
            
            if not market_id:
                logger.error(f"Could not find market for {symbol}")
                return []
            
            # Fetch recent trades
            trades = self.exchange.fetch_my_trades(market_id, limit=limit)
            
            # Process trades for easier consumption
            processed_trades = []
            for trade in trades:
                processed_trades.append({
                    'id': trade.get('id'),
                    'symbol': trade.get('symbol'),
                    'side': trade.get('side'),
                    'amount': trade.get('amount'),
                    'price': trade.get('price'),
                    'cost': trade.get('cost'),
                    'fee': trade.get('fee', {}).get('cost', 0),
                    'timestamp': trade.get('timestamp'),
                    'datetime': trade.get('datetime'),
                    'realizedPnl': trade.get('info', {}).get('closedPnl', 0)
                })
            
            return processed_trades
            
        except Exception as e:
            logger.error(f"Error fetching trade history for {symbol}: {e}")
            return [] 