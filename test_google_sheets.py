#!/usr/bin/env python3
"""
Test script for Google Sheets integration.
"""

import asyncio
import json
import os
from datetime import datetime
from src.models import SheetsConfig, TradeJournalEntry
from src.sheets_service import SheetsService
from src.config import logger

async def test_google_sheets():
    """Test Google Sheets integration."""
    
    print("🧪 Testing Google Sheets Integration")
    print("=" * 50)
    
    # Check if credentials file exists
    credentials_file = "credentials.json"
    if not os.path.exists(credentials_file):
        print(f"❌ Credentials file not found: {credentials_file}")
        print("Please follow the setup instructions in GOOGLE_SHEETS_SETUP.md")
        return False
    
    # Load test configuration
    try:
        with open("config.json", "r") as f:
            config_data = json.load(f)
        
        sheets_config_data = config_data.get("google_sheets", {})
        
        if not sheets_config_data.get("spreadsheet_id"):
            print("❌ Google Sheets spreadsheet_id not configured")
            print("Please update config.json with your spreadsheet ID")
            return False
        
        # Create sheets config
        sheets_config = SheetsConfig(
            spreadsheet_id=sheets_config_data["spreadsheet_id"],
            worksheet_name=sheets_config_data.get("worksheet_name", "Trade Journal"),
            credentials_file=sheets_config_data.get("credentials_file", "credentials.json")
        )
        
        print(f"📊 Spreadsheet ID: {sheets_config.spreadsheet_id}")
        print(f"📋 Worksheet: {sheets_config.worksheet_name}")
        print(f"🔑 Credentials: {sheets_config.credentials_file}")
        
    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        return False
    
    # Initialize sheets service
    print("\n🔌 Initializing Google Sheets service...")
    sheets_service = SheetsService(sheets_config)
    
    # Test connection
    connected = await sheets_service.initialize()
    
    if not connected:
        print("❌ Failed to connect to Google Sheets")
        return False
    
    print("✅ Successfully connected to Google Sheets")
    
    # Test logging a sample trade
    print("\n📝 Testing trade logging...")
    
    sample_trade = TradeJournalEntry(
        trade_id=f"TEST_{int(datetime.utcnow().timestamp())}",
        symbol="BTCUSDT",
        strategy="test_strategy",
        priority=1,
        entry_time=datetime.utcnow(),
        entry_price=65000.0,
        side="long",
        quantity=0.001,
        stop_loss=64000.0,
        take_profit=67000.0,
        risk_amount=10.0,
        session_type="Test Session",
        status="OPEN",
        notes="Test trade from integration test"
    )
    
    # Log the trade
    log_success = await sheets_service.log_trade_entry(sample_trade)
    
    if log_success:
        print(f"✅ Successfully logged test trade: {sample_trade.trade_id}")
    else:
        print("❌ Failed to log test trade")
        return False
    
    # Test updating the trade (simulate exit)
    print("\n📊 Testing trade update...")
    
    exit_data = {
        "exit_time": datetime.utcnow(),
        "exit_price": 66000.0,
        "exit_reason": "Take Profit",
        "pnl_usd": 1000.0,
        "pnl_percentage": 1.54
    }
    
    update_success = await sheets_service.update_trade_exit(sample_trade.trade_id, exit_data)
    
    if update_success:
        print(f"✅ Successfully updated trade exit: {sample_trade.trade_id}")
    else:
        print("❌ Failed to update trade exit")
        return False
    
    # Test getting statistics
    print("\n📈 Testing statistics retrieval...")
    
    stats = await sheets_service.get_trade_statistics()
    
    if "error" not in stats:
        print("✅ Successfully retrieved trade statistics:")
        print(f"   Total trades: {stats.get('total_trades', 0)}")
        print(f"   Open trades: {stats.get('open_trades', 0)}")
        print(f"   Closed trades: {stats.get('closed_trades', 0)}")
        print(f"   Total P&L: ${stats.get('total_pnl', 0):.2f}")
        print(f"   Win rate: {stats.get('win_rate', 0):.1f}%")
    else:
        print(f"❌ Failed to get statistics: {stats['error']}")
        return False
    
    # Test backup functionality
    print("\n💾 Testing backup functionality...")
    
    backup_result = await sheets_service.backup_trades()
    
    if backup_result.get("success"):
        print(f"✅ Successfully created backup: {backup_result['backup_file']}")
        print(f"   Trades backed up: {backup_result['trades_backed_up']}")
    else:
        print(f"❌ Failed to create backup: {backup_result.get('error', 'Unknown error')}")
        return False
    
    # Test connection status
    print("\n🔍 Testing connection status...")
    
    status = sheets_service.get_connection_status()
    print("✅ Connection status:")
    print(f"   Connected: {status['connected']}")
    print(f"   Active trades: {status['active_trades']}")
    print(f"   Last sync: {status['last_sync']}")
    
    print("\n🎉 All Google Sheets tests passed!")
    print("\nYour Google Sheets integration is working correctly.")
    print("You can now enable it in config.json by setting 'enabled': true")
    
    return True

async def test_api_endpoints():
    """Test the API endpoints."""
    
    print("\n🌐 Testing API Endpoints")
    print("=" * 30)
    
    import httpx
    
    base_url = "http://localhost:8001"
    
    try:
        async with httpx.AsyncClient() as client:
            # Test journal status
            print("📊 Testing /journal/status...")
            response = await client.get(f"{base_url}/journal/status")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Journal status: {data.get('connected', False)}")
            else:
                print(f"❌ Journal status failed: {response.status_code}")
            
            # Test statistics (only if connected)
            if response.status_code == 200 and response.json().get('connected'):
                print("📈 Testing /journal/statistics...")
                stats_response = await client.get(f"{base_url}/journal/statistics")
                
                if stats_response.status_code == 200:
                    stats = stats_response.json()
                    print(f"✅ Statistics: {stats.get('total_trades', 0)} total trades")
                else:
                    print(f"❌ Statistics failed: {stats_response.status_code}")
                
                # Test backup
                print("💾 Testing /journal/backup...")
                backup_response = await client.post(f"{base_url}/journal/backup")
                
                if backup_response.status_code == 200:
                    backup = backup_response.json()
                    print(f"✅ Backup: {backup.get('backup_file', 'Created')}")
                else:
                    print(f"❌ Backup failed: {backup_response.status_code}")
    
    except Exception as e:
        print(f"❌ API test failed: {e}")
        print("Make sure the bot is running on localhost:8001")

if __name__ == "__main__":
    print("Google Sheets Integration Test")
    print("==============================")
    
    # Run the tests
    success = asyncio.run(test_google_sheets())
    
    if success:
        print("\n🚀 Testing API endpoints (make sure bot is running)...")
        asyncio.run(test_api_endpoints())
    
    print("\nTest completed!") 