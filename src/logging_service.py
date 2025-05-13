import sys
from loguru import logger
from pathlib import Path
import functools

# Ensure config_manager is imported. If this script is run directly, this might need adjustment
# For package execution (e.g. python -m src.main), this should be fine.
try:
    from .config_manager import config_manager
except ImportError:
    # Fallback for potential direct script execution or different project structures
    # This assumes config_manager.py is in the same directory or PYTHONPATH is set
    from config_manager import config_manager

# Define and patch the USER level on the global loguru logger ONCE.
logger.level("USER", no=25, color="<blue><bold>") # Icon removed from level definition for simplicity for now

def user_custom_method(self, message, *args, **kwargs):
    self.log("USER", message, *args, **kwargs)

# Bind the custom method to the Logger class if not already present
if not hasattr(logger.__class__, 'user'):
    logger.__class__.user = user_custom_method

class LoggingService:
    def __init__(self):
        self.log_config = config_manager.get_logging_config()
        self._setup_logger()

    def _setup_logger(self):
        logger.remove()  # Remove default handler

        # Simplified Console logger
        # For USER level, we'll rely on developers using logger.user() for concise messages.
        # The format string here applies to all levels shown on the console.
        # If log_level is USER, only USER and above (WARNING, ERROR, CRITICAL) will show.
        # If log_level is INFO, INFO and USER and above will show.
        # If log_level is DEBUG, all levels will show.
        
        log_level = self.log_config.get("log_level", "INFO").upper()
        
        console_format: str
        if log_level == "USER":
            # Icon removed from here as it caused KeyError if not in record
            console_format = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{message}</level>"
        elif log_level == "DEBUG":
            console_format = "<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        else: # INFO and other levels
            console_format = "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> - <level>{message}</level>"

        logger.add(
            sys.stderr,
            level=log_level, # This sets the *minimum* level to be displayed
            format=console_format
        )
        
        # File logger removed

        # Use logger.info for internal logging service messages, not logger.user
        logger.info(f"Logging service initialized. Console Log Level: {log_level}")
        if log_level == "USER":
            logger.user("User-friendly logging is active. Only essential messages will be shown.") # Now logger.user() should work

    def get_logger(self, name: str = None):
        # The .user method is now part of the main logger class, so all instances will have it.
        if name:
            return logger.bind(name=name)
        return logger

# Global instance
# Re-initialize to apply new USER level definition if script is re-run or module reloaded.
try:
    del logging_service
    del logger_instance
except NameError:
    pass # Was not defined yet

logging_service = LoggingService()
logger_instance = logging_service.get_logger()


if __name__ == '__main__':
    # Example Usage:
    # To test, you might need to ensure config.json is accessible and
    # potentially set 'logging': {'log_level': 'USER'} or 'INFO' or 'DEBUG' in it.

    # Assuming config_manager can load config.json from the current or parent dir
    # This __main__ block might need its own ConfigManager instance for isolated testing
    # or rely on the global one if structure allows.
    
    print(f"Testing logging with configured level: {config_manager.get('logging.log_level', 'INFO')}")

    test_logger_main = logging_service.get_logger(name="MainTest")
    test_logger_user = logging_service.get_logger(name="UserTest") # Name for non-USER logs from this instance

    logger_instance.debug("This is a global debug message.")
    logger_instance.info("This is a global info message.")
    logger_instance.user("This is a global USER message via logger_instance.user()!")
    logger_instance.warning("This is a global warning message.")
    logger_instance.error("This is a global error message.")
    
    test_logger_main.debug("This is a TestLogger (main) debug message.")
    test_logger_main.info("This is a TestLogger (main) info message.")
    test_logger_main.user("This is a TestLogger (main) USER message via .user() method!")
    
    # To correctly use .user() with a bound logger, ensure patching behavior or direct use
    # The patching in get_logger might make bound loggers' .user() calls appear from "USER_LOGS"
    # For specific naming with .user(), it's often clearer to use logger_instance.patch().user()
    # or ensure the patch in get_logger behaves as expected for bound loggers.
    # For simplicity in testing here:
    logger.user("This is a direct USER message via global logger.")
    
    test_logger_user.warning("This is a TestLogger (user-test) warning message.")


    try:
        1 / 0
    except ZeroDivisionError:
        logger_instance.exception("Caught an exception!")

    print(f"\\nConsole logging should reflect the configured log_level ('{config_manager.get('logging.log_level')}') and new formats.")
    print("File logging should be disabled.") 