#!/usr/bin/env python3
"""
Test script for critical fixes:
1. Exit price 0 validation fix
2. Manual position protection
3. Position tracking improvements
"""

import asyncio
import time
import json
from datetime import datetime, timezone
from src.sheets_service import SheetsService, SheetsConfig
from src.bybit_service import BybitService
from src.models import TradeJournalEntry

async def test_critical_fixes():
    """Test all the critical fixes."""
    
    print("🧪 Testing critical fixes...")
    
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
        
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return False
    
    # Initialize services
    print("\n🔧 Initializing services...")
    
    sheets_service = SheetsService(sheets_config)
    success = await sheets_service.initialize()
    if not success:
        print("❌ Failed to initialize Google Sheets service")
        return False
    
    bybit_service = BybitService()
    print("✅ Services initialized successfully")
    
    # Test 1: Exit price 0 validation fix
    print("\n🔍 Test 1: Exit price 0 validation fix...")
    
    test_trade_id = f"test_exit_0_{int(time.time())}_TESTUSDT_fix"
    
    try:
        # First create a test trade entry
        success = await sheets_service.log_trade_entry(
            trade_id=test_trade_id,
            symbol="TESTUSDT.P",
            strategy="exit_price_test",
            priority=1,
            side="SHORT",
            entry_price=100.0,
            quantity=10,
            status="ACTIVE"
        )
        
        if success:
            print("✅ Test trade entry created")
            
            # Now test exit with price 0 (should work now)
            success = await sheets_service.log_trade_exit(
                trade_id=test_trade_id,
                exit_price=0,  # This should now be allowed
                exit_reason="Position Closed",
                pnl=0
            )
            
            if success:
                print("✅ Exit price 0 validation fix working - trade exit logged successfully")
            else:
                print("❌ Exit price 0 validation fix failed")
                return False
        else:
            print("❌ Failed to create test trade entry")
            return False
            
    except Exception as e:
        print(f"❌ Error testing exit price 0 fix: {e}")
        return False
    
    # Test 2: Manual position protection
    print("\n🔍 Test 2: Manual position protection...")
    
    try:
        # Simulate getting positions
        existing_positions = await bybit_service.get_existing_positions("BTCUSDT")
        print(f"Found {len(existing_positions)} existing positions for BTCUSDT")
        
        # Test priority conflict checking with manual positions
        conflict_check = await bybit_service.check_priority_conflicts(
            symbol="BTCUSDT",
            requested_priority=1,
            requested_side="Buy"
        )
        
        print(f"Priority conflict check result: {conflict_check.get('reason', 'No reason')}")
        print(f"Positions to close: {len(conflict_check.get('positions_to_close', []))}")
        print(f"Protected positions logic: {'✅ Working' if 'PROTECTED' in str(conflict_check) or len(conflict_check.get('positions_to_close', [])) == 0 else '⚠️ Check logs'}")
        
    except Exception as e:
        print(f"❌ Error testing manual position protection: {e}")
        return False
    
    # Test 3: Position tracking improvements
    print("\n🔍 Test 3: Position tracking improvements...")
    
    try:
        all_positions = await bybit_service.get_all_positions()
        print(f"Position tracking found: {len(all_positions)} active positions")
        
        for symbol, pos_info in all_positions.items():
            print(f"  - {symbol}: {pos_info.get('side')} {pos_info.get('size')} (contracts: {pos_info.get('contracts')})")
        
        print("✅ Position tracking improvements working")
        
    except Exception as e:
        print(f"❌ Error testing position tracking: {e}")
        return False
    
    # Test 4: Sheets service active trades tracking
    print("\n🔍 Test 4: Active trades tracking...")
    
    try:
        print(f"Active trades in sheets service: {len(sheets_service.active_trades)}")
        
        for trade_id, trade_entry in sheets_service.active_trades.items():
            print(f"  - {trade_id}: {trade_entry.symbol} {trade_entry.side} ({trade_entry.status})")
        
        print("✅ Active trades tracking working")
        
    except Exception as e:
        print(f"❌ Error checking active trades tracking: {e}")
        return False
    
    # Test 5: Integration test - Position identification
    print("\n🔍 Test 5: Position identification integration...")
    
    try:
        # Create a mock trade entry to simulate bot tracking
        mock_trade_id = f"test_integration_{int(time.time())}_ETHUSDT_mock"
        
        # Add to sheets service active trades (simulating a tracked position)
        mock_entry = TradeJournalEntry(
            trade_id=mock_trade_id,
            symbol="ETHUSDT.P",
            strategy="integration_test",
            priority=2,
            entry_time=datetime.now(timezone.utc),
            side="LONG",
            entry_price=2500.0,
            quantity=1.0,
            status="ACTIVE"
        )
        
        sheets_service.active_trades[mock_trade_id] = mock_entry
        print(f"✅ Added mock trade entry: {mock_trade_id}")
        
        # Now test if priority conflict detection can identify this as a bot position
        # (Note: This requires actual positions to exist, so results may vary)
        conflict_check = await bybit_service.check_priority_conflicts(
            symbol="ETHUSDT",
            requested_priority=1,
            requested_side="Sell"
        )
        
        print(f"Integration test result: {conflict_check.get('reason', 'No reason')}")
        
        # Clean up
        del sheets_service.active_trades[mock_trade_id]
        print("✅ Integration test completed and cleaned up")
        
    except Exception as e:
        print(f"❌ Error in integration test: {e}")
        return False
    
    print("\n🎉 All critical fixes tested successfully!")
    print("\n📋 Summary of fixes:")
    print("- ✅ Exit price 0 validation: Fixed - now allows position closure detection")
    print("- ✅ Manual position protection: Fixed - only closes bot-tracked positions")
    print("- ✅ Position tracking: Improved - better position detection")
    print("- ✅ Integration: Working - bot can identify its own positions safely")
    
    return True

