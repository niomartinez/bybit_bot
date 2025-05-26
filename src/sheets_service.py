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
import time
import traceback

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
    
    async def initialize(self, credentials_dict: Dict[str, Any] = None) -> bool:
        """
        Initialize Google Sheets connection.
        
        Args:
            credentials_dict: Optional credentials dictionary (from env var)
        
        Returns:
            bool: True if connection successful
        """
        try:
            # Load credentials from dict (env var) or file
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            if credentials_dict:
                # Use credentials from environment variable
                logger.info("📄 Using Google credentials from environment variable")
                credentials = Credentials.from_service_account_info(
                    credentials_dict,
                    scopes=scope
                )
            else:
                # Fallback to file (for local development)
                if not os.path.exists(self.config.credentials_file):
                    logger.error(f"Google Sheets credentials file not found: {self.config.credentials_file}")
                    return False
                
                logger.info("📄 Using Google credentials from file")
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
    
    async def log_trade_entry(self, trade_id: str, symbol: str, strategy: str, priority: int,
                            side: str, entry_price: float, quantity: float, 
                            stop_loss: float = None, take_profit: float = None,
                            order_id: str = None, session_type: str = None, 
                            risk_amount: float = None, status: str = "OPEN"):
        """Log a trade entry to Google Sheets."""
        try:
            if not self.client or not self.worksheet:
                logger.error("❌ Sheets service not properly initialized")
                return False
            
            # Create trade entry data
            entry_time = datetime.now(timezone.utc)
            
            trade_entry = TradeJournalEntry(
                trade_id=trade_id,
                symbol=symbol,
                strategy=strategy,
                priority=priority,
                entry_time=entry_time,
                side=side.upper(),
                entry_price=entry_price,
                quantity=quantity,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_amount=risk_amount,
                session_type=session_type,
                status=status
            )
            
            # Store in active trades for exit tracking (including PENDING orders)
            self.active_trades[trade_id] = trade_entry
            
            # Add to worksheet using the column mapping
            row_data = [
                trade_entry.trade_id,
                trade_entry.symbol,
                trade_entry.strategy,
                trade_entry.priority,
                trade_entry.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                trade_entry.entry_price,
                trade_entry.side,
                trade_entry.quantity,
                "", # Exit time (empty for new entry)
                "", # Exit price (empty for new entry)
                "", # Exit reason (empty for new entry)
                trade_entry.stop_loss or "",
                trade_entry.take_profit or "",
                trade_entry.risk_amount or "",
                "", # PnL USD (empty for new entry)
                "", # PnL % (empty for new entry)
                "", # Duration (empty for new entry)
                trade_entry.session_type or "",
                "", # Market conditions (empty for now)
                trade_entry.status,
                "", # Notes (empty for now)
                trade_entry.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                trade_entry.updated_at.strftime("%Y-%m-%d %H:%M:%S")
            ]
            
            self.worksheet.append_row(row_data)
            logger.info(f"✅ Trade entry logged to sheets: {symbol} {side} @ {entry_price} (Status: {status})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error logging trade entry: {e}")
            logger.error(f"Error details: {traceback.format_exc()}")
            return False
    
    async def log_trade_exit(self, trade_id: str, exit_price: float, exit_time: float = None,
                           exit_reason: str = None, quantity: float = None, pnl: float = None):
        """Log a trade exit to Google Sheets."""
        try:
            if not self.client or not self.worksheet:
                logger.error("❌ Sheets service not properly initialized")
                return False
            
            # Get the trade entry from active trades
            if trade_id not in self.active_trades:
                logger.warning(f"⚠️ Trade ID {trade_id} not found in active trades")
                return False
            
            trade_entry = self.active_trades[trade_id]
            
            # Update trade entry with exit information
            exit_datetime = datetime.fromtimestamp(exit_time or time.time(), tz=timezone.utc) if exit_time else datetime.now(timezone.utc)
            trade_entry.exit_time = exit_datetime
            trade_entry.exit_price = exit_price
            trade_entry.exit_reason = exit_reason or "Unknown"
            trade_entry.status = "CLOSED"
            
            # Calculate PnL if not provided
            if pnl is None and exit_price > 0:
                entry_price = trade_entry.entry_price
                qty = quantity or trade_entry.quantity
                
                if trade_entry.side.upper() == "LONG":
                    pnl = (exit_price - entry_price) * qty
                else:
                    pnl = (entry_price - exit_price) * qty
            
            trade_entry.pnl_usd = pnl
            
            # Calculate duration in minutes
            if trade_entry.entry_time and trade_entry.exit_time:
                duration = (trade_entry.exit_time - trade_entry.entry_time).total_seconds() / 60
                trade_entry.duration_minutes = int(duration)
            
            # Calculate PnL percentage
            if pnl and trade_entry.risk_amount:
                trade_entry.pnl_percentage = (pnl / trade_entry.risk_amount) * 100
            
            trade_entry.updated_at = datetime.now(timezone.utc)
            
            # Find the row in the spreadsheet for this trade
            all_values = self.worksheet.get_all_values()
            row_to_update = None
            
            for i, row in enumerate(all_values):
                if len(row) > 0 and row[0] == trade_id:  # Trade ID is in column A
                    row_to_update = i + 1  # Sheets is 1-indexed
                    break
            
            if row_to_update:
                # Update the specific cells for exit information
                # Using the column mapping from SheetsConfig
                updates = [
                    ('I', trade_entry.exit_time.strftime("%Y-%m-%d %H:%M:%S")),  # Exit time
                    ('J', str(exit_price)),  # Exit price
                    ('K', trade_entry.exit_reason),  # Exit reason
                    ('O', str(pnl or 0)),  # PnL USD
                    ('P', str(trade_entry.pnl_percentage or 0)),  # PnL %
                    ('Q', str(trade_entry.duration_minutes or 0)),  # Duration
                    ('T', 'CLOSED'),  # Status
                    ('W', trade_entry.updated_at.strftime("%Y-%m-%d %H:%M:%S"))  # Updated at
                ]
                
                # Batch update all exit fields
                for col, value in updates:
                    self.worksheet.update(f'{col}{row_to_update}', value)
                
                logger.info(f"✅ Trade exit logged to sheets: {trade_entry.symbol} @ {exit_price} (PnL: ${pnl:.2f})")
                
                # Remove from active trades
                del self.active_trades[trade_id]
                return True
            else:
                logger.error(f"❌ Could not find row for trade ID {trade_id} in spreadsheet")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error logging trade exit: {e}")
            logger.error(f"Error details: {traceback.format_exc()}")
            return False
    
    async def get_status(self):
        """Get the status of the Google Sheets service."""
        try:
            status = {
                "connected": self.is_connected,
                "spreadsheet_id": self.config.spreadsheet_id,
                "worksheet_name": self.config.worksheet_name,
                "last_update": None,
                "total_trades": 0
            }
            
            if self.worksheet:
                try:
                    # Get basic info about the sheet
                    all_values = self.worksheet.get_all_values()
                    status["total_trades"] = len(all_values) - 1  # Subtract header row
                    status["last_update"] = datetime.now(timezone.utc).isoformat()
                except Exception as e:
                    logger.warning(f"Could not get sheet details: {e}")
            
            return status
            
        except Exception as e:
            logger.error(f"❌ Error getting sheets status: {e}")
            return {"connected": False, "error": str(e)}
    
    async def test_connection(self):
        """Test the Google Sheets connection."""
        try:
            if not self.client:
                return {"success": False, "message": "Not authenticated"}
            
            if not self.worksheet:
                return {"success": False, "message": "Worksheet not accessible"}
            
            # Try to read the first cell
            test_value = self.worksheet.cell(1, 1).value
            
            # Try to get sheet info
            sheet_info = {
                "title": self.worksheet.title,
                "row_count": self.worksheet.row_count,
                "col_count": self.worksheet.col_count,
                "test_read": test_value
            }
            
            return {
                "success": True,
                "message": "Connection successful",
                "sheet_info": sheet_info
            }
            
        except Exception as e:
            logger.error(f"❌ Sheets connection test failed: {e}")
            return {"success": False, "message": str(e)}
    
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
    
    async def update_trade_status(self, trade_id: str, new_status: str, fill_price: float = None, fill_time: float = None) -> bool:
        """
        Update the status of an existing trade.
        
        Args:
            trade_id: Trade/Position ID to update
            new_status: New status (PENDING, ACTIVE, CLOSED, CANCELLED)
            fill_price: Actual fill price (if different from original entry price)
            fill_time: Time when order was filled
            
        Returns:
            bool: True if successful
        """
        try:
            if not self.client or not self.worksheet:
                logger.error("❌ Sheets service not properly initialized")
                return False
            
            # Get the trade entry from active trades
            if trade_id not in self.active_trades:
                logger.warning(f"⚠️ Trade ID {trade_id} not found in active trades")
                return False
            
            trade_entry = self.active_trades[trade_id]
            
            # Update trade entry with new status
            trade_entry.status = new_status
            trade_entry.updated_at = datetime.now(timezone.utc)
            
            # If transitioning to ACTIVE, update entry price if provided
            if new_status == "ACTIVE" and fill_price is not None:
                trade_entry.entry_price = fill_price
                if fill_time:
                    trade_entry.entry_time = datetime.fromtimestamp(fill_time, tz=timezone.utc)
            
            # Find the row in the spreadsheet for this trade
            all_values = self.worksheet.get_all_values()
            row_to_update = None
            
            for i, row in enumerate(all_values):
                if len(row) > 0 and row[0] == trade_id:  # Trade ID is in column A
                    row_to_update = i + 1  # Sheets is 1-indexed
                    break
            
            if row_to_update:
                # Update the status and related fields
                updates = [
                    ('T', new_status),  # Status
                    ('W', trade_entry.updated_at.strftime("%Y-%m-%d %H:%M:%S"))  # Updated at
                ]
                
                # If updating to ACTIVE with new fill price/time
                if new_status == "ACTIVE" and fill_price is not None:
                    updates.extend([
                        ('E', trade_entry.entry_time.strftime("%Y-%m-%d %H:%M:%S")),  # Entry time
                        ('F', str(fill_price))  # Entry price
                    ])
                
                # Batch update all fields
                for col, value in updates:
                    self.worksheet.update(f'{col}{row_to_update}', value)
                
                logger.info(f"✅ Trade status updated: {trade_entry.symbol} {trade_id} → {new_status}")
                return True
            else:
                logger.error(f"❌ Could not find row for trade ID {trade_id} in spreadsheet")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error updating trade status: {e}")
            logger.error(f"Error details: {traceback.format_exc()}")
            return False
    
    async def remove_cancelled_trade(self, trade_id: str) -> bool:
        """
        Remove a cancelled trade from tracking and optionally from the spreadsheet.
        
        Args:
            trade_id: Trade/Position ID to remove
            
        Returns:
            bool: True if successful
        """
        try:
            if not self.client or not self.worksheet:
                logger.error("❌ Sheets service not properly initialized")
                return False
            
            # Remove from active trades tracking
            if trade_id in self.active_trades:
                trade_entry = self.active_trades[trade_id]
                logger.info(f"🗑️ Removing cancelled trade: {trade_entry.symbol} {trade_id}")
                del self.active_trades[trade_id]
            
            # Find and remove the row from the spreadsheet
            all_values = self.worksheet.get_all_values()
            row_to_delete = None
            
            for i, row in enumerate(all_values):
                if len(row) > 0 and row[0] == trade_id:  # Trade ID is in column A
                    row_to_delete = i + 1  # Sheets is 1-indexed
                    break
            
            if row_to_delete:
                # Delete the row
                self.worksheet.delete_rows(row_to_delete)
                logger.info(f"✅ Removed cancelled trade from spreadsheet: {trade_id}")
                return True
            else:
                logger.warning(f"⚠️ Could not find row for trade ID {trade_id} in spreadsheet")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error removing cancelled trade: {e}")
            logger.error(f"Error details: {traceback.format_exc()}")
            return False 