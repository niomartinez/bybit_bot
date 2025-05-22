# Bybit Trading Bot

A webhook-based trading bot that executes trades on Bybit based on TradingView signals. Designed to work with the ICT 2022 Mentorship Model Strategy.

## Features

- Receive webhook signals from TradingView alert
- Process signals asynchronously
- Fetch instrument details from Bybit API
- Set maximum leverage for each trading pair
- Calculate order quantity based on Value at Risk (VaR)
- Place limit orders with stop-loss and take-profit levels
- Robust error handling and logging

## Requirements

- Python 3.9+
- Bybit account with API keys (with "Contract - Orders & Positions" permissions)
- TradingView account (for sending webhook alerts)

## Installation

1. Clone this repository:

```bash
git clone https://github.com/yourusername/bybit_bot.git
cd bybit_bot
```

2. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the dependencies:

```bash
pip install -r requirements.txt
```

4. Set up your environment variables in the `.env` file:

```
MAINNET_LIVE_BYBIT_API_KEY=your_api_key
MAINNET_LIVE_BYBIT_API_SECRET=your_api_secret
```

5. Configure the bot settings in `config.json`:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8000
  },
  "bybit_api": {
    "category": "linear",
    "default_time_in_force": "GTC",
    "max_leverage_cap": null
  },
  "risk_management": {
    "var_type": "fixed_amount",
    "var_value": 1.0,
    "portfolio_currency": "USDT"
  },
  "logging": {
    "level": "INFO",
    "file": "logs/trading_bot.log",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  }
}
```

## Usage

1. Start the bot:

```bash
python run.py
```

2. Set up TradingView alerts with webhook URL:
   - Webhook URL: `http://your_server_address:8001/webhook/tradingview`
   - Format: JSON
   - Example alert message:
```json
{
  "symbol": "{{ticker}}",
  "side": "{{strategy.order.action}}",
  "entry": "{{strategy.order.price}}",
  "stop_loss": "{{strategy.order.stop_price}}",
  "take_profit": "{{strategy.order.alert_message}}",
  "trigger_time": "{{timenow}}",
  "max_lag": "20",
  "order_type": "limit"
}
```

3. The bot will receive the webhook, process it, and place the order on Bybit.

## Endpoints

- `GET /`: Health check endpoint
- `GET /health`: Health check endpoint
- `POST /webhook/tradingview`: Webhook endpoint for TradingView signals
- `POST /webhook/test`: Test endpoint for manually testing signal processing

## Testing

You can test the webhook endpoint with cURL:

```bash
curl -X POST http://localhost:8001/webhook/test \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT.P",
    "side": "long",
    "entry": 65000.0,
    "stop_loss": 64000.0,
    "take_profit": 67000.0,
    "trigger_time": "1747778400208",
    "max_lag": 20,
    "order_type": "limit"
  }'
```

## Risk Management

The bot uses a Value at Risk (VaR) approach to risk management:

- `fixed_amount`: Always risk a fixed amount of USDT per trade (e.g., 1 USDT)
- `portfolio_percentage`: Risk a percentage of your portfolio per trade (e.g., 1% of your USDT balance)

## Deployment

For production deployment, consider using:

- A reverse proxy like Nginx
- A process manager like Supervisor or PM2
- Expose the webhook endpoint via a proper domain with SSL

## License

[MIT License](LICENSE)

## Disclaimer

This bot is for educational purposes only. Use at your own risk. Trading involves substantial risk, and you can lose a substantial amount of money. The bot author is not responsible for any financial losses. 