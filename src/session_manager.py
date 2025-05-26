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
        Get all Silver Bullet strategy orders that should be cancelled across ALL symbols.
        
        Returns:
            List[Dict[str, Any]]: List of orders to cancel
        """
        orders_to_cancel = []
        
        try:
            logger.info("🔍 Checking ALL symbols for Silver Bullet orders to cancel...")
            
            # Get ALL open orders across ALL symbols using the Bybit V5 API
            # This is much more efficient than checking individual symbols
            try:
                # Use the bybit_service exchange directly to get all open orders
                # Set parameters for Bybit V5 unified account
                params = {
                    'category': 'linear',  # Check linear perpetuals (most common for crypto trading)
                    'settleCoin': 'USDT'   # Focus on USDT-settled contracts
                }
                
                # Get all open orders across all symbols
                all_open_orders = self.bybit_service.exchange.fetch_open_orders(
                    symbol=None,  # None means all symbols
                    since=None,
                    limit=200,    # Increase limit to catch more orders
                    params=params
                )
                
                logger.info(f"Retrieved {len(all_open_orders)} total open orders across all linear USDT symbols")
                
                # Also check USDC contracts
                try:
                    params_usdc = {
                        'category': 'linear',
                        'settleCoin': 'USDC'
                    }
                    
                    usdc_orders = self.bybit_service.exchange.fetch_open_orders(
                        symbol=None,
                        since=None,
                        limit=100,
                        params=params_usdc
                    )
                    
                    all_open_orders.extend(usdc_orders)
                    logger.info(f"Added {len(usdc_orders)} USDC orders, total: {len(all_open_orders)}")
                    
                except Exception as usdc_error:
                    logger.warning(f"Could not fetch USDC orders: {usdc_error}")
                
                # Also check inverse contracts for completeness
                try:
                    params_inverse = {
                        'category': 'inverse'
                    }
                    
                    inverse_orders = self.bybit_service.exchange.fetch_open_orders(
                        symbol=None,
                        since=None,
                        limit=50,
                        params=params_inverse
                    )
                    
                    all_open_orders.extend(inverse_orders)
                    logger.info(f"Added {len(inverse_orders)} inverse orders, total: {len(all_open_orders)}")
                    
                except Exception as inverse_error:
                    logger.warning(f"Could not fetch inverse orders: {inverse_error}")
                
            except Exception as api_error:
                logger.error(f"Error fetching all open orders via API: {api_error}")
                
                # Fallback: Use the existing get_recent_orders method which includes open orders
                logger.info("Falling back to get_recent_orders method...")
                recent_orders = await self.bybit_service.get_recent_orders(limit=300)
                
                # Filter for only open orders
                all_open_orders = [order for order in recent_orders if order.get('status') == 'open']
                logger.info(f"Fallback: Found {len(all_open_orders)} open orders from recent orders")
            
            # Now filter for Silver Bullet orders across all the orders we found
            unique_symbols = set()
            
            for order in all_open_orders:
                try:
                    # Extract order info
                    order_link_id = order.get('clientOrderId', order.get('info', {}).get('orderLinkId', ''))
                    symbol = order.get('symbol', '')
                    
                    # Normalize symbol for tracking (remove trading pair format)
                    normalized_symbol = self._normalize_symbol_for_tracking(symbol)
                    if normalized_symbol:
                        unique_symbols.add(normalized_symbol)
                    
                    # Check if this is a Silver Bullet order
                    if self._is_silver_bullet_order(order_link_id):
                        orders_to_cancel.append({
                            'symbol': normalized_symbol,  # Use normalized symbol
                            'market_symbol': symbol,      # Keep original for API calls
                            'order_id': order.get('id'),
                            'order_link_id': order_link_id,
                            'side': order.get('side', ''),
                            'amount': order.get('amount', 0),
                            'order': order
                        })
                        logger.info(f"Found Silver Bullet order to cancel: {order_link_id} ({normalized_symbol})")
                
                except Exception as order_error:
                    logger.warning(f"Error processing order: {order_error}")
                    continue
            
            logger.info(f"🎯 Scanned {len(all_open_orders)} orders across {len(unique_symbols)} unique symbols")
            logger.info(f"📋 Symbols checked: {sorted(list(unique_symbols))[:20]}{'...' if len(unique_symbols) > 20 else ''}")
            logger.info(f"🚨 Found {len(orders_to_cancel)} Silver Bullet orders to cancel")
            
            return orders_to_cancel
        
        except Exception as e:
            logger.error(f"Error getting Silver Bullet orders for cancellation: {e}")
            return []
    
    def _normalize_symbol_for_tracking(self, symbol: str) -> str:
        """
        Normalize symbol from various Bybit market formats to a standard tracking format.
        
        Examples:
        - BTC/USDT:USDT -> BTCUSDT
        - ETH/USDC:USDC -> ETHUSDC  
        - BTC/USD:BTC -> BTCUSD
        - BTCUSDT -> BTCUSDT
        
        Args:
            symbol (str): Original symbol from Bybit API
        
        Returns:
            str: Normalized symbol for tracking
        """
        if not symbol:
            return ""
        
        try:
            # Handle perpetual futures format (most common)
            if '/USDT:USDT' in symbol:
                return symbol.replace('/USDT:USDT', 'USDT')
            
            if '/USDC:USDC' in symbol:
                return symbol.replace('/USDC:USDC', 'USDC')
            
            # Handle inverse perpetuals (e.g., BTC/USD:BTC -> BTCUSD)
            if '/USD:' in symbol:
                base = symbol.split('/USD:')[0]
                return f"{base}USD"
            
            # Handle regular spot format (e.g., BTC/USDT -> BTCUSDT)
            if '/' in symbol and ':' not in symbol:
                return symbol.replace('/', '')
            
            # Already in normalized format
            return symbol.upper()
            
        except Exception as e:
            logger.warning(f"Error normalizing symbol '{symbol}': {e}")
            # Fallback: just remove special characters
            return symbol.replace('/', '').replace(':', '').upper()
    
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
        
        order_link_lower = order_link_id.lower()
        
        # Debug: Log all order IDs being checked
        logger.debug(f"Checking order ID for Silver Bullet: {order_link_id}")
        
        # Check for priority 1 orders (Silver Bullet should typically be priority 1)
        is_priority_1 = (
            order_link_id.startswith('prio1_') or 
            order_link_id.startswith('p1_')
        )
        
        # Check for silver_bullet strategy ID (multiple possible formats)
        has_silver_bullet_strategy = (
            'silver_bullet' in order_link_lower or
            'silverbullet' in order_link_lower or
            '_sb_' in order_link_lower or
            'ict_strategy' in order_link_lower or
            'ict_' in order_link_lower or
            'silver' in order_link_lower
        )
        
        # Silver Bullet orders can be identified by:
        # 1. Priority 1 + Silver Bullet strategy identifier (strict match)
        # 2. Any order with silver bullet strategy identifier (looser match for missed orders)
        
        # Strict match: Priority 1 + SB strategy
        is_strict_sb_order = is_priority_1 and has_silver_bullet_strategy
        
        # Looser match: Any order with clear Silver Bullet indicators
        is_loose_sb_order = has_silver_bullet_strategy
        
        # Use strict match for now, but log both for debugging
        is_sb_order = is_strict_sb_order
        
        if is_sb_order:
            logger.info(f"✅ Identified Silver Bullet order: {order_link_id} (priority_1: {is_priority_1}, sb_strategy: {has_silver_bullet_strategy})")
        elif is_loose_sb_order:
            logger.info(f"🔍 Potential Silver Bullet order (loose match): {order_link_id} (priority_1: {is_priority_1}, sb_strategy: {has_silver_bullet_strategy})")
        else:
            logger.debug(f"❌ Not a Silver Bullet order: {order_link_id} (priority_1: {is_priority_1}, sb_strategy: {has_silver_bullet_strategy})")
        
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
                    symbol = order_info["symbol"]  # Normalized symbol for logging
                    market_symbol = order_info.get("market_symbol", symbol)  # API-compatible symbol
                    order_id = order_info["order_id"]
                    order_link_id = order_info["order_link_id"]
                    
                    logger.info(f"Cancelling Silver Bullet order: {order_link_id} ({symbol})")
                    
                    # Cancel the order using the market symbol format
                    cancel_result = self.bybit_service.exchange.cancel_order(order_id, market_symbol)
                    
                    cancellation_results["cancelled_orders"].append({
                        "symbol": symbol,
                        "market_symbol": market_symbol,
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