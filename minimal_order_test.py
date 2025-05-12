# minimal_order_test.py (refined)
import asyncio
import ccxt.async_support as ccxt
import os
from dotenv import load_dotenv
import json # For pretty printing dicts
import re # For parsing error string

async def main():
    load_dotenv(".env") 

    api_key = os.getenv("MAINNET_LIVE_BYBIT_API_KEY")
    api_secret = os.getenv("MAINNET_LIVE_BYBIT_API_SECRET")

    if not api_key or not api_secret:
        print("API Key or Secret not found in .env file for MAINNET_LIVE.")
        return

    # Match initialization from DataIngestionModule as closely as possible
    exchange_params = {
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'urls': { 
            'api': {
                'public': 'https://api.bybit.com', # Explicitly set
                'private': 'https://api.bybit.com',# Explicitly set
            }
        }, 
        'options': {
            'defaultType': 'future', 
        },
        'verbose': True  # <--- ADD THIS FOR CCXT HTTP LOGGING
    }
    exchange = ccxt.bybit(exchange_params)

    # --- Parameters from the failing log ---
    symbol_log = 'SOLUSDT' 
    order_type_log = 'Limit'
    side_log = 'buy'      # bullish
    qty_log = 0.2          
    price_log = 175.11     
    
    # --- Params dictionary as used in OrderExecutor ---
    # For V5, 'category' is important for derivatives.
    # 'linear' for USDT-margined contracts.
    params_log = {
        'timeInForce': 'GTC',
        'category': 'linear' 
    }
    # -----------------------------------------

    print(f"--- Minimal Test ---")
    print(f"Exchange Config: {exchange_params.get('options')}, URLs explicitly set.")
    print(f"Attempting to place order: {side_log} {qty_log} {symbol_log} @ {price_log}")
    print(f"With params: {params_log}")

    order_response = None
    exception_caught = None
    exception_type_name = None
    exception_args = None

    try:
        print(f"\nDEBUG: About to call exchange.create_order for {symbol_log}...")
        order_response = await exchange.create_order(
            symbol=symbol_log,
            type=order_type_log,
            side=side_log,
            amount=qty_log,
            price=price_log,
            params=params_log
        )
        print(f"DEBUG: Returned from exchange.create_order for {symbol_log}.")
        print(f"\nSUCCESS: Raw order response from create_order:\n{json.dumps(order_response, indent=2)}")

    except KeyError as ke:
        exception_caught = ke
        exception_type_name = type(ke).__name__
        exception_args = ke.args
        print(f"\nCAUGHT DIRECT KeyError in minimal_order_test.py: {ke}")
        print(f"  Type: {exception_type_name}")
        print(f"  Args: {exception_args}")
        if order_response:
            print(f"  Order response was (should be None if error in create_order): {json.dumps(order_response, indent=2)}")
            
    except ccxt.AuthenticationError as ae:
        exception_caught = ae
        exception_type_name = type(ae).__name__
        exception_args = ae.args
        print(f"\nCAUGHT CCXT AuthenticationError: {ae}")
    except ccxt.InvalidOrder as io:
        exception_caught = io
        exception_type_name = type(io).__name__
        exception_args = io.args
        print(f"\nCAUGHT CCXT InvalidOrder: {io}")
    except ccxt.NetworkError as ne:
        exception_caught = ne
        exception_type_name = type(ne).__name__
        exception_args = ne.args
        print(f"\nCAUGHT CCXT NetworkError: {ne}")
    except ccxt.ExchangeError as ee: # Catch other CCXT exchange errors
        exception_caught = ee
        exception_type_name = type(ee).__name__
        exception_args = ee.args
        print(f"\nCAUGHT CCXT ExchangeError: {type(ee).__name__} - {ee}")
    except Exception as e: # Catch any other non-CCXT exception
        exception_caught = e
        exception_type_name = type(e).__name__
        exception_args = e.args
        print(f"\nCAUGHT Generic Exception: {type(e).__name__} - {e}")
            
    finally:
        if exception_caught:
            print(f"\n--- Exception Details ---")
            print(f"Type: {exception_type_name}")
            print(f"Message: {str(exception_caught)}")
            print(f"Args: {exception_args}")
            if hasattr(exception_caught, '__cause__') and getattr(exception_caught, '__cause__'):
                print(f"Cause: {type(getattr(exception_caught, '__cause__')).__name__} - {str(getattr(exception_caught, '__cause__'))}")
            if hasattr(exception_caught, '__context__') and getattr(exception_caught, '__context__'):
                print(f"Context: {type(getattr(exception_caught, '__context__')).__name__} - {str(getattr(exception_caught, '__context__'))}")
            
            # Attempt to parse Bybit error from string representation of any caught ccxt error
            if isinstance(exception_caught, ccxt.NetworkError) or isinstance(exception_caught, ccxt.ExchangeError) :
                try:
                    error_str = str(exception_caught)
                    print(f"String of CCXT error: {error_str}")
                    if 'bybit {"retCode":' in error_str: # Note: no preceding 'bybit ' here for some errors
                        json_part_match = re.search(r'(\{"retCode\":.*?retMsg.*?\})', error_str)
                        if json_part_match:
                            json_part = json_part_match.group(1)
                            error_data = json.loads(json_part)
                            print(f"Parsed Bybit error from CCXT error string: {error_data}")
                        else:
                            print("Could not find JSON part in CCXT error string via regex.")
                    elif '{"retCode":' in error_str: # More generic check
                         json_part_match = re.search(r'(\{"retCode\":.*?retMsg.*?\})', error_str)
                         if json_part_match:
                            json_part = json_part_match.group(1)
                            error_data = json.loads(json_part)
                            print(f"Parsed Bybit error (generic check) from CCXT error string: {error_data}")
                         else:
                            print("Could not find JSON part in CCXT error string via generic regex.")

                except Exception as parse_e:
                    print(f"Could not parse Bybit error from CCXT error string: {parse_e}")

        print("\nClosing exchange connection.")
        await exchange.close()
        print("Minimal test finished.")

if __name__ == '__main__':
    asyncio.run(main()) 