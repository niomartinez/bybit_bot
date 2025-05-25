#!/usr/bin/env python3
"""
Test script for Silver Bullet Session Manager.
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta

# Add the src directory to Python path
sys.path.append('src')

from src.session_manager import SilverBulletSessionManager, NYC_TZ
from src.bybit_service import BybitService
from src.config import logger

async def test_session_manager():
    """Test the Silver Bullet Session Manager functionality."""
    logger.info("🧪 Testing Silver Bullet Session Manager...")
    
    try:
        # Initialize services
        bybit_service = BybitService()
        session_manager = SilverBulletSessionManager(bybit_service)
        
        # Test 1: Check current NYC time
        nyc_time = session_manager.get_nyc_time()
        logger.info(f"📅 Current NYC time: {nyc_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        # Test 2: Check if we're in a session
        session_status = session_manager.is_in_session()
        logger.info(f"📊 In session: {session_status['in_session']}")
        if session_status['in_session']:
            logger.info(f"🎯 Current session: {session_status['session_name']}")
        
        # Test 3: Check if we should cancel orders
        cancel_status = session_manager.should_cancel_orders()
        logger.info(f"🚨 Should cancel orders: {cancel_status['should_cancel']}")
        if cancel_status['should_cancel']:
            logger.info(f"🕐 Cancel time: {cancel_status['cancel_time']}")
        
        # Test 4: Test session status API
        status = session_manager.get_session_status()
        logger.info(f"📋 Session status: {status}")
        
        # Test 5: Test order identification
        test_order_ids = [
            "prio1_1747778400_BTCUSDT_silver_bullet",
            "prio2_1747778400_ETHUSDT_default",
            "tv_1747778400_SOLUSDT",
            "prio1_1747778400_ADAUSDT_ict_strategy",
            "random_order_id"
        ]
        
        logger.info("🔍 Testing order identification:")
        for order_id in test_order_ids:
            is_sb = session_manager._is_silver_bullet_order(order_id)
            logger.info(f"  {order_id}: {'✅ Silver Bullet' if is_sb else '❌ Not Silver Bullet'}")
        
        # Test 6: Test specific session times
        test_times = [
            datetime(2024, 1, 15, 3, 30, 0, tzinfo=NYC_TZ),  # 3:30 AM - London Open session
            datetime(2024, 1, 15, 4, 5, 0, tzinfo=NYC_TZ),   # 4:05 AM - Cancel time
            datetime(2024, 1, 15, 10, 30, 0, tzinfo=NYC_TZ), # 10:30 AM - AM session
            datetime(2024, 1, 15, 11, 5, 0, tzinfo=NYC_TZ),  # 11:05 AM - Cancel time
            datetime(2024, 1, 15, 14, 30, 0, tzinfo=NYC_TZ), # 2:30 PM - PM session
            datetime(2024, 1, 15, 15, 5, 0, tzinfo=NYC_TZ),  # 3:05 PM - Cancel time
            datetime(2024, 1, 15, 12, 0, 0, tzinfo=NYC_TZ),  # 12:00 PM - Outside session
        ]
        
        logger.info("🕐 Testing specific session times:")
        for test_time in test_times:
            session_info = session_manager.is_in_session(test_time)
            cancel_info = session_manager.should_cancel_orders(test_time)
            
            time_str = test_time.strftime("%H:%M")
            status_str = f"{time_str}: "
            
            if session_info["in_session"]:
                status_str += f"📊 In {session_info['session_name']}"
            elif cancel_info["should_cancel"]:
                status_str += f"🚨 Cancel time for {cancel_info['session_name']}"
            else:
                status_str += "⏳ Outside session"
            
            logger.info(f"  {status_str}")
        
        # Test 7: Manual cancellation test (dry run)
        logger.info("🧪 Testing manual cancellation (dry run)...")
        try:
            # This will check for Silver Bullet orders but not actually cancel them
            # unless we're at the exact cancellation time
            orders_to_cancel = await session_manager.get_silver_bullet_orders_for_cancellation()
            logger.info(f"🔍 Found {len(orders_to_cancel)} Silver Bullet orders that would be cancelled")
            
            if orders_to_cancel:
                for order in orders_to_cancel:
                    logger.info(f"  📝 Order: {order['order_link_id']} ({order['symbol']})")
        except Exception as e:
            logger.warning(f"Error testing order cancellation: {e}")
        
        logger.info("✅ Session Manager tests completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Error testing session manager: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_session_manager()) 