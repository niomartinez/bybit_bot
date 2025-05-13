import sqlite3
import datetime
import json
from pathlib import Path
from typing import Dict, Optional, List, Any
import hashlib

class StateManager:
    def __init__(self, config_manager, main_logger):
        self.config = config_manager
        self.journal_config = config_manager.get_journaling_config()
        self.logger = main_logger.bind(name="StateManager")
        
        self.db_path = Path(self.journal_config.get("db_journal_file", "logs/trade_journal.db"))
        if not self.db_path:
            self.db_path = Path(self.config.get("database.path", "logs/trade_journal.db"))

        self.logger.info(f"Using state database: {self.db_path}")
        self._init_db()

    def _get_db_connection(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row 
            conn.execute("PRAGMA journal_mode=WAL;") 
            return conn
        except sqlite3.Error as e:
            self.logger.error(f"Database connection error to {self.db_path}: {e}", exc_info=True)
            raise

    def _init_db(self):
        conn = self._get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracked_signals (
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    poi_key TEXT,
                    status TEXT NOT NULL,
                    entry_order_id TEXT,
                    sl_order_id TEXT,
                    tp_order_id TEXT, 
                    entry_signal_price REAL,
                    entry_fill_price REAL,
                    sl_price REAL,
                    tp_price REAL, 
                    position_size REAL,
                    hypothetical_tp_price REAL, -- Store the initially calculated TP for validation
                    actual_tp_ordered REAL, -- Actual TP price sent in the order
                    signal_timestamp DATETIME, -- Timestamp of the 5m signal candle
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    signal_data TEXT, 
                    filled_qty REAL, 
                    closed_price REAL, 
                    closed_by TEXT,
                    error_message TEXT
                )
            """)
            
            table_info = cursor.execute("PRAGMA table_info(tracked_signals)").fetchall()
            column_names = [info[1] for info in table_info]

            def add_column_if_not_exists(col_name, col_type):
                if col_name not in column_names:
                    cursor.execute(f"ALTER TABLE tracked_signals ADD COLUMN {col_name} {col_type}")
                    self.logger.info(f"Added '{col_name}' column to 'tracked_signals' table.")

            add_column_if_not_exists('signal_timestamp', 'DATETIME')
            add_column_if_not_exists('hypothetical_tp_price', 'REAL')
            add_column_if_not_exists('actual_tp_ordered', 'REAL')
            add_column_if_not_exists('filled_qty', 'REAL')
            add_column_if_not_exists('closed_price', 'REAL')
            add_column_if_not_exists('closed_by', 'TEXT')
            add_column_if_not_exists('poi_key', 'TEXT')
            add_column_if_not_exists('error_message', 'TEXT')

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_status ON tracked_signals (symbol, status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON tracked_signals (status)")
            
            conn.commit()
            self.logger.info("Database initialized and 'tracked_signals' table ensured.")
        except sqlite3.Error as e:
            self.logger.error(f"Database initialization error: {e}", exc_info=True)
        finally:
            if conn:
                conn.close()

    def generate_signal_id(self, signal_data: Dict[str, Any]) -> Optional[str]:
        poi_key_data = {
            'symbol': signal_data.get('symbol'),
            'direction': signal_data.get('direction'),
            'bos': signal_data.get('bos_level_15m'),
            'fvg_low': signal_data.get('fvg_low_15m'),
            'fvg_high': signal_data.get('fvg_high_15m'),
            'fibs': signal_data.get('fib_levels_15m_touched'),
            'entry_ts': signal_data.get('timestamp')[:16] # Use 5m entry timestamp up to minute for POI key part
        }
        if all(v is None or v == 'N/A' for k, v in poi_key_data.items() if k not in ['symbol', 'direction', 'entry_ts']):
             poi_key_data = {
                'symbol': signal_data.get('symbol'),
                'direction': signal_data.get('direction'),
                'entry': signal_data.get('entry_price'),
                'sl': signal_data.get('stop_loss_price'),
                'timestamp': signal_data.get('timestamp')[:16]
             }
        try:
            stable_string = json.dumps(poi_key_data, sort_keys=True)
            return hashlib.sha256(stable_string.encode()).hexdigest()[:16]
        except Exception as e:
            self.logger.error(f"Error generating signal ID: {e}", exc_info=True)
            return None

    def add_signal_entry(self, signal_id: str, signal_data: Dict[str, Any], entry_order_id: str, actual_tp_ordered: Optional[float] = None) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            signal_data_json = json.dumps(signal_data)
        except TypeError as e:
            self.logger.error(f"Failed to serialize signal_data to JSON for signal {signal_id}: {e}")
            return False
            
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                
                symbol_val = signal_data.get('symbol')
                direction_val = signal_data.get('direction')
                poi_key_val = self.generate_signal_id(signal_data) 
                status_val = 'PENDING_ENTRY'
                entry_order_id_val = entry_order_id
                entry_signal_price_val = signal_data.get('entry_price')
                sl_price_val = signal_data.get('stop_loss_price')
                position_size_val = signal_data.get('position_size')
                hypothetical_tp_price_val = signal_data.get('hypothetical_tp_price')
                signal_timestamp_val = signal_data.get('timestamp') 
                actual_tp_ordered_val = actual_tp_ordered

                cursor.execute("""
                INSERT INTO tracked_signals (
                    signal_id, symbol, direction, poi_key, status, 
                    entry_order_id, entry_signal_price, sl_price, position_size, 
                    hypothetical_tp_price, actual_tp_ordered, signal_timestamp, signal_data, 
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    signal_id, symbol_val, direction_val, poi_key_val, status_val,
                    entry_order_id_val, entry_signal_price_val, sl_price_val, position_size_val,
                    hypothetical_tp_price_val, actual_tp_ordered_val, signal_timestamp_val, signal_data_json,
                    now, now
                ))
                conn.commit()
            self.logger.info(f"Added signal {signal_id} for {symbol_val} with entry order {entry_order_id_val}, signal time {signal_timestamp_val}, hypo TP {hypothetical_tp_price_val}, actual TP ordered {actual_tp_ordered_val} to state DB.")
            return True
        except sqlite3.IntegrityError:
            self.logger.warning(f"Signal ID {signal_id} already exists in the database. Did not add.")
            return False
        except sqlite3.Error as e:
            self.logger.error(f"Database error adding signal {signal_id}: {e}", exc_info=True)
            return False

    def get_signal(self, signal_id: str) -> Optional[Dict[str, Any]]:
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tracked_signals WHERE signal_id = ?", (signal_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            self.logger.error(f"Database error getting signal {signal_id}: {e}", exc_info=True)
            return None
            
    def get_signal_by_order_id(self, order_id: str) -> Optional[Dict[str, Any]]:
         if not order_id: return None
         try:
             with self._get_db_connection() as conn:
                 cursor = conn.cursor()
                 cursor.execute("""
                     SELECT * FROM tracked_signals 
                     WHERE entry_order_id = ? OR sl_order_id = ? OR tp_order_id = ?
                 """, (order_id, order_id, order_id))
                 row = cursor.fetchone()
                 return dict(row) if row else None
         except sqlite3.Error as e:
             self.logger.error(f"Database error getting signal by order_id {order_id}: {e}", exc_info=True)
             return None

    def get_signals_by_status(self, status: str) -> List[Dict[str, Any]]:
        signals = []
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tracked_signals WHERE status = ? ORDER BY created_at ASC", (status,))
                rows = cursor.fetchall()
                signals = [dict(row) for row in rows]
            return signals
        except sqlite3.Error as e:
            self.logger.error(f"Database error getting signals with status {status}: {e}", exc_info=True)
            return []
            
    def get_active_signals_by_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        signals = []
        active_statuses = ('PENDING_ENTRY', 'ENTRY_FILLED', 'POSITION_OPEN')
        status_placeholders = ', '.join('?' * len(active_statuses))
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT * FROM tracked_signals WHERE symbol = ? AND status IN ({status_placeholders})", (symbol,) + active_statuses)
                rows = cursor.fetchall()
                signals = [dict(row) for row in rows]
            return signals
        except sqlite3.Error as e:
            self.logger.error(f"Database error getting active signals for symbol {symbol}: {e}", exc_info=True)
            return []

    def update_signal_status(self, signal_id: str, new_status: str, update_payload: Optional[Dict[str, Any]] = None) -> bool:
        if not signal_id or not new_status:
            self.logger.error("Signal ID or new_status missing for update.")
            return False

        self.logger.info(f"Updating signal {signal_id} to status: {new_status}. Payload: {update_payload}")
        
        fields_to_update = {'status': new_status, 'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        if update_payload:
            for key, value in update_payload.items():
                # Ensure key is a valid column name to prevent SQL injection (basic check)
                # Add 'error_message' to the list of whitelisted keys
                if key in ["entry_fill_price", "sl_order_id", "tp_order_id", "filled_qty", 
                           "closed_price", "closed_by", "hypothetical_tp_price", 
                           "actual_tp_ordered", "tp_price", "sl_price", 
                           "entry_order_id", "position_size", "entry_signal_price", 
                           "signal_data", "poi_key", "error_message"]: 
                    if key == "signal_data" and isinstance(value, dict):
                        fields_to_update[key] = json.dumps(value)
                    else:
                        fields_to_update[key] = value
                else:
                    self.logger.warning(f"Attempted to update non-whitelisted field '{key}' in StateManager. Skipping this field.")

        set_clause_parts = []
        values = []
        for key, value in fields_to_update.items():
            set_clause_parts.append(f"{key} = ?")
            values.append(value)
        
        set_clause = ", ".join(set_clause_parts)
        values.append(signal_id)
        
        sql = f"UPDATE tracked_signals SET {set_clause} WHERE signal_id = ?"
        
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, tuple(values))
                conn.commit()
                if cursor.rowcount == 0:
                    self.logger.warning(f"Attempted to update signal ID {signal_id} but it was not found.")
                    return False
            self.logger.info(f"Signal {signal_id} successfully updated. Status: {new_status}. Data: {update_payload or {}}.")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Database error updating signal {signal_id}: {e}", exc_info=True)
            return False

