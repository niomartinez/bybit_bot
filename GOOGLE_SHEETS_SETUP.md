# Google Sheets Trade Journaling Setup

## Overview

The Bybit Trading Bot now includes automatic trade journaling to Google Sheets. This feature logs all trades in real-time, providing comprehensive analytics and record-keeping for your trading activities.

## Features

✅ **Automatic Trade Logging**: Every trade is automatically logged to Google Sheets  
✅ **Real-time Updates**: Trade entries and exits are updated in real-time  
✅ **Performance Analytics**: Built-in statistics and performance metrics  
✅ **Strategy Breakdown**: Track performance by strategy  
✅ **Session Tracking**: Special handling for Silver Bullet sessions  
✅ **Data Backup**: Automatic backup functionality  
✅ **Error Resilience**: Continues trading even if Sheets is unavailable  

## Setup Instructions

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google Sheets API:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Sheets API"
   - Click "Enable"

### Step 2: Create Service Account

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "Service Account"
3. Fill in the service account details:
   - **Name**: `bybit-trading-bot`
   - **Description**: `Service account for Bybit trading bot Google Sheets integration`
4. Click "Create and Continue"
5. Skip role assignment (click "Continue")
6. Click "Done"

### Step 3: Generate Credentials

1. Click on the created service account
2. Go to the "Keys" tab
3. Click "Add Key" > "Create New Key"
4. Select "JSON" format
5. Click "Create"
6. Save the downloaded JSON file as `credentials.json` in your bot's root directory

### Step 4: Create Google Spreadsheet

1. Go to [Google Sheets](https://sheets.google.com/)
2. Create a new spreadsheet
3. Name it "Trading Journal" (or your preferred name)
4. Copy the spreadsheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/[SPREADSHEET_ID]/edit
   ```
5. Share the spreadsheet with your service account:
   - Click "Share" button
   - Add the service account email (found in `credentials.json` as `client_email`)
   - Give "Editor" permissions

### Step 5: Configure the Bot

1. Open `config.json`
2. Update the Google Sheets configuration:
   ```json
   {
     "google_sheets": {
       "enabled": true,
       "spreadsheet_id": "YOUR_SPREADSHEET_ID_HERE",
       "worksheet_name": "Trade Journal",
       "credentials_file": "credentials.json"
     }
   }
   ```

### Step 6: Install Dependencies

```bash
pip install -r requirements.txt
```

The following packages will be installed for Google Sheets integration:
- `google-auth==2.36.0`
- `google-auth-oauthlib==1.2.1`
- `google-auth-httplib2==0.2.0`
- `google-api-python-client==2.156.0`
- `gspread==6.1.4`

## Spreadsheet Structure

The bot automatically creates the following columns in your spreadsheet:

| Column | Field | Description |
|--------|-------|-------------|
| A | Trade ID | Unique identifier for each trade |
| B | Symbol | Trading pair (e.g., BTCUSDT) |
| C | Strategy | Strategy name (e.g., silver_bullet) |
| D | Priority | Order priority (1-5) |
| E | Entry Time | When the trade was opened |
| F | Entry Price | Entry price |
| G | Side | Long or Short |
| H | Quantity | Position size |
| I | Exit Time | When the trade was closed |
| J | Exit Price | Exit price |
| K | Exit Reason | TP/SL/Manual |
| L | Stop Loss | Stop loss price |
| M | Take Profit | Take profit price |
| N | Risk Amount | Risk amount in USD |
| O | P&L USD | Profit/Loss in USD |
| P | P&L % | Profit/Loss percentage |
| Q | Duration (min) | Trade duration in minutes |
| R | Session Type | Silver Bullet session type |
| S | Market Conditions | Market context |
| T | Status | OPEN/CLOSED/CANCELLED |
| U | Notes | Additional notes |
| V | Created At | Record creation timestamp |
| W | Updated At | Last update timestamp |

## API Endpoints

### Check Journal Status
```bash
curl http://localhost:8001/journal/status
```

### Get Trade Statistics
```bash
curl http://localhost:8001/journal/statistics
```

### Create Backup
```bash
curl -X POST http://localhost:8001/journal/backup
```

## Example API Responses

### Journal Status
```json
{
  "connected": true,
  "spreadsheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
  "worksheet_name": "Trade Journal",
  "last_sync": "2024-01-15 10:30:45",
  "active_trades": 3,
  "credentials_file": "credentials.json"
}
```

### Trade Statistics
```json
{
  "total_trades": 45,
  "open_trades": 3,
  "closed_trades": 42,
  "total_pnl": 1250.75,
  "win_rate": 68.5,
  "winning_trades": 29,
  "losing_trades": 13,
  "strategy_breakdown": {
    "silver_bullet": {
      "count": 25,
      "pnl": 850.25
    },
    "default": {
      "count": 20,
      "pnl": 400.50
    }
  },
  "last_updated": "2024-01-15 10:30:45"
}
```

## Troubleshooting

### Common Issues

#### 1. "Google Sheets credentials file not found"
- Ensure `credentials.json` is in the bot's root directory
- Check the file path in `config.json`

#### 2. "Google authentication error"
- Verify the service account has access to the spreadsheet
- Check that the Google Sheets API is enabled
- Ensure the credentials file is valid JSON

#### 3. "Spreadsheet not found"
- Verify the spreadsheet ID in `config.json`
- Ensure the service account has "Editor" permissions
- Check that the spreadsheet exists and is accessible

#### 4. "Worksheet not found"
- The bot will automatically create the worksheet if it doesn't exist
- Ensure the worksheet name in `config.json` matches exactly

### Debug Mode

To enable detailed logging for Google Sheets operations:

1. Set logging level to DEBUG in `config.json`:
   ```json
   {
     "logging": {
       "level": "DEBUG"
     }
   }
   ```

2. Check logs for Google Sheets related messages:
   ```bash
   tail -f logs/trading_bot.log | grep -E "(📝|📊|Google Sheets)"
   ```

## Security Considerations

1. **Credentials Protection**: Keep `credentials.json` secure and never commit it to version control
2. **Service Account Permissions**: Only grant necessary permissions to the service account
3. **Spreadsheet Access**: Limit spreadsheet sharing to essential users only
4. **Regular Backups**: Use the backup endpoint regularly to create local copies

## Optional: Disable Google Sheets

If you want to disable Google Sheets integration:

```json
{
  "google_sheets": {
    "enabled": false
  }
}
```

The bot will continue to function normally without trade journaling.

## Advanced Configuration

### Custom Worksheet Name
```json
{
  "google_sheets": {
    "worksheet_name": "My Custom Journal"
  }
}
```

### Alternative Credentials Location
```json
{
  "google_sheets": {
    "credentials_file": "path/to/my/credentials.json"
  }
}
```

## Data Analysis

Once your trades are logged to Google Sheets, you can:

1. **Create Charts**: Use Google Sheets' built-in charting tools
2. **Pivot Tables**: Analyze performance by strategy, symbol, or time period
3. **Conditional Formatting**: Highlight winning/losing trades
4. **Export Data**: Download as CSV/Excel for external analysis
5. **Share Reports**: Create shareable performance reports

## Support

If you encounter issues with Google Sheets integration:

1. Check the troubleshooting section above
2. Review the bot logs for error messages
3. Verify your Google Cloud setup
4. Test the API endpoints manually

The bot will continue trading even if Google Sheets is unavailable, ensuring no interruption to your trading operations. 