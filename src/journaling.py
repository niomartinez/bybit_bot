import csv
import datetime
from pathlib import Path
from typing import Dict, List, Any

class JournalingModule:
    def __init__(self, config_manager, main_logger):
        self.config = config_manager
        self.journal_config = config_manager.get_journaling_config()
        self.logger = main_logger.bind(name="JournalingModule")

        self.journal_type = self.journal_config.get("journal_file_type", "csv").lower()
        self.csv_file_path = Path(self.journal_config.get("csv_journal_file", "logs/trade_journal.csv"))
        # self.db_uri = self.journal_config.get("db_journal_uri", "sqlite:///logs/trade_journal.db") # For future DB support

        # Define base column headers for scanner signals
        # Bot-specific fields can be added later or handled by having nullable columns
        self.csv_headers = [
            "TimestampUTC", "Symbol", "Direction", "ConfidenceScore",
            "EntryPrice", "StopLossPrice", "PositionSize", "ActualRiskUSD",
            "CalculatedTPs", # This could be a string representation of multiple TPs
            "BOSLevel15m", "FVGLow15m", "FVGHigh15m", "FibLevels15mTouched",
            "EntryTrigger5m", "TickSize",
            # Future bot fields (can be empty for scanner)
            "EntryFillPrice", "ExitPrice", "PnLUSD", "FeesUSD", 
            "TradeDurationSeconds", "ExitReason", "SLOrderID", "TPOrderID"
        ]

        if self.journal_type == "csv":
            self._ensure_csv_file_exists()

        # TODO: Initialize DB connection if self.journal_type == "db"

    def _ensure_csv_file_exists(self):
        try:
            self.csv_file_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.csv_file_path.exists() or self.csv_file_path.stat().st_size == 0:
                with open(self.csv_file_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.csv_headers)
                self.logger.info(f"Created new CSV journal file with headers: {self.csv_file_path}")
        except Exception as e:
            self.logger.error(f"Error ensuring CSV journal file exists at {self.csv_file_path}: {e}", exc_info=True)

    def log_trade_signal(self, signal_data: Dict[str, Any]):
        """Logs the provided signal data to the configured journal (CSV or DB)."""
        if not signal_data or not isinstance(signal_data, dict):
            self.logger.error("Log trade signal called with invalid signal_data.")
            return

        self.logger.info(f"Logging signal for {signal_data.get('symbol', 'N/A')} {signal_data.get('direction', 'N/A')}...")

        if self.journal_type == "csv":
            self._log_to_csv(signal_data)
        elif self.journal_type == "db":
            self.logger.warning("Database journaling not yet implemented. Signal not logged to DB.")
            # self._log_to_db(signal_data) # Future implementation
        else:
            self.logger.warning(f"Unknown journal type configured: {self.journal_type}. Signal not logged.")

    def _log_to_csv(self, signal_data: Dict[str, Any]):
        try:
            # Prepare a row dictionary ensuring all headers are present, defaulting to None or empty string
            row_to_write = {header: signal_data.get(header) for header in self.csv_headers}
            
            # Specific mapping for keys that might have different names in signal_data
            # or need specific formatting
            row_to_write["TimestampUTC"] = signal_data.get('timestamp', datetime.datetime.now(datetime.timezone.utc).isoformat())
            row_to_write["Symbol"] = signal_data.get('symbol')
            row_to_write["Direction"] = signal_data.get('direction')
            row_to_write["ConfidenceScore"] = signal_data.get('confidence_score')
            row_to_write["EntryPrice"] = signal_data.get('entry_price')
            row_to_write["StopLossPrice"] = signal_data.get('stop_loss_price')
            row_to_write["PositionSize"] = signal_data.get('position_size')
            row_to_write["ActualRiskUSD"] = signal_data.get('actual_risk_usd')
            row_to_write["CalculatedTPs"] = signal_data.get('take_profit_targets_str') # Assuming SignalAlerter might pass this formatted string
            row_to_write["BOSLevel15m"] = signal_data.get('bos_level_15m')
            row_to_write["FVGLow15m"] = signal_data.get('fvg_low_15m')
            row_to_write["FVGHigh15m"] = signal_data.get('fvg_high_15m')
            row_to_write["FibLevels15mTouched"] = signal_data.get('fib_levels_15m_touched')
            row_to_write["EntryTrigger5m"] = signal_data.get('entry_trigger_5m')
            row_to_write["TickSize"] = signal_data.get('tick_size')

            # Ensure all values are suitable for CSV (e.g. convert None to empty string)
            csv_row_values = [str(row_to_write.get(header, '')) for header in self.csv_headers]

            with open(self.csv_file_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(csv_row_values)
            self.logger.info(f"Signal successfully logged to CSV: {self.csv_file_path}")

        except Exception as e:
            self.logger.error(f"Error logging signal to CSV {self.csv_file_path}: {e}", exc_info=True)

# --- Example Usage --- #
if __name__ == '__main__':
    # Mock components for testing
    class MockConfigManager:
        def get_journaling_config(self):
            return {"journal_file_type": "csv", "csv_journal_file": "logs/test_journal.csv"}
        # Add other getters if JournalingModule starts using them more broadly

    class MockLogger:
        def bind(self, name):
            print(f"Logger bound to: {name}")
            return self
        def info(self, msg): print(f"INFO: {msg}")
        def error(self, msg): print(f"ERROR: {msg}")
        def warning(self, msg): print(f"WARNING: {msg}")

    print("--- Testing JournalingModule ---")
    mock_config = MockConfigManager()
    mock_logger = MockLogger()

    journaler = JournalingModule(config_manager=mock_config, main_logger=mock_logger)

    # Create a sample signal_data dictionary, similar to what AnalysisEngine would produce
    # and what SignalAlerter uses/formats
    sample_signal_1 = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'symbol': 'BTCUSDT',
        'direction': 'LONG',
        'confidence_score': 4,
        'entry_price': 59700.12,
        'stop_loss_price': 59400.34,
        'position_size': 0.015,
        'actual_risk_usd': 0.98,
        'take_profit_targets_str': "TP1 (1.0R): 59999.9, TP2 (2.0R): 60299.7", # Formatted by Alerter
        'bos_level_15m': 60000.50,
        'fvg_low_15m': 59500.00,
        'fvg_high_15m': 59800.00,
        'fib_levels_15m_touched': "[0.618]",
        'entry_trigger_5m': "FVG Mitigation @ 59700.00",
        'tick_size': 0.1
    }

    sample_signal_2_minimal = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'symbol': 'ETHUSDT',
        'direction': 'SHORT',
        # Missing many fields, to test default handling
        'entry_price': 3000.00,
        'stop_loss_price': 3030.00,
        'position_size': 0.1,
        'actual_risk_usd': 0.99
    }

    print("\n--- Logging Signal 1 (Full) ---")
    journaler.log_trade_signal(sample_signal_1)

    print("\n--- Logging Signal 2 (Minimal) ---")
    journaler.log_trade_signal(sample_signal_2_minimal)

    print("\n--- Test with invalid data ---")
    journaler.log_trade_signal(None)
    journaler.log_trade_signal("not a dict")

    print("\n--- Journaling Test Done. Check logs/test_journal.csv ---") 