# Example usage (for standalone testing if needed)
if __name__ == '__main__':
    class MockConfigManager:
        def get_journaling_config(self):
            return {"db_journal_file": "logs/test_statemanager.db"}
        def get(self, key, default=None):
            if key == "database.path": return "logs/test_statemanager.db"
            return default

    class MockLogger:
        def bind(self, name): return self
        def info(self, msg, **kwargs): print(f"INFO: {msg}")
        def error(self, msg, **kwargs): print(f"ERROR: {msg}")
        def warning(self, msg, **kwargs): print(f"WARNING: {msg}")
        def debug(self, msg, **kwargs): print(f"DEBUG: {msg}")

    print("--- Testing StateManager ---")
    mock_config_mgr = MockConfigManager()
    mock_main_logger = MockLogger()
    
    db_file_to_test = Path(mock_config_mgr.get_journaling_config()['db_journal_file'])
    if db_file_to_test.exists():
        db_file_to_test.unlink()

    state_mgr = StateManager(config_manager=mock_config_mgr, main_logger=mock_main_logger)

    sample_ts_now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    sample_signal_data_1 = {
        'timestamp': sample_ts_now, 
        'symbol': 'BTCUSDT', 'direction': 'Buy', 'entry_price': 60000, 
        'stop_loss_price': 59500, 'position_size': 0.01,
        'hypothetical_tp_price': 61000 
    }
    signal_id_1 = state_mgr.generate_signal_id(sample_signal_data_1)
    
    print(f"Generated Signal ID: {signal_id_1}")

    added = state_mgr.add_signal_entry(signal_id_1, sample_signal_data_1, "entry_order_123")
    print(f"Signal 1 added: {added}")

    retrieved_signal = state_mgr.get_signal(signal_id_1)
    print(f"Retrieved Signal 1: {retrieved_signal}")
    if retrieved_signal:
        print(f"  Signal Timestamp from DB: {retrieved_signal.get('signal_timestamp')}")
        print(f"  Hypothetical TP from DB: {retrieved_signal.get('hypothetical_tp_price')}")
        print(f"  DB Record Created At: {retrieved_signal.get('created_at')}")
        try:
            original_data_blob = json.loads(retrieved_signal.get('signal_data', '{}'))
            print(f"  Original 'timestamp' from blob: {original_data_blob.get('timestamp')}")
            print(f"  Original 'hypothetical_tp_price' from blob: {original_data_blob.get('hypothetical_tp_price')}")
        except: pass

    updated = state_mgr.update_signal_status(signal_id_1, "ENTRY_FILLED", {'entry_fill_price': 60001, 'sl_order_id': 'sl_abc'})
    print(f"Signal 1 updated to ENTRY_FILLED: {updated}")
    
    retrieved_signal_updated = state_mgr.get_signal(signal_id_1)
    print(f"Retrieved Updated Signal 1: {retrieved_signal_updated}")

    pending_signals = state_mgr.get_signals_by_status("PENDING_ENTRY")
    print(f"Pending Entry Signals: {pending_signals}")
    
    filled_signals = state_mgr.get_signals_by_status("ENTRY_FILLED")
    print(f"Entry Filled Signals: {filled_signals}")

    active_btc_signals = state_mgr.get_active_signals_by_symbol("BTCUSDT")
    print(f"Active BTCUSDT signals: {active_btc_signals}")

    print("--- StateManager Test Done ---") 