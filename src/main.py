import asyncio
import time
import traceback
from pathlib import Path
import pandas as pd # Needed for type hints potentially

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

async def run_scanner():
    """
    Main asynchronous function to run the crypto scanner bot.
    """
    run_start_time = time.time()
    main_logger = logger_instance.bind(name="MainApp") 
    main_logger.info("--- Starting Crypto Scanner Bot ---")

    # --- Initialize Modules ---
    data_ingestion_module = None 
    order_executor = None
    state_manager = None
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        config_manager = ConfigManager(CONFIG_FILE)
        main_logger.info("ConfigManager initialized.")

        data_ingestion_module = DataIngestionModule(
            config_manager=config_manager,
            logger_object=logger_instance 
        )
        if not await data_ingestion_module.initialize():
            main_logger.critical("Failed to initialize Data Ingestion Module. Exiting.")
            return
        main_logger.info("DataIngestionModule initialized.")

        risk_management_module = RiskManagementModule(
            data_ingestion_module=data_ingestion_module,
            config_manager=config_manager,
            logger=logger_instance 
        )
        main_logger.info("RiskManagementModule initialized.")
        
        order_executor = OrderExecutor(
             data_ingestion_module=data_ingestion_module,
             config_manager=config_manager,
             main_logger=logger_instance
        )
        main_logger.info("OrderExecutor initialized.")
        
        state_manager = StateManager(
            config_manager=config_manager,
            main_logger=logger_instance
        )
        main_logger.info("StateManager initialized.")

        analysis_engine = AnalysisEngine(
            data_ingestion_module=data_ingestion_module,
            config_manager=config_manager,
            logger_object=logger_instance 
        )
        main_logger.info("AnalysisEngine initialized.")

        journaling_module = JournalingModule(
            config_manager=config_manager,
            main_logger=logger_instance 
        )
        main_logger.info("JournalingModule initialized.")

        signal_alerter = SignalAlerter(
            config_manager=config_manager,
            main_logger=logger_instance, 
            risk_management_module=risk_management_module
        )
        main_logger.info("SignalAlerter initialized.")

        main_logger.info("--- All modules initialized successfully ---")

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
        while True:
            loop_start_time = time.time()
            main_logger.info("Starting new scan cycle...")

            coins_to_scan = config_manager.get("portfolio.coins_to_scan", [])
            if not coins_to_scan:
                main_logger.warning("No coins configured in portfolio.coins_to_scan. Skipping scan cycle.")
                await asyncio.sleep(scan_interval_seconds)
                continue

            main_logger.info(f"Scanning symbols: {coins_to_scan}")

            all_potential_signals = []
            # --- Run Analysis --- 
            for symbol in coins_to_scan:
                try:
                    main_logger.info(f"Analyzing {symbol}...")
                    potential_signals = await analysis_engine.run_analysis(symbol) 
                    if potential_signals:
                        main_logger.info(f"Found {len(potential_signals)} potential raw signal(s) for {symbol}.")
                        all_potential_signals.extend(potential_signals)
                    else:
                         main_logger.debug(f"No potential raw signals found for {symbol}.")
                except Exception as e:
                    main_logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)
                await asyncio.sleep(config_manager.get("scanner.delay_between_symbols_seconds", 0.5))

            # --- Process Potential Signals --- 
            if all_potential_signals:
                main_logger.info(f"Processing {len(all_potential_signals)} total potential signals found in this cycle.")
                for signal_data in all_potential_signals:
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
                            main_logger.debug(f"Signal ID {signal_id} ({symbol}) already tracked with status {existing_signal['status']}. Skipping.")
                            continue 
                            
                        # Check for other active trades for the *same symbol*
                        active_symbol_signals = state_manager.get_active_signals_by_symbol(symbol)
                        if len(active_symbol_signals) >= max_concurrent_trades:
                            main_logger.info(f"Skipping new signal for {symbol} as {len(active_symbol_signals)} active trade(s) already exist (max: {max_concurrent_trades}).")
                            continue
                            
                        # --- New Signal Processing --- 
                        main_logger.info(f"New unique signal identified for {symbol} (ID: {signal_id}). Processing entry...") 

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

                        pos_size, actual_risk = await risk_management_module.calculate_position_size(
                            symbol=symbol,
                            entry_price=entry_f, 
                            stop_loss_price=sl_f, 
                            fixed_dollar_risk=fixed_dollar_risk
                        )
                        if pos_size is None or actual_risk is None:
                            main_logger.error(f"Could not calculate position size for {signal_id} ({symbol}). Skipping entry.")
                            continue
                        signal_data['position_size'] = pos_size
                        signal_data['actual_risk_usd'] = actual_risk
                            
                        # 3. Place Limit Entry Order (❗ LIVE ORDER PLACEMENT ❗)
                        main_logger.warning(f"ATTEMPTING TO PLACE LIVE ORDER for signal {signal_id} ({symbol} {direction} @ {entry_f})")
                        entry_order = await order_executor.place_limit_entry_order(
                            symbol=symbol,
                            side=direction, 
                            qty=pos_size,
                            price=entry_f 
                        )
                        
                        if entry_order and entry_order.get('id'):
                            entry_order_id = entry_order.get('id')
                            main_logger.info(f"Successfully placed entry order {entry_order_id} for signal {signal_id} ({symbol}).")
                            
                            # 4. Add to State Manager
                            added = state_manager.add_signal_entry(signal_id, signal_data, entry_order_id)
                            if not added:
                                 main_logger.error(f"Failed to add signal {signal_id} to StateManager DB, but order {entry_order_id} was placed! Manual intervention may be required. Consider cancelling.")
                                 # If this fails, we have an order without state tracking - needs manual check
                            
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
                                             if direction.upper() == "LONG": raw_tp = entry_f + (sl_distance * ratio)
                                             elif direction.upper() == "SHORT": raw_tp = entry_f - (sl_distance * ratio)
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
                            main_logger.info(f"Logging and Alerting NEW PENDING signal: {signal_id}")
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
            else:
                 main_logger.info("No new signals generated in this cycle to process.")
                 
            # --- TODO: Add Order Status Monitoring Logic --- 
            # ... (placeholder for monitoring logic) ...
            
            # --- TODO: Add Position/SL/TP Monitoring Logic --- 
            # ... (placeholder for monitoring logic) ...

            # --- Wait for next cycle --- 
            loop_end_time = time.time()
            loop_duration = loop_end_time - loop_start_time
            wait_time = max(0, scan_interval_seconds - loop_duration)
            main_logger.info(f"Scan cycle finished in {loop_duration:.2f}s. Waiting {wait_time:.2f}s for next cycle.")
            await asyncio.sleep(wait_time)

    except asyncio.CancelledError:
        main_logger.info("Scanner task cancelled.")
    except Exception as e:
        main_logger.critical(f"Critical error in main scanner loop: {e}", exc_info=True)
    finally:
        main_logger.info("--- Shutting down Crypto Scanner Bot ---")
        if data_ingestion_module and hasattr(data_ingestion_module, 'exchange') and data_ingestion_module.exchange:
            await data_ingestion_module.close()
        main_logger.info("--- Shutdown complete ---")


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
             logger_instance.info("Shutdown requested by user (KeyboardInterrupt).")
        else:
             print("Shutdown requested by user (KeyboardInterrupt). Logger not available.") 