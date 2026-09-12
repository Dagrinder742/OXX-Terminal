# kalshi/models.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class BalanceBreakdownItem(BaseModel):
    balance: str
    exchange_index: int

class BalanceResponse(BaseModel):
    balance: int
    balance_dollars: str
    balance_breakdown: List[BalanceBreakdownItem] = Field(default_factory=list)
    portfolio_value: int
    updated_ts: int

class TickerMessage(BaseModel):
    market_ticker: str
    price: Optional[int] = None
    yes_bid: Optional[int] = None
    yes_ask: Optional[int] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None

class WebSocketMessage(BaseModel):
    id: Optional[int] = None
    type: str
    channel: Optional[str] = None
    sid: Optional[int] = None
    msg: Optional[Dict[Any, Any]] = None
