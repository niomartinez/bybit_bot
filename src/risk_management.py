import math
from .logging_service import logger_instance # Or your specific logger type

class RiskManagementModule:
    def __init__(self, data_ingestion_module, config_manager, logger): # Changed logger type hint
        self.data_ingestion_module = data_ingestion_module
        # self.config = config_manager.get_config() # Removed, use specific getters if needed
        self.rm_config = config_manager.get_risk_management_config()
        self.logger = logger.bind(name="RiskManagementModule") # Bind to its own name
        self.contract_specs_cache = {}

    async def get_contract_specifications(self, symbol: str):
        if symbol in self.contract_specs_cache:
            return self.contract_specs_cache[symbol]

        try:
            self.logger.info(f"Fetching contract specifications for {symbol} via DataIngestionModule...")
            
            raw_specs = await self.data_ingestion_module.get_contract_specs(symbol)

            if not raw_specs:
                self.logger.error(f"Raw contract specifications not found for symbol: {symbol} from DataIngestionModule.")
                return None

            # Map fields from DataIngestionModule.get_contract_specs to what RiskManagementModule expects
            # Expected fields:
            # 'tick_size', 'quantity_step', 'min_order_qty', 'max_order_qty', 
            # 'contract_size', 'is_linear', 'quote_currency'
            mapped_specs = {
                'tick_size': raw_specs.get('tick_size'), # DIM provides this directly, refined for Bybit
                'quantity_step': raw_specs.get('lot_size'), # DIM uses 'lot_size' for Bybit's qtyStep
                'min_order_qty': raw_specs.get('min_amount'), # DIM uses 'min_amount'
                'max_order_qty': raw_specs.get('max_amount'), # DIM uses 'max_amount'
                'contract_size': raw_specs.get('contract_size', 1), # Default to 1 if not found
                'is_linear': raw_specs.get('linear', True), # Default to True
                'quote_currency': raw_specs.get('quote')
            }

            # Validate critical mapped specs
            critical_keys = ['tick_size', 'quantity_step', 'min_order_qty', 'contract_size', 'quote_currency']
            missing_critical = [key for key in critical_keys if mapped_specs.get(key) is None]

            if missing_critical:
                self.logger.error(f"Critical contract specifications missing after mapping for {symbol}: {missing_critical}. Raw specs: {raw_specs}. Mapped: {mapped_specs}")
                return None
            
            # Convert to float where necessary, as they might come as strings from ccxt info sometimes
            try:
                mapped_specs['tick_size'] = float(mapped_specs['tick_size'])
                mapped_specs['quantity_step'] = float(mapped_specs['quantity_step'])
                mapped_specs['min_order_qty'] = float(mapped_specs['min_order_qty'])
                mapped_specs['contract_size'] = float(mapped_specs['contract_size'])
                if mapped_specs.get('max_order_qty') is not None:
                    mapped_specs['max_order_qty'] = float(mapped_specs['max_order_qty'])
            except ValueError as e:
                self.logger.error(f"Error converting spec values to float for {symbol}: {e}. Specs: {mapped_specs}")
                return None

            self.contract_specs_cache[symbol] = mapped_specs
            self.logger.info(f"Cached contract specifications for {symbol} from DIM: {mapped_specs}")
            return mapped_specs

        except Exception as e:
            self.logger.error(f"Error fetching/mapping contract specifications for {symbol} via DIM: {e}", exc_info=True)
            return None

    async def calculate_position_size(self, symbol: str, entry_price: float, stop_loss_price: float, fixed_dollar_risk: float):
        """
        Calculates the position size based on a fixed dollar risk.
        Assumes linear contracts (e.g., USDT margined).
        """
        self.logger.info(f"Calculating position size for {symbol} with entry {entry_price}, SL {stop_loss_price}, risk ${fixed_dollar_risk}")

        specs = await self.get_contract_specifications(symbol)
        if not specs:
            self.logger.error(f"Could not calculate position size for {symbol} due to missing contract specs.")
            return None, None

        if specs['quote_currency'] != 'USDT' and specs['is_linear']: # Add more robust check later
             self.logger.warning(f"Calculating position size for {symbol} which is {specs['quote_currency']} margined. Ensure logic is correct.")

        if entry_price == stop_loss_price:
            self.logger.error("Entry price cannot be equal to stop-loss price.")
            return None, None

        sl_distance_price = abs(entry_price - stop_loss_price)
        if sl_distance_price == 0:
            self.logger.error("Stop-loss distance is zero.")
            return None, None
        
        # For linear contracts (e.g., BTC/USDT where profit/loss is in USDT):
        # Risk per contract = SL distance in price * contract_size (e.g., 1 for BTCUSDT means 1 contract = 1 BTC)
        # Contract size is the amount of base currency per contract.
        risk_per_contract_if_sl_hit = sl_distance_price * float(specs['contract_size'])

        if risk_per_contract_if_sl_hit <= 0:
            self.logger.error(f"Risk per contract is zero or negative for {symbol}: {risk_per_contract_if_sl_hit}. Check contract specs and prices.")
            return None, None

        initial_position_size = fixed_dollar_risk / risk_per_contract_if_sl_hit
        self.logger.debug(f"Initial calculated position size for {symbol}: {initial_position_size}")

        # Adjust to meet exchange's quantity step (lot size for quantity)
        # E.g., if quantity_step is 0.001, position size must be a multiple of 0.001
        quantity_step = float(specs['quantity_step'])
        adjusted_position_size = math.floor(initial_position_size / quantity_step) * quantity_step
        
        # Ensure it's not rounded down to zero if initial size was very small but > 0
        if adjusted_position_size == 0 and initial_position_size > 0:
             # Try rounding to the smallest possible step if fixed risk allows
            adjusted_position_size = quantity_step 
            if (risk_per_contract_if_sl_hit * adjusted_position_size) > (fixed_dollar_risk * 1.5): # Allow some margin for very small risk
                 self.logger.warning(f"Calculated position size {initial_position_size} for {symbol} is too small, rounding to {quantity_step} leads to risk {(risk_per_contract_if_sl_hit * adjusted_position_size):.2f} which exceeds target ${fixed_dollar_risk} significantly. Min order qty might not be met.")
                 adjusted_position_size = 0 # Reset if it would cause too much risk

        self.logger.debug(f"Position size for {symbol} after adjusting for quantity_step ({quantity_step}): {adjusted_position_size}")

        min_order_qty = float(specs['min_order_qty'])
        if adjusted_position_size < min_order_qty:
            self.logger.warning(f"Adjusted position size {adjusted_position_size} for {symbol} is below min_order_qty {min_order_qty}. Attempting to use min_order_qty.")
            # Check if using min_order_qty is within acceptable risk (e.g., not more than 1.5x fixed_dollar_risk)
            risk_at_min_qty = risk_per_contract_if_sl_hit * min_order_qty
            if risk_at_min_qty > (fixed_dollar_risk * 1.5): # Arbitrary 50% over risk budget
                self.logger.error(f"Using min_order_qty {min_order_qty} for {symbol} would result in risk ${risk_at_min_qty:.2f}, exceeding target ${fixed_dollar_risk} by too much. Cannot place trade.")
                return None, None
            adjusted_position_size = min_order_qty
            self.logger.info(f"Using min_order_qty {min_order_qty} for {symbol}. Actual risk will be ${risk_at_min_qty:.2f}.")


        if specs.get('max_order_qty') is not None:
            max_order_qty = float(specs['max_order_qty'])
            if adjusted_position_size > max_order_qty:
                self.logger.warning(f"Adjusted position size {adjusted_position_size} for {symbol} exceeds max_order_qty {max_order_qty}. Clamping to max_order_qty.")
                adjusted_position_size = max_order_qty
        
        if adjusted_position_size <= 0:
            self.logger.error(f"Final adjusted position size for {symbol} is {adjusted_position_size}. Cannot place trade.")
            return None, None

        actual_risk_usd = risk_per_contract_if_sl_hit * adjusted_position_size
        self.logger.info(f"Final calculated position size for {symbol}: {adjusted_position_size}, Actual $ risk: {actual_risk_usd:.2f}")

        return adjusted_position_size, actual_risk_usd

