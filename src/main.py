import asyncio
import time
import traceback
from pathlib import Path
import pandas as pd # Needed for type hints potentially
import json

# Use relative imports for modules within the same package (src)
from .config_manager import ConfigManager
from .logging_service import LoggingService, logger_instance 
from .data_ingestion import DataIngestionModule
from .analysis_engine import AnalysisEngine
from .risk_management import RiskManagementModule
from .journaling import JournalingModule
from .signal_alerter import SignalAlerter
from .state_manager import StateManager # Import StateManager
from .order_executor import OrderExecutor # Import OrderExecutor

# --- Configuration ---
LOG_DIR = Path("logs")
CONFIG_FILE = "config.json"

async def place_sl_tp_orders_for_signal(
    signal_id: str,
    signal_data: dict,
    order_executor: OrderExecutor, 
    state_manager: StateManager,
    risk_management_module: RiskManagementModule, # For contract specs if needed for formatting SL/TP
    config_manager: ConfigManager, # For TP strategy params
    main_logger
):
    """
    Places Stop Loss and Take Profit orders for a filled entry signal.
    Updates StateManager with SL/TP order IDs and new status.
    """
    symbol = signal_data.get('symbol')
    direction = signal_data.get('direction')
    # Use filled_qty from the updated signal_data or fallback to original position_size
    # The signal_data passed here should ideally be the one from DB after ENTRY_FILLED update, 
    # or enriched with filled_qty and filled_price.
    # For now, let's assume signal_data contains original entry_price, sl_price, position_size
    # and that filled_qty would be used if available and different.
    
    # Fetch the most up-to-date signal from DB to get filled_price and filled_qty
    db_signal_details = state_manager.get_signal(signal_id)
    if not db_signal_details or db_signal_details.get('status') != 'ENTRY_FILLED':
        main_logger.error(f"Signal {signal_id} not found in DB or not in ENTRY_FILLED state for SL/TP placement. Current state: {db_signal_details.get('status') if db_signal_details else 'Not Found'}. Aborting SL/TP.")
        return

    try:
        # Ensure signal_data from DB (which is JSON string) is parsed
        full_signal_data_from_db = json.loads(db_signal_details['signal_data']) if isinstance(db_signal_details['signal_data'], str) else db_signal_details['signal_data']
    except json.JSONDecodeError as jde:
        main_logger.error(f"Error decoding signal_data from DB for SL/TP placement (Signal ID: {signal_id}): {jde}. Aborting.")
        return

    filled_qty = db_signal_details.get('filled_qty', full_signal_data_from_db.get('position_size'))
    filled_price = db_signal_details.get('filled_price', full_signal_data_from_db.get('entry_price')) # Entry price from original signal
    original_sl_price = full_signal_data_from_db.get('stop_loss_price')

    if not all([symbol, direction, filled_qty, original_sl_price, filled_price]):
        main_logger.error(f"""Incomplete data for SL/TP placement for signal {signal_id}: 
                         Symbol: {symbol}, Direction: {direction}, Qty: {filled_qty}, 
                         SL: {original_sl_price}, FilledPrice: {filled_price}. Aborting SL/TP.""")
        return
    
    try:
        filled_qty_f = float(filled_qty)
        original_sl_price_f = float(original_sl_price)
        filled_price_f = float(filled_price)
    except ValueError as ve:
        main_logger.error(f"Invalid numeric value for qty/sl/filled_price for SL/TP placement (Signal ID: {signal_id}): {ve}. Aborting.")
        return

    # Check if SL/TP was already included with the entry order
    entry_order_data = full_signal_data_from_db.get('entry_order_data', {})
    if isinstance(entry_order_data, dict) and entry_order_data.get('has_sltp'):
        main_logger.info(f"Signal {signal_id} already has SL/TP included in the entry order. Updating state to POSITION_OPEN.") # INFO
        state_manager.update_signal_status(signal_id, 'POSITION_OPEN', {
            'sl_order_id': 'included_in_entry', 
            'tp_order_id': 'included_in_entry'
        })
        return

    sl_order_id = None
    tp_order_id = None

    # 1. Place Stop Loss Order
    main_logger.info(f"Placing SL order for signal {signal_id} ({symbol} {direction} Qty: {filled_qty_f} @ SL: {original_sl_price_f})") # INFO
    sl_order = await order_executor.place_stop_loss_order(
        symbol=symbol,
        side=direction, # SL side is opposite of trade direction for a stop market order
        qty=filled_qty_f,
        stop_price=original_sl_price_f
    )
    if sl_order and sl_order.get('id'):
        sl_order_id = sl_order.get('id')
        main_logger.user(f"Successfully placed SL order {sl_order_id} for signal {signal_id}.") # USER
    else:
        main_logger.error(f"Failed to place SL order for signal {signal_id}. OrderExecutor response: {sl_order}. Position is open without SL! Critical.")
        # CRITICAL: Position is open without SL. Update state to reflect this error.
        state_manager.update_signal_status(signal_id, 'SL_PLACEMENT_FAILED', {'error_message': 'Failed to place SL order.'})
        # TODO: Consider an emergency market close of the position here if SL fails.
        return # Do not proceed to TP if SL failed

    # 2. Place Take Profit Order (Primary TP)
    # Calculate TP based on strategy (e.g., first R:R target)
    # For simplicity, using the first TP from the pre-calculated string if available, otherwise fixed R:R
    # This logic needs to be robust and use the actual filled price.
    
    tp_price_f = None
    try:
        # Re-calculate TP based on actual filled_price and original SL
        sl_distance = abs(filled_price_f - original_sl_price_f)
        tp_params = config_manager.get('strategy_params.take_profit', {})
        fixed_rr_ratios = tp_params.get('fixed_rr_ratios', [2.0]) # Default to 2R if not configured
        primary_rr_target = fixed_rr_ratios[0] if fixed_rr_ratios else 2.0

        specs = await risk_management_module.get_contract_specifications(symbol)
        tick_size = specs.get('tick_size') if specs else None
        if not tick_size:
            main_logger.error(f"Cannot calculate TP for {signal_id}: Missing tick_size for {symbol}.")
            # Position is open with SL, but TP will not be placed. Update status.
            state_manager.update_signal_status(signal_id, 'TP_CALC_FAILED_NO_TICK_SIZE', {'sl_order_id': sl_order_id})
            return

        if direction.upper() == "BUY":
            raw_tp = filled_price_f + (sl_distance * primary_rr_target)
        elif direction.upper() == "SELL":
            raw_tp = filled_price_f - (sl_distance * primary_rr_target)
        else:
            main_logger.error(f"Invalid direction '{direction}' for TP calculation on signal {signal_id}.")
            state_manager.update_signal_status(signal_id, 'TP_CALC_FAILED_BAD_DIR', {'sl_order_id': sl_order_id})
            return
        
        tp_price_f = SignalAlerter._adjust_price_to_tick_size(raw_tp, tick_size, direction)
        price_precision = SignalAlerter._get_price_precision(tick_size)
        main_logger.debug(f"Calculated primary TP for signal {signal_id} at {tp_price_f:.{price_precision}f} (RR: {primary_rr_target})") # DEBUG

    except Exception as calc_e:
        main_logger.error(f"Error calculating TP price for signal {signal_id}: {calc_e}", exc_info=True)
        # Position is open with SL, but TP will not be placed. Update status.
        state_manager.update_signal_status(signal_id, 'TP_CALCULATION_FAILED', {'sl_order_id': sl_order_id})
        return

    if tp_price_f:
        main_logger.info(f"Placing TP order for signal {signal_id} ({symbol} {direction} Qty: {filled_qty_f} @ TP: {tp_price_f})") # INFO
        
        # Determine the correct side for the TP limit order (opposite of entry direction)
        tp_side = "Sell" if direction.upper() == "BUY" else "Buy"
        main_logger.debug(f"Determined TP side as '{tp_side}' for original direction '{direction}'.")

        tp_order = await order_executor.place_take_profit_order(
            symbol=symbol,
            side=tp_side, # Use the inverted side for the TP limit order
            qty=filled_qty_f,
            price=tp_price_f
        )
        if tp_order and tp_order.get('id'):
            tp_order_id = tp_order.get('id')
            main_logger.user(f"Successfully placed TP order {tp_order_id} for signal {signal_id}.") # USER
        else:
            main_logger.error(f"Failed to place TP order for signal {signal_id}. OrderExecutor response: {tp_order}. Position is open with SL but no TP.")
            # Update status to reflect SL placed, TP failed.
            state_manager.update_signal_status(signal_id, 'TP_PLACEMENT_FAILED', {'sl_order_id': sl_order_id, 'error_message': 'Failed to place TP order.'})
            return

    # 3. Update State Manager to POSITION_OPEN
    if sl_order_id and tp_order_id: # Only if both are successful
        update_payload = {
            'sl_order_id': sl_order_id, 
            'tp_order_id': tp_order_id,
            'tp_price': tp_price_f # Store the actual TP price used for the order
        }
        state_manager.update_signal_status(signal_id, 'POSITION_OPEN', update_payload)
        main_logger.user(f"Signal {signal_id} status updated to POSITION_OPEN with SL {sl_order_id}, TP {tp_order_id} (Price: {tp_price_f}).") # USER
    elif sl_order_id and not tp_order_id:
        # This case means TP placement failed or was skipped.
        # We should still update the status to reflect that SL is on, but potentially store that TP failed.
        update_payload_sl_only = {
            'sl_order_id': sl_order_id,
            'tp_order_id': None, # Explicitly set tp_order_id to None
            'tp_price': None     # Explicitly set tp_price to None
        }
        # The status was already updated to TP_CALCULATION_FAILED or TP_PLACEMENT_FAILED by earlier logic.
        # We might just need to ensure sl_order_id is in the DB for that status.
        state_manager.update_signal_status(signal_id, state_manager.get_signal(signal_id).get('status', 'SL_OK_TP_FAILED'), update_payload_sl_only)
        main_logger.warning(f"Signal {signal_id} has SL {sl_order_id} but TP placement failed/skipped. Status: {state_manager.get_signal(signal_id).get('status', 'SL_OK_TP_FAILED')}.") # WARNING
    else:
        # This case means SL placement failed.
        main_logger.error(f"Signal {signal_id} reached end of SL/TP placement without successful SL. Status was set to SL_PLACEMENT_FAILED.")

