"""
Simple test script to verify configuration loading.
"""

import sys
from src.config import config, get_api_credentials

def test_config():
    """Test the configuration loading."""
    print("\nTesting configuration loading...")
    
    # Print server config
    print(f"\nServer Configuration:")
    print(f"  Host: {config.server.host}")
    print(f"  Port: {config.server.port}")
    
    # Print Bybit API config
    print(f"\nBybit API Configuration:")
    print(f"  Category: {config.bybit_api.category}")
    print(f"  Time in Force: {config.bybit_api.default_time_in_force}")
    print(f"  Max Leverage Cap: {config.bybit_api.max_leverage_cap}")
    
    # Print Risk Management config
    print(f"\nRisk Management Configuration:")
    print(f"  VaR Type: {config.risk_management.var_type}")
    print(f"  VaR Value: {config.risk_management.var_value}")
    print(f"  Portfolio Currency: {config.risk_management.portfolio_currency}")
    
    # Print Logging config
    print(f"\nLogging Configuration:")
    print(f"  Level: {config.logging.level}")
    print(f"  File: {config.logging.file}")
    print(f"  Format: {config.logging.format}")
    
    # Test API credentials
    try:
        api_key, api_secret = get_api_credentials()
        # Mask all but the first and last 4 characters of the API key
        masked_key = api_key[:4] + '*' * (len(api_key) - 8) + api_key[-4:]
        # Mask all but the first and last 4 characters of the API secret
        masked_secret = api_secret[:4] + '*' * (len(api_secret) - 8) + api_secret[-4:]
        
        print(f"\nAPI Credentials:")
        print(f"  API Key: {masked_key}")
        print(f"  API Secret: {masked_secret}")
        print("\nConfiguration and API credentials loaded successfully!")
    except Exception as e:
        print(f"\nError loading API credentials: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = test_config()
    sys.exit(0 if success else 1) 