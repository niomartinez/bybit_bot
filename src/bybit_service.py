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
            
            response = self.exchange.privatePostV5PositionSetLeverage(params)
            
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
        tp: float
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
            
            # Prepare parameters for Bybit V5 API
            params = {
                'stopLoss': sl_str,
                'takeProfit': tp_str,
                'timeInForce': config.bybit_api.default_time_in_force,
            }
            
            # For Bybit V5 API, category is REQUIRED and must be explicit
            if market_type == 'linear':
                params['category'] = 'linear'  # USDT perpetuals
                logger.info(f"Setting category=linear for perpetual futures")
            elif market_type == 'inverse':
                params['category'] = 'inverse'  # Inverse perpetuals  
                logger.info(f"Setting category=inverse for inverse perpetuals")
            elif market_type == 'spot':
                params['category'] = 'spot'    # Spot trading
                logger.info(f"Setting category=spot for spot trading")
            
            # Create unique order ID based on timestamp and symbol
            order_link_id = f"tv_{int(time.time())}_{symbol.replace('/', '').replace(':', '')}"
            params['orderLinkId'] = order_link_id
            
            # Additional Bybit V5 specific parameters for perpetuals
            if market_type == 'linear':
                # For linear perpetuals, we can also specify position index for hedge mode
                # Default to 0 for one-way mode (most common)
                params['positionIdx'] = 0
                
            logger.info(f"Final API params: {params}")
            
            # Place the order using the exact market ID found
            try:
                logger.info(f"Placing {side} limit order for {symbol} ({market_type}): {qty_str} @ {price_str} (SL: {sl_str}, TP: {tp_str})")
                logger.info(f"Using market_id: {market_id} with category: {params.get('category')}")
                
                order = self.exchange.create_order(
                    symbol=order_symbol,  # Use the exact market_id found
                    type='limit',
                    side=side.lower(),  # ccxt uses lowercase side
                    amount=qty_adjusted,  # Use numeric value
                    price=price_str,
                    params=params
                )
                
                logger.info(f"✅ Placed {side} limit order for {symbol}: {qty_str} @ {price_str} (SL: {sl_str}, TP: {tp_str})")
                logger.info(f"Order placed in market: {order.get('symbol', 'Unknown')} with category: {params.get('category')}")
                return {
                    'success': True,
                    'order': order,
                    'message': 'Order placed successfully'
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
                            'message': 'Order placed successfully with integer quantity'
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