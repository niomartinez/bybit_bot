# Silver Bullet Session-Based Order Cancellation

## Overview

This implementation adds automatic cancellation of Silver Bullet strategy orders when exiting Silver Bullet trading sessions. The system ensures that priority 1 "silver_bullet" strategy limit orders are cancelled exactly 5 minutes after each Silver Bullet session ends, regardless of server timezone.

## Silver Bullet Sessions (NYC Time)

| Session | Time (NYC) | Cancellation Time |
|---------|------------|-------------------|
| London Open | 3:00-4:00 AM | 4:05 AM |
| AM Session | 10:00-11:00 AM | 11:05 AM |
| PM Session | 2:00-3:00 PM | 3:05 PM |

## Features Implemented

### 1. Session Manager (`src/session_manager.py`)

- **Fixed NYC Timezone**: Uses UTC-5 offset to ensure consistent session timing regardless of server location
- **Session Detection**: Accurately detects when in Silver Bullet sessions
- **Cancellation Timing**: Triggers order cancellations 5 minutes after session ends
- **Order Identification**: Identifies Silver Bullet orders by priority and strategy ID

### 2. Order Tracking

Orders are tracked using a specific format:
```
prio{priority}_{timestamp}_{symbol}_{strategy_id}
```

Examples:
- `prio1_1747778400_BTCUSDT_silver_bullet` ✅ (Will be cancelled)
- `prio2_1747778400_ETHUSDT_default` ❌ (Won't be cancelled)
- `prio1_1747778400_SOLUSDT_ict_strategy` ✅ (Will be cancelled)

### 3. Background Monitoring

- Runs continuously as a background task
- Checks every 30 seconds for cancellation times
- Logs session status every 15 minutes during business hours
- Handles errors gracefully without crashing the main application

### 4. API Endpoints

- `GET /sessions/status` - Check current session status
- `POST /sessions/cancel-orders` - Manually trigger order cancellation (for testing)

## Order Cancellation Criteria

An order will be cancelled if ALL of the following conditions are met:

1. ✅ **Priority 1**: Order must have priority 1 (`prio1_` prefix)
2. ✅ **Silver Bullet Strategy**: Order must contain strategy identifier:
   - `silver_bullet` in the order ID, OR
   - `_sb_` in the order ID, OR  
   - `ict_strategy` in the order ID
3. ✅ **Session End**: Must be exactly at cancellation time (4:05 AM, 11:05 AM, or 3:05 PM NYC)
4. ✅ **Active Order**: Order must still be open/pending (not filled or already cancelled)

## Example Webhook for Silver Bullet Orders

```json
{
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
}
```

## Testing

### Run Session Manager Tests
```bash
python test_session_manager.py
```

### Test with Webhook
```bash
curl -X POST http://localhost:8001/webhook/test \
  -H "Content-Type: application/json" \
  -d @test_silver_bullet_webhook.json
```

### Check Session Status
```bash
curl http://localhost:8001/sessions/status
```

### Manual Order Cancellation (Testing)
```bash
curl -X POST http://localhost:8001/sessions/cancel-orders
```

## Logging

The system provides detailed logging:

- 🎯 Session detection and status
- 📊 Order identification and tracking  
- 🚨 Cancellation events and results
- ⚠️ Errors and warnings
- ✅ Successful operations

## Safety Features

1. **No False Positives**: Only cancels orders that explicitly match all criteria
2. **Error Resilience**: Continues monitoring even if individual operations fail
3. **Timezone Safety**: Uses fixed NYC timezone regardless of server location
4. **Manual Override**: API endpoint for emergency manual cancellation
5. **Comprehensive Logging**: Full audit trail of all cancellation actions

## Integration with Existing System

- ✅ **No Breaking Changes**: Existing functionality remains unchanged
- ✅ **Background Operation**: Runs independently without affecting webhook processing
- ✅ **Priority System**: Works with existing priority conflict resolution
- ✅ **Multi-Strategy**: Compatible with existing multi-strategy configuration

## Monitoring

Check the application logs for session-related events:

```bash
tail -f logs/trading_bot.log | grep -E "(🎯|📊|🚨|Silver Bullet)"
```

The system will log:
- Session start/end events
- Order cancellation attempts
- Successful cancellations
- Any errors in the process 