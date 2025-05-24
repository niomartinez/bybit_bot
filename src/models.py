"""
Pydantic models for webhook payloads and configuration.
"""

from pydantic import BaseModel, Field, validator
from typing import Literal, Optional, Dict, Any, Union


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
    multi_strategy: Optional[MultiStrategyConfig] = None
    logging: LoggingConfig 