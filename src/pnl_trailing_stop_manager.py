"""
PnL-based Trailing Stop Manager for automatically setting stop losses to break-even 
when positions reach a specified PnL threshold (e.g., 50% profit).
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Set, Optional, Any
from src.config import logger, config
from src.bybit_service import BybitService


class PnLTrailingStopManager:
    """
    Manages PnL-based trailing stops for open positions.
    
    When a position reaches the configured PnL threshold (default 50%), 
    automatically sets the stop loss to break-even (entry price).
    """
    
    def __init__(self, bybit_service: BybitService):
        """Initialize the PnL trailing stop manager."""
        self.bybit_service = bybit_service
        self.config = config.pnl_trailing_stop
        
        # Track positions that have already been adjusted to avoid multiple adjustments
        self.adjusted_positions: Set[str] = set()
        
        # Track position creation times to respect minimum age requirement
        self.position_creation_times: Dict[str, datetime] = {}
        
        # Status tracking
        self.monitoring_active = False
        self.last_check_time: Optional[datetime] = None
        
        logger.info(f"PnL Trailing Stop Manager initialized - Threshold: {self.config.pnl_threshold_percentage}%")
        logger.info(f"Configuration: {self.config.dict()}")
    
    async def start_monitoring(self):
        """Start the PnL monitoring background task."""
        if not self.config.enabled:
            logger.info("💤 PnL trailing stop monitoring is disabled in configuration")
            return
        
        if self.monitoring_active:
            logger.warning("⚠️ PnL monitoring is already active")
            return
        
        logger.info(f"🎯 Starting PnL trailing stop monitoring (threshold: {self.config.pnl_threshold_percentage}%, interval: {self.config.monitoring_interval_seconds}s)")
        self.monitoring_active = True
        
        while self.monitoring_active:
            try:
                await self._monitor_positions()
                await asyncio.sleep(self.config.monitoring_interval_seconds)
                
            except Exception as e:
                logger.error(f"❌ Error in PnL monitoring: {e}")
                await asyncio.sleep(self.config.monitoring_interval_seconds)
    
    def stop_monitoring(self):
        """Stop the PnL monitoring."""
        logger.info("🛑 Stopping PnL trailing stop monitoring")
        self.monitoring_active = False
    
    async def _monitor_positions(self):
        """Monitor all active positions for PnL threshold breaches."""
        try:
            # Get all active positions
            positions = await self.bybit_service.get_all_positions()
            
            if not positions:
                logger.debug("No active positions to monitor")
                return
            
            self.last_check_time = datetime.now(timezone.utc)
            
            # Track which positions we see in this check
            current_positions = set(positions.keys())
            
            # Clean up tracking for positions that no longer exist
            self._cleanup_closed_positions(current_positions)
            
            # Check each position
            for symbol, position_data in positions.items():
                await self._check_position_for_trailing_stop(symbol, position_data)
                
        except Exception as e:
            logger.error(f"Error monitoring positions: {e}")
    
    def _cleanup_closed_positions(self, current_positions: Set[str]):
        """Remove tracking data for closed positions."""
        # Clean up adjusted positions tracking
        closed_positions = self.adjusted_positions - current_positions
        for symbol in closed_positions:
            self.adjusted_positions.discard(symbol)
            logger.debug(f"Cleaned up tracking for closed position: {symbol}")
        
        # Clean up position creation times
        closed_creation_times = set(self.position_creation_times.keys()) - current_positions
        for symbol in closed_creation_times:
            del self.position_creation_times[symbol]
            logger.debug(f"Cleaned up creation time tracking for: {symbol}")
    
    async def _check_position_for_trailing_stop(self, symbol: str, position_data: Dict[str, Any]):
        """Check a single position for PnL threshold and apply trailing stop if needed."""
        try:
            # Skip if already adjusted
            if symbol in self.adjusted_positions:
                logger.debug(f"Position {symbol} already adjusted, skipping")
                return
            
            # Track position creation time if not already tracked
            if symbol not in self.position_creation_times:
                self.position_creation_times[symbol] = datetime.now(timezone.utc)
                logger.debug(f"Started tracking position creation time for {symbol}")
            
            # Check minimum position age
            position_age = datetime.now(timezone.utc) - self.position_creation_times[symbol]
            min_age_delta = timedelta(minutes=self.config.min_position_age_minutes)
            
            if position_age < min_age_delta:
                logger.debug(f"Position {symbol} too young ({position_age.total_seconds():.0f}s < {min_age_delta.total_seconds():.0f}s)")
                return
            
            # Calculate current PnL percentage
            pnl_percentage = await self.bybit_service.get_position_pnl_percentage(symbol)
            
            if pnl_percentage is None:
                logger.debug(f"Could not calculate PnL percentage for {symbol}")
                return
            
            # Check if PnL threshold is reached
            if pnl_percentage >= self.config.pnl_threshold_percentage:
                logger.info(f"🎯 PnL threshold reached for {symbol}: {pnl_percentage:.2f}% >= {self.config.pnl_threshold_percentage}%")
                
                # Get position details for stop loss calculation
                success = await self._apply_trailing_stop(symbol, position_data, pnl_percentage)
                
                if success:
                    # Mark this position as adjusted
                    self.adjusted_positions.add(symbol)
                    logger.info(f"✅ Applied trailing stop for {symbol} - marked as adjusted")
                else:
                    logger.warning(f"⚠️ Failed to apply trailing stop for {symbol}")
            else:
                logger.debug(f"Position {symbol}: PnL {pnl_percentage:.2f}% < threshold {self.config.pnl_threshold_percentage}%")
                
        except Exception as e:
            logger.error(f"Error checking position {symbol} for trailing stop: {e}")
    
    async def _apply_trailing_stop(self, symbol: str, position_data: Dict[str, Any], current_pnl_pct: float) -> bool:
        """Apply trailing stop (set stop loss to break-even) for a position."""
        try:
            # Get position details
            raw_position = position_data.get('raw_position', {})
            entry_price = float(raw_position.get('avgPrice', 0))
            side = position_data.get('side', '').lower()
            size = float(position_data.get('size', 0))
            
            if entry_price <= 0:
                logger.error(f"Invalid entry price for {symbol}: {entry_price}")
                return False
            
            if size == 0:
                logger.error(f"Invalid position size for {symbol}: {size}")
                return False
            
            # Calculate break-even stop loss price
            break_even_price = entry_price + self.config.break_even_offset
            
            # Calculate stop loss based on position side
            if side == 'short':
                # For short positions, stop loss should be ABOVE entry price to protect against upward price movement
                stop_loss_price = entry_price + self.config.break_even_offset
            else:
                # For long positions, stop loss should be BELOW entry price to protect against downward price movement
                stop_loss_price = entry_price - self.config.break_even_offset
            
            # Ensure the stop loss makes sense given current profitability
            # If we're profitable, stop loss should protect the profit
            current_price = float(raw_position.get('markPrice', entry_price))
            
            # For break-even protection, adjust the stop loss to entry price level
            if side == 'long':
                # Long position break-even: stop loss at entry price (with small offset if configured)
                stop_loss_price = entry_price - abs(self.config.break_even_offset)  # Slightly below entry for safety
                logger.debug(f"Long position {symbol}: setting SL below entry at {stop_loss_price}")
            else:
                # Short position break-even: stop loss at entry price (with small offset if configured)  
                stop_loss_price = entry_price + abs(self.config.break_even_offset)  # Slightly above entry for safety
                logger.debug(f"Short position {symbol}: setting SL above entry at {stop_loss_price}")
            
            logger.info(f"💰 Setting break-even stop loss for {symbol}:")
            logger.info(f"   Side: {side.upper()}")
            logger.info(f"   Entry Price: ${entry_price:.4f}")
            logger.info(f"   Current Price: ${current_price:.4f}")
            logger.info(f"   PnL: {current_pnl_pct:.2f}%")
            logger.info(f"   Stop Loss: ${stop_loss_price:.4f}")
            
            # Apply the stop loss using the trading stop API
            result = await self.bybit_service.set_trading_stop(
                symbol=symbol,
                stop_loss=stop_loss_price,
                sl_trigger_by=self.config.trigger_price_type
            )
            
            if result.get('success', False):
                logger.info(f"✅ Successfully set break-even stop loss for {symbol} at ${stop_loss_price:.4f}")
                
                # Optional: Log to journaling system if available
                try:
                    from src.main import sheets_service
                    if sheets_service:
                        # Add a note to the trade journal about the trailing stop activation
                        note = f"PnL Trailing Stop activated at {current_pnl_pct:.2f}% profit - SL set to break-even at ${stop_loss_price:.4f}"
                        # This would require a method to add notes to existing trades
                        # sheets_service.add_trade_note(symbol, note)
                        logger.debug(f"Note for journal: {note}")
                except Exception as journal_error:
                    logger.debug(f"Could not log trailing stop to journal: {journal_error}")
                
                return True
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"❌ Failed to set stop loss for {symbol}: {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying trailing stop for {symbol}: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the PnL trailing stop manager."""
        return {
            "enabled": self.config.enabled,
            "monitoring_active": self.monitoring_active,
            "pnl_threshold_percentage": self.config.pnl_threshold_percentage,
            "break_even_offset": self.config.break_even_offset,
            "monitoring_interval_seconds": self.config.monitoring_interval_seconds,
            "adjusted_positions_count": len(self.adjusted_positions),
            "adjusted_positions": list(self.adjusted_positions),
            "tracked_positions_count": len(self.position_creation_times),
            "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None
        }
    
    def reset_position_tracking(self, symbol: Optional[str] = None):
        """Reset tracking for a specific position or all positions."""
        if symbol:
            self.adjusted_positions.discard(symbol)
            self.position_creation_times.pop(symbol, None)
            logger.info(f"Reset tracking for position: {symbol}")
        else:
            self.adjusted_positions.clear()
            self.position_creation_times.clear()
            logger.info("Reset tracking for all positions") 