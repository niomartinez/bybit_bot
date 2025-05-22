"""
Configuration loader for the trading bot.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
from src.models import BotConfig
from src.logger_setup import setup_logger

# Load environment variables from .env file
load_dotenv()

# Set up a basic logger before we have the full config
logger = setup_logger(level="INFO")


def load_config(config_path="config.json"):
    """
    Load configuration from a JSON file.
    
    Args:
        config_path (str): Path to the configuration file
    
    Returns:
        BotConfig: Configuration object
    """
    try:
        config_file = Path(config_path)
        if not config_file.exists():
            logger.error(f"Configuration file not found: {config_path}")
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(config_file, 'r') as f:
            config_data = json.load(f)
        
        # Validate configuration using Pydantic
        config = BotConfig(**config_data)
        logger.info(f"Configuration loaded successfully from {config_path}")
        return config
    
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing configuration file: {e}")
        raise
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        raise


def get_api_credentials():
    """
    Get Bybit API credentials from environment variables.
    
    Returns:
        tuple: (api_key, api_secret)
    """
    api_key = os.getenv("MAINNET_LIVE_BYBIT_API_KEY")
    api_secret = os.getenv("MAINNET_LIVE_BYBIT_API_SECRET")
    
    if not api_key or not api_secret:
        logger.error("Bybit API credentials not found in environment variables")
        raise ValueError("Bybit API credentials not found in environment variables")
    
    return api_key, api_secret


# Load configuration
config = load_config()

# Update logger with configuration
logger = setup_logger(
    level=config.logging.level,
    log_file=config.logging.file,
    log_format=config.logging.format
) 