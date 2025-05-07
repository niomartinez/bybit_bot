import json
import os
from dotenv import load_dotenv
from typing import Dict, Any, List, Optional

CONFIG_FILE_PATH = "config.json"

class ConfigManager:
    def __init__(self, config_file_path: str = CONFIG_FILE_PATH):
        self.config_file_path = config_file_path
        self.settings: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Loads the main JSON configuration file and then environment variables."""
        try:
            with open(self.config_file_path, 'r') as f:
                self.settings = json.load(f)
        except FileNotFoundError:
            print(f"Error: Configuration file not found at {self.config_file_path}")
            # Potentially raise an exception or exit
            return
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from {self.config_file_path}")
            # Potentially raise an exception or exit
            return

        # Load environment variables from the .env file specified in config
        dotenv_path = self.settings.get("secrets_env_file", ".env") 
        if load_dotenv(dotenv_path):
            print(f"Loaded secrets from {dotenv_path}")
        else:
            print(f"Warning: Could not load secrets from {dotenv_path}. File might be missing or empty.")

        # Overwrite or set API keys from environment variables
        # These keys in .env will take precedence if also defined (though unlikely) in config.json
        api_key_env = self.settings.get('cex_api', {}).get('api_key_env_var', 'BYBIT_API_KEY')
        api_secret_env = self.settings.get('cex_api', {}).get('api_secret_env_var', 'BYBIT_API_SECRET')
        self.settings['cex_api']['api_key'] = os.getenv(api_key_env)
        self.settings['cex_api']['api_secret'] = os.getenv(api_secret_env)

        # Determine active API URL based on testnet flag
        is_testnet = self.settings.get('cex_api', {}).get('testnet', False)
        api_urls = self.settings.get('cex_api', {}).get('api_urls', {})
        if is_testnet:
            self.settings['cex_api']['active_api_url'] = api_urls.get('testnet')
        else:
            self.settings['cex_api']['active_api_url'] = api_urls.get('mainnet')

        # Load notification secrets if enabled
        if self.settings.get('notifications', {}).get('enable_telegram', False):
            token_env_var = self.settings['notifications'].get('telegram_bot_token_env', 'TELEGRAM_BOT_TOKEN')
            chat_id_env_var = self.settings['notifications'].get('telegram_chat_id_env', 'TELEGRAM_CHAT_ID')
            self.settings['notifications']['telegram_bot_token'] = os.getenv(token_env_var)
            self.settings['notifications']['telegram_chat_id'] = os.getenv(chat_id_env_var)
        
        if self.settings.get('notifications', {}).get('enable_discord', False):
            webhook_env_var = self.settings['notifications'].get('discord_webhook_url_env', 'DISCORD_WEBHOOK_URL')
            self.settings['notifications']['discord_webhook_url'] = os.getenv(webhook_env_var)

    def get(self, key: str, default: Any = None) -> Any:
        """Access a configuration value using dot notation for nested keys."""
        keys = key.split('.')
        value = self.settings
        try:
            for k in keys:
                if isinstance(value, dict):
                    value = value[k]
                elif isinstance(value, list) and k.isdigit():
                    value = value[int(k)]
                else:
                    return default # Key path not valid
            return value
        except (KeyError, IndexError, TypeError):
            return default

    def get_cex_api_config(self) -> Dict[str, Any]:
        return self.get('cex_api', {})

    def get_logging_config(self) -> Dict[str, Any]:
        return self.get('logging', {})

    def get_portfolio_config(self) -> Dict[str, Any]:
        return self.get('portfolio', {})

    def get_strategy_params(self) -> Dict[str, Any]:
        return self.get('strategy_params', {})

    def get_risk_management_config(self) -> Dict[str, Any]:
        return self.get('risk_management', {})

    def get_notification_config(self) -> Dict[str, Any]:
        return self.get('notifications', {})
    
    def get_journaling_config(self) -> Dict[str, Any]:
        return self.get('journaling', {})

# Global instance (optional, but can be convenient)
config_manager = ConfigManager()

if __name__ == '__main__':
    # Example usage:
    print("--- CEX API Config ---")
    print(f"Exchange ID: {config_manager.get('cex_api.exchange_id')}")
    print(f"Testnet enabled: {config_manager.get('cex_api.testnet')}")
    print(f"Active API URL: {config_manager.get('cex_api.active_api_url')}")
    print(f"API Key Env Var: {config_manager.get('cex_api.api_key_env_var')}")
    print(f"API Secret Env Var: {config_manager.get('cex_api.api_secret_env_var')}")
    print(f"API Key: {config_manager.get('cex_api.api_key')}") # Should be loaded from .env
    print(f"API Secret: {config_manager.get('cex_api.api_secret')}") # Should be loaded from .env

    print("\n--- Logging Config ---")
    print(f"Log File: {config_manager.get('logging.log_file')}")
    print(f"Log Level: {config_manager.get('logging.log_level')}")

    print("\n--- Portfolio Config ---")
    print(f"Coins to Scan: {config_manager.get('portfolio.coins_to_scan')}")
    print(f"First coin: {config_manager.get('portfolio.coins_to_scan.0')}") # Example of accessing list item

    print("\n--- Strategy Params ---")
    print(f"Contextual Timeframe: {config_manager.get('strategy_params.timeframes.contextual')}")
    print(f"Fib Levels: {config_manager.get('strategy_params.fibonacci.levels_to_watch')}")

    print("\n--- Risk Management ---")
    print(f"Fixed Dollar Risk: {config_manager.get('risk_management.fixed_dollar_risk_per_trade')}")

    print("\n--- Notifications ---")
    print(f"Enable Telegram: {config_manager.get('notifications.enable_telegram')}")
    print(f"Telegram Token: {config_manager.get('notifications.telegram_bot_token')}") # Will be None if not set in .env

    print("\n--- Journaling ---")
    print(f"Journal Type: {config_manager.get('journaling.journal_file_type')}")

    # Test a non-existent key
    print(f"\nNon-existent key: {config_manager.get('some.non_existent.key', 'Default Value')}") 