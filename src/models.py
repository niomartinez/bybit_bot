"""
Pydantic models for webhook payloads and configuration.
"""

from pydantic import BaseModel, Field, validator
from typing import Literal, Optional, Dict, Any, Union, List
from datetime import datetime
from enum import Enum


class TradingViewSignal(BaseModel):
    """
    Model for the webhook payload received from TradingView.
    
    Example:
    {
        "symbol": "SOLUSDT.P",
        "side": "short",
        "entry": "167.98",
        "stop_loss": "169.6598",
        "take_profit": "162.9406",
        "trigger_time": "1747778400208",
        "max_lag": "20",
        "order_type": "limit",
        "strategy_id": "ict_strategy_a",
        "priority": 1
    }
    """
    symbol: str
    side: Literal['long', 'short']
    entry: float
    stop_loss: float
    take_profit: float
    trigger_time: str
    max_lag: int = 20
    order_type: str = "limit"
    strategy_id: Optional[str] = None
    priority: int = 2  # Default to priority 2 (lower priority)
    
    quantity: Optional[float] = None
    reduce_only: Optional[bool] = False
    close_position: Optional[bool] = False

    @validator('priority', pre=True)
    def validate_priority(cls, v):
        """Convert priority from string to int and validate range."""
        if isinstance(v, str):
            try:
                v = int(v)
            except ValueError:
                raise ValueError(f"Priority must be a valid integer, got: {v}")
        
        if not isinstance(v, int):
            raise ValueError(f"Priority must be an integer, got: {type(v)}")
        
        if v < 1:
            raise ValueError(f"Priority must be >= 1, got: {v}")
        
        return v


class ServerConfig(BaseModel):
    """Configuration for the webhook server."""
    host: str
    port: int


class BybitApiConfig(BaseModel):
    """Configuration for Bybit API."""
    category: str
    default_time_in_force: str
    max_leverage_cap: Optional[int] = None


class RiskManagementConfig(BaseModel):
    """Configuration for risk management."""
    var_type: Literal['fixed_amount', 'portfolio_percentage']
    var_value: float
    portfolio_currency: str = "USDT"


class PnLTrailingStopConfig(BaseModel):
    """Configuration for PnL-based trailing stop functionality."""
    enabled: bool = Field(True, description="Enable PnL-based trailing stop")
    target_percentage: float = Field(50.0, description="Percentage of distance to take profit target to trigger trailing stop (default: 50%)")
    break_even_offset: float = Field(0.0, description="Offset from entry price for break-even stop (in price units)")
    monitoring_interval_seconds: int = Field(60, description="How often to check positions for target threshold (default: 60 seconds)")
    trigger_price_type: Literal["LastPrice", "MarkPrice", "IndexPrice"] = Field("LastPrice", description="Price type for stop loss trigger")
    max_adjustments_per_position: int = Field(1, description="Maximum number of stop loss adjustments per position")
    min_position_age_minutes: int = Field(5, description="Minimum position age before applying trailing stop (minutes)")
    fallback_to_pnl: bool = Field(True, description="If no take profit target, fallback to PnL percentage")
    fallback_pnl_percentage: float = Field(50.0, description="PnL percentage to use when no take profit target exists")


class LoggingConfig(BaseModel):
    """Configuration for logging."""
    level: str
    file: str
    format: str


class StrategyConfig(BaseModel):
    """Configuration for individual strategy."""
    var_multiplier: float = 1.0
    max_leverage_override: Optional[int] = None
    enabled: bool = True


class MultiStrategyConfig(BaseModel):
    """Configuration for multi-strategy trading."""
    enabled: bool = True
    hedge_mode: bool = True
    auto_switch_to_hedge: bool = True
    max_strategies_per_symbol: int = 5
    allow_pyramiding: bool = True
    max_pyramiding_orders: int = 3
    strategy_configs: Dict[str, StrategyConfig] = {}


class BotConfig(BaseModel):
    """Main configuration model."""
    server: ServerConfig
    bybit_api: BybitApiConfig
    risk_management: RiskManagementConfig
    pnl_trailing_stop: Optional[PnLTrailingStopConfig] = Field(default_factory=PnLTrailingStopConfig)
    multi_strategy: Optional[MultiStrategyConfig] = None
    logging: LoggingConfig 
    google_sheets: Optional[Dict[str, Any]] = None