# Example Usage (for testing - to be moved to a test script or main.py)
if __name__ == '__main__':
    import asyncio
    import os
    from dotenv import load_dotenv
    # Assuming these modules are in parent directory or src and runnable with python -m src.risk_management
    from .data_ingestion import DataIngestionModule
    from .config_manager import ConfigManager # ConfigManager itself does not take a logger
    from .logging_service import logger_instance as global_logger # Use the global logger instance

    load_dotenv()

    async def test_risk_management():
        # Setup
        test_logger = global_logger.bind(name="RiskManagementTest")
        test_logger.info("Starting Risk Management Module Test")

        # API_KEY = os.getenv("BYBIT_TESTNET_API_KEY") # Delegated to ConfigManager
        # API_SECRET = os.getenv("BYBIT_TESTNET_API_SECRET") # Delegated to ConfigManager

        # if not API_KEY or not API_SECRET:
        #     test_logger.error("Error: BYBIT_TESTNET_API_KEY or BYBIT_TESTNET_API_SECRET not found directly via os.getenv(). Relying on ConfigManager.")
            # return # Don't return here, let ConfigManager try

        config_path = 'config.json' 
        
        try:
            test_config_manager = ConfigManager(config_path)
            if not test_config_manager.get('cex_api.api_key') or not test_config_manager.get('cex_api.api_secret'):
                test_logger.critical("API Keys not successfully loaded by ConfigManager. Check .env path in config.json (secrets_env_file) and ensure actual env var names (api_key_env_var, api_secret_env_var) in config.json match keys in .env file.")
                return
            test_logger.info("ConfigManager initialized and API keys seem to be loaded by it.")

        except Exception as e:
            test_logger.critical(f"Failed to initialize ConfigManager: {e}", exc_info=True)
            return
        
        # Initialize DataIngestionModule
        try:
            # DataIngestionModule takes config_manager and logger_object
            data_ingestion_module = DataIngestionModule(
                config_manager=test_config_manager, # Pass the test's ConfigManager instance
                logger_object=global_logger  # Pass the global logger, DIM will bind it
            )
            # The initialize method in DIM now uses the passed config_manager to get API keys etc.
            initialized = await data_ingestion_module.initialize()
            if not initialized or not data_ingestion_module.exchange:
                 test_logger.critical("Exchange not initialized in DataIngestionModule.")
                 return

        except Exception as e:
            test_logger.critical(f"Failed to initialize DataIngestionModule: {e}", exc_info=True)
            return

        # Initialize RiskManagementModule
        # RiskManagementModule takes data_ingestion_module, config_manager, and a logger instance
        risk_manager = RiskManagementModule(data_ingestion_module, test_config_manager, global_logger)

        # Test Cases
        test_symbols = test_config_manager.get('portfolio.coins_to_scan', default=["BTCUSDT", "ETHUSDT"])
        fixed_risk = test_config_manager.get('risk_management.fixed_dollar_risk_per_trade', default=1.0)

        if not test_symbols:
            test_logger.warning("No test symbols found in config portfolio.coins_to_scan, using defaults.")
            test_symbols = ["BTCUSDT", "ETHUSDT"]

        for symbol in test_symbols:
            test_logger.info(f"--- Testing {symbol} ---")
            try:
                ticker = await data_ingestion_module.exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                entry_price_long = current_price * 0.995 
                sl_long = entry_price_long * 0.99 
                
                entry_price_short = current_price * 1.005 
                sl_short = entry_price_short * 1.01 

            except Exception as e:
                test_logger.error(f"Could not fetch ticker for {symbol} to set realistic prices: {e}")
                # Fallback prices
                if symbol == "BTCUSDT": entry_price_long, sl_long = 60000, 59400; entry_price_short, sl_short = 60000, 60600
                elif symbol == "ETHUSDT": entry_price_long, sl_long = 3000, 2970; entry_price_short, sl_short = 3000, 3030
                elif symbol == "SOLUSDT": entry_price_long, sl_long = 150, 148.5; entry_price_short, sl_short = 150, 151.5
                elif symbol == "DOGEUSDT": entry_price_long, sl_long = 0.15, 0.1485; entry_price_short, sl_short = 0.15, 0.1515
                elif symbol == "ORDIUSDT": entry_price_long, sl_long = 40, 39.6; entry_price_short, sl_short = 40, 40.4
                else: entry_price_long, sl_long = 100, 99; entry_price_short, sl_short = 100, 101 # Generic fallback

            test_logger.info(f"Test Case 1: LONG for {symbol} | Entry: {entry_price_long}, SL: {sl_long}, Risk: ${fixed_risk}")
            pos_size, actual_risk = await risk_manager.calculate_position_size(symbol, entry_price_long, sl_long, fixed_risk)
            if pos_size is not None:
                test_logger.info(f"Result for {symbol} LONG: Pos Size = {pos_size}, Actual Risk = ${actual_risk:.4f}")
            else:
                test_logger.error(f"Failed to calculate position size for {symbol} LONG.")

            test_logger.info(f"Test Case 2: SHORT for {symbol} | Entry: {entry_price_short}, SL: {sl_short}, Risk: ${fixed_risk}")
            pos_size_short, actual_risk_short = await risk_manager.calculate_position_size(symbol, entry_price_short, sl_short, fixed_risk)
            if pos_size_short is not None:
                test_logger.info(f"Result for {symbol} SHORT: Pos Size = {pos_size_short}, Actual Risk = ${actual_risk_short:.4f}")
            else:
                test_logger.error(f"Failed to calculate position size for {symbol} SHORT.")
            
            test_logger.info(f"--- Finished {symbol} ---")
            await asyncio.sleep(test_config_manager.get_cex_api_config().get('rate_limit_test_delay_seconds', 1)) # Add small delay

        # Test edge case: SL too close to entry
        test_logger.info(f"--- Testing Edge Case: SL too close ---")
        symbol_edge = "BTCUSDT"
        entry_edge, sl_edge = 60000, 59999.9 
        pos_size_edge, actual_risk_edge = await risk_manager.calculate_position_size(symbol_edge, entry_edge, sl_edge, fixed_risk)
        if pos_size_edge is not None:
            test_logger.info(f"Result for {symbol_edge} EDGE: Pos Size = {pos_size_edge}, Actual Risk = ${actual_risk_edge:.4f}")
        else:
            test_logger.error(f"Failed to calculate position size for {symbol_edge} EDGE (expected if SL too small).")

        # Test SL = entry
        test_logger.info(f"--- Testing Edge Case: SL = Entry ---")
        entry_edge_eq, sl_edge_eq = 60000, 60000
        pos_size_edge_eq, actual_risk_edge_eq = await risk_manager.calculate_position_size(symbol_edge, entry_edge_eq, sl_edge_eq, fixed_risk)
        if pos_size_edge_eq is None:
            test_logger.info(f"Correctly failed to calculate for SL = Entry for {symbol_edge}.")
        else:
            test_logger.error(f"Incorrectly calculated position for SL = Entry for {symbol_edge}.")


        if data_ingestion_module.exchange:
            await data_ingestion_module.close()
        test_logger.info("Risk Management Module Test Finished")

    if __name__ == '__main__':
        # Create logs directory if it doesn't exist
        if not os.path.exists('logs'):
            os.makedirs('logs')
        asyncio.run(test_risk_management()) 