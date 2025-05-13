import sys
from pathlib import Path
from loguru import logger

class LoggingService:
    _instance = None

    def __new__(cls, config_manager=None):
        if cls._instance is None:
            cls._instance = super(LoggingService, cls).__new__(cls)
            # Initialize logger only once
            cls._instance.initialize_logger(config_manager)
        return cls._instance

    def initialize_logger(self, config_manager=None):
        logger.remove() # Remove default handler

        log_level = "INFO" # Default level
        # File logging parameters removed

        if config_manager:
            log_cfg = config_manager.get_logging_config()
            log_level = log_cfg.get("log_level", "INFO").upper()
            # File logging parameters are ignored here now

        # --- Configure Console Sink --- 
        logger.add(
            sys.stderr,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=True
        )

        # --- File Sink Removed --- 
        # No longer adding a file sink based on config

        self.logger = logger
        self.logger.info(f"Logging initialized. Console Level: {log_level}")

    def get_logger(self, name="Default"):
        """Returns a logger instance bound with the given name."""
        return self.logger.bind(name=name)

# --- Global Instance ---
# Attempt to initialize with None initially, requires calling initialize_logger later if needed
# Or assume config_manager is passed during initial import somewhere (like in main)
logger_instance = LoggingService().logger # Provide the configured logger instance

if __name__ == '__main__':
    # Example Usage:
    # To run this directly for testing, you might need to adjust imports if config_manager is not found
    # One way is to ensure your PYTHONPATH includes the project root when running from src/
    # Or temporarily modify the import: from config_manager import config_manager

    test_logger = logger_instance.bind(name="TestLogger")

    logger_instance.debug("This is a debug message.") # Won't show if level is INFO
    logger_instance.info("This is an info message.")
    test_logger.info("This is an info message from TestLogger.")
    logger_instance.warning("This is a warning message.")
    logger_instance.error("This is an error message.")
    logger_instance.critical("This is a critical message.")

    try:
        1 / 0
    except ZeroDivisionError:
        logger_instance.exception("Caught an exception!")

    print(f"\nCheck the console output and the log file at: {config_manager.get('logging.log_file')}") 