class OrderSide(str, Enum):
    LONG = "long"
    SHORT = "short"

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"

class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

class TradingSignal(BaseModel):
    symbol: str = Field(..., description="Trading symbol (e.g., BTCUSDT.P)")
    side: OrderSide = Field(..., description="Order side: long or short")
    entry: float = Field(..., description="Entry price")
    stop_loss: Optional[float] = Field(None, description="Stop loss price")
    take_profit: Optional[float] = Field(None, description="Take profit price")
    trigger_time: str = Field(..., description="Trigger timestamp from TradingView")
    max_lag: Optional[int] = Field(20, description="Maximum lag in seconds")
    order_type: OrderType = Field(OrderType.LIMIT, description="Order type")
    priority: Optional[int] = Field(1, description="Order priority (1-5)")
    strategy_id: Optional[str] = Field("default", description="Strategy identifier")

class OrderResult(BaseModel):
    success: bool
    order_id: Optional[str] = None
    message: str
    symbol: str
    side: str
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    timestamp: datetime
    strategy_id: Optional[str] = None
    priority: Optional[int] = None

class TradeJournalEntry(BaseModel):
    """Model for trade journal entries to be logged to Google Sheets"""
    
    # Trade Identification
    trade_id: str = Field(..., description="Unique trade identifier")
    symbol: str = Field(..., description="Trading symbol")
    strategy: str = Field(..., description="Strategy name")
    priority: int = Field(..., description="Order priority")
    
    # Entry Details
    entry_time: datetime = Field(..., description="Entry timestamp")
    entry_price: float = Field(..., description="Entry price")
    side: str = Field(..., description="Long or Short")
    quantity: float = Field(..., description="Position size")
    
    # Exit Details (filled when trade closes)
    exit_time: Optional[datetime] = Field(None, description="Exit timestamp")
    exit_price: Optional[float] = Field(None, description="Exit price")
    exit_reason: Optional[str] = Field(None, description="Exit reason (TP/SL/Manual)")
    
    # Risk Management
    stop_loss: Optional[float] = Field(None, description="Stop loss price")
    take_profit: Optional[float] = Field(None, description="Take profit price")
    risk_amount: Optional[float] = Field(None, description="Risk amount in USD")
    
    # Performance Metrics
    pnl_usd: Optional[float] = Field(None, description="P&L in USD")
    pnl_percentage: Optional[float] = Field(None, description="P&L percentage")
    duration_minutes: Optional[int] = Field(None, description="Trade duration in minutes")
    
    # Market Context
    session_type: Optional[str] = Field(None, description="Silver Bullet session type")
    market_conditions: Optional[str] = Field(None, description="Market conditions")
    
    # Status
    status: str = Field("OPEN", description="Trade status: OPEN/CLOSED/CANCELLED")
    notes: Optional[str] = Field(None, description="Additional notes")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class SheetsConfig(BaseModel):
    """Configuration for Google Sheets integration"""
    
    spreadsheet_id: str = Field(..., description="Google Sheets spreadsheet ID")
    worksheet_name: str = Field("Trade Journal", description="Worksheet name")
    credentials_file: str = Field("credentials.json", description="Path to Google credentials file")
    
    # Column mapping for the spreadsheet
    columns: Dict[str, str] = Field(default={
        "A": "trade_id",
        "B": "symbol", 
        "C": "strategy",
        "D": "priority",
        "E": "entry_time",
        "F": "entry_price",
        "G": "side",
        "H": "quantity",
        "I": "exit_time",
        "J": "exit_price", 
        "K": "exit_reason",
        "L": "stop_loss",
        "M": "take_profit",
        "N": "risk_amount",
        "O": "pnl_usd",
        "P": "pnl_percentage",
        "Q": "duration_minutes",
        "R": "session_type",
        "S": "market_conditions",
        "T": "status",
        "U": "notes",
        "V": "created_at",
        "W": "updated_at"
    })

class HealthCheck(BaseModel):
    status: str
    timestamp: datetime
    version: str = "1.0.0"
    services: Dict[str, str] = {} 