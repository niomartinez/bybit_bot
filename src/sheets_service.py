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
            
            # Validate trade_entry has required attributes
            if not hasattr(trade_entry, 'symbol') or not hasattr(trade_entry, 'side'):
                logger.error(f"❌ Invalid trade entry for {trade_id}: missing required attributes")
                return False
            
            # Validate exit_price (allow 0 for position closure detection)
            if not isinstance(exit_price, (int, float)) or exit_price < 0:
                logger.error(f"❌ Invalid exit price for {trade_id}: {exit_price}")
                return False
            
            # Special handling for exit_price = 0 (position closure without exit order found)
            if exit_price == 0:
                logger.warning(f"⚠️ Exit price is 0 for {trade_id} - using position closure detection")
                # Try to get a reasonable exit price from the position or use entry price as fallback
                if hasattr(trade_entry, 'entry_price') and trade_entry.entry_price > 0:
                    exit_price = trade_entry.entry_price  # Neutral exit for unknown price
                    logger.info(f"Using entry price as exit price fallback: {exit_price}")
            
            # Update trade entry with exit information
            exit_datetime = datetime.fromtimestamp(exit_time or time.time(), tz=timezone.utc) if exit_time else datetime.now(timezone.utc)
            trade_entry.exit_time = exit_datetime
            trade_entry.exit_price = exit_price
            trade_entry.exit_reason = exit_reason or "Unknown"
            trade_entry.status = "CLOSED"
            
            # Calculate PnL if not provided
            if pnl is None and exit_price > 0:
                try:
                    entry_price = trade_entry.entry_price or 0
                    qty = quantity or trade_entry.quantity or 0
                    
                    if trade_entry.side.upper() == "LONG":
                        pnl = (exit_price - entry_price) * qty
                    else:
                        pnl = (entry_price - exit_price) * qty
                        
                    # Ensure pnl is a valid number
                    if not isinstance(pnl, (int, float)) or not abs(pnl) < float('inf'):
                        pnl = 0
                        
                except Exception as e:
                    logger.warning(f"⚠️ Error calculating PnL for {trade_id}: {e}")
                    pnl = 0
            
            # Ensure pnl is never None
            pnl = pnl if pnl is not None else 0
            trade_entry.pnl_usd = pnl
            
            # Calculate duration in minutes
            if trade_entry.entry_time and trade_entry.exit_time:
                try:
                    duration = (trade_entry.exit_time - trade_entry.entry_time).total_seconds() / 60
                    trade_entry.duration_minutes = int(duration) if duration >= 0 else 0
                except Exception as e:
                    logger.warning(f"⚠️ Error calculating duration for {trade_id}: {e}")
                    trade_entry.duration_minutes = 0
            
            # Calculate PnL percentage
            try:
                trade_entry.pnl_percentage = 0
                if pnl and pnl != 0:
                    # Method 1: Use risk amount if available (preferred)
                    if trade_entry.risk_amount and trade_entry.risk_amount > 0:
                        trade_entry.pnl_percentage = (pnl / trade_entry.risk_amount) * 100
                    # Method 2: Calculate based on position value
                    elif trade_entry.entry_price and trade_entry.quantity:
                        position_value = trade_entry.entry_price * trade_entry.quantity
                        if position_value > 0:
                            trade_entry.pnl_percentage = (pnl / position_value) * 100
                    # Method 3: Calculate based on entry price percentage
                    elif trade_entry.entry_price and trade_entry.entry_price > 0:
                        price_change_pct = (pnl / trade_entry.quantity) / trade_entry.entry_price * 100 if trade_entry.quantity > 0 else 0
                        trade_entry.pnl_percentage = price_change_pct
                        
                logger.debug(f"P&L calculation for {trade_id}: ${pnl:.2f} ({trade_entry.pnl_percentage:.2f}%)")
            except Exception as e:
                logger.warning(f"⚠️ Error calculating PnL percentage for {trade_id}: {e}")
                trade_entry.pnl_percentage = 0
            
            trade_entry.updated_at = datetime.now(timezone.utc)
            
            # Find the row in the spreadsheet for this trade
            all_values = self.worksheet.get_all_values()
            row_to_update = None
            
            for i, row in enumerate(all_values):
                if len(row) > 0 and row[0] == trade_id:  # Trade ID is in column A
                    row_to_update = i + 1  # Sheets is 1-indexed
                    break
            
            if row_to_update:
                # Prepare values ensuring they're all valid for Google Sheets
                exit_time_str = trade_entry.exit_time.strftime("%Y-%m-%d %H:%M:%S") if trade_entry.exit_time else ""
                exit_price_str = str(exit_price) if exit_price is not None else ""
                exit_reason_str = str(trade_entry.exit_reason) if trade_entry.exit_reason is not None else "Unknown"
                pnl_str = f"{pnl:.2f}" if pnl is not None else "0"
                pnl_pct_str = f"{trade_entry.pnl_percentage:.2f}" if trade_entry.pnl_percentage is not None else "0"
                duration_str = str(trade_entry.duration_minutes) if trade_entry.duration_minutes is not None else "0"
                updated_str = trade_entry.updated_at.strftime("%Y-%m-%d %H:%M:%S") if trade_entry.updated_at else ""
                
                # Preserve original SL/TP values from trade entry
                sl_str = str(trade_entry.stop_loss) if trade_entry.stop_loss is not None else ""
                tp_str = str(trade_entry.take_profit) if trade_entry.take_profit is not None else ""
                risk_amount_str = str(trade_entry.risk_amount) if trade_entry.risk_amount is not None else ""
                session_type_str = str(trade_entry.session_type) if trade_entry.session_type is not None else ""
                
                # Use batch update with proper range for better reliability
                range_name = f'I{row_to_update}:W{row_to_update}'
                values = [
                    exit_time_str,     # I - Exit time
                    exit_price_str,    # J - Exit price
                    exit_reason_str,   # K - Exit reason
                    sl_str,           # L - Stop Loss (preserve original)
                    tp_str,           # M - Take Profit (preserve original)
                    risk_amount_str,  # N - Risk Amount (preserve original)
                    pnl_str,          # O - PnL USD
                    pnl_pct_str,      # P - PnL %
                    duration_str,     # Q - Duration
                    session_type_str, # R - Session Type (preserve original)
                    "",               # S - Market Conditions (empty for now)
                    "CLOSED",         # T - Status
                    "",               # U - Notes (empty for now)
                    "",               # V - Created At (preserve original, don't update)
                    updated_str       # W - Updated at
                ]
                
                # Batch update all exit fields at once
                self.worksheet.update(range_name, [values])
                
                pnl_display = f"${pnl:.2f}" if pnl is not None else "$0.00"
                logger.info(f"✅ Trade exit logged to sheets: {trade_entry.symbol} @ {exit_price} (PnL: {pnl_display})")
                
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
                # Prepare values ensuring they're all valid for Google Sheets
                status_str = str(new_status) if new_status is not None else "PENDING"
                updated_str = trade_entry.updated_at.strftime("%Y-%m-%d %H:%M:%S") if trade_entry.updated_at else ""
                
                # First update the status and updated_at fields
                status_range = f'T{row_to_update}:W{row_to_update}'
                status_values = [status_str, "", "", updated_str]  # T, U, V, W
                self.worksheet.update(status_range, [status_values])
                
                # If updating to ACTIVE with new fill price/time, update entry fields
                if new_status == "ACTIVE" and fill_price is not None:
                    entry_time_str = trade_entry.entry_time.strftime("%Y-%m-%d %H:%M:%S") if trade_entry.entry_time else ""
                    fill_price_str = str(fill_price) if fill_price is not None else ""
                    
                    entry_range = f'E{row_to_update}:F{row_to_update}'
                    entry_values = [entry_time_str, fill_price_str]  # E, F
                    self.worksheet.update(entry_range, [entry_values])
                
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