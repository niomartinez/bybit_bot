"""
FastAPI application for Bybit trading bot.
"""

import asyncio
import time
import traceback
import json
import os
import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from datetime import datetime, timezone

from src.models import TradingViewSignal, SheetsConfig
from src.signal_processor import SignalProcessor
from src.bybit_service import BybitService
from src.session_manager import SilverBulletSessionManager
from src.sheets_service import SheetsService
from src.config import config, logger

# Create FastAPI app
app = FastAPI(
    title="Bybit Trading Bot",
    description="Trading bot that executes trades on Bybit based on TradingView webhook signals",
    version="0.1.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Global variables for services
signal_processor: SignalProcessor = None
session_manager: SilverBulletSessionManager = None
sheets_service: SheetsService = None
monitoring_active = False

def get_credentials_from_env():
    """Get Google Sheets credentials from environment variable or file."""
    try:
        # Try environment variable first (for Render deployment)
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if creds_json:
            logger.info("📄 Using Google credentials from environment variable")
            return json.loads(creds_json)
        
        # Fallback to file (for local development)
        creds_file = "credentials.json"
        if os.path.exists(creds_file):
            logger.info("📄 Using Google credentials from file")
            with open(creds_file, 'r') as f:
                return json.load(f)
        
        logger.warning("⚠️ No Google credentials found (env var GOOGLE_CREDENTIALS or credentials.json file)")
        return None
    except Exception as e:
        logger.error(f"❌ Error loading Google credentials: {e}")
        return None

async def initialize_sheets_service():
    """Initialize Google Sheets service if credentials are available."""
    global sheets_service
    
    try:
        credentials = get_credentials_from_env()
        if not credentials:
            logger.warning("📊 Google Sheets integration disabled - no credentials found")
            return None
        
        # Get sheets config from config.json
        sheets_config_data = getattr(config, "google_sheets", {})
        if not sheets_config_data or not sheets_config_data.get("enabled", False):
            logger.info("📊 Google Sheets integration disabled in config")
            return None
        
        sheets_config = SheetsConfig(**sheets_config_data)
        sheets_service = SheetsService(sheets_config)
        
        # Initialize with credentials from environment variable
        success = await sheets_service.initialize(credentials)
        if not success:
            logger.error("❌ Failed to initialize Google Sheets connection")
            return None
        
        logger.info("✅ Google Sheets service initialized successfully")
        return sheets_service
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Google Sheets service: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        return None

async def monitor_trade_lifecycle():
    """Background task to monitor trade lifecycle: PENDING → ACTIVE → CLOSED."""
    global monitoring_active, sheets_service, signal_processor
    
    if not sheets_service:
        logger.info("📊 Trade monitoring disabled - no sheets service")
        return
    
    logger.info("🔍 Starting trade lifecycle monitoring (every 5 minutes)...")
    monitoring_active = True
    
    # Track processed orders/positions to avoid duplicates
    processed_fill_orders = set()
    processed_exit_orders = set()
    
    while monitoring_active:
        try:
            # Get recent orders and current positions
            recent_orders = await signal_processor.bybit_service.get_recent_orders(limit=100)
            current_positions = await signal_processor.bybit_service.get_all_positions()
            
            # Create a lookup of currently tracked trades
            pending_trades = {tid: trade for tid, trade in sheets_service.active_trades.items() if trade.status == "PENDING"}
            active_trades = {tid: trade for tid, trade in sheets_service.active_trades.items() if trade.status == "ACTIVE"}
            
            # Enhanced monitoring: also show actual positions vs tracked trades
            actual_position_count = len(current_positions)
            tracked_active_count = len(active_trades)
            
            if actual_position_count != tracked_active_count:
                logger.warning(f"📊 Position tracking mismatch: {tracked_active_count} TRACKED active, {actual_position_count} ACTUAL positions")
                logger.info(f"📊 Actual positions: {list(current_positions.keys())}")
                logger.info(f"📊 Tracked active trades: {[trade.symbol.replace('.P', '') for trade in active_trades.values()]}")
                
                # Debug: Check for symbol format mismatches
                actual_symbols = set(current_positions.keys())
                tracked_symbols = set(trade.symbol.replace('.P', '') for trade in active_trades.values())
                
                # Also try alternative symbol normalizations for better matching
                def normalize_symbol(symbol):
                    """Normalize symbol to base format like BTCUSDT"""
                    # Remove .P suffix
                    symbol = symbol.replace('.P', '')
                    # Handle exchange formats like BTC/USDT:USDT -> BTCUSDT
                    if '/USDT:USDT' in symbol:
                        symbol = symbol.replace('/USDT:USDT', 'USDT')
                    elif '/USDC:USDC' in symbol:
                        symbol = symbol.replace('/USDC:USDC', 'USDC')
                    elif '/' in symbol and ':' in symbol:
                        # Generic format like BTC/USDT:USDT
                        parts = symbol.split('/')
                        if len(parts) == 2:
                            base = parts[0]
                            quote_part = parts[1].split(':')[0]  # Get USDT from USDT:USDT
                            symbol = base + quote_part
                    
                    return symbol.upper()
                
                # Re-normalize tracked symbols for better comparison
                tracked_symbols_normalized = set(normalize_symbol(trade.symbol) for trade in active_trades.values())
                
                untracked_positions = actual_symbols - tracked_symbols_normalized
                tracked_without_position = tracked_symbols_normalized - actual_symbols
                
                if untracked_positions:
                    logger.warning(f"🔍 Untracked positions (likely manual): {list(untracked_positions)}")
                if tracked_without_position:
                    logger.warning(f"🔍 Tracked trades without positions: {list(tracked_without_position)}")
                
            else:
                logger.info(f"📊 Monitoring: {len(pending_trades)} PENDING, {len(active_trades)} ACTIVE trades, {actual_position_count} positions")
            
            # Step 1: Check PENDING orders for fills (PENDING → ACTIVE)
            for trade_id, trade_entry in pending_trades.items():
                symbol = trade_entry.symbol
                
                # Look for this order in recent filled orders
                for order in recent_orders:
                    order_id = order.get('clientOrderId') or order.get('id')
                    order_status = order.get('status', '').lower()
                    
                    if (order_id == trade_id and 
                        order_status in ['filled', 'closed'] and 
                        order_id not in processed_fill_orders):
                        
                        processed_fill_orders.add(order_id)
                        
                        # Get actual fill details
                        fill_price = float(order.get('price') or order.get('average') or trade_entry.entry_price)
                        fill_time = order.get('timestamp')
                        
                        if isinstance(fill_time, (int, float)):
                            fill_timestamp = fill_time / 1000 if fill_time > 1e10 else fill_time
                        else:
                            fill_timestamp = time.time()
                        
                        # Update status to ACTIVE
                        await sheets_service.update_trade_status(
                            trade_id=trade_id,
                            new_status="ACTIVE",
                            fill_price=fill_price,
                            fill_time=fill_timestamp
                        )
                        
                        logger.info(f"🎯 Order FILLED: {symbol} {trade_entry.side} @ {fill_price} (ID: {trade_id})")
                        break
            
            # Step 2: Check ACTIVE positions for exits (ACTIVE → CLOSED)
            for trade_id, trade_entry in active_trades.items():
                symbol = trade_entry.symbol
                symbol_clean = symbol.replace('.P', '')  # Remove .P suffix for comparison
                
                # Check if position still exists (more robust checking)
                current_pos = current_positions.get(symbol_clean)
                position_size = abs(current_pos.get('size', 0)) if current_pos else 0
                position_contracts = abs(current_pos.get('contracts', 0)) if current_pos else 0
                
                # More robust position closure detection
                position_exists = position_size > 0 or position_contracts > 0
                
                # Only consider position closed if we're CERTAIN it's closed
                if not position_exists:
                    # Position is closed - look for exit order
                    exit_found = False
                    
                    for order in recent_orders:
                        order_status = order.get('status', '').lower()
                        order_symbol = order.get('symbol', '').replace('/USDT:USDT', '').replace('/USDC:USDC', '').replace('/', '')
                        order_side = order.get('side', '').lower()
                        order_id = order.get('clientOrderId') or order.get('id')
                        
                        if (order_status in ['filled', 'closed'] and 
                            order_symbol == symbol and
                            order_id not in processed_exit_orders):
                            
                            # Check if this is an exit order (opposite direction)
                            is_exit = False
                            if trade_entry.side.lower() == "long" and order_side == "sell":
                                is_exit = True
                            elif trade_entry.side.lower() == "short" and order_side == "buy":
                                is_exit = True
                            
                            if is_exit:
                                processed_exit_orders.add(order_id)
                                
                                exit_price = float(order.get('price') or order.get('average') or 0)
                                exit_quantity = float(order.get('amount') or order.get('filled') or 0)
                                exit_timestamp = order.get('timestamp')
                                
                                if isinstance(exit_timestamp, (int, float)):
                                    exit_time = exit_timestamp / 1000 if exit_timestamp > 1e10 else exit_timestamp
                                else:
                                    exit_time = time.time()
                                
                                # Determine exit reason
                                exit_reason = "Manual"
                                if trade_entry.take_profit and abs(exit_price - trade_entry.take_profit) < abs(exit_price - (trade_entry.stop_loss or 999999)):
                                    exit_reason = "Take Profit"
                                elif trade_entry.stop_loss and abs(exit_price - (trade_entry.stop_loss or 0)) < abs(exit_price - (trade_entry.take_profit or 999999)):
                                    exit_reason = "Stop Loss"
                                
                                # Calculate PnL
                                if trade_entry.side.upper() == "LONG":
                                    pnl = (exit_price - trade_entry.entry_price) * exit_quantity
                                else:
                                    pnl = (trade_entry.entry_price - exit_price) * exit_quantity
                                
                                # Log the exit
                                await sheets_service.log_trade_exit(
                                    trade_id=trade_id,
                                    exit_price=exit_price,
                                    exit_time=exit_time,
                                    exit_reason=exit_reason,
                                    quantity=exit_quantity,
                                    pnl=pnl
                                )
                                
                                logger.info(f"📝 Position CLOSED: {symbol} {exit_reason} @ {exit_price} (PnL: ${pnl:.2f})")
                                exit_found = True
                                break
                    
                    # If no exit order found but position is closed, get proper exit price
                    if not exit_found:
                        exit_price = 0
                        exit_reason = "Position Closed"
                        
                        try:
                            # Option 1: Look for recent market orders for this symbol (any side)
                            symbol_orders = [o for o in recent_orders 
                                           if o.get('symbol', '').replace('/USDT:USDT', '').replace('/USDC:USDC', '').replace('/', '') == symbol_clean
                                           and o.get('status', '').lower() in ['filled', 'closed']
                                           and o.get('timestamp', 0) > 0]
                            
                            if symbol_orders:
                                # Get the most recent filled order for this symbol
                                latest_order = max(symbol_orders, key=lambda x: x.get('timestamp', 0))
                                exit_price = float(latest_order.get('price') or latest_order.get('average') or 0)
                                
                                # Try to determine if it was TP/SL based on price proximity
                                if exit_price > 0:
                                    entry_price = trade_entry.entry_price or 0
                                    tp_price = trade_entry.take_profit or 0
                                    sl_price = trade_entry.stop_loss or 0
                                    
                                    # Check which is closer - TP or SL
                                    if tp_price > 0 and sl_price > 0:
                                        tp_distance = abs(exit_price - tp_price)
                                        sl_distance = abs(exit_price - sl_price)
                                        if tp_distance < sl_distance and tp_distance < abs(entry_price * 0.02):  # Within 2% of TP
                                            exit_reason = "Take Profit"
                                        elif sl_distance < abs(entry_price * 0.02):  # Within 2% of SL
                                            exit_reason = "Stop Loss"
                                    
                                logger.info(f"Using recent market order price as exit: {exit_price} ({exit_reason})")
                            
                            # Option 2: Try to fetch current market price for the symbol
                            if exit_price == 0:
                                try:
                                    # Get current market price from exchange
                                    market_id = signal_processor.bybit_service.get_market_id(symbol_clean, 'linear')
                                    ticker = signal_processor.bybit_service.exchange.fetch_ticker(market_id)
                                    exit_price = float(ticker.get('last', 0) or ticker.get('close', 0) or 0)
                                    if exit_price > 0:
                                        exit_reason = "Market Close"
                                        logger.info(f"Using current market price as exit: {exit_price}")
                                except Exception as ticker_error:
                                    logger.warning(f"Could not fetch market price for {symbol_clean}: {ticker_error}")
                            
                            # Option 3: Last resort - use entry price but mark as unknown exit
                            if exit_price == 0:
                                exit_price = trade_entry.entry_price or 0
                                exit_reason = "Position Closed (Unknown Price)"
                                logger.warning(f"Using entry price as last resort: {exit_price}")
                                
                        except Exception as e:
                            logger.warning(f"Error determining exit price for {symbol}: {e}")
                            exit_price = trade_entry.entry_price or 0
                            exit_reason = "Position Closed (Error)"
                        
                        # Calculate proper P&L
                        pnl = 0
                        if exit_price > 0 and trade_entry.entry_price > 0 and trade_entry.quantity > 0:
                            if trade_entry.side.upper() == "LONG":
                                pnl = (exit_price - trade_entry.entry_price) * trade_entry.quantity
                            else:
                                pnl = (trade_entry.entry_price - exit_price) * trade_entry.quantity
                        
                        await sheets_service.log_trade_exit(
                            trade_id=trade_id,
                            exit_price=exit_price,
                            exit_reason=exit_reason,
                            pnl=pnl
                        )
                        logger.info(f"📝 Position closed detected: {symbol} @ {exit_price} (PnL: ${pnl:.2f}, Reason: {exit_reason})")
            
            # Step 3: Check PENDING orders for cancellations (PENDING → remove)
            for trade_id, trade_entry in list(pending_trades.items()):
                # Look for this order in recent orders to see if it was cancelled
                order_found = False
                
                for order in recent_orders:
                    order_id = order.get('clientOrderId') or order.get('id')
                    order_status = order.get('status', '').lower()
                    
                    if order_id == trade_id:
                        order_found = True
                        
                        if order_status in ['cancelled', 'canceled', 'rejected', 'expired']:
                            # Order was cancelled - remove from tracking
                            await sheets_service.remove_cancelled_trade(trade_id)
                            logger.info(f"🗑️ Order CANCELLED: {trade_entry.symbol} {trade_entry.side} (ID: {trade_id})")
                        break
                
                # If order not found in recent orders and it's been a while, it might be cancelled
                # Check if order was created more than 1 hour ago
                order_age_hours = (datetime.now(timezone.utc) - trade_entry.entry_time).total_seconds() / 3600
                if not order_found and order_age_hours > 1:
                    logger.warning(f"⚠️ PENDING order not found in recent orders: {trade_entry.symbol} (age: {order_age_hours:.1f}h)")
                    # Could optionally mark as cancelled after a certain time
            
            # ✅ Monitor every 5 minutes (300 seconds)
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"❌ Error in trade lifecycle monitoring: {e}")
            logger.error(f"Error details: {traceback.format_exc()}")
            await asyncio.sleep(300)  # Still wait 5 minutes on error

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global signal_processor, session_manager, sheets_service
    
    try:
        logger.info("Starting Bybit Trading Bot...")
        
        # Initialize core services
        signal_processor = SignalProcessor()
        
        # Initialize session manager with bybit service
        session_manager = SilverBulletSessionManager(signal_processor.bybit_service)
        
        # Initialize Google Sheets service
        sheets_service = await initialize_sheets_service()
        
        # Connect sheets service to signal processor
        if sheets_service and signal_processor:
            signal_processor.set_sheets_service(sheets_service)
            logger.info("🔗 Connected sheets service to signal processor")
        
        logger.info("All services initialized successfully")
        
        # Start background tasks
        asyncio.create_task(session_manager.monitor_sessions())
        logger.info("🎯 Silver Bullet session monitoring started")
        
        if sheets_service:
            asyncio.create_task(monitor_trade_lifecycle())
            logger.info("📊 Trade lifecycle monitoring started")
        
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    global monitoring_active
    logger.info("Shutting down Bybit Trading Bot...")
    monitoring_active = False

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "services": {
            "signal_processor": signal_processor is not None,
            "session_manager": session_manager is not None,
            "sheets_service": sheets_service is not None,
            "trade_monitoring": monitoring_active
        }
    }

