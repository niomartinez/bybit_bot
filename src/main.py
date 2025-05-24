"""
FastAPI application for Bybit trading bot.
"""

import asyncio
import time
import traceback
import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from src.models import TradingViewSignal
from src.signal_processor import SignalProcessor
from src.bybit_service import BybitService
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
    allow_origins=["*"],  # In production, restrict this to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
bybit_service = None
signal_processor = None

@app.on_event("startup")
async def startup_event():
    """Startup event handler."""
    global bybit_service, signal_processor
    
    logger.info("Starting Bybit Trading Bot...")
    
    # Initialize services
    try:
        bybit_service = BybitService()
        signal_processor = SignalProcessor()
        logger.info("All services initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing services: {e}")
        # We don't raise here to allow the server to start even with initialization errors
        # This allows for graceful handling of service errors at runtime

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler."""
    logger.info("Shutting down Bybit Trading Bot...")

def custom_openapi():
    """Generate custom OpenAPI schema."""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Bybit Trading Bot API",
        version="0.1.0",
        description="This API provides endpoints for receiving trading signals from TradingView and executing trades on Bybit.",
        routes=app.routes,
    )
    
    # Add custom documentation
    openapi_schema["info"]["x-logo"] = {
        "url": "https://bybit.com/favicon.ico"
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

def get_signal_processor():
    """Dependency to get the SignalProcessor instance."""
    if signal_processor is None:
        logger.error("SignalProcessor not initialized")
        raise HTTPException(status_code=503, detail="Service not available")
    return signal_processor

@app.get("/")
async def root():
    """
    Root endpoint.
    
    Returns:
        dict: Basic information about the API
    """
    return {
        "message": "Bybit Trading Bot is running",
        "version": "0.1.0",
        "documentation": "/docs",
        "health": "/health"
    }

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        dict: Health status information
    """
    # Check if services are initialized
    services_status = {
        "bybit_service": bybit_service is not None,
        "signal_processor": signal_processor is not None
    }
    
    # Get basic info like uptime
    uptime = time.time() - app.state.start_time if hasattr(app.state, "start_time") else None
    
    return {
        "status": "healthy" if all(services_status.values()) else "degraded",
        "services": services_status,
        "uptime_seconds": uptime,
        "config": {
            "server": {
                "host": config.server.host,
                "port": config.server.port
            },
            "risk_management": {
                "var_type": config.risk_management.var_type,
                "portfolio_currency": config.risk_management.portfolio_currency
            }
        }
    }

async def process_signal_task(signal_processor: SignalProcessor, signal: TradingViewSignal):
    """
    Background task to process a TradingView signal.
    
    Args:
        signal_processor (SignalProcessor): The signal processor instance
        signal (TradingViewSignal): The signal to process
    """
    try:
        strategy_id = signal.strategy_id or "default"
        logger.info(f"Processing signal in background task: {signal.symbol} {signal.side} (strategy: {strategy_id})")
        
        result = await signal_processor.process_signal(signal)
        
        if result.get("success"):
            position_idx = result.get("position_idx", 0)
            position_mode = "one-way" if position_idx == 0 else ("buy hedge" if position_idx == 1 else "sell hedge")
            logger.info(f"Signal processing completed successfully: {signal.symbol} {signal.side} (strategy: {strategy_id}, mode: one-way)")
        else:
            logger.warning(f"Signal processing failed: {signal.symbol} {signal.side} (strategy: {strategy_id}) - {result.get('message')}")
            
        logger.info(f"Signal processing result: {result}")
    except Exception as e:
        stack_trace = traceback.format_exc()
        logger.error(f"Error processing signal in background task: {e}\n{stack_trace}")

