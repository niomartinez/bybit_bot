import datetime
from pathlib import Path
import math # For rounding to tick size

class SignalAlerter:
    def __init__(self, config_manager, main_logger, risk_management_module):
        self.config = config_manager # Store the whole config manager for now
        self.notification_config = config_manager.get_notification_config()
        self.strategy_config = config_manager.get_strategy_params()
        self.logger = main_logger.bind(name="SignalAlerter")
        self.risk_manager = risk_management_module

        self.signals_log_file = Path(self.notification_config.get("signals_log_file", "logs/trade_signals.log"))
        self.signals_log_file.parent.mkdir(parents=True, exist_ok=True)

        # TODO: Initialize Telegram/Discord handlers if enabled in config

    @staticmethod
    def _get_price_precision(tick_size: float) -> int:
        """Derives the number of decimal places from a tick size."""
        if tick_size >= 1:
            return 0
        # Convert to string to count decimal places accurately, avoiding float precision issues
        tick_size_str = f"{tick_size:.10f}".rstrip('0')
        if '.' in tick_size_str:
            return len(tick_size_str.split('.')[1])
        return 0

    @staticmethod
    def _adjust_price_to_tick_size(price: float, tick_size: float, direction: str = "NEUTRAL") -> float:
        """Adjusts a price to be a valid multiple of the tick_size."""
        if tick_size == 0: return price # Should not happen with valid specs
        # For TPs, we want to round in favor of the trade if possible, or to nearest.
        # Long TPs: round down (conservative) or nearest.
        # Short TPs: round up (conservative) or nearest.
        # For simplicity here, let's round to the nearest tick. 
        # More advanced rounding (e.g. math.floor for long TPs, math.ceil for short TPs after scaling)
        # could be implemented if being slightly off from an exact R:R is acceptable for hitting a valid price.
        
        # Round to the number of decimal places dictated by tick_size first to avoid float artifacts
        precision = SignalAlerter._get_price_precision(tick_size)
        price = round(price, precision + 1) # Round to one more precision to help with math.fmod or decimal division

        # Simple rounding to nearest tick for now
        return round(price / tick_size) * tick_size

    def _format_signal_message(self, signal_data: dict) -> str:
        """Formats the signal data into a human-readable string."""
        
        tp_levels_str = "N/A"
        tick_size = signal_data.get('tick_size')
        price_precision = self._get_price_precision(tick_size) if tick_size else signal_data.get('price_precision', 2)

        if signal_data.get('entry_price') and signal_data.get('stop_loss_price') and signal_data.get('position_size'):
            entry_price = float(signal_data['entry_price'])
            sl_price = float(signal_data['stop_loss_price'])
            direction = signal_data.get('direction', 'N/A').upper()
            sl_distance = abs(entry_price - sl_price)

            tp_ratios = self.strategy_config.get('take_profit', {}).get('fixed_rr_ratios', [1.0, 2.0, 3.0])
            tps = []
            if sl_distance > 0:
                for ratio in tp_ratios:
                    raw_tp = 0
                    if direction == "LONG":
                        raw_tp = entry_price + (sl_distance * ratio)
                    elif direction == "SHORT":
                        raw_tp = entry_price - (sl_distance * ratio)
                    else:
                        continue
                    
                    adjusted_tp = self._adjust_price_to_tick_size(raw_tp, tick_size, direction) if tick_size else raw_tp
                    tps.append(f"TP{len(tps)+1} ({ratio}R): {adjusted_tp:.{price_precision}f}")
                tp_levels_str = ", ".join(tps) if tps else "N/A"
        
        entry_price_str = f"{signal_data.get('entry_price', 'N/A'):.{price_precision}f}" if isinstance(signal_data.get('entry_price'), float) and tick_size else str(signal_data.get('entry_price', 'N/A'))
        sl_price_str = f"{signal_data.get('stop_loss_price', 'N/A'):.{price_precision}f}" if isinstance(signal_data.get('stop_loss_price'), float) and tick_size else str(signal_data.get('stop_loss_price', 'N/A'))
        bos_level_str = f"{signal_data.get('bos_level_15m', 'N/A'):.{price_precision}f}" if isinstance(signal_data.get('bos_level_15m'), float) and tick_size else str(signal_data.get('bos_level_15m', 'N/A'))
        fvg_low_str = f"{signal_data.get('fvg_low_15m', 'N/A'):.{price_precision}f}" if isinstance(signal_data.get('fvg_low_15m'), float) and tick_size else str(signal_data.get('fvg_low_15m', 'N/A'))
        fvg_high_str = f"{signal_data.get('fvg_high_15m', 'N/A'):.{price_precision}f}" if isinstance(signal_data.get('fvg_high_15m'), float) and tick_size else str(signal_data.get('fvg_high_15m', 'N/A'))

        message_lines = [
            "TRADE SIGNAL" + (" (PAPER)" if self.config.get_cex_api_config().get("testnet") else ""),
            f"Timestamp: {signal_data.get('timestamp', datetime.datetime.now(datetime.timezone.utc).isoformat())}",
            f"Symbol: {signal_data.get('symbol', 'N/A')}",
            f"Direction: {signal_data.get('direction', 'N/A').upper()}",
            f"Confidence: {signal_data.get('confidence_score', 'N/A')}/5",
            "--- 15m POI ---",
            f"  BOS Level: {bos_level_str}",
            f"  FVG Range: {fvg_low_str} - {fvg_high_str}",
            f"  Fib Levels Touched: {signal_data.get('fib_levels_15m_touched', 'N/A')}",
            "--- 5m Entry ---",
            f"  Trigger Type: {signal_data.get('entry_trigger_5m', 'N/A')}",
            f"  Entry Price: {entry_price_str}",
            f"  Stop Loss: {sl_price_str}",
            f"  Take Profit Targets: {tp_levels_str}",
            f"  Position Size: {signal_data.get('position_size', 'N/A')}",
            f"  Actual Risk $: {signal_data.get('actual_risk_usd', 'N/A'):.2f}" if isinstance(signal_data.get('actual_risk_usd'), float) else f"  Actual Risk $: {signal_data.get('actual_risk_usd', 'N/A')}",
        ]
        return "\n".join(message_lines)

    def _log_signal_to_file(self, formatted_signal: str):
        try:
            with open(self.signals_log_file, 'a') as f:
                f.write(f"{formatted_signal}\n--- --- ---\n")
            self.logger.info(f"Signal logged to {self.signals_log_file}")
        except Exception as e:
            self.logger.error(f"Failed to log signal to file {self.signals_log_file}: {e}")

    def alert(self, signal_data: dict):
        """
        Processes the signal data, formats it, logs it, and sends notifications.
        signal_data should be a dictionary with all necessary fields.
        """
        if not signal_data or not isinstance(signal_data, dict):
            self.logger.error("Alert called with invalid signal_data.")
            return

        self.logger.info(f"Processing alert for {signal_data.get('symbol', 'N/A')} {signal_data.get('direction', 'N/A')}...")
        
        if 'symbol' in signal_data and 'tick_size' not in signal_data:
             self.logger.warning(f"Tick size not in signal_data for {signal_data['symbol']}. TP formatting might be suboptimal or use default precision.")

        formatted_message = self._format_signal_message(signal_data)
        
        # Output to console
        print("\n" + "="*30)
        print(formatted_message)
        print("="*30 + "\n")
        
        # Log to dedicated signals file
        self._log_signal_to_file(formatted_message)
        
        # TODO: Implement Telegram notifications
        if self.notification_config.get("enable_telegram", False):
            # self._send_telegram_message(formatted_message)
            self.logger.info("Telegram notifications enabled but sending not yet implemented.")
            pass

        # TODO: Implement Discord notifications
        if self.notification_config.get("enable_discord", False):
            # self._send_discord_message(formatted_message)
            self.logger.info("Discord notifications enabled but sending not yet implemented.")
            pass
        
        self.logger.info(f"Alert processing finished for {signal_data.get('symbol', 'N/A')}.")


