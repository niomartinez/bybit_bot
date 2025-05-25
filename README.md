# Bybit Trading Bot

A webhook-based trading bot that executes trades on Bybit based on TradingView signals. Designed to work with the ICT 2022 Mentorship Model Strategy with Silver Bullet session management and automatic trade journaling.

## Features

### Core Trading Features
- Receive webhook signals from TradingView alerts
- Process signals asynchronously with priority-based order management
- Fetch instrument details from Bybit API
- Set maximum leverage for each trading pair
- Calculate order quantity based on Value at Risk (VaR)
- Place limit orders with stop-loss and take-profit levels
- Multi-strategy support with individual risk management

### Silver Bullet Session Management
- **Automatic Session Detection**: Tracks Silver Bullet sessions (3-4 AM, 10-11 AM, 2-3 PM NYC time)
- **Session-Based Order Cancellation**: Automatically cancels Silver Bullet orders 5 minutes after session ends
- **Priority-Based Order Management**: Handles order conflicts based on priority levels
- **Background Monitoring**: Continuous session monitoring without affecting trading operations

### Google Sheets Trade Journaling
- **Automatic Trade Logging**: Every trade is logged to Google Sheets in real-time
- **Performance Analytics**: Built-in statistics and performance metrics
- **Strategy Breakdown**: Track performance by individual strategies
- **Data Backup**: Automatic backup functionality with JSON exports
- **Real-time Updates**: Trade entries and exits updated automatically

### Advanced Features
- Robust error handling and comprehensive logging
- Multi-strategy configuration with individual settings
- Priority-based conflict resolution
- Session-aware trade management
- RESTful API for monitoring and control

## Requirements

- Python 3.9+
- Bybit account with API keys (with "Contract - Orders & Positions" permissions)
- TradingView account (for sending webhook alerts)
- Google Cloud account (optional, for Google Sheets integration)

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
    "port": 8001
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
  "multi_strategy": {
    "enabled": true,
    "strategy_configs": {
      "silver_bullet": {
        "var_multiplier": 1.0,
        "enabled": true
      }
    }
  },
  "google_sheets": {
    "enabled": false,
    "spreadsheet_id": "",
    "worksheet_name": "Trade Journal",
    "credentials_file": "credentials.json"
  }
}
```

## Google Sheets Setup (Optional)

For automatic trade journaling, follow the detailed setup guide:

📖 **[Google Sheets Setup Guide](GOOGLE_SHEETS_SETUP.md)**

Quick setup:
1. Create Google Cloud project and enable Sheets API
2. Create service account and download credentials
3. Create Google Spreadsheet and share with service account
4. Update `config.json` with spreadsheet ID and enable the feature

## Usage

1. Start the bot:

```bash
python run.py
```

2. Set up TradingView alerts with webhook URL:
   - Webhook URL: `http://your_server_address:8001/webhook/tradingview`
   - Format: JSON
   - Example Silver Bullet alert message:
```json
{
  "symbol": "{{ticker}}",
  "side": "{{strategy.order.action}}",
  "entry": "{{strategy.order.price}}",
  "stop_loss": "{{strategy.order.stop_price}}",
  "take_profit": "{{strategy.order.alert_message}}",
  "trigger_time": "{{timenow}}",
  "max_lag": "20",
  "order_type": "limit",
  "priority": 1,
  "strategy_id": "silver_bullet"
}
```

3. The bot will:
   - Receive and process the webhook
   - Place orders on Bybit with proper risk management
   - Log trades to Google Sheets (if enabled)
   - Monitor Silver Bullet sessions and cancel orders automatically

## API Endpoints

### Core Endpoints
- `GET /`: Basic information and available endpoints
- `GET /health`: Comprehensive health check with service status
- `POST /webhook/tradingview`: Main webhook endpoint for TradingView signals
- `POST /webhook/test`: Test endpoint for manual signal testing

### Silver Bullet Session Management
- `GET /sessions/status`: Current Silver Bullet session status
- `POST /sessions/cancel-orders`: Manually trigger order cancellation

### Google Sheets Trade Journal
- `GET /journal/status`: Google Sheets connection status
- `GET /journal/statistics`: Trade performance statistics
- `POST /journal/backup`: Create backup of all trades

## Testing

### Test Basic Webhook
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
    "order_type": "limit",
    "priority": 1,
    "strategy_id": "silver_bullet"
  }'
```

### Test Silver Bullet Session
```bash
# Check current session status
curl http://localhost:8001/sessions/status

# Manually trigger order cancellation (for testing)
curl -X POST http://localhost:8001/sessions/cancel-orders
```

### Test Google Sheets Integration
```bash
# Check journal status
curl http://localhost:8001/journal/status

# Get trade statistics
curl http://localhost:8001/journal/statistics

# Create backup
curl -X POST http://localhost:8001/journal/backup
```

### Run Comprehensive Tests
```bash
# Test session manager
python test_session_manager.py

# Test Google Sheets integration
python test_google_sheets.py
```

## Risk Management

The bot uses a sophisticated Value at Risk (VaR) approach:

- **Fixed Amount**: Always risk a fixed amount of USDT per trade
- **Portfolio Percentage**: Risk a percentage of your portfolio per trade
- **Strategy-Specific Multipliers**: Different risk levels per strategy
- **Priority-Based Conflicts**: Higher priority orders can override lower priority ones

## Silver Bullet Sessions

The bot automatically manages Silver Bullet trading sessions:

| Session | NYC Time | Cancellation Time |
|---------|----------|-------------------|
| London Open | 3:00-4:00 AM | 4:05 AM |
| AM Session | 10:00-11:00 AM | 11:05 AM |
| PM Session | 2:00-3:00 PM | 3:05 PM |

**Key Features:**
- Only cancels Priority 1 orders with Silver Bullet strategy identifiers
- Uses fixed NYC timezone for consistency
- Comprehensive logging and monitoring
- Manual override capabilities

## Multi-Strategy Configuration

Configure multiple strategies with individual settings:

```json
{
  "multi_strategy": {
    "enabled": true,
    "strategy_configs": {
      "silver_bullet": {
        "var_multiplier": 1.0,
        "max_leverage_override": null,
        "enabled": true
      },
      "ict_strategy_a": {
        "var_multiplier": 0.8,
        "max_leverage_override": 50,
        "enabled": true
      }
    }
  }
}
```

## Deployment

For production deployment:

1. **Reverse Proxy**: Use Nginx for SSL termination and load balancing
2. **Process Manager**: Use Supervisor or PM2 for process management
3. **Domain & SSL**: Expose webhook via proper domain with SSL certificate
4. **Monitoring**: Set up log monitoring and alerting
5. **Backups**: Regular backups of trade data and configuration

Example Nginx configuration:
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://localhost:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Documentation

- 📖 [Silver Bullet Session Cancellation](SILVER_BULLET_SESSION_CANCELLATION.md)
- 📊 [Google Sheets Setup Guide](GOOGLE_SHEETS_SETUP.md)
- 🧪 [Testing Documentation](test_session_manager.py)

## License

[MIT License](LICENSE)

## Disclaimer

This bot is for educational purposes only. Use at your own risk. Trading involves substantial risk, and you can lose a substantial amount of money. The bot author is not responsible for any financial losses.

**Important Notes:**
- Always test with small amounts first
- Monitor the bot's performance regularly
- Keep your API keys secure
- Understand the risks of automated trading
- The Silver Bullet session management is designed for specific ICT strategies 