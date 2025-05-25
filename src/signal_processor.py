"""
Signal processor for handling TradingView webhook signals.
"""

import math
import traceback
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from src.models import TradingViewSignal, StrategyConfig, TradeJournalEntry
from src.bybit_service import BybitService
from src.config import config, logger

class SignalProcessor:
    """
    Processes TradingView webhook signals and executes trades on Bybit.
    """
    
    def __init__(self):
        """Initialize the signal processor."""
        self.bybit_service = BybitService()
        self.sheets_service = None  # Will be set by main app if available
        logger.info("SignalProcessor initialized")
    
    def set_sheets_service(self, sheets_service):
        """Set the Google Sheets service for trade journaling."""
        self.sheets_service = sheets_service
        logger.info("Google Sheets service connected to SignalProcessor")
    
    async def process_signal(self, signal: TradingViewSignal) -> Dict[str, Any]:
        """
        Process a TradingView signal and execute a trade on Bybit.
        
        Args:
            signal (TradingViewSignal): The signal to process
        
        Returns:
            Dict[str, Any]: Result of the processing
        """
        try:
            logger.info(f"Processing signal: {signal.model_dump_json()}")
            
            # Extract strategy ID and validate if multi-strategy is enabled
            strategy_id = signal.strategy_id or "default"
            logger.info(f"Processing signal for strategy: {strategy_id}")
            
            # Check if strategy is enabled
            if hasattr(config, 'multi_strategy') and config.multi_strategy and config.multi_strategy.enabled:
                strategy_config = self._get_strategy_config(strategy_id)
                if not strategy_config.enabled:
                    logger.warning(f"Strategy {strategy_id} is disabled, skipping signal")
                    return {
                        "success": False,
                        "message": f"Strategy {strategy_id} is disabled",
                        "error": "strategy_disabled",
                        "strategy_id": strategy_id
                    }
            
            # Step 1: Normalize the symbol (remove .P suffix if present)
            symbol = self.bybit_service.normalize_symbol(signal.symbol)
            logger.info(f"Normalized symbol: {symbol}")
            
            # Step 2: Get instrument information
            instrument_info = await self.bybit_service.get_instrument_info(symbol)
            market_type = instrument_info.get('market_type', 'unknown')
            logger.info(f"Got instrument info for {symbol} (market type: {market_type})")
            
            # Log key instrument info
            self._log_instrument_info(symbol, instrument_info)
            
            # Step 3: Determine max leverage (with strategy-specific override)
            max_leverage = self._get_max_leverage(instrument_info)
            
            # Apply strategy-specific leverage override
            if hasattr(config, 'multi_strategy') and config.multi_strategy and config.multi_strategy.enabled:
                strategy_config = self._get_strategy_config(strategy_id)
                if strategy_config.max_leverage_override:
                    max_leverage = min(max_leverage, strategy_config.max_leverage_override)
                    logger.info(f"Applied strategy {strategy_id} leverage override: {max_leverage}x")
            
            # Step 4: Apply leverage cap from config if needed
            if (config.bybit_api.max_leverage_cap is not None and 
                config.bybit_api.max_leverage_cap > 0 and 
                config.bybit_api.max_leverage_cap < max_leverage):
                max_leverage = config.bybit_api.max_leverage_cap
                logger.info(f"Applied global leverage cap: {max_leverage}x")
            
            # Step 5: Set leverage for the symbol if it's a leveraged market
            if market_type in ['linear', 'inverse', 'swap', 'future']:
                leverage_result = await self.bybit_service.set_leverage(symbol, max_leverage)
                # Check if setting leverage was successful, log but continue regardless
                if isinstance(leverage_result, dict) and leverage_result.get('success') is False:
                    logger.warning(f"Failed to set leverage for {symbol}: {leverage_result.get('message', 'Unknown error')}. Continuing with order placement.")
                else:
                    logger.info(f"Set leverage for {symbol}: {max_leverage}x")
            else:
                logger.info(f"Skipping leverage setting for {symbol} as it's a {market_type} market")
            
            # Step 6: Calculate VaR (Value at Risk) with strategy-specific multiplier
            var_amount = await self._calculate_var(strategy_id)
            logger.info(f"Calculated VaR amount for strategy {strategy_id}: {var_amount} USDT")
            
            # Step 7: Calculate order quantity (or use override if provided)
            if signal.quantity is not None:
                quantity = signal.quantity
                logger.info(f"Using override quantity from signal: {quantity}")
                # Still get min_qty and qty_step for validation
                _, min_qty, qty_step = await self._calculate_quantity(
                    symbol=symbol,
                    instrument_info=instrument_info,
                    entry_price=signal.entry,
                    stop_loss=signal.stop_loss,
                    var_amount=var_amount,
                    max_leverage=max_leverage
                )
            else:
                quantity, min_qty, qty_step = await self._calculate_quantity(
                    symbol=symbol,
                    instrument_info=instrument_info,
                    entry_price=signal.entry,
                    stop_loss=signal.stop_loss,
                    var_amount=var_amount,
                    max_leverage=max_leverage
                )
                logger.info(f"Calculated order quantity: {quantity} (min: {min_qty}, step: {qty_step})")
            
            # Step 8: Convert signal side ("long", "short") to Bybit API side ("Buy", "Sell")
            order_side = "Buy" if signal.side == "long" else "Sell"
            
            # Step 9: Check for priority conflicts and handle order cancellations
            logger.info(f"🎯 Checking priority conflicts for {symbol} (Priority: {signal.priority}, Side: {order_side})")
            
            conflict_check = await self.bybit_service.check_priority_conflicts(
                symbol=symbol,
                requested_priority=signal.priority,
                requested_side=order_side
            )
            
            if not conflict_check['allow_order']:
                logger.warning(f"Order blocked due to priority conflict: {conflict_check['reason']}")
                return {
                    "success": False,
                    "message": f"Order blocked: {conflict_check['reason']}",
                    "error": "priority_conflict",
                    "symbol": symbol,
                    "side": order_side,
                    "priority": signal.priority,
                    "conflicts": conflict_check['conflicts_found'],
                    "strategy_id": strategy_id
                }
            
            # Cancel lower priority orders if needed
            if conflict_check['orders_to_cancel']:
                logger.info(f"🗑️ Cancelling {len(conflict_check['orders_to_cancel'])} conflicting orders before placing new order")
                cancellation_result = await self.bybit_service.cancel_orders_by_priority(conflict_check['orders_to_cancel'])
                
                success_count = len(cancellation_result['cancelled_orders'])
                total_count = cancellation_result['total_attempted']
                
                if success_count < total_count:
                    logger.warning(f"Only cancelled {success_count}/{total_count} orders. Proceeding anyway.")
                else:
                    logger.info(f"✅ Successfully cancelled all {success_count} conflicting orders")
            
            # Close lower priority positions if needed (Priority 1 override)
            if conflict_check['positions_to_close']:
                logger.info(f"🔄 Closing {len(conflict_check['positions_to_close'])} Priority 2 positions for Priority 1 override")
                closure_result = await self.bybit_service.close_all_positions(symbol, f"Priority {signal.priority} override")
                
                closed_count = len(closure_result['closed_positions'])
                total_positions = closure_result['total_attempted']
                
                if closed_count < total_positions:
                    logger.warning(f"Only closed {closed_count}/{total_positions} positions. Proceeding anyway.")
                else:
                    logger.info(f"✅ Successfully closed all {closed_count} Priority 2 positions")
            
            # Step 10: Handle special order types
            if signal.reduce_only:
                logger.info(f"Processing reduce-only order for {symbol}")
                # For reduce-only orders, we might need different logic
                # This could be implemented later for partial TP/SL functionality
            
            if signal.close_position:
                logger.info(f"Processing close position order for {symbol}")
                # For closing positions, we might want to close specific strategy positions
                # This could be implemented later for strategy-specific position closure
            
            # Step 11: Place the limit order with SL/TP and strategy ID
            order_result = await self.bybit_service.place_limit_order(
                symbol=symbol,
                side=order_side,
                qty=quantity,
                price=signal.entry,
                sl=signal.stop_loss,
                tp=signal.take_profit,
                strategy_id=strategy_id,
                priority=signal.priority
            )
            
            # Check if order placement was successful
            if order_result.get('success', False):
                logger.info(f"Order placed successfully for strategy {strategy_id}: {order_result}")
                
                # Log trade to Google Sheets if available
                await self._log_trade_entry(
                    signal=signal,
                    symbol=symbol,
                    order_side=order_side,
                    quantity=quantity,
                    var_amount=var_amount,
                    order_result=order_result
                )
                
                return {
                    "success": True,
                    "message": "Order placed successfully",
                    "order": order_result.get('order', {}),
                    "symbol": symbol,
                    "side": order_side,
                    "quantity": quantity,
                    "entry": signal.entry,
                    "stop_loss": signal.stop_loss,
                    "take_profit": signal.take_profit,
                    "risk_amount": var_amount,
                    "strategy_id": strategy_id,
                    "priority": signal.priority,
                    "position_idx": order_result.get('position_idx', 0)
                }
            else:
                # Order placement failed but handled gracefully
                logger.warning(f"Order placement failed for strategy {strategy_id}: {order_result.get('message', 'Unknown error')}")
                return {
                    "success": False,
                    "message": f"Order placement failed: {order_result.get('message', 'Unknown error')}",
                    "error": order_result.get('error', 'unknown_error'),
                    "order_details": order_result.get('order_details', {}),
                    "symbol": symbol,
                    "side": order_side,
                    "quantity": quantity,
                    "entry": signal.entry,
                    "stop_loss": signal.stop_loss,
                    "take_profit": signal.take_profit,
                    "risk_amount": var_amount,
                    "strategy_id": strategy_id,
                    "priority": signal.priority
                }
        
        except Exception as e:
            stack_trace = traceback.format_exc()
            logger.error(f"Error processing signal for strategy {signal.strategy_id or 'default'}: {e}\n{stack_trace}")
            return {
                "success": False,
                "message": f"Error processing signal: {str(e)}",
                "error": "signal_processing_error",
                "symbol": signal.symbol,
                "side": signal.side,
                "entry": signal.entry,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "strategy_id": signal.strategy_id or "default",
                "priority": getattr(signal, 'priority', 2)
            }
    
    async def _log_trade_entry(
        self, 
        signal: TradingViewSignal, 
        symbol: str, 
        order_side: str, 
        quantity: float, 
        var_amount: float, 
        order_result: Dict[str, Any]
    ) -> None:
        """
        Log trade entry to Google Sheets.
        
        Args:
            signal: Original trading signal
            symbol: Normalized symbol
            order_side: Order side (Buy/Sell)
            quantity: Order quantity
            var_amount: Risk amount
            order_result: Order placement result
        """
        if not self.sheets_service or not self.sheets_service.is_connected:
            logger.debug("Google Sheets not available - skipping trade logging")
            return
        
        try:
            # Get order ID from result
            order_id = order_result.get('order', {}).get('orderLinkId', '')
            if not order_id:
                order_id = order_result.get('order', {}).get('orderId', '')
            
            # Determine session type if it's a Silver Bullet strategy
            session_type = None
            if signal.strategy_id and 'silver_bullet' in signal.strategy_id.lower():
                # You could integrate with session manager here to get current session
                session_type = "Silver Bullet"
            
            # Create trade journal entry
            trade_entry = TradeJournalEntry(
                trade_id=order_id or f"{symbol}_{int(datetime.utcnow().timestamp())}",
                symbol=symbol,
                strategy=signal.strategy_id or "default",
                priority=signal.priority or 2,
                entry_time=datetime.utcnow(),
                entry_price=signal.entry,
                side=signal.side,  # Keep original side (long/short)
                quantity=quantity,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                risk_amount=var_amount,
                session_type=session_type,
                status="OPEN"
            )
            
            # Log to Google Sheets
            success = await self.sheets_service.log_trade_entry(trade_entry)
            
            if success:
                logger.info(f"📝 Trade logged to Google Sheets: {trade_entry.trade_id}")
            else:
                logger.warning(f"Failed to log trade to Google Sheets: {trade_entry.trade_id}")
                
        except Exception as e:
            logger.error(f"Error logging trade to Google Sheets: {e}")
    
    def _log_instrument_info(self, symbol: str, instrument_info: Dict[str, Any]) -> None:
        """
        Log key instrument information.
        
        Args:
            symbol (str): Symbol
            instrument_info (Dict[str, Any]): Instrument information
        """
        try:
            market_type = instrument_info.get('market_type', 'unknown')
            
            # Log basic info
            logger.info(f"Instrument details for {symbol} ({market_type}):")
            
            # Log precision info
            if 'precision' in instrument_info:
                precision = instrument_info['precision']
                logger.info(f"  Precision: amount={precision.get('amount')}, price={precision.get('price')}")
            
            # Log limits info
            if 'limits' in instrument_info:
                limits = instrument_info['limits']
                amount_limits = limits.get('amount', {})
                price_limits = limits.get('price', {})
                cost_limits = limits.get('cost', {})
                leverage_limits = limits.get('leverage', {})
                
                logger.info(f"  Amount limits: min={amount_limits.get('min')}, max={amount_limits.get('max')}")
                logger.info(f"  Price limits: min={price_limits.get('min')}, max={price_limits.get('max')}")
                logger.info(f"  Cost limits: min={cost_limits.get('min')}, max={cost_limits.get('max')}")
                logger.info(f"  Leverage limits: min={leverage_limits.get('min')}, max={leverage_limits.get('max')}")
            
            # Log additional info from raw API response
            if 'info' in instrument_info and isinstance(instrument_info['info'], dict):
                info = instrument_info['info']
                
                # Log lotSizeFilter if available
                if 'lotSizeFilter' in info:
                    lot_filter = info['lotSizeFilter']
                    logger.info(f"  Lot size filter: {lot_filter}")
                
                # Log leverageFilter if available
                if 'leverageFilter' in info:
                    leverage_filter = info['leverageFilter']
                    logger.info(f"  Leverage filter: {leverage_filter}")
                
                # Log priceFilter if available
                if 'priceFilter' in info:
                    price_filter = info['priceFilter']
                    logger.info(f"  Price filter: {price_filter}")
        
        except Exception as e:
            logger.warning(f"Error logging instrument info: {e}")
    
    def _get_max_leverage(self, instrument_info: Dict[str, Any]) -> int:
        """
        Extract the maximum leverage from instrument info.
        
        Args:
            instrument_info (Dict[str, Any]): Instrument information
        
        Returns:
            int: Maximum leverage
        """
        # Set reasonable defaults based on market type
        market_type = instrument_info.get('market_type', '')
        if market_type == 'spot':
            logger.info(f"Market type is spot, using leverage: 1x")
            return 1
        elif market_type in ['linear', 'inverse', 'swap', 'future']:
            # Use a more reasonable default for perpetual futures
            default_leverage = 10  # Conservative but reasonable for most perpetuals
        else:
            default_leverage = 1
        
        try:
            # First, check if we successfully fetched leverage from Bybit V5 API
            if ('limits' in instrument_info and 
                'leverage' in instrument_info['limits'] and 
                instrument_info['limits']['leverage'].get('max') is not None):
                max_lev = int(instrument_info['limits']['leverage']['max'])
                logger.info(f"Found max leverage in limits.leverage.max: {max_lev}x")
                return max_lev
            
            # Try Bybit-specific leverageFilter in the raw API response
            if ('info' in instrument_info and 
                isinstance(instrument_info['info'], dict) and 
                'leverageFilter' in instrument_info['info']):
                leverage_filter = instrument_info['info']['leverageFilter']
                if isinstance(leverage_filter, dict) and 'maxLeverage' in leverage_filter:
                    max_lev_str = leverage_filter['maxLeverage']
                    if max_lev_str and max_lev_str != '0':
                        max_lev = int(float(max_lev_str))
                        logger.info(f"Found max leverage in info.leverageFilter.maxLeverage: {max_lev}x")
                        return max_lev
            
            # Try direct leverage field in the raw API response
            if ('info' in instrument_info and 
                isinstance(instrument_info['info'], dict) and 
                'leverage' in instrument_info['info']):
                leverage_value = instrument_info['info']['leverage']
                if leverage_value and str(leverage_value) != '0':
                    max_lev = int(float(leverage_value))
                    logger.info(f"Found max leverage in info.leverage: {max_lev}x")
                    return max_lev
            
            # Check CCXT standardized leverage limits
            if ('limits' in instrument_info and 
                'leverage' in instrument_info['limits'] and 
                instrument_info['limits']['leverage'] is not None):
                leverage_limits = instrument_info['limits']['leverage']
                if isinstance(leverage_limits, dict) and 'max' in leverage_limits:
                    max_lev_value = leverage_limits['max']
                    if max_lev_value is not None and max_lev_value > 0:
                        max_lev = int(max_lev_value)
                        logger.info(f"Found max leverage in CCXT limits: {max_lev}x")
                        return max_lev
            
            # For linear perpetuals, try to infer from symbol patterns
            if market_type == 'linear':
                # Most USDT perpetuals on Bybit have decent leverage
                logger.info(f"Linear perpetual detected, using reasonable default leverage: {default_leverage}x")
                return default_leverage
            
            # If all else fails, use the default based on market type
            logger.warning(f"Could not find max leverage in instrument info for {market_type} market. Using default: {default_leverage}x")
            return default_leverage
        
        except Exception as e:
            logger.error(f"Error extracting max leverage: {e}")
            logger.info(f"Using default leverage due to error: {default_leverage}x")
            return default_leverage
    
    async def _calculate_var(self, strategy_id: str) -> float:
        """
        Calculate the Value at Risk (VaR) amount based on configuration and strategy-specific multiplier.
        
        Args:
            strategy_id (str): Strategy identifier for strategy-specific VaR calculation
        
        Returns:
            float: VaR amount in USDT
        """
        var_type = config.risk_management.var_type
        var_value = config.risk_management.var_value
        
        # Get strategy-specific multiplier
        var_multiplier = 1.0
        if hasattr(config, 'multi_strategy') and config.multi_strategy and config.multi_strategy.enabled:
            strategy_config = self._get_strategy_config(strategy_id)
            var_multiplier = strategy_config.var_multiplier
            logger.info(f"Using VaR multiplier for strategy {strategy_id}: {var_multiplier}x")
        
        if var_type == "fixed_amount":
            base_var = var_value
            final_var = base_var * var_multiplier
            logger.info(f"Using fixed amount VaR: {base_var} × {var_multiplier} = {final_var} USDT")
            return final_var
        
        elif var_type == "portfolio_percentage":
            # Get the USDT balance
            balance = await self.bybit_service.get_usdt_balance()
            
            # Calculate the base VaR amount as a percentage of the balance
            base_var = balance * var_value
            final_var = base_var * var_multiplier
            
            # Log the calculation
            logger.info(f"Calculated VaR as {var_value * 100}% of {balance} USDT × {var_multiplier} = {final_var} USDT")
            
            return final_var
        
        else:
            # This shouldn't happen due to Pydantic validation, but just in case
            logger.error(f"Invalid VaR type: {var_type}")
            return 1.0  # Default to a conservative value
    
    async def _calculate_quantity(
        self, 
        symbol: str, 
        instrument_info: Dict[str, Any], 
        entry_price: float, 
        stop_loss: float, 
        var_amount: float,
        max_leverage: int
    ) -> Tuple[float, float, float]:
        """
        Calculate the order quantity based on the VaR, entry price, and stop loss.
        
        Args:
            symbol (str): Symbol to calculate quantity for
            instrument_info (Dict[str, Any]): Instrument information
            entry_price (float): Entry price
            stop_loss (float): Stop loss price
            var_amount (float): VaR amount in USDT
            max_leverage (int): Maximum leverage
        
        Returns:
            Tuple[float, float, float]: (Order quantity, minimum quantity, quantity step)
        """
        try:
            # Get the quantity step and minimum order quantity from instrument info
            qty_step = self._get_qty_step(instrument_info)
            min_qty = self._get_min_qty(instrument_info)
            
            # Get market type to determine calculation method
            market_type = instrument_info.get('market_type', 'unknown')
            logger.info(f"Calculating quantity for {symbol} ({market_type}) with VaR: {var_amount} USDT")
            
            # Calculate the price difference between entry and stop loss
            price_difference = abs(entry_price - stop_loss)
            
            if price_difference == 0:
                logger.error("Entry price and stop loss are the same. Cannot calculate quantity.")
                raise ValueError("Entry price and stop loss are the same.")
            
            # Calculate the raw quantity based on market type
            if market_type in ['linear', 'inverse', 'swap', 'future']:
                # For futures/perpetual contracts with leverage
                logger.info(f"Using leveraged calculation with leverage: {max_leverage}x")
                logger.info(f"Price difference: {price_difference} ({entry_price} - {stop_loss})")
                
                # Calculate raw quantity based on VaR and price difference
                # VaR-based position sizing: risk per contract = price_difference
                # Maximum quantity = VaR / risk_per_contract
                raw_qty = var_amount / price_difference
                
                logger.info(f"Raw quantity calculation: {var_amount} ÷ {price_difference} = {raw_qty}")
                
                # Calculate the notional value and required margin
                notional_value = raw_qty * entry_price
                required_margin = notional_value / max_leverage
                
                logger.info(f"Notional value: {raw_qty} × {entry_price} = {notional_value} USDT")
                logger.info(f"Required margin with {max_leverage}x leverage: {notional_value} ÷ {max_leverage} = {required_margin} USDT")
                
                # Check for minimum notional value requirements
                min_order_value = self._get_min_notional_value(instrument_info)
                
                if min_order_value > 0 and notional_value < min_order_value:
                    logger.warning(f"Order notional value ({notional_value}) is below minimum ({min_order_value}). Adjusting quantity.")
                    # Adjust raw quantity to meet minimum notional value
                    raw_qty = (min_order_value / entry_price) * 1.01  # Add 1% buffer
                    notional_value = raw_qty * entry_price
                    required_margin = notional_value / max_leverage
                    logger.info(f"Adjusted quantity to meet minimum notional: {raw_qty} (notional: {notional_value}, margin: {required_margin})")
            else:
                # For spot markets (no leverage)
                logger.info("Using spot calculation (no leverage)")
                
                # In spot markets, we simply use VaR as the position size
                # or calculate based on stop loss distance
                raw_qty = var_amount / entry_price
                
                logger.info(f"Raw spot quantity calculation: {var_amount} ÷ {entry_price} = {raw_qty}")
            
            logger.info(f"Raw quantity: {raw_qty}, Qty step: {qty_step}, Min qty: {min_qty}")
            
            # For leveraged markets, check if we have sufficient margin
            if market_type in ['linear', 'inverse', 'swap', 'future']:
                # Get available balance to check margin requirements
                try:
                    available_balance = await self.bybit_service.get_usdt_balance()
                    notional_value = raw_qty * entry_price
                    required_margin = notional_value / max_leverage
                    
                    logger.info(f"Balance check: Available={available_balance} USDT, Required margin={required_margin} USDT")
                    
                    if required_margin > available_balance:
                        # Calculate maximum possible quantity with available balance
                        max_possible_notional = available_balance * max_leverage * 0.95  # Use 95% of available balance for safety
                        max_possible_qty = max_possible_notional / entry_price
                        max_var_with_balance = max_possible_qty * price_difference
                        
                        logger.warning(f"Insufficient margin! Required: {required_margin} USDT, Available: {available_balance} USDT")
                        logger.info(f"Maximum possible VaR with current balance: {max_var_with_balance} USDT")
                        logger.info(f"Maximum possible quantity: {max_possible_qty} contracts")
                        
                        # Auto-adjust the quantity to fit available balance
                        if max_possible_qty >= min_qty:
                            logger.info(f"Auto-adjusting quantity from {raw_qty} to {max_possible_qty} to fit available balance")
                            raw_qty = max_possible_qty
                            # Recalculate margins with adjusted quantity
                            notional_value = raw_qty * entry_price
                            required_margin = notional_value / max_leverage
                            logger.info(f"Adjusted position: Quantity={raw_qty}, Notional={notional_value} USDT, Margin={required_margin} USDT")
                        else:
                            logger.error(f"Even minimum quantity ({min_qty}) would require more margin than available")
                            # We'll proceed and let the exchange reject it with a clear error
                except Exception as balance_error:
                    logger.warning(f"Could not check balance for margin validation: {balance_error}")
            
            # Check if this market requires whole numbers
            requires_whole_numbers = self._check_if_requires_whole_numbers(instrument_info)
            
            if requires_whole_numbers:
                logger.info(f"Market appears to require whole numbers for quantity")
                # Round down to whole number
                adjusted_qty = math.floor(raw_qty)
                
                # Ensure the quantity is at least the minimum
                if adjusted_qty < min_qty:
                    logger.warning(f"Calculated quantity ({adjusted_qty}) is below minimum ({min_qty}). Using minimum.")
                    adjusted_qty = math.ceil(min_qty)  # Use ceiling to ensure we meet minimum
                
                logger.info(f"Final quantity (whole number): {adjusted_qty}")
                return adjusted_qty, min_qty, qty_step
            
            # For other markets, apply standard quantity adjustments
            # Use Decimal for more precise calculations
            d_raw_qty = Decimal(str(raw_qty))
            d_qty_step = Decimal(str(qty_step))
            
            # Calculate how many steps fit into raw_qty
            steps = d_raw_qty / d_qty_step
            
            # Floor to get whole number of steps
            steps_floor = steps.to_integral_exact(rounding=ROUND_DOWN)
            
            # Multiply by step size to get adjusted quantity
            adjusted_qty = float(steps_floor * d_qty_step)
            
            # Ensure the quantity is at least the minimum
            if adjusted_qty < min_qty:
                logger.warning(f"Calculated quantity ({adjusted_qty}) is below minimum ({min_qty}). Using minimum.")
                adjusted_qty = min_qty
            
            # Format the quantity according to the precision
            precision = self._get_quantity_precision(instrument_info)
            formatted_qty = round(adjusted_qty, precision)
            
            logger.info(f"Final quantity after adjustments: {formatted_qty}")
            return formatted_qty, min_qty, qty_step
        
        except Exception as e:
            logger.error(f"Error calculating quantity: {e}", exc_info=True)
            raise
    
    def _get_qty_step(self, instrument_info: Dict[str, Any]) -> float:
        """
        Get the quantity step from instrument info.
        
        Args:
            instrument_info (Dict[str, Any]): Instrument information
        
        Returns:
            float: Quantity step
        """
        # Default to a conservative value if not found
        default_step = 0.001
        
        try:
            # Try CCXT standardized format first
            if 'precision' in instrument_info and 'amount' in instrument_info['precision']:
                precision = instrument_info['precision']['amount']
                if precision is not None:
                    if isinstance(precision, float):
                        return precision
                    elif isinstance(precision, int):
                        return 10 ** -precision
            
            # Try Bybit-specific formats
            if 'info' in instrument_info and isinstance(instrument_info['info'], dict):
                # Try lotSizeFilter
                if 'lotSizeFilter' in instrument_info['info']:
                    lot_filter = instrument_info['info']['lotSizeFilter']
                    if isinstance(lot_filter, dict) and 'qtyStep' in lot_filter:
                        return float(lot_filter['qtyStep'])
            
            # If all else fails, use the default
            logger.warning(f"Could not find quantity step in instrument info. Using default: {default_step}")
            return default_step
        
        except Exception as e:
            logger.error(f"Error extracting quantity step: {e}")
            return default_step
    
    def _get_min_qty(self, instrument_info: Dict[str, Any]) -> float:
        """
        Get the minimum order quantity from instrument info.
        
        Args:
            instrument_info (Dict[str, Any]): Instrument information
        
        Returns:
            float: Minimum order quantity
        """
        # Default to a conservative value if not found
        default_min = 0.001
        
        try:
            # Try CCXT standardized format first
            if 'limits' in instrument_info and 'amount' in instrument_info['limits']:
                amount_limits = instrument_info['limits']['amount']
                if amount_limits is not None and 'min' in amount_limits and amount_limits['min'] is not None:
                    return float(amount_limits['min'])
            
            # Try Bybit-specific formats
            if 'info' in instrument_info and isinstance(instrument_info['info'], dict):
                # Try lotSizeFilter
                if 'lotSizeFilter' in instrument_info['info']:
                    lot_filter = instrument_info['info']['lotSizeFilter']
                    if isinstance(lot_filter, dict) and 'minOrderQty' in lot_filter:
                        return float(lot_filter['minOrderQty'])
            
            # If all else fails, use the default
            logger.warning(f"Could not find min order quantity in instrument info. Using default: {default_min}")
            return default_min
        
        except Exception as e:
            logger.error(f"Error extracting min order quantity: {e}")
            return default_min
    
    def _get_quantity_precision(self, instrument_info: Dict[str, Any]) -> int:
        """
        Get the quantity precision from instrument info.
        
        Args:
            instrument_info (Dict[str, Any]): Instrument information
        
        Returns:
            int: Quantity precision
        """
        # Default to a conservative value if not found
        default_precision = 4
        
        try:
            # Try CCXT standardized format first
            if 'precision' in instrument_info and 'amount' in instrument_info['precision']:
                precision = instrument_info['precision']['amount']
                if precision is not None:
                    if isinstance(precision, int):
                        return precision
                    elif isinstance(precision, float):
                        # Convert decimal precision to number of decimal places
                        return abs(int(math.log10(precision)))
            
            # Try calculating from qty_step
            qty_step = self._get_qty_step(instrument_info)
            if qty_step is not None:
                # Calculate precision from step size
                return abs(int(math.log10(qty_step)))
            
            # If all else fails, use the default
            logger.warning(f"Could not determine quantity precision. Using default: {default_precision}")
            return default_precision
        
        except Exception as e:
            logger.error(f"Error determining quantity precision: {e}")
            return default_precision
    
    def _get_min_notional_value(self, instrument_info: Dict[str, Any]) -> float:
        """
        Get the minimum notional value from instrument info.
        
        Args:
            instrument_info (Dict[str, Any]): Instrument information
        
        Returns:
            float: Minimum notional value
        """
        # Default to zero (no minimum) if not found
        default_min = 0.0
        
        try:
            # Try CCXT standardized format first
            if 'limits' in instrument_info and 'cost' in instrument_info['limits']:
                cost_limits = instrument_info['limits']['cost']
                if cost_limits is not None and 'min' in cost_limits and cost_limits['min'] is not None:
                    return float(cost_limits['min'])
            
            # Try Bybit-specific formats
            if 'info' in instrument_info and isinstance(instrument_info['info'], dict):
                # Try lotSizeFilter for minOrderAmt
                if 'lotSizeFilter' in instrument_info['info']:
                    lot_filter = instrument_info['info']['lotSizeFilter']
                    if isinstance(lot_filter, dict) and 'minOrderAmt' in lot_filter:
                        return float(lot_filter['minOrderAmt'])
            
            # If all else fails, use the default
            logger.debug(f"Could not find min notional value in instrument info. Using default: {default_min}")
            return default_min
        
        except Exception as e:
            logger.error(f"Error extracting min notional value: {e}")
            return default_min
    
    def _check_if_requires_whole_numbers(self, instrument_info: Dict[str, Any]) -> bool:
        """
        Check if the instrument requires whole number quantities (common for some futures).
        
        Args:
            instrument_info (Dict[str, Any]): Instrument information
            
        Returns:
            bool: True if the instrument likely requires whole numbers
        """
        try:
            # Check market type
            market_type = instrument_info.get('market_type', '')
            if market_type not in ['linear', 'inverse', 'swap', 'future']:
                return False
            
            # Check if minOrderQty is a whole number - indicates contract sizing
            min_qty = self._get_min_qty(instrument_info)
            if min_qty.is_integer() and min_qty >= 1.0:
                # Check qty step
                qty_step = self._get_qty_step(instrument_info)
                # If step size is also a whole number, it's likely a contract-based instrument
                if qty_step.is_integer() and qty_step >= 1.0:
                    return True
            
            # Check 'lot_size_filter' for additional clues
            if 'info' in instrument_info and isinstance(instrument_info['info'], dict):
                lot_filter = instrument_info['info'].get('lotSizeFilter', {})
                if isinstance(lot_filter, dict):
                    # If basePrecision is 0 or 1, it likely means whole numbers are required
                    base_precision = lot_filter.get('basePrecision', '')
                    if base_precision in ['0', '1', 0, 1]:
                        return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error checking if market requires whole numbers: {e}")
            return False
    
    def _get_strategy_config(self, strategy_id: str):
        """
        Get configuration for a specific strategy.
        
        Args:
            strategy_id (str): Strategy identifier
        
        Returns:
            StrategyConfig: Strategy configuration
        """
        try:
            if (hasattr(config, 'multi_strategy') and 
                config.multi_strategy and 
                config.multi_strategy.strategy_configs):
                
                # Try to get specific strategy config
                if strategy_id in config.multi_strategy.strategy_configs:
                    return config.multi_strategy.strategy_configs[strategy_id]
                
                # Fall back to default strategy config
                if 'default' in config.multi_strategy.strategy_configs:
                    logger.info(f"Strategy {strategy_id} not found, using default config")
                    return config.multi_strategy.strategy_configs['default']
            
            # If no multi-strategy config, create default
            logger.info(f"No strategy config found for {strategy_id}, using defaults")
            return StrategyConfig()
            
        except Exception as e:
            logger.error(f"Error getting strategy config for {strategy_id}: {e}")
            return StrategyConfig() 