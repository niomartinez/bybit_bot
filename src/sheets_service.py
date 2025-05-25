"""
Google Sheets Service for Trade Journaling
Automatically logs all trades to a Google Sheets document for analysis and record-keeping.
"""

import os
import json
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import gspread
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials
from src.config import logger
from src.models import TradeJournalEntry, SheetsConfig

class SheetsService:
    """
    Service for managing Google Sheets trade journal integration.
    
    Features:
    - Automatic trade logging to Google Sheets
    - Real-time trade updates (entry, exit, P&L)
    - Performance analytics and reporting
    - Backup and data integrity
    """
    
    def __init__(self, config: SheetsConfig):
        """Initialize the Google Sheets service."""
        self.config = config
        self.client = None
        self.spreadsheet = None
        self.worksheet = None
        self.is_connected = False
        
        # Trade tracking
        self.active_trades: Dict[str, TradeJournalEntry] = {}
        self.last_sync_time: Optional[datetime] = None
        
        logger.info("SheetsService initialized")
    
    async def initialize(self) -> bool:
        """
        Initialize Google Sheets connection.
        
        Returns:
            bool: True if connection successful
        """
        try:
            # Check if credentials file exists
            if not os.path.exists(self.config.credentials_file):
                logger.error(f"Google Sheets credentials file not found: {self.config.credentials_file}")
                return False
            
            # Load credentials
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            credentials = Credentials.from_service_account_file(
                self.config.credentials_file, 
                scopes=scope
            )
            
            # Initialize gspread client
            self.client = gspread.authorize(credentials)
            
            # Open spreadsheet
            self.spreadsheet = self.client.open_by_key(self.config.spreadsheet_id)
            
            # Get or create worksheet
            try:
                self.worksheet = self.spreadsheet.worksheet(self.config.worksheet_name)
                logger.info(f"Connected to existing worksheet: {self.config.worksheet_name}")
            except gspread.WorksheetNotFound:
                # Create new worksheet
                self.worksheet = self.spreadsheet.add_worksheet(
                    title=self.config.worksheet_name,
                    rows=1000,
                    cols=26  # A-Z columns
                )
                logger.info(f"Created new worksheet: {self.config.worksheet_name}")
                
                # Initialize headers
                await self._initialize_headers()
            
            self.is_connected = True
            self.last_sync_time = datetime.utcnow()
            
            logger.info(f"✅ Google Sheets service connected successfully")
            logger.info(f"📊 Spreadsheet: {self.spreadsheet.title}")
            logger.info(f"📋 Worksheet: {self.config.worksheet_name}")
            
            return True
            
        except GoogleAuthError as e:
            logger.error(f"Google authentication error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error initializing Google Sheets service: {e}")
            return False
    
    async def _initialize_headers(self) -> None:
        """Initialize spreadsheet headers."""
        try:
            headers = [
                "Trade ID", "Symbol", "Strategy", "Priority",
                "Entry Time", "Entry Price", "Side", "Quantity",
                "Exit Time", "Exit Price", "Exit Reason",
                "Stop Loss", "Take Profit", "Risk Amount",
                "P&L USD", "P&L %", "Duration (min)",
                "Session Type", "Market Conditions", "Status",
                "Notes", "Created At", "Updated At"
            ]
            
            # Set headers in row 1
            self.worksheet.update('A1:W1', [headers])
            
            # Format headers (bold)
            self.worksheet.format('A1:W1', {
                'textFormat': {'bold': True},
                'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
            })
            
            logger.info("Initialized Google Sheets headers")
            
        except Exception as e:
            logger.error(f"Error initializing headers: {e}")
    
    async def log_trade_entry(self, trade: TradeJournalEntry) -> bool:
        """
        Log a new trade entry to Google Sheets.
        
        Args:
            trade (TradeJournalEntry): Trade entry to log
            
        Returns:
            bool: True if successful
        """
        if not self.is_connected:
            logger.warning("Google Sheets not connected - cannot log trade entry")
            return False
        
        try:
            # Store in active trades
            self.active_trades[trade.trade_id] = trade
            
            # Prepare row data
            row_data = self._trade_to_row_data(trade)
            
            # Append to spreadsheet
            self.worksheet.append_row(row_data)
            
            logger.info(f"📝 Logged trade entry to Google Sheets: {trade.trade_id} ({trade.symbol} {trade.side})")
            
            return True
            
        except Exception as e:
            logger.error(f"Error logging trade entry to Google Sheets: {e}")
            return False
    
    async def update_trade_exit(self, trade_id: str, exit_data: Dict[str, Any]) -> bool:
        """
        Update trade with exit information.
        
        Args:
            trade_id (str): Trade ID to update
            exit_data (Dict[str, Any]): Exit data (price, time, reason, P&L)
            
        Returns:
            bool: True if successful
        """
        if not self.is_connected:
            logger.warning("Google Sheets not connected - cannot update trade exit")
            return False
        
        try:
            # Find trade in active trades
            if trade_id not in self.active_trades:
                logger.warning(f"Trade {trade_id} not found in active trades")
                return False
            
            trade = self.active_trades[trade_id]
            
            # Update trade with exit data
            trade.exit_time = exit_data.get('exit_time', datetime.utcnow())
            trade.exit_price = exit_data.get('exit_price')
            trade.exit_reason = exit_data.get('exit_reason', 'Manual')
            trade.pnl_usd = exit_data.get('pnl_usd')
            trade.pnl_percentage = exit_data.get('pnl_percentage')
            trade.status = "CLOSED"
            trade.updated_at = datetime.utcnow()
            
            # Calculate duration
            if trade.entry_time and trade.exit_time:
                duration = trade.exit_time - trade.entry_time
                trade.duration_minutes = int(duration.total_seconds() / 60)
            
            # Find row in spreadsheet and update
            row_number = await self._find_trade_row(trade_id)
            if row_number:
                row_data = self._trade_to_row_data(trade)
                range_name = f'A{row_number}:W{row_number}'
                self.worksheet.update(range_name, [row_data])
                
                logger.info(f"📊 Updated trade exit in Google Sheets: {trade_id} (P&L: ${trade.pnl_usd:.2f})")
            
            # Remove from active trades
            del self.active_trades[trade_id]
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating trade exit in Google Sheets: {e}")
            return False
    
    async def _find_trade_row(self, trade_id: str) -> Optional[int]:
        """
        Find the row number for a specific trade ID.
        
        Args:
            trade_id (str): Trade ID to find
            
        Returns:
            Optional[int]: Row number if found
        """
        try:
            # Get all trade IDs from column A
            trade_ids = self.worksheet.col_values(1)  # Column A
            
            for i, cell_trade_id in enumerate(trade_ids):
                if cell_trade_id == trade_id:
                    return i + 1  # gspread uses 1-based indexing
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding trade row: {e}")
            return None
    
    def _trade_to_row_data(self, trade: TradeJournalEntry) -> List[Any]:
        """
        Convert trade entry to spreadsheet row data.
        
        Args:
            trade (TradeJournalEntry): Trade entry
            
        Returns:
            List[Any]: Row data for spreadsheet
        """
        return [
            trade.trade_id,
            trade.symbol,
            trade.strategy,
            trade.priority,
            trade.entry_time.strftime('%Y-%m-%d %H:%M:%S') if trade.entry_time else '',
            trade.entry_price,
            trade.side,
            trade.quantity,
            trade.exit_time.strftime('%Y-%m-%d %H:%M:%S') if trade.exit_time else '',
            trade.exit_price or '',
            trade.exit_reason or '',
            trade.stop_loss or '',
            trade.take_profit or '',
            trade.risk_amount or '',
            trade.pnl_usd or '',
            trade.pnl_percentage or '',
            trade.duration_minutes or '',
            trade.session_type or '',
            trade.market_conditions or '',
            trade.status,
            trade.notes or '',
            trade.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            trade.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        ]
    
    async def get_trade_statistics(self) -> Dict[str, Any]:
        """
        Get trade statistics from Google Sheets.
        
        Returns:
            Dict[str, Any]: Trade statistics
        """
        if not self.is_connected:
            return {"error": "Google Sheets not connected"}
        
        try:
            # Get all data
            all_data = self.worksheet.get_all_records()
            
            if not all_data:
                return {"total_trades": 0, "message": "No trades found"}
            
            # Calculate statistics
            total_trades = len(all_data)
            closed_trades = [trade for trade in all_data if trade.get('Status') == 'CLOSED']
            open_trades = [trade for trade in all_data if trade.get('Status') == 'OPEN']
            
            # P&L calculations
            total_pnl = sum(float(trade.get('P&L USD', 0) or 0) for trade in closed_trades)
            winning_trades = [trade for trade in closed_trades if float(trade.get('P&L USD', 0) or 0) > 0]
            losing_trades = [trade for trade in closed_trades if float(trade.get('P&L USD', 0) or 0) < 0]
            
            win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0
            
            # Strategy breakdown
            strategy_stats = {}
            for trade in all_data:
                strategy = trade.get('Strategy', 'Unknown')
                if strategy not in strategy_stats:
                    strategy_stats[strategy] = {'count': 0, 'pnl': 0}
                strategy_stats[strategy]['count'] += 1
                if trade.get('Status') == 'CLOSED':
                    strategy_stats[strategy]['pnl'] += float(trade.get('P&L USD', 0) or 0)
            
            return {
                "total_trades": total_trades,
                "open_trades": len(open_trades),
                "closed_trades": len(closed_trades),
                "total_pnl": round(total_pnl, 2),
                "win_rate": round(win_rate, 2),
                "winning_trades": len(winning_trades),
                "losing_trades": len(losing_trades),
                "strategy_breakdown": strategy_stats,
                "last_updated": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            logger.error(f"Error getting trade statistics: {e}")
            return {"error": str(e)}
    
    async def backup_trades(self) -> Dict[str, Any]:
        """
        Create a backup of all trades.
        
        Returns:
            Dict[str, Any]: Backup result
        """
        if not self.is_connected:
            return {"success": False, "error": "Google Sheets not connected"}
        
        try:
            # Get all data
            all_data = self.worksheet.get_all_records()
            
            # Create backup filename
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"trade_backup_{timestamp}.json"
            backup_path = os.path.join("documents", backup_filename)
            
            # Ensure documents directory exists
            os.makedirs("documents", exist_ok=True)
            
            # Save backup
            with open(backup_path, 'w') as f:
                json.dump(all_data, f, indent=2, default=str)
            
            logger.info(f"📁 Created trade backup: {backup_filename}")
            
            return {
                "success": True,
                "backup_file": backup_filename,
                "backup_path": backup_path,
                "trades_backed_up": len(all_data),
                "timestamp": timestamp
            }
            
        except Exception as e:
            logger.error(f"Error creating trade backup: {e}")
            return {"success": False, "error": str(e)}
    
    def get_connection_status(self) -> Dict[str, Any]:
        """
        Get Google Sheets connection status.
        
        Returns:
            Dict[str, Any]: Connection status
        """
        return {
            "connected": self.is_connected,
            "spreadsheet_id": self.config.spreadsheet_id if self.is_connected else None,
            "worksheet_name": self.config.worksheet_name,
            "last_sync": self.last_sync_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_sync_time else None,
            "active_trades": len(self.active_trades),
            "credentials_file": self.config.credentials_file
        } 