async def run_scanner():
    """
    Main asynchronous function to run the crypto scanner bot.
    """
    run_start_time = time.time()
    main_logger = logger_instance.bind(name="MainApp") 
    main_logger.user("--- Starting Crypto Scanner Bot ---")

    # --- Initialize Modules ---
    data_ingestion_module = None 
    order_executor = None
    state_manager = None
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        config_manager = ConfigManager(CONFIG_FILE)
        main_logger.debug("ConfigManager initialized.") # DEBUG

        data_ingestion_module = DataIngestionModule(
            config_manager=config_manager,
            logger_object=logger_instance 
        )
        if not await data_ingestion_module.initialize():
            main_logger.critical("Failed to initialize Data Ingestion Module. Exiting.")
            return
        main_logger.debug("DataIngestionModule initialized.") # DEBUG

        risk_management_module = RiskManagementModule(
            data_ingestion_module=data_ingestion_module,
            config_manager=config_manager,
            logger=logger_instance 
        )
        main_logger.debug("RiskManagementModule initialized.") # DEBUG
        
        order_executor = OrderExecutor(
             data_ingestion_module=data_ingestion_module,
             config_manager=config_manager,
             main_logger=logger_instance
        )
        main_logger.debug("OrderExecutor initialized.") # DEBUG
        
        state_manager = StateManager(
            config_manager=config_manager,
            main_logger=logger_instance
        )
        main_logger.debug("StateManager initialized.") # DEBUG

        analysis_engine = AnalysisEngine(
            data_ingestion_module=data_ingestion_module,
            config_manager=config_manager,
            logger_object=logger_instance 
        )
        main_logger.debug("AnalysisEngine initialized.") # DEBUG

        journaling_module = JournalingModule(
            config_manager=config_manager,
            main_logger=logger_instance 
        )
        main_logger.debug("JournalingModule initialized.") # DEBUG

        signal_alerter = SignalAlerter(
            config_manager=config_manager,
            main_logger=logger_instance, 
            risk_management_module=risk_management_module
        )
        main_logger.debug("SignalAlerter initialized.") # DEBUG

        main_logger.info("--- All modules initialized successfully ---") # INFO for a major milestone

    except Exception as e:
        main_logger.critical(f"Error during module initialization: {e}", exc_info=True)
        if data_ingestion_module and hasattr(data_ingestion_module, 'exchange') and data_ingestion_module.exchange:
            await data_ingestion_module.close()
        return

    # --- Configuration for the loop ---
    scan_interval_seconds = config_manager.get("scanner.scan_interval_minutes", 5) * 60
    fixed_dollar_risk = config_manager.get("risk_management.fixed_dollar_risk_per_trade", 1.0)
    max_concurrent_trades = config_manager.get("portfolio.max_concurrent_trades", 1)

    try:
        # To track outcomes per symbol for USER level summary
        symbols_with_potential_signals_this_cycle = set()
        symbols_with_placed_orders_this_cycle = set()

        while True:
            loop_start_time = time.time()
            main_logger.user("Starting new scan cycle...")

            # Clear per-cycle tracking sets
            symbols_with_potential_signals_this_cycle.clear()
            symbols_with_placed_orders_this_cycle.clear()

            coins_to_scan = config_manager.get("portfolio.coins_to_scan", [])
            if not coins_to_scan:
                main_logger.warning("No coins configured in portfolio.coins_to_scan. Skipping scan cycle.")
                await asyncio.sleep(scan_interval_seconds)
                continue

            main_logger.info(f"Scanning symbols: {coins_to_scan}")

            all_potential_signals_aggregated = [] # Renamed for clarity
            # --- Run Analysis --- 
            for symbol in coins_to_scan:
                main_logger.user(f"Scanning: {symbol}...") # USER log for current symbol
                try:
                    main_logger.debug(f"Analyzing {symbol}...")
                    potential_signals_for_this_symbol = await analysis_engine.run_analysis(symbol) 
                    if potential_signals_for_this_symbol:
                        main_logger.info(f"Found {len(potential_signals_for_this_symbol)} potential raw signal(s) for {symbol}.")
                        symbols_with_potential_signals_this_cycle.add(symbol)
                        all_potential_signals_aggregated.extend(potential_signals_for_this_symbol)
                    # else: # Decided to not log "no initial signals" at USER level for brevity
                    #    main_logger.debug(f"No initial potential signals found for {symbol}.")
                except Exception as e:
                    main_logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)
                await asyncio.sleep(config_manager.get("scanner.delay_between_symbols_seconds", 0.5))

            # --- Process Potential Signals --- 
            if all_potential_signals_aggregated:
                main_logger.info(f"Processing {len(all_potential_signals_aggregated)} total potential signals found in this cycle.")
                for signal_data in all_potential_signals_aggregated:
                    # --- VERY EARLY CHECK AND LOG (Before Try Block) --- 
                    if not isinstance(signal_data, dict):
                        main_logger.error(f"Received signal_data is not a dictionary! Type: {type(signal_data)}, Value: {signal_data}. Skipping this item.")
                        continue
                    main_logger.debug(f"Processing raw signal_data dict: {signal_data}")
                    # --- END EARLY CHECK --- 
                    
                    signal_id = None # Ensure signal_id is defined for logging in exception block
                    try:
                        symbol = signal_data.get('symbol')
                        if not symbol:
                            main_logger.warning(f"Signal data missing symbol: {signal_data}. Skipping.")
                            continue
                        
                        # 1. Generate Signal ID & Check State
                        signal_id = state_manager.generate_signal_id(signal_data)
                        if not signal_id:
                             main_logger.error(f"Could not generate signal ID for: {signal_data}. Skipping.")
                             continue
                             
                        existing_signal = state_manager.get_signal(signal_id)
                        if existing_signal:
                            # Skip if signal is already in a final state or a non-retryable error state
                            non_actionable_statuses = ['ENTRY_FILLED', 'POSITION_OPEN', 'SL_FILLED', 'TP_FILLED', 'CANCELLED', 'REJECTED', 'CLOSED_SL', 'CLOSED_TP', 'CANCELLED_STALE', 'CANCELLED_TP_HIT_PENDING', 'CANCELLED_STALE_NOT_FOUND', 'CLOSED_OR_CANCELLED_HISTORICAL', 'SL_PLACEMENT_FAILED', 'TP_PLACEMENT_FAILED', 'TP_CALCULATION_FAILED']
                            # Also skip UNKNOWN_API_STATUS to prevent reprocessing until manually checked or status changes
                            if existing_signal['status'] in non_actionable_statuses or existing_signal['status'] == 'UNKNOWN_API_STATUS':
                                main_logger.debug(f"Signal ID {signal_id} ({symbol}) already tracked with status {existing_signal['status']}. Skipping.")
                                continue 
                            # If PENDING_ENTRY, it will be handled by the order status monitoring section later
                            elif existing_signal['status'] == 'PENDING_ENTRY':
                                main_logger.debug(f"Signal ID {signal_id} ({symbol}) is PENDING_ENTRY. Will be checked by monitor. Skipping new order placement.")
                                continue
                            # Check for other active trades for the *same symbol*
                            active_symbol_signals = state_manager.get_active_signals_by_symbol(symbol)
                            if len(active_symbol_signals) >= max_concurrent_trades:
                                main_logger.info(f"Skipping new signal for {symbol} as {len(active_symbol_signals)} active trade(s) already exist (max: {max_concurrent_trades}).") # INFO
                                continue
                            
                            # --- New Signal Processing --- 
                            main_logger.info(f"New unique signal identified for {symbol} (ID: {signal_id}). Processing entry...") # INFO

                            entry = signal_data.get('entry_price')
                            sl = signal_data.get('stop_loss_price')
                            direction = signal_data.get('direction')
                            if not all([entry, sl, direction]):
                                 main_logger.warning(f"Incomplete signal data for {signal_id}, missing entry/sl/direction. Skipping.")
                                 continue
                                 
                            # 2. Calculate Position Size
                            try:
                                entry_f = float(entry)
                                sl_f = float(sl)
                            except (ValueError, TypeError):
                                main_logger.error(f"Invalid numeric value for entry or SL in signal {signal_id}. Entry: {entry}, SL: {sl}. Skipping.")
                                continue

                            # Wrap the calculate_position_size call in a specific try-except
                            pos_size = None
                            actual_risk = None
                            try:
                                pos_size, actual_risk = await risk_management_module.calculate_position_size(
                                    symbol=symbol,
                                    entry_price=entry_f, 
                                    stop_loss_price=sl_f, 
                                    fixed_dollar_risk=fixed_dollar_risk
                                )
                            except KeyError as ke:
                                # Check if this is the specific KeyError we are hunting
                                problematic_key = '"retCode"' # The key causing the error, with literal quotes
                                # Check if the problematic key string is present in the exception arguments
                                if any(problematic_key in str(arg) for arg in ke.args):
                                    main_logger.error(f"Caught specific KeyError involving '\\\"retCode\\\"' during calculate_position_size for {signal_id}. Origin likely within RiskManagement or DataIngestion specs fetch.", exc_info=True)
                                else:
                                    main_logger.error(f"Caught unexpected KeyError during calculate_position_size for {signal_id}: {ke}", exc_info=True)
                                continue # Skip this signal if position size calculation fails
                            except Exception as calc_e:
                                 main_logger.error(f"Caught general exception during calculate_position_size for {signal_id}: {calc_e}", exc_info=True)
                                 continue # Skip this signal

                            if pos_size is None or actual_risk is None:
                                main_logger.error(f"Could not calculate position size for {signal_id} ({symbol}) (returned None). Skipping entry.")
                                continue
                            
                            # --- >>> PRE-ORDER VALIDATION AGAINST CURRENT MARKET PRICE <<< ---
                            proceed_to_place_order = True # Assume true, set to false if validation fails
                            try:
                                ticker = await order_executor.exchange.fetch_ticker(symbol)
                                current_market_price = float(ticker['last'])
                                main_logger.debug(f"[{signal_id}] PRE-ORDER CHECK for {symbol}: Entry={entry_f}, SL={sl_f}, Current Market={current_market_price}") # DEBUG

                                if direction.upper() == "BUY":
                                    if sl_f >= current_market_price:
                                        main_logger.warning(f"[{signal_id}] STALE/INVALID BUY (SL validation): SL ({sl_f}) is at or above current market ({current_market_price}). Invalidating pre-order.")
                                        proceed_to_place_order = False
                                    # Optional: Check if entry_f is too far from current_market_price (e.g., > 5% away, making it a chase)
                                    # elif entry_f > current_market_price * 1.05: 
                                    #     main_logger.warning(f"[{signal_id}] STALE BUY (Entry validation): Entry ({entry_f}) is >5% above current market ({current_market_price}). Invalidating pre-order.")
                                    #     proceed_to_place_order = False
                                elif direction.upper() == "SELL":
                                    if sl_f <= current_market_price:
                                        main_logger.warning(f"[{signal_id}] STALE/INVALID SELL (SL validation): SL ({sl_f}) is at or below current market ({current_market_price}). Invalidating pre-order.")
                                        proceed_to_place_order = False
                                    # Optional: Check if entry_f is too far from current_market_price
                                    # elif entry_f < current_market_price * 0.95:
                                    #     main_logger.warning(f"[{signal_id}] STALE SELL (Entry validation): Entry ({entry_f}) is <5% below current market ({current_market_price}). Invalidating pre-order.")
                                    #     proceed_to_place_order = False
                                
                                if not proceed_to_place_order:
                                    main_logger.info(f"[{signal_id}] Skipping order placement due to pre-order validation failure.") # INFO
                                    continue # Skip to the next signal_data

                            except Exception as e_ticker_val:
                                main_logger.error(f"[{signal_id}] Error during pre-order ticker validation for {symbol}: {e_ticker_val}. Order will NOT be placed as a precaution.", exc_info=True)
                                proceed_to_place_order = False # Do not proceed if ticker check fails
                                continue # Skip to next signal if ticker fetch fails
                            # --- >>> END PRE-ORDER VALIDATION <<< ---
                            
                            # This check is now redundant if continue is used above, but as a safeguard:
                            # if not proceed_to_place_order:
                            #    main_logger.debug(f"[{signal_id}] Double check: Not proceeding to order placement.")
                            #    continue

                            main_logger.debug(f"[{signal_id}] Pre-order validation passed. Proceeding to place order for {symbol}.") # DEBUG
                            # --- Granular Logging Before Final Steps --- 
                            main_logger.debug(f"[{signal_id}] Calculated pos_size: {pos_size} (Type: {type(pos_size)}), actual_risk: {actual_risk} (Type: {type(actual_risk)}) ")
                            main_logger.debug(f"[{signal_id}] signal_data before assignment: {signal_data}")
                            
                            signal_data['position_size'] = pos_size 
                            signal_data['actual_risk_usd'] = actual_risk
                            
                            main_logger.debug(f"[{signal_id}] signal_data after assignment: {signal_data}")
                            main_logger.debug(f"[{signal_id}] Values for warning log - symbol: {symbol}, direction: {direction}, entry_f: {entry_f}")
                            # --- End Granular Logging ---
                            
                            main_logger.user(f"ATTEMPTING TO PLACE ORDER for signal {signal_id} ({symbol} {direction} @ {entry_f})") # USER
                            
                            # --- Add specific try-except around the order placement call ---
                            entry_order = None # Initialize to None before the try block
                            try:
                                main_logger.debug(f"[{signal_id}] About to call order_executor.place_limit_entry_order") # DEBUG
                                
                                # Calculate TP price for this order based on R:R
                                tp_price_f = None
                                try:
                                    sl_distance = abs(entry_f - sl_f)
                                    tp_params = config_manager.get('strategy_params.take_profit', {})
                                    fixed_rr_ratios = tp_params.get('fixed_rr_ratios', [2.0])  # Default to 2R
                                    primary_rr_target = fixed_rr_ratios[0] if fixed_rr_ratios else 2.0
                                    
                                    if direction.upper() == "BUY":
                                        tp_price_f = entry_f + (sl_distance * primary_rr_target)
                                    elif direction.upper() == "SELL":
                                        tp_price_f = entry_f - (sl_distance * primary_rr_target)
                                    else:
                                        # This warning should now be less likely
                                        tp_price_f = None
                                except Exception as tp_calc_e:
                                    main_logger.error(f"Error calculating TP price for entry order: {tp_calc_e}", exc_info=True)
                                    tp_price_f = None
                                
                                # Place order with SL/TP included
                                entry_order = await order_executor.place_limit_entry_order(
                                    symbol=symbol,
                                    side=direction, 
                                    qty=pos_size,
                                    price=entry_f,
                                    sl_price=sl_f,  # Include SL price directly in order
                                    tp_price=tp_price_f  # Include TP price if calculated
                                )
                                main_logger.debug(f"[{signal_id}] Returned from order_executor.place_limit_entry_order. Response: {entry_order}") # DEBUG
                            except KeyError as ke_order_call:
                                main_logger.error(f"KeyError specifically during place_limit_entry_order call for {signal_id}: {ke_order_call}", exc_info=True)
                                # entry_order remains None, will be caught by subsequent checks or main exception handler
                            except Exception as e_order_call:
                                main_logger.error(f"Exception specifically during place_limit_entry_order call for {signal_id}: {e_order_call}", exc_info=True)
                                # entry_order remains None
                            # --- End specific try-except ---

                            # --- Explicitly check if order placement failed --- 
                            if entry_order is None:
                                main_logger.error(f"Order placement failed for signal {signal_id} (returned None). Skipping further processing for this signal. Check OrderExecutor logs for details.")
                                continue # Skip to the next potential signal
                            # --- End explicit check ---
                            
                            # Check if the response *still* looks like a Bybit error (shouldn't happen with new executor logic, but safeguard)
                            if isinstance(entry_order, dict) and entry_order.get('retCode') != 0 and not entry_order.get('id'):
                                main_logger.error(f"Order placement seems to have failed for signal {signal_id} despite not returning None. Raw response: {entry_order}. Skipping.")
                                continue
                            
                            # Proceed only if entry_order looks valid (has an 'id')
                            entry_order_id = entry_order.get('id')
                            if entry_order_id:
                                current_signal_symbol = signal_data.get('symbol', 'UnknownSymbol') # Get symbol for this specific signal
                                main_logger.user(f"{current_signal_symbol}: Order {entry_order_id} placed (Signal ID: {signal_id}). Status: PENDING_ENTRY")
                                symbols_with_placed_orders_this_cycle.add(current_signal_symbol)
                                
                                # Store SL/TP details if they were included with the order
                                signal_data['entry_order_data'] = {
                                    'id': entry_order_id,
                                    'has_sltp': entry_order.get('has_sltp', False),
                                    'sl_price': entry_order.get('sl_price'), # Original SL sent
                                    'tp_price': entry_order.get('tp_price')  # Actual TP sent
                                }
                                
                                if signal_data['entry_order_data']['has_sltp']:
                                    main_logger.info(f"Entry order {entry_order_id} for {signal_id} includes SL ({signal_data['entry_order_data']['sl_price']}) & TP ({signal_data['entry_order_data']['tp_price']}) directly.") # INFO
                                
                                # 4. Add to State Manager, now including the actual_tp_ordered if available
                                actual_tp_ordered_for_db = signal_data['entry_order_data'].get('tp_price') if signal_data['entry_order_data'].get('has_sltp') else None
                                added = state_manager.add_signal_entry(
                                    signal_id,
                                    signal_data, 
                                    entry_order_id,
                                    actual_tp_ordered=actual_tp_ordered_for_db
                                )
                                if not added:
                                     main_logger.error(f"Failed to add signal {signal_id} to StateManager DB, but order {entry_order_id} was placed! Manual intervention required.")
                                
                                # 5. Enrich for Alert/Journal (Now that order is placed)
                                specs = await risk_management_module.get_contract_specifications(symbol) 
                                signal_data['tick_size'] = specs.get('tick_size') if specs else None
                                
                                tp_levels_str = "N/A"
                                if signal_data['tick_size']:
                                    try:
                                         sl_distance = abs(entry_f - sl_f)
                                         price_precision = SignalAlerter._get_price_precision(signal_data['tick_size'])
                                         tp_ratios = config_manager.get('strategy_params.take_profit', {}).get('fixed_rr_ratios', [1.0, 2.0, 3.0])
                                         tps = []
                                         if sl_distance > 0:
                                             for ratio in tp_ratios:
                                                 raw_tp = 0
                                                 if direction.upper() == "BUY": raw_tp = entry_f + (sl_distance * ratio)
                                                 elif direction.upper() == "SELL": raw_tp = entry_f - (sl_distance * ratio)
                                                 else: continue
                                                 adjusted_tp = SignalAlerter._adjust_price_to_tick_size(raw_tp, signal_data['tick_size'], direction)
                                                 tps.append(f"TP{len(tps)+1} ({ratio}R): {adjusted_tp:.{price_precision}f}")
                                             tp_levels_str = ", ".join(tps) if tps else "N/A"
                                    except Exception as calc_e:
                                        main_logger.error(f"Error calculating TPs for alert/journal: {calc_e}")
                                signal_data['take_profit_targets_str'] = tp_levels_str
                                signal_data['entry_order_id'] = entry_order_id # Add order ID for logging
                                signal_data['status'] = 'PENDING_ENTRY' # Add status for logging
                                
                                # 6. Log NEW PENDING signal to Journal & Alert
                                main_logger.debug(f"Logging and Alerting NEW PENDING signal: {signal_id}") # DEBUG
                                journaling_module.log_trade_signal(signal_data) 
                                signal_alerter.alert(signal_data) 

                            else:
                                # OrderExecutor now logs the specific Bybit error if retCode != 0
                                main_logger.error(f"Failed to place entry order for signal {signal_id} ({symbol}). See OrderExecutor logs for details.")
                                # No need to update state here as it wasn't added

                    except Exception as e:
                         # Log which signal ID (if generated) failed and the specific exception
                         failed_id = signal_id if signal_id else "N/A"
                         main_logger.error(f"Error processing potential signal for {signal_data.get('symbol', '?')} (ID: {failed_id}): {type(e).__name__} - {e}", exc_info=True)
                         # Add detailed logging for entry_order if it exists in this scope
                         # Use repr() for potentially complex objects
                         entry_order_val = repr(entry_order) if 'entry_order' in locals() else "Not Defined"
                         main_logger.error(f"Value of 'entry_order' at time of exception: {entry_order_val}, Type: {type(entry_order) if 'entry_order' in locals() else 'N/A'}")
            else:
                 main_logger.info("No new signals generated in this cycle to process.")

            # --- Summary Logging for USER Level (after processing all signals) ---
            for symbol_iter in coins_to_scan: # Iterate through the original list to maintain order if desired
                if symbol_iter in symbols_with_placed_orders_this_cycle:
                    pass # Already logged when order was placed
                elif symbol_iter in symbols_with_potential_signals_this_cycle:
                    main_logger.user(f"{symbol_iter}: Potential signals found, but no orders placed (e.g., invalidated, risk issues)." ) # USER
                else:
                    # This means no potential signals were even found by analysis_engine for this symbol
                    main_logger.info(f"{symbol_iter}: No potential setups identified in this cycle.") # INFO, not USER, to keep USER log cleaner
                 
            # --- Order Status Monitoring ---
            main_logger.info("Checking status of PENDING_ENTRY orders...")
            pending_entry_signals = state_manager.get_signals_by_status('PENDING_ENTRY')
            if not pending_entry_signals:
                main_logger.info("No PENDING_ENTRY orders to monitor in this cycle.") # INFO
            else:
                main_logger.info(f"Found {len(pending_entry_signals)} PENDING_ENTRY order(s) to check.") # INFO
                for signal_in_db in pending_entry_signals:
                    signal_id = signal_in_db['signal_id']
                    order_id = signal_in_db['entry_order_id']
                    symbol = signal_in_db['symbol']
                    signal_data_json = signal_in_db['signal_data']
                    
                    # Deserialize signal_data from JSON string to dict
                    try:
                        signal_data = json.loads(signal_data_json) if isinstance(signal_data_json, str) else signal_data_json
                    except json.JSONDecodeError as jde:
                        main_logger.error(f"Error decoding signal_data JSON for signal {signal_id} (Order ID: {order_id}): {jde}. Skipping status check for this order.")
                        continue

                    if not order_id:
                        main_logger.warning(f"Signal {signal_id} for {symbol} has status PENDING_ENTRY but no entry_order_id. Skipping.")
                        continue

                    try:
                        main_logger.debug(f"Checking status for order {order_id} (Signal ID: {signal_id}, Symbol: {symbol})")
                        # Ensure order_executor is not None
                        if order_executor is None:
                            main_logger.error("OrderExecutor is not initialized. Cannot check order status.")
                            break # Break from this loop, will be caught by outer loop or initialization error

                        order_status_details = await order_executor.check_order_status(symbol=symbol, order_id=order_id)

                        if order_status_details:
                            status = order_status_details.get('status')
                            main_logger.info(f"Order {order_id} (Signal ID: {signal_id}) status: {status}") # INFO

                            if status == 'filled' or status == 'closed': 
                                main_logger.user(f"Entry order {order_id} for signal {signal_id} ({symbol}) is FILLED/CLOSED.") # USER
                                filled_price = order_status_details.get('averagePrice', signal_data.get('entry_price')) 
                                filled_qty = order_status_details.get('filled', signal_data.get('position_size'))
                                
                                # Ensure status update happens *before* triggering next step
                                state_manager.update_signal_status(signal_id, 'ENTRY_FILLED', {'filled_price': filled_price, 'filled_qty': filled_qty})
                                main_logger.debug(f"Updated signal {signal_id} status to ENTRY_FILLED in StateManager.") # DEBUG
                                
                                # --- Trigger SL/TP Placement ---
                                main_logger.info(f"Attempting to place SL/TP orders for filled signal {signal_id}...") # INFO
                                # Fetch the *updated* signal details from DB which now include filled_price/qty
                                updated_db_signal_details = state_manager.get_signal(signal_id)
                                if updated_db_signal_details and updated_db_signal_details['status'] == 'ENTRY_FILLED':
                                    try:
                                        updated_signal_data_for_sltp = json.loads(updated_db_signal_details['signal_data']) if isinstance(updated_db_signal_details['signal_data'], str) else updated_db_signal_details['signal_data']
                                        # Enrich with DB fields
                                        updated_signal_data_for_sltp['filled_price'] = updated_db_signal_details.get('filled_price')
                                        updated_signal_data_for_sltp['filled_qty'] = updated_db_signal_details.get('filled_qty')
                                        
                                        await place_sl_tp_orders_for_signal(
                                            signal_id=signal_id, 
                                            signal_data=updated_signal_data_for_sltp, # Pass data possibly enriched with filled details
                                            order_executor=order_executor, 
                                            state_manager=state_manager, 
                                            risk_management_module=risk_management_module, 
                                            config_manager=config_manager,
                                            main_logger=main_logger
                                        )
                                    except json.JSONDecodeError as jde_sltp:
                                        main_logger.error(f"Error decoding updated signal_data for SL/TP placement (Signal ID: {signal_id}): {jde_sltp}. SL/TP placement aborted.")
                                        state_manager.update_signal_status(signal_id, 'SLTP_PLACEMENT_FAILED_JSON_ERROR', {'error_message': f"JSON decode error before SL/TP placement: {jde_sltp}"})
                                    except Exception as e_sltp:
                                        main_logger.error(f"Unexpected error during SL/TP placement call for signal {signal_id}: {e_sltp}", exc_info=True)
                                        state_manager.update_signal_status(signal_id, 'SLTP_PLACEMENT_FAILED_UNKNOWN_ERROR', {'error_message': f"Unknown error during SL/TP placement: {e_sltp}"})
                                else:
                                     main_logger.error(f"Could not retrieve updated ENTRY_FILLED signal {signal_id} from DB before placing SL/TP. Aborting SL/TP.")
                                     # Status remains ENTRY_FILLED, but needs manual check for SL/TP
                            
                            elif status == 'open':
                                main_logger.debug(f"Entry order {order_id} for signal {signal_id} ({symbol}) is still OPEN.") # DEBUG
                                # --- >>> Stale Order Cancellation Logic <<< ---
                                try:
                                    # Retrieve necessary details from signal_data (already loaded from JSON)
                                    # and signal_in_db (which is the direct DB record)
                                    entry_price_f = float(signal_data.get('entry_price'))
                                    sl_price_f = float(signal_data.get('stop_loss_price'))
                                    direction = signal_data.get('direction')
                                    # Get hypothetical_tp_price from the database record for the signal
                                    hypothetical_tp_price_str = signal_in_db.get('hypothetical_tp_price')
                                    hypothetical_tp_price_f = None # Initialize

                                    if hypothetical_tp_price_str is not None:
                                        try:
                                            hypothetical_tp_price_f = float(hypothetical_tp_price_str)
                                        except ValueError:
                                            main_logger.error(f"[{signal_id}] Invalid format for hypothetical_tp_price ('{hypothetical_tp_price_str}'). Skipping market-based staleness check for TP.")
                                    else:
                                         main_logger.warning(f"[{signal_id}] Missing hypothetical_tp_price for stale check. Skipping market-based staleness check for TP.")

                                    main_logger.debug(f"[{signal_id}] Performing market-based staleness check for OPEN PENDING_ENTRY order {order_id}.") # DEBUG
                                    
                                    ticker = await order_executor.exchange.fetch_ticker(symbol)
                                    current_market_price = float(ticker['last'])
                                    main_logger.debug(f"[{signal_id}] Stale Check: Current Market Price for {symbol} is {current_market_price}. Entry: {entry_price_f}, SL: {sl_price_f}, Hypo TP: {hypothetical_tp_price_f if hypothetical_tp_price_f is not None else 'N/A'}") # DEBUG

                                    cancel_reason = None
                                    cancellation_details_for_db = {}

                                    # 1. Check TP Hit
                                    if hypothetical_tp_price_f is not None:
                                        if direction.upper() == "BUY" and current_market_price >= hypothetical_tp_price_f:
                                            cancel_reason = "CANCELLED_STALE_TP_HIT_MARKET"
                                            main_logger.warning(f"[{signal_id}] STALE (TP Hit Market): Buy order {order_id}, Current Price ({current_market_price}) >= Hypo TP ({hypothetical_tp_price_f})")
                                        elif direction.upper() == "SELL" and current_market_price <= hypothetical_tp_price_f:
                                            cancel_reason = "CANCELLED_STALE_TP_HIT_MARKET"
                                            main_logger.warning(f"[{signal_id}] STALE (TP Hit Market): Sell order {order_id}, Current Price ({current_market_price}) <= Hypo TP ({hypothetical_tp_price_f})")
                                    
                                    # 2. Check SL Hit/Invalidated (if not already TP hit)
                                    if not cancel_reason:
                                        if direction.upper() == "BUY" and current_market_price <= sl_price_f:
                                            cancel_reason = "CANCELLED_STALE_SL_HIT_MARKET"
                                            main_logger.warning(f"[{signal_id}] STALE (SL Hit Market): Buy order {order_id}, Current Price ({current_market_price}) <= SL ({sl_price_f})")
                                        elif direction.upper() == "SELL" and current_market_price >= sl_price_f:
                                            cancel_reason = "CANCELLED_STALE_SL_HIT_MARKET"
                                            main_logger.warning(f"[{signal_id}] STALE (SL Hit Market): Sell order {order_id}, Current Price ({current_market_price}) >= SL ({sl_price_f})")

                                    # 3. Check if entry is too far from current market (market moved away)
                                    if not cancel_reason:
                                        staleness_deviation_percent = config_manager.get("scanner.staleness_entry_deviation_percent", 2.0) / 100.0
                                        if direction.upper() == "BUY" and entry_price_f < current_market_price * (1 - staleness_deviation_percent):
                                            # For a buy, if entry is significantly *below* current market (market ran up)
                                            cancel_reason = "CANCELLED_STALE_MARKET_MOVED_AWAY"
                                            main_logger.warning(f"[{signal_id}] STALE (Market Moved Away): Buy order {order_id}, Entry ({entry_f}) < Current Price ({current_market_price}) by > {staleness_deviation_percent*100:.2f}%")
                                        elif direction.upper() == "SELL" and entry_price_f > current_market_price * (1 + staleness_deviation_percent):
                                            # For a sell, if entry is significantly *above* current market (market ran down)
                                            cancel_reason = "CANCELLED_STALE_MARKET_MOVED_AWAY"
                                            main_logger.warning(f"[{signal_id}] STALE (Market Moved Away): Sell order {order_id}, Entry ({entry_f}) > Current Price ({current_market_price}) by > {staleness_deviation_percent*100:.2f}%")

                                    # --- Attempt Cancellation If Stale ---
                                    if cancel_reason:
                                        main_logger.user(f"[{signal_id}] Order {order_id} for {symbol} is STALE due to '{cancel_reason}'. Attempting cancellation.") # USER
                                        cancellation_details_for_db = {
                                            'cancellation_reason': cancel_reason,
                                            'market_price_at_cancellation': current_market_price,
                                            'original_entry': entry_price_f,
                                            'original_sl': sl_price_f,
                                            'hypothetical_tp': hypothetical_tp_price_f if hypothetical_tp_price_f is not None else None
                                        }
                                        # Cancel the order
                                        cancel_api_response = await order_executor.cancel_order(order_id, symbol)
                                        
                                        # Check Bybit V5 response structure for cancellation confirmation
                                        # Successful cancellation often returns the order details with status 'Cancelled' or 'Canceled'
                                        if cancel_api_response and (
                                            cancel_api_response.get('id') == order_id or 
                                            cancel_api_response.get('status', '').lower() in ['canceled', 'cancelled'] or
                                            cancel_api_response.get('orderStatus', '').lower() in ['canceled', 'cancelled'] # Common Bybit V5 field
                                            ):
                                            main_logger.info(f"[{signal_id}] Successfully cancelled stale order {order_id}. API Response: {cancel_api_response}") # INFO
                                            cancellation_details_for_db['cancel_api_response_status'] = cancel_api_response.get('status', cancel_api_response.get('orderStatus', 'Success'))
                                            state_manager.update_signal_status(signal_id, cancel_reason, cancellation_details_for_db)
                                        else:
                                            # Handle potential errors like "Order has been filled" or "Order not found / already cancelled" gracefully
                                            # These might not be 'failures' in cancelling, but indicate the order state changed before cancellation could execute.
                                            ret_code = cancel_api_response.get('retCode') if isinstance(cancel_api_response, dict) else None
                                            ret_msg = cancel_api_response.get('retMsg', 'Unknown error or non-dict response') if isinstance(cancel_api_response, dict) else str(cancel_api_response)

                                            # Specific Bybit error codes for "already filled/cancelled" etc. should be checked here if known.
                                            # Example: 110007 often means order not found or already processed
                                            if ret_code == 110007 or "order not exists" in ret_msg.lower() or "order has been filled" in ret_msg.lower() or "order has been cancelled" in ret_msg.lower():
                                                 main_logger.warning(f"[{signal_id}] Attempted to cancel stale order {order_id}, but it was likely already filled/cancelled. API Response: {cancel_api_response}. Will re-check status normally.")
                                                 # Don't update status to CANCELLATION_FAILED here, let the normal status check proceed
                                            else:
                                                 main_logger.error(f"[{signal_id}] Failed to cancel stale order {order_id} or cancellation not confirmed by API. API Response: {cancel_api_response}")
                                                 cancellation_details_for_db['cancel_api_response_status'] = 'FAILURE_OR_UNKNOWN'
                                                 cancellation_details_for_db['cancel_api_raw_response'] = str(cancel_api_response) # Store raw response for debugging
                                                 state_manager.update_signal_status(signal_id, "CANCELLATION_FAILED_STALE", cancellation_details_for_db)
                                        
                                        # IMPORTANT: After cancellation attempt (success or fail), skip further API status checks for this order *in this cycle*.
                                        # The state is updated, or normal check will happen next cycle if cancellation failed non-terminally.
                                        continue # Skip to the next signal_in_db in pending_entry_signals
                                        
                                except Exception as stale_check_e:
                                    main_logger.error(f"[{signal_id}] Error during market-based stale check for order {order_id}: {stale_check_e}", exc_info=True)
                                # --- <<< End Stale Order Cancellation Logic >>> ---

                            # Handle other API statuses ('canceled', 'rejected', etc.) - This part remains unchanged
                            elif status in ['canceled', 'cancelled']:
                                main_logger.user(f"Order {order_id} (Signal ID: {signal_id}) has status '{status}'. Updating DB.") # USER
                                state_manager.update_signal_status(signal_id, 'CANCELLED', {'cancellation_reason': 'API reported Canceled'})
                            elif status in ['rejected', 'expired']:
                                main_logger.warning(f"Order {order_id} (Signal ID: {signal_id}) has status '{status}'. Updating DB.")
                                state_manager.update_signal_status(signal_id, status.upper(), {'rejection_reason': f'API reported {status}'})
                            # Handle new statuses from check_order_status
                            elif status in ['notfound', 'unknown_after_retries', 'historical_notfound']:
                                if status == 'historical_notfound':
                                    new_db_status = 'CANCELLED_STALE_NOT_FOUND'
                                    main_logger.warning(f"Order {order_id} for signal {signal_id} ({symbol}) reported as '{status}' by OrderExecutor. Marking as {new_db_status} in DB.")
                                else: # 'notfound' or 'unknown_after_retries'
                                    new_db_status = 'UNKNOWN_API_STATUS' # Default for other not founds
                                    if status == 'notfound': # Explicitly not found by first checks
                                        main_logger.error(f"Order {order_id} for signal {signal_id} ({symbol}) reported as '{status}' (not found by open/closed checks, nor specific fetch_order). Marking as {new_db_status} in DB.")
                                    elif status == 'unknown_after_retries':
                                        main_logger.error(f"Order {order_id} for signal {signal_id} ({symbol}) reported as '{status}' after multiple retries. Marking as {new_db_status} in DB.")
                                    else: # Should not happen given the input list, but as a fallback
                                        main_logger.error(f"Order {order_id} for signal {signal_id} ({symbol}) reported as unhandled status '{status}' in notfound block. Marking as {new_db_status} in DB.")

                                state_manager.update_signal_status(signal_id, new_db_status, {'error_message': f'Order status check returned {status}'})
                            elif status in ['network_error', 'exchange_error', 'unexpected_error_check_status', 'unknown_loop_exit']:
                                main_logger.error(f"Order {order_id} for signal {signal_id} ({symbol}) encountered error: '{status}'. Marking as CHECK_STATUS_FAILED in DB.")
                                state_manager.update_signal_status(signal_id, 'CHECK_STATUS_FAILED', {'error_message': f'Order status check returned {status}.'})
                            else: 
                                main_logger.debug(f"Order {order_id} (Signal ID: {signal_id}) has status '{status}'. No status update action taken in DB yet.") # DEBUG
                        else:
                            main_logger.warning(f"Could not retrieve status details for order {order_id} (Signal ID: {signal_id}) from OrderExecutor (returned None/empty). This should ideally not happen.")
                            # Consider updating status to ERROR or UNKNOWN if consistently not found.
                            # current_db_signal = state_manager.get_signal(signal_id)
                            # if current_db_signal and current_db_signal['status'] == 'PENDING_ENTRY':
                            #     main_logger.error(f"Order {order_id} for signal {signal_id} status check failed, but still PENDING_ENTRY in DB. Marking as CHECK_STATUS_FAILED.")
                            #     state_manager.update_signal_status(signal_id, 'CHECK_STATUS_FAILED')

                    except Exception as e:
                        main_logger.error(f"Error checking status for order {order_id} (Signal ID: {signal_id}): {e}", exc_info=True)
            
            # --- Position/SL/TP Monitoring ---
            main_logger.info("Checking status of POSITION_OPEN orders (SL/TP monitoring)...") # INFO
            position_open_signals = state_manager.get_signals_by_status('POSITION_OPEN')

            if not position_open_signals:
                main_logger.info("No POSITION_OPEN orders to monitor for SL/TP.") # INFO
            else:
                main_logger.info(f"Found {len(position_open_signals)} POSITION_OPEN order(s) to monitor for SL/TP.") # INFO
                for db_signal in position_open_signals:
                    signal_id = db_signal['signal_id']
                    symbol = db_signal['symbol']
                    sl_order_id = db_signal.get('sl_order_id')
                    tp_order_id = db_signal.get('tp_order_id')
                    # Original signal_data might be needed for journaling full details upon close
                    try:
                        original_signal_data = json.loads(db_signal['signal_data']) if isinstance(db_signal['signal_data'], str) else db_signal['signal_data']
                    except json.JSONDecodeError as jde:
                        main_logger.error(f"Error decoding original_signal_data for {signal_id} during SL/TP monitoring: {jde}. Using partial data.")
                        original_signal_data = {'symbol': symbol} # Fallback
                    
                    original_signal_data['signal_id'] = signal_id # Ensure ID is part of data for journaling

                    if not order_executor:
                        main_logger.error("OrderExecutor not initialized. Cannot monitor SL/TP.")
                        break

                    # --- Check SL Order --- 
                    if sl_order_id:
                        try:
                            main_logger.debug(f"Checking SL order {sl_order_id} for signal {signal_id} ({symbol})")
                            sl_status_details = await order_executor.check_order_status(symbol=symbol, order_id=sl_order_id)
                            
                            if sl_status_details:
                                sl_status = sl_status_details.get('status')
                                main_logger.info(f"SL order {sl_order_id} (Signal {signal_id}) status: {sl_status}") # INFO
                                
                                if sl_status == 'filled' or sl_status == 'closed': # 'closed' often means fully filled
                                    filled_price = sl_status_details.get('averagePrice', original_signal_data.get('stop_loss_price'))
                                    main_logger.warning(f"!!! STOP LOSS HIT for signal {signal_id} ({symbol}) at price {filled_price} (Order ID: {sl_order_id}) !!!") # WARNING
                                    state_manager.update_signal_status(signal_id, 'CLOSED_SL', {'closed_price': filled_price, 'closed_by': 'SL'})
                                    original_signal_data['status'] = 'CLOSED_SL'
                                    original_signal_data['closed_price'] = filled_price
                                    journaling_module.log_trade_signal(original_signal_data) # Log final state
                                    signal_alerter.alert(original_signal_data, is_closure=True)
                                    
                                    if tp_order_id:
                                        main_logger.info(f"Attempting to cancel TP order {tp_order_id} for signal {signal_id} as SL was hit.") # INFO
                                        # Store cancellation attempt info if needed, or just log
                                        cancel_tp_response = await order_executor.cancel_order(tp_order_id, symbol)
                                        main_logger.info(f"Cancel TP order {tp_order_id} response: {cancel_tp_response}") # INFO
                                    continue # Move to next signal, this one is resolved

                                elif sl_status in ['canceled', 'cancelled', 'rejected', 'expired']:
                                    main_logger.error(f"SL order {sl_order_id} for signal {signal_id} ({symbol}) is {sl_status}! Position might be unprotected. Critical!")
                                    state_manager.update_signal_status(signal_id, f'SL_INACTIVE_{sl_status.upper()}', {'sl_order_id': sl_order_id, 'tp_order_id': tp_order_id, 'error_message': f'SL order reported as {sl_status}'})
                                    # TODO: Implement emergency handling? E.g., market close position.
                                    continue # Position is now in an error state, process next signal

                                elif sl_status in ['notfound', 'historical_notfound', 'unknown_after_retries']:
                                    new_db_status = 'SL_ORDER_NOT_FOUND_API'
                                    error_message_detail = f"SL order {sl_order_id} for signal {signal_id} ({symbol}) reported as '{sl_status}' by OrderExecutor."
                                    main_logger.error(f"{error_message_detail} Position might be unprotected. Critical! Marking as {new_db_status} in DB.")
                                    state_manager.update_signal_status(signal_id, new_db_status, {'sl_order_id': sl_order_id, 'error_message': error_message_detail})
                                    continue # Position is in an error state

                                elif sl_status in ['network_error', 'exchange_error', 'unexpected_error_check_status', 'unknown_loop_exit']:
                                    main_logger.error(f"SL order {sl_order_id} for signal {signal_id} ({symbol}) encountered API/network error: '{sl_status}'. Status check will retry next cycle.")
                                    # No state change, allow retry in next cycle
                                
                                # If sl_status is 'open' or any other unhandled status, it implies the SL is still active or in an indeterminate state.
                                # No specific action needed here, loop will check again.
                                else:
                                    main_logger.debug(f"SL order {sl_order_id} for signal {signal_id} status '{sl_status}'. No immediate closure action.") # DEBUG

                            else: # sl_status_details is None
                                main_logger.warning(f"Could not retrieve SL order {sl_order_id} status details (None returned) for signal {signal_id}. It might have been cancelled or does not exist. Check next cycle.")
                                # To avoid rapidly flipping state if it's a temporary API glitch, we might not change state immediately
                                # unless this persists over multiple cycles (more advanced handling).
                                # For now, if check_order_status returns None, we assume a temporary issue and retry.
                                current_status_in_db = state_manager.get_signal(signal_id).get('status')
                                if current_status_in_db == 'POSITION_OPEN': # Still expect it to be open
                                     main_logger.warning(f"SL order {sl_order_id} status check returned None for signal {signal_id}, but signal is POSITION_OPEN in DB. Potential issue with check_order_status or order disappeared.") # WARNING
                                     # Consider a specific state like 'SL_CHECK_FAILED_NO_DETAILS' if this becomes common.
                        except Exception as e:
                            main_logger.error(f"Error checking SL order {sl_order_id} for signal {signal_id}: {e}", exc_info=True)
                    else:
                        main_logger.error(f"Signal {signal_id} ({symbol}) is POSITION_OPEN but has no sl_order_id. Critical error in state.")
                        state_manager.update_signal_status(signal_id, 'MISSING_SL_ORDER_ID')
                        continue # Skip to next signal

                    # --- Check TP Order (only if SL not hit in this cycle) ---
                    if tp_order_id:
                        # First, ensure the signal hasn't already been closed by SL in this same cycle run
                        current_signal_status_for_tp_check = state_manager.get_signal(signal_id).get('status')
                        if current_signal_status_for_tp_check != 'POSITION_OPEN':
                            main_logger.info(f"Signal {signal_id} is no longer POSITION_OPEN (current: {current_signal_status_for_tp_check}). Skipping TP check for this cycle.")
                            continue

                        try:
                            main_logger.debug(f"Checking TP order {tp_order_id} for signal {signal_id} ({symbol})")
                            tp_status_details = await order_executor.check_order_status(symbol=symbol, order_id=tp_order_id)

                            if tp_status_details:
                                tp_status = tp_status_details.get('status')
                                main_logger.info(f"TP order {tp_order_id} (Signal {signal_id}) status: {tp_status}") # INFO
                                
                                if tp_status == 'filled' or tp_status == 'closed':
                                    # Ensure signal wasn't already closed by SL (double check, though prior check should catch it)
                                    if state_manager.get_signal(signal_id).get('status') == 'POSITION_OPEN':
                                        filled_price = tp_status_details.get('averagePrice', original_signal_data.get('take_profit_targets_str')) # Fallback is not ideal here
                                        actual_tp_price_from_db = db_signal.get('tp_price', 'N/A') # Get ordered TP price
                                        main_logger.user(f"$$$ TAKE PROFIT HIT for signal {signal_id} ({symbol}) at price {filled_price} (Order ID: {tp_order_id}, Ordered TP: {actual_tp_price_from_db}) $$$ ") # USER
                                        state_manager.update_signal_status(signal_id, 'CLOSED_TP', {'closed_price': filled_price, 'closed_by': 'TP'})
                                        original_signal_data['status'] = 'CLOSED_TP'
                                        original_signal_data['closed_price'] = filled_price
                                        journaling_module.log_trade_signal(original_signal_data) # Log final state
                                        signal_alerter.alert(original_signal_data, is_closure=True)

                                        if sl_order_id:
                                            main_logger.info(f"Attempting to cancel SL order {sl_order_id} for signal {signal_id} as TP was hit.") # INFO
                                            cancel_sl_response = await order_executor.cancel_order(sl_order_id, symbol)
                                            main_logger.info(f"Cancel SL order {sl_order_id} response: {cancel_sl_response}") # INFO
                                        continue # Move to next signal, this one is resolved
                                    else:
                                        main_logger.debug(f"TP order {tp_order_id} for signal {signal_id} found filled, but signal already closed (e.g. by SL). No action.") # DEBUG
                                        continue

                                elif tp_status in ['canceled', 'cancelled', 'rejected', 'expired']:
                                    main_logger.warning(f"TP order {tp_order_id} for signal {signal_id} ({symbol}) is {tp_status}. Position remains open with SL only (if SL is active).")
                                    # Update status to reflect TP inactive, but SL might still be active.
                                    # Do not mark as fully error if SL is still there.
                                    current_db_status = state_manager.get_signal(signal_id).get('status')
                                    if current_db_status == 'POSITION_OPEN': # Only update if not already closed by SL
                                        state_manager.update_signal_status(signal_id, f'TP_INACTIVE_{tp_status.upper()}', {'sl_order_id': sl_order_id, 'tp_order_id': tp_order_id, 'error_message': f'TP order reported as {tp_status}'})
                                    # Position continues, but without this specific TP.

                                elif tp_status in ['notfound', 'historical_notfound', 'unknown_after_retries']:
                                    new_db_status = 'TP_ORDER_NOT_FOUND_API'
                                    error_message_detail = f"TP order {tp_order_id} for signal {signal_id} ({symbol}) reported as '{tp_status}' by OrderExecutor."
                                    main_logger.warning(f"{error_message_detail} Signal was POSITION_OPEN. Marking as {new_db_status} in DB.")
                                    current_db_status = state_manager.get_signal(signal_id).get('status')
                                    if current_db_status == 'POSITION_OPEN': # Only update if not already closed by SL
                                        state_manager.update_signal_status(signal_id, new_db_status, {'tp_order_id': tp_order_id, 'error_message': error_message_detail})
                                
                                elif tp_status in ['network_error', 'exchange_error', 'unexpected_error_check_status', 'unknown_loop_exit']:
                                    main_logger.error(f"TP order {tp_order_id} for signal {signal_id} ({symbol}) encountered API/network error: '{tp_status}'. Status check will retry next cycle.")
                                    # No state change, allow retry in next cycle
                                else:
                                    main_logger.debug(f"TP order {tp_order_id} for signal {signal_id} status '{tp_status}'. No immediate closure action.") # DEBUG

                            else: # tp_status_details is None
                                main_logger.warning(f"Could not retrieve TP order {tp_order_id} status details (None returned) for signal {signal_id}. It might have been cancelled or does not exist. Check next cycle.")
                                # Similar to SL, avoid rapid state change on temporary glitch.
                                current_status_in_db = state_manager.get_signal(signal_id).get('status')
                                if current_status_in_db == 'POSITION_OPEN': # Still expect it to be open
                                     main_logger.warning(f"TP order {tp_order_id} status check returned None for signal {signal_id}, but signal is POSITION_OPEN in DB. Potential issue with check_order_status or order disappeared.") # WARNING
                                     # Consider a specific state like 'TP_CHECK_FAILED_NO_DETAILS'.
                        except Exception as e:
                            main_logger.error(f"Error checking TP order {tp_order_id} for signal {signal_id}: {e}", exc_info=True)
                    # If no tp_order_id but position is open, it means TP placement might have failed earlier.
                    # The status should reflect that (e.g., TP_PLACEMENT_FAILED). No specific action here unless new TPs are to be attempted.
                    # or if the SL was hit in this same cycle, this TP check part would be skipped.
                
            # --- Wait for next cycle --- 
            loop_end_time = time.time()
            loop_duration = loop_end_time - loop_start_time
            wait_time = max(0, scan_interval_seconds - loop_duration)
            main_logger.user(f"Scan cycle finished in {loop_duration:.2f}s. Waiting {wait_time:.2f}s for next cycle.") # USER
            await asyncio.sleep(wait_time)

    except asyncio.CancelledError:
        main_logger.info("Scanner task cancelled.") # INFO
    except Exception as e:
        main_logger.critical(f"Critical error in main scanner loop: {e}", exc_info=True)
    finally:
        main_logger.user("--- Shutting down Crypto Scanner Bot ---") # USER
        if data_ingestion_module and hasattr(data_ingestion_module, 'exchange') and data_ingestion_module.exchange:
            await data_ingestion_module.close()
        main_logger.info("--- Shutdown complete ---") # INFO


if __name__ == "__main__":
    try:
        # Ensure logs directory exists before initializing logger via LoggingService
        try: from .config_manager import ConfigManager 
        except ImportError: from config_manager import ConfigManager # Fallback for direct run?

        config_mgr_for_logs = ConfigManager(CONFIG_FILE)
        log_cfg = config_mgr_for_logs.get_logging_config()
        log_file = Path(log_cfg.get("log_file", "logs/bot.log"))
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Now LoggingService can be safely imported relatively if run with -m
        from .logging_service import logger_instance 
        
        asyncio.run(run_scanner())
    except KeyboardInterrupt:
        # Ensure logger_instance is available here
        try: from .logging_service import logger_instance 
        except ImportError: logger_instance = None
        
        if logger_instance:
             logger_instance.user("Shutdown requested by user (KeyboardInterrupt).") # USER
        else:
             print("Shutdown requested by user (KeyboardInterrupt). Logger not available.") 