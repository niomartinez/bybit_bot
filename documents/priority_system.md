# Priority-Based Order Management System

## Overview

The Bybit trading bot now supports a **priority-based order management system** that allows for sophisticated trade execution control based on signal priority levels. This system replaces the complex strategy-specific SL/TP approach with a simpler, more reliable priority-based conflict resolution mechanism.

## Priority Levels

The system supports priority levels (expandable but currently configured for 2 levels):

- **Priority 1**: **High Priority** - Always executes, can cancel lower priority orders
- **Priority 2**: **Normal Priority** - Only executes if no higher priority orders exist

### Default Behavior
- All signals default to **Priority 2** if no priority is specified
- Priority can be sent as either string (`"1"`, `"2"`) or integer (`1`, `2`)

## Priority Rules

### Priority 1 (High Priority)
- ✅ **Always executes** regardless of existing orders
- ✅ **Cancels all Priority 2 orders** for the same symbol before execution
- ✅ **Closes all Priority 2 positions** for the same symbol before execution
- ✅ **Can reverse positions** (change from long to short or vice versa)
- ✅ **Follows pyramiding limits** with other Priority 1 orders (max 3 same-direction orders)
- ✅ **Cancels conflicting Priority 1 orders** when changing direction

### Priority 2 (Normal Priority)
- ❌ **Blocked if Priority 1 orders exist** for the same symbol
- ✅ **Executes if no Priority 1 orders exist**
- ✅ **Follows pyramiding limits** with other Priority 2 orders (max 3 same-direction orders)
- ❌ **Cannot reverse positions** (blocked if opposite direction position exists)
- ❌ **Blocked by direction conflicts** with existing Priority 2 orders

## Signal Format

### TradingView Webhook Payload

```json
{
  "symbol": "NEARUSDT.P",
  "side": "long",
  "entry": "1.2",
  "stop_loss": "0.5",
  "take_profit": "1.5",
  "trigger_time": "{{$timestamp}}000",
  "max_lag": "20",
  "priority": "1",
  "order_type": "limit",
  "strategy_id": "my_strategy"
}
```

### Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `priority` | `string/int` | No | Priority level: `"1"` (high) or `"2"` (normal). Defaults to `2` |
| `symbol` | `string` | Yes | Trading symbol (e.g., `"NEARUSDT.P"`) |
| `side` | `string` | Yes | `"long"` or `"short"` |
| `entry` | `string/float` | Yes | Entry price |
| `stop_loss` | `string/float` | Yes | Stop loss price |
| `take_profit` | `string/float` | Yes | Take profit price |
| `strategy_id` | `string` | No | Strategy identifier for tracking |

## Order ID Format

Orders are tagged with priority-based IDs for tracking:

- **Priority 1**: `prio1_{timestamp}_{symbol}_{strategy}`
- **Priority 2**: `tv_{timestamp}_{symbol}_{strategy}`

Examples:
- `prio1_1748106464_NEARUSDT_strategy_a` (Priority 1)
- `tv_1748106464_NEARUSDT_strategy_b` (Priority 2)

## Conflict Resolution Flow

### When Priority 1 Signal Arrives:
1. **Check existing Priority 2 orders** → Cancel all Priority 2 orders for symbol
2. **Check existing Priority 2 positions** → Close all Priority 2 positions for symbol
3. **Check existing Priority 1 orders**:
   - Same direction → Check pyramiding limits (max 3)
   - Opposite direction → Cancel all existing Priority 1 orders
4. **Execute order** with attached SL/TP

### When Priority 2 Signal Arrives:
1. **Check for Priority 1 orders** → Block execution if any exist
2. **Check existing Priority 2 orders**:
   - Opposite direction → Block execution
   - Same direction → Check pyramiding limits (max 3)
3. **Check positions** → Block if would reverse position
4. **Execute order** if all checks pass

## Configuration

### Multi-Strategy Settings (`config.json`)

```json
{
  "multi_strategy": {
    "enabled": true,
    "hedge_mode": false,
    "auto_switch_to_hedge": false,
    "max_strategies_per_symbol": 5,
    "allow_pyramiding": true,
    "max_pyramiding_orders": 3,
    "strategy_configs": {
      "default": {
        "var_multiplier": 1.0,
        "enabled": true
      }
    }
  }
}
```

### Key Settings:
- `hedge_mode: false` - Uses one-way position mode
- `max_pyramiding_orders: 3` - Maximum same-direction orders per priority level
- `allow_pyramiding: true` - Enables multiple orders in same direction

## Use Cases

### High-Frequency Strategy Override
```json
{
  "symbol": "BTCUSDT.P",
  "side": "short",
  "entry": "67000",
  "priority": "1",
  "strategy_id": "breakout_strategy"
}
```
This Priority 1 signal will cancel any existing Priority 2 orders and execute immediately.

### Normal Strategy Execution
```json
{
  "symbol": "BTCUSDT.P", 
  "side": "long",
  "entry": "66000",
  "priority": "2",
  "strategy_id": "trend_following"
}
```
This Priority 2 signal will only execute if no Priority 1 orders exist for BTCUSDT.

### Pyramiding Same Direction
Multiple Priority 2 signals in the same direction (up to 3) will be allowed:
1. First long order at 66000 ✅
2. Second long order at 65500 ✅ 
3. Third long order at 65000 ✅
4. Fourth long order at 64500 ❌ (pyramiding limit reached)

## Benefits

1. **Simplified SL/TP**: Uses standard Bybit attached SL/TP instead of complex separate orders
2. **Clear Priority Hierarchy**: Priority 1 always wins, Priority 2 follows rules
3. **Complete Position Control**: Priority 1 can both cancel orders AND close positions
4. **Position Protection**: Prevents unwanted position reversals for lower priority signals
5. **Pyramiding Control**: Allows controlled scaling into positions
6. **Reliable Execution**: No timing issues with order filling before SL/TP creation

## Migration Notes

- **Reverted from hedge mode** to one-way mode for simplicity
- **Removed strategy-specific SL/TP** quantities (was causing timing issues)
- **Standard Bybit SL/TP** now attached to main orders (more reliable)
- **Priority-based conflicts** replace complex multi-strategy position tracking

## Error Handling

The system provides clear error messages:

```json
{
  "success": false,
  "message": "Order blocked: Priority 2 blocked: Priority 1 orders exist for BTCUSDT",
  "error": "priority_conflict",
  "priority": 2,
  "conflicts": ["Blocked by Priority 1 order: prio1_1748106464_BTCUSDT_strategy_a"]
}
```

## Logging

Priority conflicts and resolutions are logged:
```
🎯 Checking priority conflicts for NEARUSDT (Priority: 1, Side: Buy)
Priority 1 signal received - will cancel all Priority 2 orders for NEARUSDT
🗑️ Cancelling 2 lower priority orders before placing new order
✅ Successfully cancelled all 2 conflicting orders
``` 