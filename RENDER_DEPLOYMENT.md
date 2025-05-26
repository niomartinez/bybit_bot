# Render Deployment Guide

## Setting Up Google Sheets Integration on Render

### Step 1: Environment Variable Setup

In your Render dashboard, go to your service settings and add this environment variable:

**Key:** `GOOGLE_CREDENTIALS`  
**Value:** Copy the entire contents of your `credentials.json` file as a single line JSON string.

**Example:**
```json
{"type":"service_account","project_id":"your-project","private_key_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"...@your-project.iam.gserviceaccount.com","client_id":"...","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"...","universe_domain":"googleapis.com"}
```

### Step 2: Verify Configuration

Your `config.json` should have Google Sheets enabled:

```json
{
  "google_sheets": {
    "enabled": true,
    "spreadsheet_id": "your-spreadsheet-id",
    "worksheet_name": "Trade Journal",
    "backup_enabled": true,
    "backup_frequency_hours": 24
  }
}
```

### Step 3: Test Endpoints

After deployment, test these endpoints:

1. **Health Check:** `GET /health`
2. **Sheets Status:** `GET /sheets/status` 
3. **Sheets Test:** `POST /sheets/test`
4. **Session Status:** `GET /sessions/status`

### Step 4: Monitor Logs

Look for these log messages indicating successful initialization:

```
✅ Google Sheets service initialized successfully
🔗 Connected sheets service to signal processor
📊 Trade exit monitoring started
```

### Troubleshooting

**If you see "Invalid JSON data" errors:**
- Check that the `GOOGLE_CREDENTIALS` environment variable is properly formatted
- Ensure no extra spaces or line breaks in the JSON

**If sheets integration is disabled:**
- Verify `google_sheets.enabled` is `true` in config.json
- Check that the spreadsheet ID is correct

**If trade monitoring doesn't work:**
- Ensure the bot has active positions to monitor
- Check logs for position and trade history fetch errors 