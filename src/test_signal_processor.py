"""
Test script for the signal processor.
"""

import asyncio
import sys
import json
from src.signal_processor import SignalProcessor
from src.models import TradingViewSignal
from src.config import logger

async def test_signal_processor():
    """Test the signal processor with a mock signal."""
    try:
        logger.info("Starting signal processor test...")
        
        # Create a mock signal
        # Sample: {"symbol":"SOLUSDT.P","side":"short","entry":"167.98","stop_loss":"169.6598","take_profit":"162.9406","trigger_time":"1747778400208","max_lag":"20","order_type":"test_short"}
        mock_signal_data = {
            "symbol": "BTCUSDT.P",
            "side": "long",
            "entry": 65000.0,  # Current BTC price is around 65k
            "stop_loss": 64000.0,  # $1000 below entry
            "take_profit": 67000.0,  # $2000 above entry
            "trigger_time": "1747778400208",
            "max_lag": 20,
            "order_type": "limit"
        }
        
        # Create the signal object
        signal = TradingViewSignal(**mock_signal_data)
        logger.info(f"Created mock signal: {signal.model_dump_json()}")
        
        # Initialize the signal processor
        processor = SignalProcessor()
        logger.info("Signal processor initialized.")
        
        # Process the signal (don't actually place an order)
        logger.info("Note: We're using a mock signal for testing. No actual order will be placed.")
        # Enable the following line if you want to actually test the order placement:
        # result = await processor.process_signal(signal)
        # logger.info(f"Signal processing result: {result}")
        
        # Instead, test the individual components:
        
        # Test signal normalization
        symbol = processor.bybit_service.normalize_symbol(signal.symbol)
        logger.info(f"Normalized symbol: {symbol}")
        
        # Test getting instrument info
        try:
            instrument_info = await processor.bybit_service.get_instrument_info(symbol)
            logger.info(f"Got instrument info for {symbol}")
            
            # Test max leverage extraction
            max_leverage = processor._get_max_leverage(instrument_info)
            logger.info(f"Max leverage: {max_leverage}")
            
            # Test VAR calculation (don't actually set leverage)
            var_amount = await processor._calculate_var()
            logger.info(f"VaR amount: {var_amount} USDT")
            
            # Test quantity calculation
            quantity = processor._calculate_quantity(
                symbol=symbol,
                instrument_info=instrument_info,
                entry_price=signal.entry,
                stop_loss=signal.stop_loss,
                var_amount=var_amount,
                max_leverage=max_leverage
            )
            logger.info(f"Calculated quantity: {quantity}")
            
            # Print the params that would be used for the order
            order_side = "Buy" if signal.side == "long" else "Sell"
            logger.info(f"Order params: {symbol} {order_side} {quantity} @ {signal.entry} (SL: {signal.stop_loss}, TP: {signal.take_profit})")
            
        except Exception as e:
            logger.error(f"Error in instrument info or calculation steps: {e}")
        
        logger.info("Signal processor test completed.")
        return True
        
    except Exception as e:
        logger.error(f"Error in signal processor test: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_signal_processor())
    sys.exit(0 if result else 1) 