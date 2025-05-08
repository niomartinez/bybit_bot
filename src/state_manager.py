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
        
        # Use the db_journal_uri from config for the state database
        db_path_str = self.journal_config.get("db_journal_uri", "sqlite:///logs/bot_state.db")
        # Ensure the URI starts with sqlite:///
        if not db_path_str.startswith("sqlite:///"):
            self.logger.warning(f"Invalid db_journal_uri format: {db_path_str}. Using default sqlite:///logs/bot_state.db")
            db_path_str = "sqlite:///logs/bot_state.db"
            
        self.db_path = Path(db_path_str[len("sqlite:///"):])
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Using state database: {self.db_path}")
        self._init_db()

    def _get_db_connection(self):
        """Establishes and returns a database connection."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10) # Add timeout
            conn.row_factory = sqlite3.Row # Return rows as dict-like objects
            # Enable Write-Ahead Logging for better concurrency (optional but good practice)
            conn.execute("PRAGMA journal_mode=WAL;") 
            return conn
        except sqlite3.Error as e:
            self.logger.error(f"Database connection error to {self.db_path}: {e}", exc_info=True)
            raise

    def _init_db(self):
        """Initializes the database table if it doesn't exist."""
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracked_signals (
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    poi_key TEXT,  -- e.g., timestamp or hash of POI details
                    status TEXT NOT NULL, -- PENDING_ENTRY, ENTRY_FILLED, POSITION_OPEN, SL_FILLED, TP_FILLED, CANCELLED, ERROR
                    entry_order_id TEXT,
                    sl_order_id TEXT,
                    tp_order_id TEXT, 
                    entry_signal_price REAL,
                    entry_fill_price REAL,
                    sl_price REAL,
                    tp_price REAL, -- Could store primary TP price or JSON of multiple TPs
                    position_size REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)
                # Add indexes for faster lookups
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON tracked_signals (status);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_status ON tracked_signals (symbol, status);")
                conn.commit()
            self.logger.info("Database initialized and 'tracked_signals' table ensured.")
        except sqlite3.Error as e:
            self.logger.error(f"Database initialization error: {e}", exc_info=True)

    def generate_signal_id(self, signal_data: Dict[str, Any]) -> Optional[str]:
        """
        Generates a reasonably unique ID for a signal based on key characteristics.
        Using POI details if available, otherwise falls back to entry details.
        """
        # Use POI details for uniqueness if available
        poi_key_data = {
            'symbol': signal_data.get('symbol'),
            'direction': signal_data.get('direction'),
            'bos': signal_data.get('bos_level_15m'),
            'fvg_low': signal_data.get('fvg_low_15m'),
            'fvg_high': signal_data.get('fvg_high_15m'),
            'fibs': signal_data.get('fib_levels_15m_touched'),
        }
        # Fallback to entry details if POI details are sparse
        # Check if all values *other than* symbol and direction are None or 'N/A'
        if all(v is None or v == 'N/A' for k, v in poi_key_data.items() if k not in ['symbol', 'direction']):
             poi_key_data = {
                'symbol': signal_data.get('symbol'),
                'direction': signal_data.get('direction'),
                'entry': signal_data.get('entry_price'),
                'sl': signal_data.get('stop_loss_price'),
                'timestamp': signal_data.get('timestamp')[:16] # Use timestamp up to minute
             }

        # Create a stable string representation and hash it
        try:
            stable_string = json.dumps(poi_key_data, sort_keys=True)
            return hashlib.sha256(stable_string.encode()).hexdigest()[:16] # Shortened hash
        except Exception as e:
            self.logger.error(f"Error generating signal ID: {e}", exc_info=True)
            return None

    def add_signal_entry(self, signal_id: str, signal_data: Dict[str, Any], entry_order_id: str) -> bool:
        """Adds a new signal to track with its pending entry order."""
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO tracked_signals 
                (signal_id, symbol, direction, poi_key, status, entry_order_id, entry_signal_price, sl_price, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    signal_id,
                    signal_data.get('symbol'),
                    signal_data.get('direction'),
                    self.generate_signal_id(signal_data), # Store the key used for ID generation
                    'PENDING_ENTRY',
                    entry_order_id,
                    signal_data.get('entry_price'),
                    signal_data.get('stop_loss_price'),
                    now,
                    now
                ))
                conn.commit()
            self.logger.info(f"Added signal {signal_id} for {signal_data.get('symbol')} with entry order {entry_order_id} to state DB.")
            return True
        except sqlite3.IntegrityError:
            self.logger.warning(f"Signal ID {signal_id} already exists in the database. Did not add.")
            return False
        except sqlite3.Error as e:
            self.logger.error(f"Database error adding signal {signal_id}: {e}", exc_info=True)
            return False

    def update_signal_status(self, signal_id: str, new_status: str, update_data: Optional[Dict[str, Any]] = None) -> bool:
        """Updates the status and optionally other fields for a tracked signal."""
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        fields_to_update = {'status': new_status, 'updated_at': now_str}
        if update_data:
            fields_to_update.update(update_data)
        
        set_clause = ", ".join([f"{key} = ?" for key in fields_to_update.keys()])
        values = list(fields_to_update.values()) + [signal_id]
        
        sql = f"UPDATE tracked_signals SET {set_clause} WHERE signal_id = ?"
        
        try:
            with self._get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, values)
                conn.commit()
                if cursor.rowcount == 0:
                    self.logger.warning(f"Attempted to update signal ID {signal_id} but it was not found.")
                    return False
            self.logger.info(f"Updated signal {signal_id} status to {new_status}. Update data: {update_data or {}}")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Database error updating signal {signal_id}: {e}", exc_info=True)
            return False

    def get_signal(self, signal_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves the current state of a specific signal."""
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
         """Retrieves the current state of a specific signal by one of its order IDs."""
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
        """Retrieves all signals with a specific status."""
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
        """Retrieves signals for a symbol that are potentially active (pending or open position)."""
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

# --- Example Usage --- #
if __name__ == '__main__':
    # Mock components for testing
    class MockConfigManager:
        def get_journaling_config(self):
            # Use a dedicated test DB
            return {"db_journal_uri": "sqlite:///logs/test_state_manager.db"}

    class MockLogger:
        def bind(self, name):
            print(f"Logger bound to: {name}")
            return self
        def info(self, msg): print(f"INFO: {msg}")
        def error(self, msg): print(f"ERROR: {msg}")
        def warning(self, msg): print(f"WARNING: {msg}")

    print("--- Testing StateManager ---")
    mock_config = MockConfigManager()
    mock_logger = MockLogger()
    
    # Clean up previous test DB if exists
    test_db_path = Path("logs/test_state_manager.db")
    if test_db_path.exists():
        print(f"Removing old test DB: {test_db_path}")
        test_db_path.unlink()

    state_manager = StateManager(config_manager=mock_config, main_logger=mock_logger)

    # Sample signal data
    signal_1 = {
        'symbol': 'BTCUSDT', 'direction': 'LONG', 'entry_price': 60000, 'stop_loss_price': 59500,
        'bos_level_15m': 59800, 'fvg_low_15m': 59600, 'fvg_high_15m': 59700, 'fib_levels_15m_touched': "[0.5]"
    }
    signal_id_1 = state_manager.generate_signal_id(signal_1)
    print(f"Generated Signal ID 1: {signal_id_1}")

    signal_2 = {
        'symbol': 'ETHUSDT', 'direction': 'SHORT', 'entry_price': 3000, 'stop_loss_price': 3050,
        'bos_level_15m': 3010, 'fvg_low_15m': 3020, 'fvg_high_15m': 3040, 'fib_levels_15m_touched': "[0.618]"
    }
    signal_id_2 = state_manager.generate_signal_id(signal_2)
    print(f"Generated Signal ID 2: {signal_id_2}")

    # Test adding signals
    print("\n--- Adding Signals ---")
    state_manager.add_signal_entry(signal_id_1, signal_1, "ORDER_BTC_ENTRY_1")
    state_manager.add_signal_entry(signal_id_2, signal_2, "ORDER_ETH_ENTRY_1")
    # Test adding duplicate
    state_manager.add_signal_entry(signal_id_1, signal_1, "ORDER_BTC_ENTRY_DUPLICATE") 

    # Test getting signals
    print("\n--- Getting Signals ---")
    retrieved_1 = state_manager.get_signal(signal_id_1)
    print(f"Retrieved Signal 1: {retrieved_1}")
    retrieved_nonexistent = state_manager.get_signal("nonexistent_id")
    print(f"Retrieved Nonexistent: {retrieved_nonexistent}")
    retrieved_by_order = state_manager.get_signal_by_order_id("ORDER_ETH_ENTRY_1")
    print(f"Retrieved by Order ID ('ORDER_ETH_ENTRY_1'): {retrieved_by_order}")

    # Test getting by status
    print("\n--- Getting Pending Signals ---")
    pending_signals = state_manager.get_signals_by_status('PENDING_ENTRY')
    print(f"Found {len(pending_signals)} pending signals: {pending_signals}")

    # Test updating status
    print("\n--- Updating Signal 1 ---")
    update_info_1 = {
        'status': 'ENTRY_FILLED',
        'entry_fill_price': 60005.0,
        'position_size': 0.01
    }
    state_manager.update_signal_status(signal_id_1, 'ENTRY_FILLED', update_info_1)
    retrieved_1_updated = state_manager.get_signal(signal_id_1)
    print(f"Retrieved Signal 1 Updated: {retrieved_1_updated}")
    
    # Test updating SL/TP orders
    update_info_sl = {
         'sl_order_id': 'ORDER_BTC_SL_1'
    }
    state_manager.update_signal_status(signal_id_1, 'POSITION_OPEN', update_info_sl)
    retrieved_1_sl_set = state_manager.get_signal(signal_id_1)
    print(f"Retrieved Signal 1 SL Set: {retrieved_1_sl_set}")

    # Test getting active signals by symbol
    print("\n--- Getting Active Signals for BTCUSDT ---")
    active_btc = state_manager.get_active_signals_by_symbol('BTCUSDT')
    print(f"Active BTC signals: {active_btc}")
    
    print("\n--- Getting Active Signals for ETHUSDT ---")
    active_eth = state_manager.get_active_signals_by_symbol('ETHUSDT')
    print(f"Active ETH signals: {active_eth}")

    print("\n--- StateManager Test Done ---") 