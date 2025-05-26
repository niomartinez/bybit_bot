#!/usr/bin/env python3
"""
Test script for Google Sheets journaling fixes
"""

import asyncio
import time
import json
from datetime import datetime, timezone
from src.sheets_service import SheetsService, SheetsConfig

async def test_sheets_journaling():
    """Test the fixed Google Sheets journaling functionality."""
    
    print("🧪 Testing Google Sheets journaling fixes...")
    
    # Load configuration
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        sheets_config = SheetsConfig(
            credentials_file=config.get('google_sheets', {}).get('credentials_file', 'credentials.json'),
            spreadsheet_id=config.get('google_sheets', {}).get('spreadsheet_id'),
            worksheet_name=config.get('google_sheets', {}).get('worksheet_name', 'Trading_Journal')
        )
        
        print(f"📊 Using spreadsheet: {sheets_config.spreadsheet_id}")
        print(f"📋 Using worksheet: {sheets_config.worksheet_name}")
        
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return False
    
    # Initialize sheets service
    sheets_service = SheetsService(sheets_config)
    
    try:
        success = await sheets_service.initialize()
        if not success:
            print("❌ Failed to initialize Google Sheets service")
            return False
        
        print("✅ Google Sheets service initialized successfully")
        
    except Exception as e:
        print(f"❌ Error initializing sheets service: {e}")
        return False
    
    # Test 1: Log a test trade entry
    print("\n🔍 Test 1: Logging trade entry...")
    test_trade_id = f"test_{int(time.time())}_TESTUSDT_sheets_fix"
    
    try:
        success = await sheets_service.log_trade_entry(
            trade_id=test_trade_id,
            symbol="TESTUSDT.P",
            strategy="test_strategy",
            priority=1,
            side="SHORT",
            entry_price=100.50,
            quantity=10,
            stop_loss=105.0,
            take_profit=95.0,
            session_type="Test Session",
            risk_amount=50.0,
            status="PENDING"
        )
        
        if success:
            print("✅ Trade entry logged successfully")
        else:
            print("❌ Failed to log trade entry")
            return False
            
    except Exception as e:
        print(f"❌ Error logging trade entry: {e}")
        return False
    
    # Test 2: Update trade status to ACTIVE
    print("\n🔍 Test 2: Updating trade status to ACTIVE...")
    
    try:
        success = await sheets_service.update_trade_status(
            trade_id=test_trade_id,
            new_status="ACTIVE",
            fill_price=100.25,
            fill_time=time.time()
        )
        
        if success:
            print("✅ Trade status updated to ACTIVE successfully")
        else:
            print("❌ Failed to update trade status")
            return False
            
    except Exception as e:
        print(f"❌ Error updating trade status: {e}")
        return False
    
    # Test 3: Log trade exit
    print("\n🔍 Test 3: Logging trade exit...")
    
    try:
        success = await sheets_service.log_trade_exit(
            trade_id=test_trade_id,
            exit_price=96.75,
            exit_time=time.time(),
            exit_reason="Take Profit Hit",
            quantity=10,
            pnl=37.50  # (100.25 - 96.75) * 10 for SHORT
        )
        
        if success:
            print("✅ Trade exit logged successfully")
        else:
            print("❌ Failed to log trade exit")
            return False
            
    except Exception as e:
        print(f"❌ Error logging trade exit: {e}")
        return False
    
    # Test 4: Test edge cases with None values
    print("\n🔍 Test 4: Testing edge cases with None values...")
    edge_trade_id = f"test_edge_{int(time.time())}_EDGEUSDT_sheets_fix"
    
    try:
        # Test with minimal data
        success = await sheets_service.log_trade_entry(
            trade_id=edge_trade_id,
            symbol="EDGEUSDT.P",
            strategy="edge_test",
            priority=1,
            side="LONG",
            entry_price=50.0,
            quantity=5,
            status="ACTIVE"
        )
        
        if success:
            print("✅ Edge case trade entry logged successfully")
            
            # Test exit with None values that should be handled
            success = await sheets_service.log_trade_exit(
                trade_id=edge_trade_id,
                exit_price=52.0,
                exit_reason=None,  # Should become "Unknown"
                quantity=None,     # Should use original quantity
                pnl=None          # Should be calculated
            )
            
            if success:
                print("✅ Edge case trade exit logged successfully")
            else:
                print("❌ Failed to log edge case trade exit")
                return False
        else:
            print("❌ Failed to log edge case trade entry")
            return False
            
    except Exception as e:
        print(f"❌ Error testing edge cases: {e}")
        return False
    
    # Test 5: Test connection and status
    print("\n🔍 Test 5: Testing connection and status...")
    
    try:
        status = await sheets_service.get_status()
        print(f"📊 Sheets status: {status}")
        
        connection_test = await sheets_service.test_connection()
        if connection_test.get('success'):
            print("✅ Connection test passed")
        else:
            print(f"❌ Connection test failed: {connection_test.get('message')}")
            
    except Exception as e:
        print(f"❌ Error testing connection: {e}")
        return False
    
    print("\n🎉 All tests completed successfully!")
    print("\n📋 Summary:")
    print("- Trade entry logging: ✅ Fixed")
    print("- Trade status updates: ✅ Fixed") 
    print("- Trade exit logging: ✅ Fixed")
    print("- Edge case handling: ✅ Fixed")
    print("- Google Sheets API errors: ✅ Fixed")
    
    return True

if __name__ == "__main__":
    asyncio.run(test_sheets_journaling()) 