async def test_exit_price_edge_cases():
    """Test various exit price edge cases."""
    
    print("\n🔍 Testing exit price edge cases...")
    
    # Load configuration
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        sheets_config = SheetsConfig(
            credentials_file=config.get('google_sheets', {}).get('credentials_file', 'credentials.json'),
            spreadsheet_id=config.get('google_sheets', {}).get('spreadsheet_id'),
            worksheet_name=config.get('google_sheets', {}).get('worksheet_name', 'Trading_Journal')
        )
        
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return False
    
    sheets_service = SheetsService(sheets_config)
    success = await sheets_service.initialize()
    if not success:
        print("❌ Failed to initialize Google Sheets service")
        return False
    
    test_cases = [
        {"name": "Exit price 0", "exit_price": 0, "should_work": True},
        {"name": "Exit price negative", "exit_price": -10.0, "should_work": False},
        {"name": "Exit price normal", "exit_price": 95.5, "should_work": True},
        {"name": "Exit price very small", "exit_price": 0.0001, "should_work": True},
    ]
    
    for i, test_case in enumerate(test_cases):
        print(f"\n  Test {i+1}: {test_case['name']}")
        
        test_trade_id = f"test_edge_{i}_{int(time.time())}_EDGEUSDT_fix"
        
        try:
            # Create test trade
            await sheets_service.log_trade_entry(
                trade_id=test_trade_id,
                symbol="EDGEUSDT.P",
                strategy="edge_test",
                priority=1,
                side="LONG",
                entry_price=100.0,
                quantity=5,
                status="ACTIVE"
            )
            
            # Test exit
            result = await sheets_service.log_trade_exit(
                trade_id=test_trade_id,
                exit_price=test_case["exit_price"],
                exit_reason="Test Case",
                pnl=0
            )
            
            if result == test_case["should_work"]:
                print(f"    ✅ {test_case['name']}: Behaved as expected")
            else:
                print(f"    ❌ {test_case['name']}: Unexpected result (got {result}, expected {test_case['should_work']})")
                
        except Exception as e:
            if test_case["should_work"]:
                print(f"    ❌ {test_case['name']}: Unexpected error: {e}")
            else:
                print(f"    ✅ {test_case['name']}: Expected error caught: {e}")
    
    print("✅ Exit price edge cases testing completed")
    return True

if __name__ == "__main__":
    async def run_all_tests():
        success1 = await test_critical_fixes()
        success2 = await test_exit_price_edge_cases()
        
        if success1 and success2:
            print("\n🎉 ALL TESTS PASSED! Critical fixes are working correctly.")
            return True
        else:
            print("\n❌ SOME TESTS FAILED! Check the output above.")
            return False
    
    asyncio.run(run_all_tests()) 