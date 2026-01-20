"""
Data models for the webhook trading system
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Side(str, Enum):
    """Trade side"""
    BUY = "BUY"
    SELL = "SELL"
    LONG = "LONG"
    SHORT = "SHORT"


class Action(str, Enum):
    """Alert action types"""
    LONG = "LONG"
    SHORT = "SHORT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    CLOSE_ALL = "CLOSE_ALL"


class ExitReason(str, Enum):
    """Reason for position exit"""
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    MANUAL = "MANUAL"
    SIGNAL = "SIGNAL"


class PositionStatus(str, Enum):
    """Position lifecycle status"""
    ACTIVE = "ACTIVE"
    TRAILING = "TRAILING"
    CLOSED = "CLOSED"


# Pydantic models for API validation
class TradingViewAlert(BaseModel):
    """Incoming webhook alert from TradingView"""
    action: Action
    symbol: str

    # Exact prices (calculated by TradingView) - PREFERRED
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    trailing_activation_price: Optional[float] = None

    # Fallback percentages (if exact prices not provided)
    price: Optional[float] = None  # Deprecated - use entry_price
    stop_loss_pct: Optional[float] = Field(default=1.5, ge=0.1, le=10.0)
    take_profit_pct: Optional[float] = Field(default=1.5, ge=0.1, le=20.0)
    trailing_activation_pct: Optional[float] = Field(default=0.8, ge=0.0, le=10.0)

    # Trailing distance (still use percentage)
    trailing_distance_pct: float = Field(default=0.75, ge=0.1, le=5.0)

    # Position settings
    position_size_usd: float = Field(default=100.0, gt=0)
    leverage: float = Field(default=1.0, ge=1.0, le=10.0)  # Increased for nano perps

    class Config:
        use_enum_values = True


# Dataclass models for internal use
@dataclass
class Trade:
    """Individual trade execution record"""
    symbol: str
    price: float
    size: float
    side: Side
    timestamp: datetime
    trade_id: str = ""


@dataclass
class Position:
    """Active trading position"""
    position_id: str
    product_id: str
    side: str  # "LONG" or "SHORT"
    size: float
    entry_price: float
    current_price: float = 0.0

    # Exit parameters
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    trailing_activation_price: float = 0.0
    trailing_distance_pct: float = 0.75

    # State
    status: PositionStatus = PositionStatus.ACTIVE
    trailing_active: bool = False
    trailing_stop_price: float = 0.0

    # Metadata
    opened_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    exit_reason: Optional[ExitReason] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0

    def update_pnl(self):
        """Calculate current P&L"""
        if self.side == "LONG":
            self.pnl = (self.current_price - self.entry_price) * self.size
            self.pnl_pct = ((self.current_price - self.entry_price) / self.entry_price) * 100
        else:  # SHORT
            self.pnl = (self.entry_price - self.current_price) * self.size
            self.pnl_pct = ((self.entry_price - self.current_price) / self.entry_price) * 100

    def should_stop_loss(self) -> bool:
        """Check if stop loss should trigger"""
        if self.side == "LONG":
            return self.current_price <= self.stop_loss_price
        else:  # SHORT
            return self.current_price >= self.stop_loss_price

    def should_take_profit(self) -> bool:
        """Check if take profit should trigger"""
        if self.side == "LONG":
            return self.current_price >= self.take_profit_price
        else:  # SHORT
            return self.current_price <= self.take_profit_price

    def should_activate_trailing(self) -> bool:
        """Check if trailing stop should activate"""
        if self.trailing_active:
            return False

        if self.side == "LONG":
            return self.current_price >= self.trailing_activation_price
        else:  # SHORT
            return self.current_price <= self.trailing_activation_price

    def update_trailing_stop(self):
        """Update trailing stop price (only moves in favorable direction)"""
        if not self.trailing_active:
            return

        if self.side == "LONG":
            # For longs, trailing stop follows price up
            new_stop = self.current_price * (1 - self.trailing_distance_pct / 100)
            if new_stop > self.trailing_stop_price:
                self.trailing_stop_price = new_stop
        else:  # SHORT
            # For shorts, trailing stop follows price down
            new_stop = self.current_price * (1 + self.trailing_distance_pct / 100)
            if new_stop < self.trailing_stop_price or self.trailing_stop_price == 0:
                self.trailing_stop_price = new_stop

    def should_trailing_stop(self) -> bool:
        """Check if trailing stop should trigger"""
        if not self.trailing_active:
            return False

        if self.side == "LONG":
            return self.current_price <= self.trailing_stop_price
        else:  # SHORT
            return self.current_price >= self.trailing_stop_price


@dataclass
class Balance:
    """Account balance"""
    currency: str
    available: float
    hold: float
    total: float