if __name__ == '__main__':
    # This test block needs to be more carefully constructed
    # It needs a mock/real ConfigManager, logger, and potentially RiskManagementModule
    # For now, a very basic test:
    
    # Mock necessary components for basic testing
    class MockConfigManager:
        def get_notification_config(self):
            return {"signals_log_file": "logs/test_trade_signals.log", "enable_telegram": False, "enable_discord": False}
        def get_strategy_params(self):
            return {'take_profit': {'fixed_rr_ratios': [1.0, 2.0]}}
        def get_cex_api_config(self):
            return {"testnet": True}
        def get(self, key, default=None): # Basic get for testnet flag in format_signal
            if key == "cex_api.testnet": return self.get_cex_api_config().get("testnet", default)
            return default


    class MockLogger:
        def bind(self, name):
            print(f"Logger bound to: {name}")
            return self # Return self for chained calls if any, or a new mock logger
        def info(self, msg): print(f"INFO: {msg}")
        def error(self, msg): print(f"ERROR: {msg}")
        def warning(self, msg): print(f"WARNING: {msg}")

    class MockRiskManagementModule: # Not used in current alerter directly but good for future
        pass

    print("--- Testing SignalAlerter ---")
    mock_config = MockConfigManager()
    mock_logger = MockLogger()
    mock_rm = MockRiskManagementModule()

    alerter = SignalAlerter(config_manager=mock_config, main_logger=mock_logger, risk_management_module=mock_rm)

    sample_signal_1 = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'symbol': 'BTCUSDT',
        'direction': 'LONG',
        'confidence_score': 4,
        'bos_level_15m': 60000.50,
        'fvg_low_15m': 59500.00,
        'fvg_high_15m': 59800.00,
        'fib_levels_15m_touched': "[0.618]",
        'entry_trigger_5m': "FVG Mitigation @ 59700.00",
        'entry_price': 59700.12,
        'stop_loss_price': 59400.34,
        'position_size': 0.015,
        'actual_risk_usd': 0.98,
        'tick_size': 0.1 # Added for BTC
    }
    
    sample_signal_2 = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'symbol': 'ETHUSDT',
        'direction': 'SHORT',
        'confidence_score': 3,
        'bos_level_15m': 3000.00,
        'fvg_low_15m': 3050.00,
        'fvg_high_15m': 3080.00,
        'fib_levels_15m_touched': "[0.5, 0.618]",
        'entry_trigger_5m': "5m MSS, retest of 3060.00",
        'entry_price': 3060.50,
        'stop_loss_price': 3090.10,
        'position_size': 0.25,
        'actual_risk_usd': 1.01,
        'tick_size': 0.01 # Added for ETH
    }
    
    no_price_precision_signal = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'symbol': 'ADAUSDT',
        'direction': 'LONG',
        'entry_price': 0.4512,
        'stop_loss_price': 0.4400,
        'position_size': 100.0,
        'actual_risk_usd': 0.95,
        'tick_size': 0.0001 # Added for ADA
    }


    print("\n--- Alerting Signal 1 ---")
    alerter.alert(sample_signal_1)
    
    print("\n--- Alerting Signal 2 ---")
    alerter.alert(sample_signal_2)

    print("\n--- Alerting Signal with missing price precision ---")
    alerter.alert(no_price_precision_signal)
    
    print("\n--- Test with invalid data ---")
    alerter.alert(None)
    alerter.alert("not a dict")

    print("\n--- Test Done. Check logs/test_trade_signals.log ---") 