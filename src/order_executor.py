import ccxt.async_support as ccxt
from typing import Dict, Optional, Tuple, Any
import time
import math # For formatting

class OrderExecutor:
    def __init__(self, data_ingestion_module, config_manager, main_logger):
        self.config = config_manager
        self.logger = main_logger.bind(name="OrderExecutor")
        self.dim = data_ingestion_module
        self.exchange = self.dim.exchange # Assumes DIM has initialized exchange
        self.rm_config = config_manager.get_risk_management_config()
        
        if not self.exchange:
            self.logger.critical("Exchange object not found in DataIngestionModule! OrderExecutor cannot function.")
            # Consider raising an exception here
            raise ValueError("Exchange not initialized in DataIngestionModule for OrderExecutor.")
            
        self.logger.info("OrderExecutor initialized.")

    # --- Helper for Formatting --- 
    def _format_price(self, symbol: str, price: float, specs: Optional[Dict] = None) -> Optional[str]:
        """Formats price according to the tick size for the symbol."""
        try:
            if specs is None:
                 # Try fetching on the fly - might be slow, better to pass specs
                 self.logger.warning(f"Specs not passed to _format_price for {symbol}. Fetching on demand...")
                 # This requires get_contract_specs to be sync or running this in async context
                 # For simplicity, assume specs are passed or formatting fails
                 return None 
                 
            tick_size = specs.get('tick_size')
            if tick_size is None or tick_size <= 0:
                self.logger.error(f"Invalid tick_size {tick_size} for {symbol} in specs. Cannot format price.")
                return None
            
            # Calculate precision based on tick_size
            precision = 0
            if tick_size < 1:
                tick_size_str = f"{tick_size:.10f}".rstrip('0')
                if '.' in tick_size_str:
                    precision = len(tick_size_str.split('.')[1])
            
            # Format the price string
            formatted_price = f"{price:.{precision}f}"
            # self.logger.debug(f"Formatted price for {symbol}: {price} -> {formatted_price} (precision: {precision})")
            return formatted_price
        except Exception as e:
             self.logger.error(f"Error formatting price {price} for {symbol}: {e}")
             return None

    def _format_quantity(self, symbol: str, quantity: float, specs: Optional[Dict] = None) -> Optional[str]:
        """Formats quantity according to the lot size (quantity step) for the symbol."""
        try:
            if specs is None:
                 self.logger.warning(f"Specs not passed to _format_quantity for {symbol}. Fetching on demand...")
                 return None
                 
            qty_step = specs.get('lot_size') # lot_size is used for qtyStep in DIM
            if qty_step is None or qty_step <= 0:
                self.logger.error(f"Invalid qty_step (lot_size) {qty_step} for {symbol} in specs. Cannot format quantity.")
                return None

            # Calculate precision based on qty_step
            precision = 0
            if qty_step < 1:
                step_str = f"{qty_step:.10f}".rstrip('0')
                if '.' in step_str:
                    precision = len(step_str.split('.')[1])
            
            # Format the quantity string
            formatted_qty = f"{quantity:.{precision}f}"
            # self.logger.debug(f"Formatted quantity for {symbol}: {quantity} -> {formatted_qty} (precision: {precision})")
            return formatted_qty
        except Exception as e:
             self.logger.error(f"Error formatting quantity {quantity} for {symbol}: {e}")
             return None

    # --- Order Placement Methods --- 
    async def place_limit_entry_order(self, symbol: str, side: str, qty: float, price: float, params: Optional[Dict] = None) -> Optional[Dict]:
        """Places a limit entry order."""
        if not self.exchange:
            self.logger.error("Exchange not available.")
            return None
        
        # Fetch specs for formatting
        specs = await self.dim.get_contract_specs(symbol)
        if not specs:
             self.logger.error(f"Cannot place order for {symbol}, failed to get contract specs.")
             return None
             
        formatted_qty = self._format_quantity(symbol, qty, specs)
        formatted_price = self._format_price(symbol, price, specs)
        
        if formatted_qty is None or formatted_price is None:
            self.logger.error(f"Failed to format quantity or price for {symbol}. Qty: {qty}, Price: {price}")
            return None
            
        order_type = 'Limit'
        ccxt_side = side.lower()
        self.logger.info(f"Placing {ccxt_side} {order_type} entry order: {symbol}, Qty: {formatted_qty}, Price: {formatted_price}")
        
        default_params = { 'timeInForce': 'GTC' }
        if params: default_params.update(params)

        try:
            order_response = await self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=ccxt_side,
                amount=float(formatted_qty),
                price=float(formatted_price),
                params=default_params
            )
            
            # --- MORE ROBUST CHECKING ---
            if not isinstance(order_response, dict):
                self.logger.error(f"Unexpected response type from create_order: {type(order_response)}. Response: {order_response}")
                return None

            bybit_ret_code_raw = order_response.get('retCode')
            if bybit_ret_code_raw is not None:
                try:
                    bybit_ret_code = int(bybit_ret_code_raw)
                    if bybit_ret_code != 0:
                        ret_msg = order_response.get('retMsg', 'Unknown Bybit Error')
                        self.logger.error(f"Bybit API Error placing limit entry order: Code={bybit_ret_code}, Msg='{ret_msg}'. Symbol={symbol}")
                        return None # Explicitly return None on Bybit error
                except (ValueError, TypeError):
                    self.logger.error(f"Could not interpret retCode '{bybit_ret_code_raw}' as integer for {symbol}. Raw: {order_response}")
                    return None # Treat as failure

            ccxt_order_id = order_response.get('id')
            if ccxt_order_id:
                info_error_code_raw = order_response.get('info', {}).get('retCode')
                if info_error_code_raw is not None:
                     try:
                         info_error_code = int(info_error_code_raw)
                         if info_error_code != 0:
                              ret_msg = order_response.get('info', {}).get('retMsg', 'Unknown Bybit Error in Info')
                              self.logger.error(f"Bybit API Error (in info dict) placing limit entry order: Code={info_error_code}, Msg='{ret_msg}'. Symbol={symbol}")
                              return None # Treat as failure
                     except (ValueError, TypeError):
                          self.logger.error(f"Could not interpret info.retCode '{info_error_code_raw}' as integer for {symbol}. Treating as potential issue.")
                          return None # Treat as failure
                
                # If we have an ID and no error codes indicated failure, assume success
                self.logger.info(f"Limit entry order placed successfully via CCXT for {symbol}. Order ID: {ccxt_order_id}")
                self.logger.debug(f"Order details: {order_response}")
                return order_response
            else:
                # No 'id' and top-level 'retCode' was 0 or missing - ambiguous response
                self.logger.error(f"Order placement response for limit entry {symbol} lacks CCXT ID and did not have a non-zero top-level retCode. Raw: {order_response}")
                return None
                 
        except ccxt.ExchangeError as e:
            self.logger.error(f"ExchangeError placing limit entry order for {symbol}: {e}", exc_info=True)
        except Exception as e:
            self.logger.error(f"Unexpected error placing limit entry order for {symbol}: {e}", exc_info=True)
        
        return None

    async def place_stop_loss_order(self, symbol: str, side: str, qty: float, stop_price: float, params: Optional[Dict] = None) -> Optional[Dict]:
        """Places a stop-loss order (typically STOP_MARKET)."""
        if not self.exchange:
            self.logger.error("Exchange not available.")
            return None

        specs = await self.dim.get_contract_specs(symbol)
        if not specs:
             self.logger.error(f"Cannot place SL for {symbol}, failed to get contract specs.")
             return None
             
        formatted_qty = self._format_quantity(symbol, qty, specs)
        formatted_stop_price = self._format_price(symbol, stop_price, specs)
        
        if formatted_qty is None or formatted_stop_price is None:
            self.logger.error(f"Failed to format quantity or stop_price for SL {symbol}. Qty: {qty}, StopPrice: {stop_price}")
            return None

        # Determine the side for the closing stop order (opposite of position)
        sl_side = 'sell' if side.lower() == 'buy' else 'buy'
        order_type = 'Stop' # This implies StopMarket on many exchanges
        
        self.logger.info(f"Placing {sl_side} {order_type} stop loss order: {symbol}, Qty: {formatted_qty}, Stop Price: {formatted_stop_price}")

        default_params = { 'reduceOnly': True, 'timeInForce': 'GTC', 'triggerBy': 'LastPrice'}
        if params: default_params.update(params)

        try:
            order_response = await self.exchange.create_order(
                symbol=symbol, type=order_type, side=sl_side, amount=float(formatted_qty),
                stopPrice=float(formatted_stop_price), params=default_params
            )

            # --- MORE ROBUST CHECKING ---
            if not isinstance(order_response, dict):
                self.logger.error(f"Unexpected response type from create_order (SL): {type(order_response)}. Response: {order_response}")
                return None

            bybit_ret_code_raw = order_response.get('retCode')
            if bybit_ret_code_raw is not None:
                try:
                    bybit_ret_code = int(bybit_ret_code_raw)
                    if bybit_ret_code != 0:
                        ret_msg = order_response.get('retMsg', 'Unknown Bybit Error')
                        self.logger.error(f"Bybit API Error placing SL order: Code={bybit_ret_code}, Msg='{ret_msg}'. Symbol={symbol}")
                        return None 
                except (ValueError, TypeError):
                    self.logger.error(f"Could not interpret retCode '{bybit_ret_code_raw}' as integer for SL {symbol}. Raw: {order_response}")
                    return None 

            ccxt_order_id = order_response.get('id')
            if ccxt_order_id:
                info_error_code_raw = order_response.get('info', {}).get('retCode')
                if info_error_code_raw is not None:
                     try:
                         info_error_code = int(info_error_code_raw)
                         if info_error_code != 0:
                              ret_msg = order_response.get('info', {}).get('retMsg', 'Unknown Bybit Error in Info')
                              self.logger.error(f"Bybit API Error (in info dict) placing SL order: Code={info_error_code}, Msg='{ret_msg}'. Symbol={symbol}")
                              return None 
                     except (ValueError, TypeError):
                          self.logger.error(f"Could not interpret info.retCode '{info_error_code_raw}' as integer for SL {symbol}. Treating as potential issue.")
                          return None 
                
                self.logger.info(f"Stop loss order placed successfully via CCXT for {symbol}. Order ID: {ccxt_order_id}")
                return order_response
            else:
                self.logger.error(f"Order placement response for SL {symbol} lacks CCXT ID and did not have a non-zero top-level retCode. Raw: {order_response}")
                return None

        except ccxt.ExchangeError as e:
            self.logger.error(f"ExchangeError placing stop loss order for {symbol}: {e}", exc_info=True)
        except Exception as e:
            self.logger.error(f"Unexpected error placing stop loss order for {symbol}: {e}", exc_info=True)
        return None

    async def place_take_profit_order(self, symbol: str, side: str, qty: float, price: float, params: Optional[Dict] = None) -> Optional[Dict]:
        """Places a take-profit order (typically LIMIT)."""
        if not self.exchange:
            self.logger.error("Exchange not available.")
            return None
            
        specs = await self.dim.get_contract_specs(symbol)
        if not specs:
             self.logger.error(f"Cannot place TP for {symbol}, failed to get contract specs.")
             return None
             
        formatted_qty = self._format_quantity(symbol, qty, specs)
        formatted_price = self._format_price(symbol, price, specs)
        
        if formatted_qty is None or formatted_price is None:
            self.logger.error(f"Failed to format quantity or price for TP {symbol}. Qty: {qty}, Price: {price}")
            return None
            
        # Determine the side for the closing TP order (opposite of position)
        tp_side = 'sell' if side.lower() == 'buy' else 'buy'
        order_type = 'Limit' 
        
        self.logger.info(f"Placing {tp_side} {order_type} take profit order: {symbol}, Qty: {formatted_qty}, Price: {formatted_price}")

        default_params = { 'reduceOnly': True, 'timeInForce': 'GTC' }
        if params: default_params.update(params)

        try:
            order_response = await self.exchange.create_order(
                symbol=symbol, type=order_type, side=tp_side, amount=float(formatted_qty),
                price=float(formatted_price), params=default_params
            )

            # --- MORE ROBUST CHECKING ---
            if not isinstance(order_response, dict):
                self.logger.error(f"Unexpected response type from create_order (TP): {type(order_response)}. Response: {order_response}")
                return None

            bybit_ret_code_raw = order_response.get('retCode')
            if bybit_ret_code_raw is not None:
                try:
                    bybit_ret_code = int(bybit_ret_code_raw)
                    if bybit_ret_code != 0:
                        ret_msg = order_response.get('retMsg', 'Unknown Bybit Error')
                        self.logger.error(f"Bybit API Error placing TP order: Code={bybit_ret_code}, Msg='{ret_msg}'. Symbol={symbol}")
                        return None
                except (ValueError, TypeError):
                    self.logger.error(f"Could not interpret retCode '{bybit_ret_code_raw}' as integer for TP {symbol}. Raw: {order_response}")
                    return None

            ccxt_order_id = order_response.get('id')
            if ccxt_order_id:
                info_error_code_raw = order_response.get('info', {}).get('retCode')
                if info_error_code_raw is not None:
                     try:
                         info_error_code = int(info_error_code_raw)
                         if info_error_code != 0:
                              ret_msg = order_response.get('info', {}).get('retMsg', 'Unknown Bybit Error in Info')
                              self.logger.error(f"Bybit API Error (in info dict) placing TP order: Code={info_error_code}, Msg='{ret_msg}'. Symbol={symbol}")
                              return None
                     except (ValueError, TypeError):
                          self.logger.error(f"Could not interpret info.retCode '{info_error_code_raw}' as integer for TP {symbol}. Treating as potential issue.")
                          return None 

                self.logger.info(f"Take profit order placed successfully via CCXT for {symbol}. Order ID: {ccxt_order_id}")
                return order_response
            else:
                self.logger.error(f"Order placement response for TP {symbol} lacks CCXT ID and did not have a non-zero top-level retCode. Raw: {order_response}")
                return None

        except ccxt.ExchangeError as e:
            self.logger.error(f"ExchangeError placing take profit order for {symbol}: {e}", exc_info=True)
        except Exception as e:
            self.logger.error(f"Unexpected error placing take profit order for {symbol}: {e}", exc_info=True)
        return None

    async def check_order_status(self, order_id: str, symbol: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Fetches the status of a specific order by ID."""
        if not self.exchange:
            self.logger.error("Exchange not available.")
            return None
            
        if not order_id:
            self.logger.error("Order ID not provided for status check.")
            return None
            
        self.logger.debug(f"Checking status for order ID: {order_id} on {symbol}")
        try:
            # Ensure exchange supports fetchOrder
            if not self.exchange.has.get('fetchOrder'):
                self.logger.error(f"Exchange {self.exchange.id} does not support fetchOrder.")
                return None
                
            order_status = await self.exchange.fetch_order(order_id, symbol, params=params if params else {})
            self.logger.debug(f"Status for order {order_id}: {order_status.get('status')}")
            return order_status
        except ccxt.OrderNotFound as e:
            self.logger.warning(f"OrderNotFound when checking status for order ID {order_id} on {symbol}: {e}")
            # This might mean it was filled and removed, or cancelled, or never existed.
            # Consider fetching trade history if needed to confirm fill.
            return {'status': 'notFound'} # Return a specific status
        except ccxt.ExchangeError as e:
            self.logger.error(f"ExchangeError checking order status for {order_id}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error checking order status for {order_id}: {e}", exc_info=True)
            
        return None

    async def cancel_order(self, order_id: str, symbol: str, params: Optional[Dict] = None) -> bool:
        """Cancels a specific order by ID."""
        if not self.exchange:
            self.logger.error("Exchange not available.")
            return False
            
        if not order_id:
            self.logger.error("Order ID not provided for cancellation.")
            return False
            
        self.logger.info(f"Attempting to cancel order ID: {order_id} on {symbol}")
        try:
            # Ensure exchange supports cancelOrder
            if not self.exchange.has.get('cancelOrder'):
                self.logger.error(f"Exchange {self.exchange.id} does not support cancelOrder.")
                return False

            await self.exchange.cancel_order(order_id, symbol, params=params if params else {})
            self.logger.info(f"Successfully requested cancellation for order ID: {order_id}")
            return True
        except ccxt.OrderNotFound as e:
            self.logger.warning(f"OrderNotFound when cancelling order ID {order_id} on {symbol}: {e} (Might be already filled/cancelled)")
            # Consider this a success in the sense that the order is no longer open
            return True 
        except ccxt.ExchangeError as e:
            self.logger.error(f"ExchangeError cancelling order {order_id}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error cancelling order {order_id}: {e}", exc_info=True)
            
        return False

# --- Example Usage (Requires Live/Testnet with API Keys) --- #
if __name__ == '__main__':
    import asyncio
    from .config_manager import ConfigManager
    from .logging_service import logger_instance
    from .data_ingestion import DataIngestionModule
    
    # --- !!! WARNING: This test block can place REAL orders if configured for live mainnet !!! ---
    # --- !!! Ensure API keys have appropriate permissions and you understand the risk !!! ---

    async def test_order_executor():
        logger_instance.info("--- Testing OrderExecutor --- CAUTION: LIVE/TEST ORDERS POSSIBLE ---")
        
        config_manager = ConfigManager("config.json")
        logger = logger_instance.bind(name="OrderExecutorTest")
        
        # Use settings from config (testnet or live)
        is_testnet = config_manager.get("cex_api.testnet", True)
        logger.info(f"Test running with testnet={is_testnet}")

        data_module = DataIngestionModule(config_manager, logger_instance)
        initialized = await data_module.initialize()
        if not initialized or not data_module.exchange:
            logger.error("Failed to initialize DataIngestionModule. Aborting test.")
            return

        order_executor = OrderExecutor(data_module, config_manager, logger_instance)

        # --- Test Parameters (Adjust carefully!) ---
        test_symbol = "BTCUSDT" # Use a symbol available on the target environment
        test_entry_price = None
        test_qty = None # Min qty
        
        # Fetch current price and minimum qty for realistic test
        try:
            logger.info(f"Fetching specs and ticker for {test_symbol}...")
            specs = await data_module.get_contract_specs(test_symbol)
            ticker = await data_module.exchange.fetch_ticker(test_symbol)
            
            if specs and ticker and specs.get('min_amount') and ticker.get('last'):
                test_qty = float(specs['min_amount'])
                current_price = float(ticker['last'])
                # Set limit price far away to likely not fill immediately for testing cancel/check
                test_entry_price_long = round(current_price * 0.80, specs.get('price_precision', 1)) # 20% below
                test_entry_price_short = round(current_price * 1.20, specs.get('price_precision', 1)) # 20% above
                test_sl_price_long = round(test_entry_price_long * 0.99, specs.get('price_precision', 1)) # 1% SL
                test_tp_price_long = round(test_entry_price_long * 1.02, specs.get('price_precision', 1)) # 2% TP
                test_sl_price_short = round(test_entry_price_short * 1.01, specs.get('price_precision', 1)) # 1% SL
                test_tp_price_short = round(test_entry_price_short * 0.98, specs.get('price_precision', 1)) # 2% TP
                logger.info(f"Using {test_symbol}: Min Qty={test_qty}, Current Price={current_price}, Test Entry Long={test_entry_price_long}, Test Entry Short={test_entry_price_short}")
            else:
                logger.error("Could not fetch necessary info (ticker/specs/min_amount) to set realistic test parameters.")
                await data_module.close()
                return
        except Exception as e:
            logger.error(f"Error fetching initial info: {e}", exc_info=True)
            await data_module.close()
            return
        
        # --- Test Placing Limit Entry --- 
        logger.info("\n--- Testing Place Limit Entry (LONG) ---")
        long_entry_order = await order_executor.place_limit_entry_order(test_symbol, "buy", test_qty, test_entry_price_long)
        long_order_id = long_entry_order.get('id') if long_entry_order else None

        if long_order_id:
            logger.info(f"Successfully placed LONG entry order {long_order_id}. Waiting a bit...")
            await asyncio.sleep(5)
            
            # --- Test Checking Status --- 
            logger.info(f"\n--- Testing Check Order Status ({long_order_id}) ---")
            status_result = await order_executor.check_order_status(long_order_id, test_symbol)
            logger.info(f"Status check result: {status_result}")
            
            # --- Test Cancelling Order --- 
            logger.info(f"\n--- Testing Cancel Order ({long_order_id}) ---")
            cancel_result = await order_executor.cancel_order(long_order_id, test_symbol)
            logger.info(f"Cancel result: {cancel_result}")
            
            await asyncio.sleep(3)
            logger.info(f"\n--- Re-Checking Status After Cancel ({long_order_id}) ---")
            status_after_cancel = await order_executor.check_order_status(long_order_id, test_symbol)
            logger.info(f"Status after cancel: {status_after_cancel}")
            # Expected status might be 'canceled', 'closed', or 'notFound' depending on exchange/timing
        else:
            logger.error("Failed to place LONG entry order, cannot test check/cancel.")

        # --- Test Placing SL/TP (Conceptual - requires position/fill) --- 
        # These would normally be placed *after* an entry order fills.
        logger.info("\n--- Testing Place SL Order (Conceptual - SHORT position) ---")
        # Assume we entered SHORT at test_entry_price_short
        sl_order = await order_executor.place_stop_loss_order(test_symbol, "sell", test_qty, test_sl_price_short)
        sl_order_id = sl_order.get('id') if sl_order else None
        if sl_order_id:
            logger.info(f"Placed conceptual SL order {sl_order_id}. Cancelling...")
            await asyncio.sleep(2)
            await order_executor.cancel_order(sl_order_id, test_symbol)
            
        logger.info("\n--- Testing Place TP Order (Conceptual - SHORT position) ---")
        tp_order = await order_executor.place_take_profit_order(test_symbol, "sell", test_qty, test_tp_price_short)
        tp_order_id = tp_order.get('id') if tp_order else None
        if tp_order_id:
            logger.info(f"Placed conceptual TP order {tp_order_id}. Cancelling...")
            await asyncio.sleep(2)
            await order_executor.cancel_order(tp_order_id, test_symbol)

        # --- Cleanup --- 
        await data_module.close()
        logger.info("--- OrderExecutor Test Done --- CAUTION: Check exchange UI for any unexpected open orders! ---")

    # Ensure logs directory exists
    log_config = ConfigManager("config.json").get_logging_config()
    log_file_path = Path(log_config.get("log_file", "logs/bot.log"))
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    asyncio.run(test_order_executor()) 