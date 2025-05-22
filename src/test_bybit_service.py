"""
Test script for the Bybit service.
"""

import asyncio
import sys
from src.bybit_service import BybitService
from src.config import logger

async def test_bybit_service():
    """Test the Bybit service."""
    try:
        logger.info("Starting Bybit service test...")
        
        # Initialize the service
        service = BybitService()
        logger.info("Bybit service initialized successfully.")
        
        # Test symbol normalization
        test_symbol = "BTCUSDT.P"
        normalized_symbol = service.normalize_symbol(test_symbol)
        logger.info(f"Symbol normalization: {test_symbol} -> {normalized_symbol}")
        
        # Test balance fetching
        try:
            balance = await service.get_usdt_balance()
            logger.info(f"USDT Balance: {balance}")
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
        
        # Test getting instrument info for a common symbol
        symbol = "BTCUSDT"
        try:
            instrument_info = await service.get_instrument_info(symbol)
            logger.info(f"Got instrument info for {symbol}:")
            logger.info(f"  Precision: {instrument_info['precision']}")
            logger.info(f"  Limits: {instrument_info['limits']}")
            
            # If 'leverage' is available, also print it
            if 'info' in instrument_info and 'leverage' in instrument_info['info']:
                logger.info(f"  Leverage: {instrument_info['info']['leverage']}")
            
            # If 'leverageFilter' is available, also print max leverage
            if 'info' in instrument_info and 'leverageFilter' in instrument_info['info']:
                max_leverage = instrument_info['info']['leverageFilter']['maxLeverage']
                logger.info(f"  Max Leverage: {max_leverage}")
            
        except Exception as e:
            logger.error(f"Error getting instrument info: {e}")
        
        logger.info("Bybit service test completed.")
        return True
    
    except Exception as e:
        logger.error(f"Error in Bybit service test: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_bybit_service())
    sys.exit(0 if result else 1) 