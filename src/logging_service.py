import sys
from loguru import logger
from pathlib import Path

from .config_manager import config_manager # Use absolute import if running as module, relative if script

class LoggingService:
    def __init__(self):
        self.log_config = config_manager.get_logging_config()
        self._setup_logger()

    def _setup_logger(self):
        logger.remove() # Remove default handler

        log_level = self.log_config.get("log_level", "INFO").upper()
        log_file_path_str = self.log_config.get("log_file", "logs/bot.log")
        
        log_file_path = Path(log_file_path_str)
        log_file_path.parent.mkdir(parents=True, exist_ok=True) # Ensure log directory exists

        # Console logger
        logger.add(
            sys.stderr, 
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
        
        # File logger
        logger.add(
            log_file_path_str,
            level=log_level,
            rotation=f"{self.log_config.get('log_rotation_size_mb', 10)} MB",
            retention=self.log_config.get('log_backup_count', 5),
            compression="zip", # Optional: compress rotated logs
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
        )
        
        logger.info(f"Logging service initialized. Level: {log_level}. File: {log_file_path_str}")

    def get_logger(self, name: str = None):
        if name:
            return logger.bind(name=name)
        return logger

# Global instance (optional, but can be convenient)
logging_service = LoggingService()
logger_instance = logging_service.get_logger()

if __name__ == '__main__':
    # Example Usage:
    # To run this directly for testing, you might need to adjust imports if config_manager is not found
    # One way is to ensure your PYTHONPATH includes the project root when running from src/
    # Or temporarily modify the import: from config_manager import config_manager

    test_logger = logging_service.get_logger("TestLogger")

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