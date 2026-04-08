"""Portfolio and alerts state with JSON file persistence."""
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

STARTING_CASH = 10_000.0
SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "portfolio.json")


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_cost: float  # average cost per share

    def to_dict(self, current_price: float) -> dict:
        value = self.quantity * current_price
        cost_basis = self.quantity * self.avg_cost
        pnl = value - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0.0
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": round(self.avg_cost, 4),
            "current_price": round(current_price, 4),
            "value": round(value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        }


@dataclass
class Trade:
    id: str
    symbol: str
    action: str  # "buy" | "sell"
    quantity: float
    price: float
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "price": round(self.price, 4),
            "total": round(self.quantity * self.price, 2),
            "timestamp": self.timestamp,
        }


@dataclass
class Alert:
    id: str
    symbol: str
    condition: str  # "above" | "below"
    target_price: float
    created_at: float
    triggered: bool = False
    triggered_at: Optional[float] = None
    triggered_price: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "condition": self.condition,
            "target_price": self.target_price,
            "created_at": self.created_at,
            "triggered": self.triggered,
            "triggered_at": self.triggered_at,
            "triggered_price": self.triggered_price,
        }


class Portfolio:
    def __init__(self):
        self.cash: float = STARTING_CASH
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.alerts: Dict[str, Alert] = {}
        self._load()

    def _save(self):
        """Save portfolio state to JSON file."""
        os.makedirs(os.path.dirname(SAVE_FILE), exist_ok=True)
        data = {
            "cash": self.cash,
            "positions": {
                sym: {"symbol": p.symbol, "quantity": p.quantity, "avg_cost": p.avg_cost}
                for sym, p in self.positions.items()
            },
            "trades": [
                {"id": t.id, "symbol": t.symbol, "action": t.action,
                 "quantity": t.quantity, "price": t.price, "timestamp": t.timestamp}
                for t in self.trades
            ],
            "alerts": {
                aid: {"id": a.id, "symbol": a.symbol, "condition": a.condition,
                      "target_price": a.target_price, "created_at": a.created_at,
                      "triggered": a.triggered, "triggered_at": a.triggered_at,
                      "triggered_price": a.triggered_price}
                for aid, a in self.alerts.items()
            },
        }
        with open(SAVE_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self):
        """Load portfolio state from JSON file if it exists."""
        if not os.path.exists(SAVE_FILE):
            return
        try:
            with open(SAVE_FILE, "r") as f:
                data = json.load(f)
            self.cash = data.get("cash", STARTING_CASH)
            self.positions = {
                sym: Position(symbol=p["symbol"], quantity=p["quantity"], avg_cost=p["avg_cost"])
                for sym, p in data.get("positions", {}).items()
            }
            self.trades = [
                Trade(id=t["id"], symbol=t["symbol"], action=t["action"],
                      quantity=t["quantity"], price=t["price"], timestamp=t["timestamp"])
                for t in data.get("trades", [])
            ]
            self.alerts = {
                aid: Alert(id=a["id"], symbol=a["symbol"], condition=a["condition"],
                           target_price=a["target_price"], created_at=a["created_at"],
                           triggered=a.get("triggered", False),
                           triggered_at=a.get("triggered_at"),
                           triggered_price=a.get("triggered_price"))
                for aid, a in data.get("alerts", {}).items()
            }
            print(f"Loaded portfolio: ${self.cash:.2f} cash, {len(self.positions)} positions, {len(self.trades)} trades")
        except Exception as e:
            print(f"Warning: Could not load save file: {e}")

    def buy(self, symbol: str, quantity: float, price: float) -> dict:
        cost = quantity * price
        if cost > self.cash:
            raise ValueError(f"Insufficient cash. Need ${cost:.2f}, have ${self.cash:.2f}")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        self.cash -= cost

        if symbol in self.positions:
            pos = self.positions[symbol]
            total_qty = pos.quantity + quantity
            pos.avg_cost = (pos.quantity * pos.avg_cost + quantity * price) / total_qty
            pos.quantity = total_qty
        else:
            self.positions[symbol] = Position(symbol=symbol, quantity=quantity, avg_cost=price)

        trade = Trade(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            action="buy",
            quantity=quantity,
            price=price,
            timestamp=time.time(),
        )
        self.trades.append(trade)
        self._save()
        return trade.to_dict()

    def sell(self, symbol: str, quantity: float, price: float) -> dict:
        if symbol not in self.positions:
            raise ValueError(f"No position in {symbol}")
        pos = self.positions[symbol]
        if quantity > pos.quantity:
            raise ValueError(f"Cannot sell {quantity} shares, only have {pos.quantity}")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        self.cash += quantity * price
        pos.quantity -= quantity

        if pos.quantity < 1e-9:
            del self.positions[symbol]

        trade = Trade(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            action="sell",
            quantity=quantity,
            price=price,
            timestamp=time.time(),
        )
        self.trades.append(trade)
        self._save()
        return trade.to_dict()

    def add_alert(self, symbol: str, condition: str, target_price: float) -> Alert:
        alert = Alert(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            condition=condition,
            target_price=target_price,
            created_at=time.time(),
        )
        self.alerts[alert.id] = alert
        self._save()
        return alert

    def delete_alert(self, alert_id: str):
        if alert_id not in self.alerts:
            raise ValueError(f"Alert {alert_id} not found")
        del self.alerts[alert_id]
        self._save()

    def check_alerts(self, prices: Dict[str, float]) -> List[Alert]:
        triggered = []
        for alert in self.alerts.values():
            if alert.triggered:
                continue
            price = prices.get(alert.symbol)
            if price is None:
                continue
            hit = (alert.condition == "above" and price >= alert.target_price) or \
                  (alert.condition == "below" and price <= alert.target_price)
            if hit:
                alert.triggered = True
                alert.triggered_at = time.time()
                alert.triggered_price = price
                triggered.append(alert)
        if triggered:
            self._save()
        return triggered

    def summary(self, prices: Dict[str, float]) -> dict:
        holdings = [pos.to_dict(prices.get(sym, pos.avg_cost)) for sym, pos in self.positions.items()]
        portfolio_value = sum(h["value"] for h in holdings)
        total_value = self.cash + portfolio_value
        unrealized_pnl = sum(h["pnl"] for h in holdings)
        winners_count = sum(1 for h in holdings if h["pnl"] > 0)
        losers_count = sum(1 for h in holdings if h["pnl"] < 0)
        largest_holding = max(holdings, key=lambda holding: holding["value"], default=None)
        return {
            "cash": round(self.cash, 2),
            "portfolio_value": round(portfolio_value, 2),
            "total_value": round(total_value, 2),
            "starting_cash": STARTING_CASH,
            "total_pnl": round(total_value - STARTING_CASH, 2),
            "total_pnl_pct": round((total_value - STARTING_CASH) / STARTING_CASH * 100, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "positions_count": len(holdings),
            "winners_count": winners_count,
            "losers_count": losers_count,
            "largest_holding_symbol": largest_holding["symbol"] if largest_holding else None,
            "holdings": holdings,
        }


# Singleton instance
portfolio = Portfolio()
