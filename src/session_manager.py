"""
Silver Bullet Session Manager for tracking trading sessions and managing order cancellations.
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from src.config import logger
from src.bybit_service import BybitService

# NYC timezone with proper DST handling
try:
    import zoneinfo
    NYC_TZ = zoneinfo.ZoneInfo("America/New_York")
except ImportError:
    # Fallback for Python < 3.9 or systems without zoneinfo
    try:
        import pytz
        NYC_TZ = pytz.timezone("America/New_York")
    except ImportError:
        # Final fallback - use current time offset estimation
        # This is less accurate but works as a last resort
        import time
        # Estimate current offset based on system
        if time.daylight and time.localtime().tm_isdst:
            # Currently in DST, NYC is likely EDT (UTC-4)
            NYC_TZ = timezone(timedelta(hours=-4))  # EDT (UTC-4)
        else:
            # Currently not in DST, NYC is likely EST (UTC-5)  
            NYC_TZ = timezone(timedelta(hours=-5))  # EST (UTC-5)
        logger.warning("Using fallback timezone estimation. Install zoneinfo or pytz for accurate DST handling.")

class SilverBulletSessionManager:
    """
    Manages Silver Bullet trading sessions and handles session-based order cancellations.
    
    Silver Bullet Sessions (NYC time):
    - 03:00-04:00 AM (London Open)
    - 10:00-11:00 AM (AM Session) 
    - 14:00-15:00 PM (PM Session)
    
    Cancellation happens 5 minutes after each session ends:
    - 04:05 AM
    - 11:05 AM  
    - 15:05 PM
    """
    
    def __init__(self, bybit_service: BybitService):
        """Initialize the session manager."""
        self.bybit_service = bybit_service
        self.session_definitions = [
            {
                "name": "London Open",
                "start_hour": 3,
                "start_minute": 0,
                "end_hour": 4,
                "end_minute": 0,
                "cancel_hour": 4,
                "cancel_minute": 5
            },
            {
                "name": "AM Session", 
                "start_hour": 10,
                "start_minute": 0,
                "end_hour": 11,
                "end_minute": 0,
                "cancel_hour": 11,
                "cancel_minute": 5
            },
            {
                "name": "PM Session",
                "start_hour": 14,
                "start_minute": 0, 
                "end_hour": 15,
                "end_minute": 0,
                "cancel_hour": 15,
                "cancel_minute": 5
            }
        ]
        
        # Track session states
        self.current_session: Optional[Dict[str, Any]] = None
        self.last_check_time: Optional[datetime] = None
        self.pending_cancellations: List[str] = []  # Track symbols with pending cancellations
        
        logger.info("SilverBulletSessionManager initialized")
    
    def get_nyc_time(self) -> datetime:
        """
        Get current time in NYC timezone.
        
        Returns:
            datetime: Current NYC time
        """
        return datetime.now(NYC_TZ)
    
    def is_in_session(self, nyc_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Check if we're currently in a Silver Bullet session.
        
        Args:
            nyc_time (Optional[datetime]): NYC time to check (defaults to current time)
        
        Returns:
            Dict[str, Any]: Session status information
        """
        if nyc_time is None:
            nyc_time = self.get_nyc_time()
        
        current_hour = nyc_time.hour
        current_minute = nyc_time.minute
        
        for session in self.session_definitions:
            start_hour = session["start_hour"]
            start_minute = session["start_minute"]
            end_hour = session["end_hour"]
            end_minute = session["end_minute"]
            
            # Check if current time is within session
            start_total_minutes = start_hour * 60 + start_minute
            end_total_minutes = end_hour * 60 + end_minute
            current_total_minutes = current_hour * 60 + current_minute
            
            if start_total_minutes <= current_total_minutes < end_total_minutes:
                return {
                    "in_session": True,
                    "session": session,
                    "session_name": session["name"],
                    "nyc_time": nyc_time
                }
        
        return {
            "in_session": False,
            "session": None,
            "session_name": None,
            "nyc_time": nyc_time
        }
    
    def should_cancel_orders(self, nyc_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Check if we should cancel orders (5 minutes after session ends).
        
        Args:
            nyc_time (Optional[datetime]): NYC time to check (defaults to current time)
        
        Returns:
            Dict[str, Any]: Cancellation status information
        """
        if nyc_time is None:
            nyc_time = self.get_nyc_time()
        
        current_hour = nyc_time.hour
        current_minute = nyc_time.minute
        
        for session in self.session_definitions:
            cancel_hour = session["cancel_hour"]
            cancel_minute = session["cancel_minute"]
            
            # Check if we're exactly at the cancellation time (within 1 minute window)
            if (current_hour == cancel_hour and 
                cancel_minute <= current_minute < cancel_minute + 1):
                return {
                    "should_cancel": True,
                    "session": session,
                    "session_name": session["name"],
                    "cancel_time": f"{cancel_hour:02d}:{cancel_minute:02d}",
                    "nyc_time": nyc_time
                }
        
        return {
            "should_cancel": False,
            "session": None,
            "session_name": None,
            "cancel_time": None,
            "nyc_time": nyc_time
        }
    
    async def get_silver_bullet_orders_for_cancellation(self) -> List[Dict[str, Any]]:
        """
        Get all Silver Bullet strategy orders that should be cancelled.
        
        Returns:
            List[Dict[str, Any]]: List of orders to cancel
        """
        orders_to_cancel = []
        
        try:
            # Get all active symbols that might have SB orders
            # For now, we'll check common crypto symbols, but this could be enhanced
            # to track symbols dynamically based on order history
            common_symbols = [
                "BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "DOTUSDT", 
                "LINKUSDT", "AVAXUSDT", "MATICUSDT", "ATOMUSDT", "NEARUSDT"
            ]
            
            logger.info(f"Checking {len(common_symbols)} symbols for Silver Bullet orders to cancel")
            
            for symbol in common_symbols:
                try:
                    # Get existing orders for this symbol
                    existing_orders = await self.bybit_service.get_existing_orders(symbol)
                    
                    for order in existing_orders:
                        order_link_id = order.get('clientOrderId', order.get('info', {}).get('orderLinkId', ''))
                        
                        # Check if this is a Silver Bullet order
                        if self._is_silver_bullet_order(order_link_id):
                            orders_to_cancel.append({
                                'symbol': symbol,
                                'order_id': order.get('id'),
                                'order_link_id': order_link_id,
                                'side': order.get('side', ''),
                                'amount': order.get('amount', 0),
                                'order': order
                            })
                            logger.info(f"Found Silver Bullet order to cancel: {order_link_id} ({symbol})")
                
                except Exception as e:
                    logger.warning(f"Error checking orders for {symbol}: {e}")
                    continue
            
            logger.info(f"Found {len(orders_to_cancel)} Silver Bullet orders to cancel")
            return orders_to_cancel
        
        except Exception as e:
            logger.error(f"Error getting Silver Bullet orders for cancellation: {e}")
            return []
    
    def _is_silver_bullet_order(self, order_link_id: str) -> bool:
        """
        Check if an order is a Silver Bullet strategy order that should be cancelled.
        
        Args:
            order_link_id (str): Order link ID to check
        
        Returns:
            bool: True if this is a Silver Bullet order to cancel
        """
        if not order_link_id:
            return False
        
        # Check for priority 1 orders (Silver Bullet should be priority 1)
        is_priority_1 = (
            order_link_id.startswith('prio1_') or 
            order_link_id.startswith('p1_')
        )
        
        # Check for silver_bullet strategy ID
        has_silver_bullet_strategy = (
            'silver_bullet' in order_link_id.lower() or
            '_sb_' in order_link_id.lower() or
            'ict_strategy' in order_link_id.lower()  # Alternative strategy naming
        )
        
        # Must be priority 1 AND have silver bullet strategy identifier
        is_sb_order = is_priority_1 and has_silver_bullet_strategy
        
        if is_sb_order:
            logger.info(f"Identified Silver Bullet order: {order_link_id} (priority_1: {is_priority_1}, sb_strategy: {has_silver_bullet_strategy})")
        
        return is_sb_order
    
    async def cancel_session_orders(self) -> Dict[str, Any]:
        """
        Cancel all Silver Bullet orders at session end.
        
        Returns:
            Dict[str, Any]: Cancellation results
        """
        try:
            nyc_time = self.get_nyc_time()
            cancel_check = self.should_cancel_orders(nyc_time)
            
            if not cancel_check["should_cancel"]:
                return {
                    "cancelled": False,
                    "reason": "Not at cancellation time",
                    "nyc_time": nyc_time.strftime("%Y-%m-%d %H:%M:%S %Z")
                }
            
            session_name = cancel_check["session_name"]
            cancel_time = cancel_check["cancel_time"]
            
            logger.info(f"🚨 Silver Bullet session ended: {session_name} - Cancelling orders at {cancel_time} NYC")
            
            # Get orders to cancel
            orders_to_cancel = await self.get_silver_bullet_orders_for_cancellation()
            
            if not orders_to_cancel:
                logger.info("No Silver Bullet orders found to cancel")
                return {
                    "cancelled": True,
                    "session_name": session_name,
                    "cancel_time": cancel_time,
                    "orders_cancelled": 0,
                    "orders_found": 0,
                    "message": "No Silver Bullet orders to cancel",
                    "nyc_time": nyc_time.strftime("%Y-%m-%d %H:%M:%S %Z")
                }
            
            # Cancel the orders
            cancellation_results = {
                "cancelled_orders": [],
                "failed_cancellations": [],
                "total_attempted": len(orders_to_cancel)
            }
            
            logger.info(f"Cancelling {len(orders_to_cancel)} Silver Bullet orders...")
            
            for order_info in orders_to_cancel:
                try:
                    symbol = order_info["symbol"]
                    order_id = order_info["order_id"]
                    order_link_id = order_info["order_link_id"]
                    
                    logger.info(f"Cancelling Silver Bullet order: {order_link_id} ({symbol})")
                    
                    # Cancel the order
                    cancel_result = self.bybit_service.exchange.cancel_order(order_id, symbol)
                    
                    cancellation_results["cancelled_orders"].append({
                        "symbol": symbol,
                        "order_id": order_id,
                        "order_link_id": order_link_id,
                        "cancel_result": cancel_result
                    })
                    
                    logger.info(f"✅ Cancelled Silver Bullet order: {order_link_id}")
                
                except Exception as cancel_error:
                    error_msg = f"Failed to cancel Silver Bullet order {order_info.get('order_link_id', 'Unknown')}: {str(cancel_error)}"
                    logger.error(error_msg)
                    cancellation_results["failed_cancellations"].append({
                        "order_info": order_info,
                        "error": error_msg
                    })
            
            success_count = len(cancellation_results["cancelled_orders"])
            total_count = len(orders_to_cancel)
            
            logger.info(f"Session cancellation complete: {success_count}/{total_count} Silver Bullet orders cancelled")
            
            return {
                "cancelled": True,
                "session_name": session_name,
                "cancel_time": cancel_time,
                "orders_cancelled": success_count,
                "orders_found": total_count,
                "failed_cancellations": len(cancellation_results["failed_cancellations"]),
                "message": f"Cancelled {success_count}/{total_count} Silver Bullet orders for {session_name} session",
                "details": cancellation_results,
                "nyc_time": nyc_time.strftime("%Y-%m-%d %H:%M:%S %Z")
            }
        
        except Exception as e:
            logger.error(f"Error in session order cancellation: {e}")
            return {
                "cancelled": False,
                "error": str(e),
                "nyc_time": self.get_nyc_time().strftime("%Y-%m-%d %H:%M:%S %Z")
            }
    
    async def monitor_sessions(self) -> None:
        """
        Continuous monitoring of Silver Bullet sessions.
        This method should be called as a background task.
        """
        logger.info("Starting Silver Bullet session monitoring...")
        
        while True:
            try:
                nyc_time = self.get_nyc_time()
                
                # Check if we should cancel orders
                cancel_check = self.should_cancel_orders(nyc_time)
                
                if cancel_check["should_cancel"]:
                    logger.info(f"🎯 Session cancellation time detected: {cancel_check['session_name']} at {cancel_check['cancel_time']}")
                    
                    # Perform cancellation
                    cancel_result = await self.cancel_session_orders()
                    
                    if cancel_result.get("cancelled"):
                        logger.info(f"✅ Session cancellation completed: {cancel_result.get('message', '')}")
                    else:
                        logger.warning(f"❌ Session cancellation failed: {cancel_result.get('reason', 'Unknown error')}")
                
                # Log session status every 15 minutes during business hours
                if nyc_time.minute % 15 == 0 and nyc_time.second < 30:
                    session_status = self.is_in_session(nyc_time)
                    if session_status["in_session"]:
                        logger.info(f"📊 Currently in Silver Bullet session: {session_status['session_name']} (NYC: {nyc_time.strftime('%H:%M')})")
                
                # Sleep for 30 seconds before next check
                await asyncio.sleep(30)
            
            except Exception as e:
                logger.error(f"Error in session monitoring: {e}")
                # Sleep longer on error to prevent spam
                await asyncio.sleep(60)
    
    def get_session_status(self) -> Dict[str, Any]:
        """
        Get current session status for API endpoints.
        
        Returns:
            Dict[str, Any]: Current session status
        """
        nyc_time = self.get_nyc_time()
        session_info = self.is_in_session(nyc_time)
        cancel_info = self.should_cancel_orders(nyc_time)
        
        # Calculate next session times
        next_sessions = []
        for session in self.session_definitions:
            next_start = nyc_time.replace(
                hour=session["start_hour"], 
                minute=session["start_minute"], 
                second=0, 
                microsecond=0
            )
            
            # If session already passed today, move to tomorrow
            if next_start <= nyc_time:
                next_start += timedelta(days=1)
            
            next_sessions.append({
                "name": session["name"],
                "start_time": next_start.strftime("%H:%M"),
                "hours_until": round((next_start - nyc_time).total_seconds() / 3600, 1)
            })
        
        # Sort by time until next session
        next_sessions.sort(key=lambda x: x["hours_until"])
        
        return {
            "nyc_time": nyc_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "in_session": session_info["in_session"],
            "current_session": session_info.get("session_name"),
            "should_cancel_now": cancel_info["should_cancel"],
            "next_cancellation": cancel_info.get("cancel_time"),
            "next_sessions": next_sessions,
            "session_definitions": self.session_definitions
        } 