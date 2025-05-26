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
        sheets_config_data = config.get("google_sheets", {})
        if not sheets_config_data.get("enabled", False):
            logger.info("📊 Google Sheets integration disabled in config")
            return None
        
        sheets_config = SheetsConfig(**sheets_config_data)
        sheets_service = SheetsService(sheets_config)
        
        # Test the connection
        await sheets_service.initialize_sheet()
        logger.info("✅ Google Sheets service initialized successfully")
        return sheets_service
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Google Sheets service: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        return None

async def monitor_trade_exits():
    """Background task to monitor for trade exits and journal them."""
    global monitoring_active, sheets_service, signal_processor
    
    if not sheets_service:
        logger.info("📊 Trade monitoring disabled - no sheets service")
        return
    
    logger.info("🔍 Starting trade exit monitoring for journaling...")
    monitoring_active = True
    
    # Track last known positions to detect exits
    last_positions = {}
    
    while monitoring_active:
        try:
            # Get current positions from Bybit
            current_positions = await signal_processor.bybit_service.get_all_positions()
            
            # Check for position exits (positions that were active but now closed)
            for symbol, last_pos in last_positions.items():
                current_pos = current_positions.get(symbol)
                
                # Position was closed
                if last_pos.get('size', 0) != 0 and (not current_pos or current_pos.get('size', 0) == 0):
                    logger.info(f"📝 Position exit detected for {symbol} - logging to sheets")
                    
                    # Get recent trade history for this symbol
                    try:
                        trades = await signal_processor.bybit_service.get_trade_history(symbol, limit=10)
                        
                        for trade in trades:
                            # Log the trade exit
                            await sheets_service.log_trade_exit(
                                symbol=symbol,
                                exit_price=float(trade.get('price', 0)),
                                exit_time=trade.get('timestamp'),
                                quantity=float(trade.get('amount', 0)),
                                pnl=float(trade.get('realizedPnl', 0)),
                                fee=float(trade.get('fee', 0))
                            )
                            
                    except Exception as e:
                        logger.error(f"❌ Error logging trade exit for {symbol}: {e}")
            
            # Update last known positions
            last_positions = current_positions.copy()
            
            # Check every 30 seconds
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"❌ Error in trade monitoring: {e}")
            await asyncio.sleep(60)  # Wait longer on error

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
            asyncio.create_task(monitor_trade_exits())
            logger.info("📊 Trade exit monitoring started")
        
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
        result = await session_manager.cancel_silver_bullet_orders()
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Manual cancellation failed: {e}")
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
        
        # If sheets service is available and order was placed, log the entry
        if sheets_service and result.get('success') and 'order' in result:
            try:
                await sheets_service.log_trade_entry(
                    symbol=signal.symbol,
                    side=signal.side,
                    entry_price=signal.entry,
                    quantity=result.get('quantity', 0),
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    strategy_id=signal.strategy_id,
                    order_id=result['order'].get('clientOrderId', ''),
                    timestamp=time.time()
                )
                logger.info(f"📝 Trade entry logged to Google Sheets for {signal.symbol}")
            except Exception as e:
                logger.error(f"❌ Failed to log trade entry to sheets: {e}")
        
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

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=config["server"]["host"],
        port=config["server"]["port"],
        reload=True
    ) 