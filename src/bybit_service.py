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
                }
            })
            
            logger.info("Bybit exchange object created")
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
        
        # First, check if the symbol is in the format that's directly usable
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
        
        # If no match found, try again with a different market type
        if market_type == 'linear':
            try:
                logger.info(f"Trying to find {symbol} in spot market")
                return self.get_market_id(symbol, 'spot')
            except ValueError:
                pass
        elif market_type != 'linear':
            try:
                logger.info(f"Trying to find {symbol} in linear market")
                return self.get_market_id(symbol, 'linear')
            except ValueError:
                pass
        
        # If still not found, log available symbols and raise an error
        logger.error(f"Symbol {symbol} not found in available {market_type} markets")
        available_markets = list(self.exchange.markets.keys())[:10]
        logger.debug(f"Available markets (first 10): {available_markets}...")
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
            # Try to get the market ID for both linear (futures) and spot markets
            try:
                market_id = self.get_market_id(symbol, 'linear')
                market_type = 'linear'
            except ValueError:
                market_id = self.get_market_id(symbol, 'spot')
                market_type = 'spot'
            
            # Get market info
            instrument_info = self.exchange.markets[market_id]
            instrument_info['market_type'] = market_type  # Add market type for reference
            
            # If the market doesn't have info, try to fetch it
            if 'info' not in instrument_info or not instrument_info['info']:
                # Some CCXT exchanges require a separate call to get full instrument details
                logger.info(f"Fetching detailed instrument info for {symbol}")
                try:
                    # Try using exchange-specific methods if available
                    if hasattr(self.exchange, 'fetchMarket'):
                        instrument_info = self.exchange.fetchMarket(market_id)
                    # Alternatively, use Bybit's V5 API directly via ccxt custom params
                    else:
                        params = {
                            'category': market_type,
                            'symbol': symbol
                        }
                        instrument_info = self.exchange.publicGetV5MarketInstrumentsInfo(params)
                except Exception as fetch_error:
                    logger.warning(f"Could not fetch detailed instrument info: {fetch_error}")
            
            logger.info(f"Retrieved instrument info for {symbol} (market type: {market_type})")
            return instrument_info
        
        except Exception as e:
            logger.error(f"Error getting instrument info for {symbol}: {e}")
            raise
    
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
            # Try to get the market ID for linear (futures) market first
            try:
                market_id = self.get_market_id(symbol, 'linear')
                market_type = 'linear'
            except ValueError:
                # Try inverse as fallback
                try:
                    market_id = self.get_market_id(symbol, 'inverse')
                    market_type = 'inverse'
                except ValueError:
                    # If neither found, use whatever is available
                    market_id = self.get_market_id(symbol)
                    market = self.exchange.markets[market_id]
                    market_type = market.get('type', '')
            
            # Check if the market is a perpetual/linear/inverse market
            if market_type not in ['swap', 'future', 'linear', 'inverse']:
                logger.warning(f"Market {symbol} ({market_id}) type '{market_type}' doesn't support leverage setting. Skipping.")
                return {'success': False, 'message': f"Market {symbol} doesn't support leverage setting", 'leverageSet': False}
            
            # Set leverage
            try:
                # For V5 API, we need to specify both symbol and leverage
                params = {
                    'category': market_type,
                    'symbol': symbol.replace('/', ''),  # Remove any '/' for Bybit API format
                }
                
                response = self.exchange.set_leverage(leverage, market_id, params=params)
                logger.info(f"Set leverage for {symbol} to {leverage}x")
                return {'success': True, 'message': f"Set leverage to {leverage}x", 'leverageSet': True, 'response': response}
            except ccxt.NotSupported as e:
                logger.warning(f"Setting leverage not supported for {symbol}: {e}. Skipping.")
                return {'success': False, 'message': str(e), 'leverageSet': False}
            
        except Exception as e:
            logger.error(f"Error setting leverage for {symbol}: {e}")
            # Instead of raising, return a failure response
            return {'success': False, 'message': str(e), 'leverageSet': False}
    
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
            # Try to get the market ID first for linear (perpetual) markets
            try:
                market_id = self.get_market_id(symbol, 'linear')
                market_type = 'linear'
            except ValueError:
                # If not found in linear, try spot
                market_id = self.get_market_id(symbol, 'spot')
                market_type = 'spot'
            
            # Format prices to strings with appropriate precision
            try:
                market = self.exchange.markets[market_id]
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
                # For linear futures, check if whole number quantity is required
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
            
            # Prepare parameters
            params = {
                'stopLoss': sl_str,
                'takeProfit': tp_str,
                'timeInForce': config.bybit_api.default_time_in_force,
                'category': market_type,
            }
            
            # Create unique order ID based on timestamp and symbol
            order_link_id = f"tv_{int(time.time())}_{symbol.replace('/', '')}"
            params['orderLinkId'] = order_link_id
            
            # Place the order
            try:
                logger.info(f"Placing {side} limit order for {symbol} ({market_type}): {qty_str} @ {price_str} (SL: {sl_str}, TP: {tp_str})")
                
                # Try with adjusted numeric quantity first
                order = self.exchange.create_order(
                    symbol=market_id,
                    type='limit',
                    side=side.lower(),  # ccxt uses lowercase side
                    amount=qty_adjusted,  # Use numeric value
                    price=price_str,
                    params=params
                )
                
                logger.info(f"Placed {side} limit order for {symbol}: {qty_str} @ {price_str} (SL: {sl_str}, TP: {tp_str})")
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
                        'side': side,
                        'quantity': qty_str,
                        'price': price_str,
                        'stop_loss': sl_str,
                        'take_profit': tp_str
                    }
                }
            except ccxt.ExchangeError as e:
                error_message = str(e)
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
                            symbol=market_id,
                            type='limit',
                            side=side.lower(),
                            amount=rounded_qty,
                            price=price_str,
                            params=params
                        )
                        
                        logger.info(f"Placed {side} limit order for {symbol} with integer quantity: {rounded_qty} @ {price_str}")
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
                                'side': side,
                                'quantity': rounded_qty if 'rounded_qty' in locals() else qty_str,
                                'price': price_str,
                                'stop_loss': sl_str,
                                'take_profit': tp_str
                            }
                        }
                else:
                    # Handle other exchange errors
                    logger.error(f"Exchange error for {symbol}: {e}")
                    return {
                        'success': False,
                        'message': f"Exchange error: {str(e)}",
                        'error': 'exchange_error',
                        'order_details': {
                            'symbol': symbol,
                            'side': side,
                            'quantity': qty_str,
                            'price': price_str,
                            'stop_loss': sl_str,
                            'take_profit': tp_str
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
                    'side': side,
                    'quantity': qty_str if 'qty_str' in locals() else str(qty),
                    'price': price_str if 'price_str' in locals() else str(price),
                    'stop_loss': sl_str if 'sl_str' in locals() else str(sl),
                    'take_profit': tp_str if 'tp_str' in locals() else str(tp)
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