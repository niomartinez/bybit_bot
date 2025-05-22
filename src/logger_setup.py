"""
Logger setup for the trading bot.
"""

import logging
import os
import sys
from pathlib import Path


def setup_logger(level="INFO", log_file=None, log_format=None):
    """
    Set up the logger for the application.
    
    Args:
        level (str): Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file (str): Path to the log file
        log_format (str): Format for the log messages
    
    Returns:
        logging.Logger: Configured logger
    """
    # Set up default values
    level = getattr(logging, level.upper(), logging.INFO)
    log_format = log_format or "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Create logger
    logger = logging.getLogger("bybit_bot")
    logger.setLevel(level)
    
    # Remove existing handlers to avoid duplicates
    if logger.handlers:
        logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(log_format)
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Create file handler if log_file is provided
    if log_file:
        # Create directory if it doesn't exist
        log_dir = os.path.dirname(log_file)
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    logger.info(f"Logger initialized with level: {logging.getLevelName(level)}")
    return logger 