# Session management endpoints
@app.get("/sessions/status")
async def get_session_status():
    """Get current Silver Bullet session status."""
    if not session_manager:
        raise HTTPException(status_code=503, detail="Session manager not initialized")
    
    return session_manager.get_session_status()

@app.post("/sessions/cancel-orders")
async def manual_cancel_orders():
    """Manually trigger Silver Bullet order cancellation."""
    if not session_manager:
        raise HTTPException(status_code=503, detail="Session manager not initialized")
    
    try:
        result = await session_manager.cancel_session_orders()
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Manual cancellation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sessions/debug-orders")
async def debug_silver_bullet_orders():
    """Debug endpoint to check all current orders and Silver Bullet detection."""
    if not session_manager:
        raise HTTPException(status_code=503, detail="Session manager not initialized")
    
    try:
        # Get all current orders for analysis
        orders_analysis = await session_manager.get_silver_bullet_orders_for_cancellation()
        
        # Also get a sample of recent orders for comparison
        recent_orders = await signal_processor.bybit_service.get_recent_orders(limit=50)
        open_orders = [order for order in recent_orders if order.get('status') == 'open']
        
        # Analyze each open order
        order_analysis = []
        for order in open_orders:
            order_link_id = order.get('clientOrderId', order.get('info', {}).get('orderLinkId', ''))
            symbol = order.get('symbol', '')
            
            # Test the detection logic
            is_silver_bullet = session_manager._is_silver_bullet_order(order_link_id)
            
            order_analysis.append({
                'order_id': order.get('id'),
                'order_link_id': order_link_id,
                'symbol': symbol,
                'side': order.get('side'),
                'amount': order.get('amount'),
                'price': order.get('price'),
                'is_silver_bullet': is_silver_bullet,
                'analysis': {
                    'has_priority_1': order_link_id.startswith('prio1_') or order_link_id.startswith('p1_'),
                    'has_silver_keyword': any(keyword in order_link_id.lower() for keyword in 
                                            ['silver_bullet', 'silverbullet', '_sb_', 'ict_strategy', 'ict_', 'silver'])
                }
            })
        
        return {
            "silver_bullet_orders_found": len(orders_analysis),
            "total_open_orders": len(open_orders),
            "order_analysis": order_analysis,
            "silver_bullet_orders": orders_analysis
        }
        
    except Exception as e:
        logger.error(f"Debug orders failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Google Sheets endpoints
@app.get("/sheets/status")
async def get_sheets_status():
    """Get Google Sheets integration status."""
    if not sheets_service:
        return {"enabled": False, "message": "Sheets service not initialized"}
    
    try:
        status = await sheets_service.get_status()
        return {"enabled": True, "status": status}
    except Exception as e:
        return {"enabled": False, "error": str(e)}

@app.post("/sheets/test")
async def test_sheets_integration():
    """Test Google Sheets integration."""
    if not sheets_service:
        raise HTTPException(status_code=503, detail="Sheets service not initialized")
    
    try:
        result = await sheets_service.test_connection()
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Sheets test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Trading webhook endpoint
@app.post("/webhook/tradingview")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive and process TradingView webhook signals."""
    try:
        # Get the raw request body
        body = await request.body()
        
        if not body:
            logger.warning("Received empty webhook body")
            raise HTTPException(status_code=400, detail="Empty request body")
        
        # Parse JSON
        try:
            webhook_data = json.loads(body.decode('utf-8'))
            logger.info(f"Received webhook data: {webhook_data}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook: {e}")
            logger.error(f"Raw body: {body.decode('utf-8', errors='ignore')}")
            raise HTTPException(status_code=400, detail="Invalid JSON format")
        
        # Validate the signal
        try:
            signal = TradingViewSignal(**webhook_data)
            logger.info(f"Validated signal: {signal.model_dump_json()}")
        except Exception as e:
            logger.error(f"Signal validation failed: {e}")
            logger.error(f"Webhook data: {webhook_data}")
            raise HTTPException(status_code=400, detail=f"Invalid signal format: {str(e)}")
        
        # Check signal lag
        if signal.trigger_time:
            current_time = int(time.time() * 1000)
            lag_ms = current_time - int(signal.trigger_time)
            lag_seconds = lag_ms / 1000
            
            logger.info(f"Signal lag: {lag_seconds:.1f}s")
            
            if lag_seconds > signal.max_lag:
                logger.warning(f"Signal rejected due to high lag: {lag_seconds:.1f}s > {signal.max_lag}s")
                return JSONResponse(
                    status_code=202,
                    content={"status": "rejected", "reason": "signal_too_old", "lag_seconds": lag_seconds}
                )
        
        # Process signal in background
        background_tasks.add_task(process_signal_background, signal)
        
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "message": "Signal queued for processing"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")

async def get_current_session_type():
    """Get the current Silver Bullet session type."""
    try:
        if session_manager:
            status = session_manager.get_session_status()
            if status.get('in_session'):
                return status.get('session_name', 'Unknown')
        return "Outside Session"
    except Exception:
        return "Unknown"

async def process_signal_background(signal: TradingViewSignal):
    """Process trading signal in background."""
    try:
        logger.info(f"Processing signal in background task: {signal.symbol} {signal.side} (strategy: {signal.strategy_id})")
        
        if not signal_processor:
            logger.error("Signal processor not initialized")
            return
        
        # Process the signal
        result = await signal_processor.process_signal(signal)
        logger.info(f"Signal processing result: {result}")
        
        # ✅ NEW APPROACH: Journal immediately when order is placed with PENDING status
        if sheets_service and result.get('success') and 'order' in result:
            try:
                # Extract position ID from order result
                order_info = result.get('order', {})
                position_id = order_info.get('clientOrderId') or order_info.get('id') or order_info.get('info', {}).get('orderLinkId', '')
                
                if position_id:
                    # Calculate risk amount from VaR
                    risk_amount = result.get('risk_amount', 0)
                    
                    # Get session type
                    session_type = await get_current_session_type()
                    logger.debug(f"Session type for {signal.symbol}: {session_type}")
                    
                    # Journal the order as PENDING
                    await sheets_service.log_trade_entry(
                        trade_id=position_id,
                        symbol=signal.symbol,
                        strategy=signal.strategy_id or "unknown",
                        priority=signal.priority or 2,
                        side=signal.side,
                        entry_price=signal.entry,
                        quantity=result.get('quantity', 0),
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        order_id=position_id,
                        session_type=session_type,
                        risk_amount=risk_amount,
                        status="PENDING"  # Order placed but not filled yet
                    )
                    
                    logger.info(f"📝 Order journaled as PENDING: {signal.symbol} {signal.side} @ {signal.entry} (ID: {position_id})")
                else:
                    logger.warning("No position ID found in order result - cannot journal")
                    
            except Exception as e:
                logger.error(f"❌ Error journaling order: {e}")
                logger.error(f"Error details: {traceback.format_exc()}")
        
        logger.info(f"✅ Order processing complete - monitoring will track state transitions")
        
    except Exception as e:
        logger.error(f"Error processing signal in background: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")

# Custom OpenAPI schema
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Bybit Trading Bot API",
        version="0.1.0",
        description="API for managing Bybit trading bot operations",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

def start():
    """Start the FastAPI application with uvicorn."""
    uvicorn.run(
        "src.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=True
    )

if __name__ == "__main__":
    start() 