@app.post("/webhook/tradingview", status_code=202)
async def webhook_tradingview(
    request: Request, 
    background_tasks: BackgroundTasks,
    signal_processor: SignalProcessor = Depends(get_signal_processor)
):
    """
    Webhook endpoint for TradingView signals.
    
    This endpoint receives trading signals from TradingView in JSON format and processes them asynchronously.
    The signal is validated and then passed to the signal processor for execution.
    
    Example payload:
    ```json
    {
        "symbol": "BTCUSDT.P",
        "side": "long",
        "entry": 65000.0,
        "stop_loss": 64000.0,
        "take_profit": 67000.0,
        "trigger_time": "1747778400208",
        "max_lag": 20,
        "order_type": "limit"
    }
    ```
    
    Args:
        request (Request): The incoming request
        background_tasks (BackgroundTasks): FastAPI background tasks
        signal_processor (SignalProcessor): Signal processor dependency
    
    Returns:
        JSONResponse: Acknowledgment of signal receipt
    """
    try:
        # Get request start time for latency calculation
        request_time = time.time()
        
        # Get the raw JSON data
        try:
            json_data = await request.json()
            logger.info(f"Received webhook data: {json_data}")
        except Exception as json_error:
            logger.error(f"Invalid JSON data: {json_error}")
            raise HTTPException(status_code=400, detail=f"Invalid JSON data: {str(json_error)}")
        
        # Validate the data against our model
        try:
            signal = TradingViewSignal(**json_data)
            logger.info(f"Validated signal: {signal.model_dump_json()}")
        except Exception as validation_error:
            logger.error(f"Invalid signal data: {validation_error}")
            raise HTTPException(status_code=400, detail=f"Invalid signal data: {str(validation_error)}")
        
        # Check if the signal is too old
        if hasattr(signal, 'trigger_time') and signal.trigger_time:
            try:
                # Parse trigger_time as milliseconds since epoch
                trigger_time = int(signal.trigger_time) / 1000  # Convert to seconds
                current_time = time.time()
                
                # Calculate lag
                lag_seconds = current_time - trigger_time
                
                # If max_lag is defined, check if signal is too old
                if hasattr(signal, 'max_lag') and signal.max_lag:
                    max_lag_seconds = int(signal.max_lag)
                    if lag_seconds > max_lag_seconds:
                        logger.warning(f"Signal too old: {lag_seconds:.1f}s > {max_lag_seconds}s max lag")
                        return JSONResponse(
                            status_code=200,  # Still return 200 to acknowledge receipt
                            content={
                                "message": "Signal received but not processed",
                                "reason": "Signal too old",
                                "lag_seconds": lag_seconds,
                                "max_lag_seconds": max_lag_seconds
                            }
                        )
                
                logger.info(f"Signal lag: {lag_seconds:.1f}s")
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse trigger_time or max_lag: {e}")
        
        # Process the signal in the background
        background_tasks.add_task(process_signal_task, signal_processor, signal)
        
        # Calculate response time
        response_time = (time.time() - request_time) * 1000  # Convert to milliseconds
        
        # Return a success response immediately
        return JSONResponse(
            status_code=202,  # Accepted
            content={
                "message": "Signal received and processing started",
                "symbol": signal.symbol,
                "side": signal.side,
                "strategy_id": signal.strategy_id or "default",
                "processing": "async",
                "response_time_ms": round(response_time, 2)
            }
        )
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    
    except Exception as e:
        stack_trace = traceback.format_exc()
        logger.error(f"Error processing webhook: {e}\n{stack_trace}")
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")

@app.post("/webhook/test", status_code=202)
async def webhook_test(
    signal: TradingViewSignal, 
    background_tasks: BackgroundTasks,
    signal_processor: SignalProcessor = Depends(get_signal_processor)
):
    """
    Test endpoint for TradingView signals with body validation.
    
    This endpoint is similar to /webhook/tradingview but accepts the signal directly in the request body,
    making it easier to test with tools like cURL or Postman.
    
    Args:
        signal (TradingViewSignal): The signal data
        background_tasks (BackgroundTasks): FastAPI background tasks
        signal_processor (SignalProcessor): Signal processor dependency
    
    Returns:
        JSONResponse: Acknowledgment of signal receipt
    """
    try:
        request_time = time.time()
        
        logger.info(f"Received test webhook: {signal.model_dump_json()}")
        
        # Process the signal in the background
        background_tasks.add_task(process_signal_task, signal_processor, signal)
        
        # Calculate response time
        response_time = (time.time() - request_time) * 1000  # Convert to milliseconds
        
        # Return a success response immediately
        return JSONResponse(
            status_code=202,  # Accepted
            content={
                "message": "Test signal received and processing started",
                "symbol": signal.symbol,
                "side": signal.side,
                "strategy_id": signal.strategy_id or "default",
                "processing": "async",
                "response_time_ms": round(response_time, 2)
            }
        )
    
    except Exception as e:
        stack_trace = traceback.format_exc()
        logger.error(f"Error processing test webhook: {e}\n{stack_trace}")
        raise HTTPException(status_code=500, detail=f"Error processing test webhook: {str(e)}")

def start():
    """Start the FastAPI application."""
    # Set the start time for uptime tracking
    app.state.start_time = time.time()
    
    uvicorn.run(
        "src.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    start() 