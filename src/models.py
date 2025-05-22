"""
Pydantic models for webhook payloads and configuration.
"""

from pydantic import BaseModel, Field
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
        "order_type": "test_short"
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


class BotConfig(BaseModel):
    """Main configuration model."""
    server: ServerConfig
    bybit_api: BybitApiConfig
    risk_management: RiskManagementConfig
    logging: LoggingConfig 