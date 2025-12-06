# core/trader.py
import time

class TradeManager:
    """
    Simple TradeManager compatible with PaperExecutor.
    Methods:
      - open(side, price, size)
      - close(price, reason)
      - calculate_pnl(price)
    Stores position as dict: {'side': 'LONG'|'SHORT', 'entry': price, 'size': float, 'opened_at': ts}
    """
    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self.position = None
        self.trades = []
        self.total = 0.0
        self.last_trade = 0.0

    def can_trade(self):
        # optional throttle
        return time.time() - self.last_trade > float(self.cfg.get("min_trade_gap", 0.5))

    def open(self, side, price, size=None):
        if self.position:
            # already have a position; ignore open
            print("⚠ TradeManager: open() called but position already exists - ignoring")
            return
        side = str(side).upper()
        size = size or float(self.cfg.get("position_size", 0.01))
        self.position = {
            "side": side,
            "entry": float(price),
            "size": float(size),
            "opened_at": time.time()
        }
        self.last_trade = time.time()
        print(f"\n📈 OPEN {side} @ {price} size={size}")

    def close(self, price, reason=""):
        if not self.position:
            print("⚪ TradeManager: close() called but no position exists - ignoring")
            return 0.0
        entry = float(self.position["entry"])
        side = self.position["side"]
        size = float(self.position.get("size", self.cfg.get("position_size", 0.01)))
        # PnL is (price - entry) * size for LONG, reversed for SHORT
        pnl = (float(price) - entry) * (1.0 if side == "LONG" else -1.0) * size * (self.cfg.get("leverage", 1) if self.cfg else 1)
        self.total += pnl
        self.trades.append({
            "side": side,
            "entry": entry,
            "exit": float(price),
            "size": size,
            "pnl": pnl,
            "reason": reason,
            "ts": time.time()
        })
        print(f"📉 CLOSE {side} @ {price} PnL={pnl:.2f} TOTAL={self.total:.2f} ({reason})")
        self.position = None
        return pnl

    def calculate_pnl(self, current_price):
        if not self.position:
            return 0.0
        entry = float(self.position["entry"])
        side = self.position["side"]
        size = float(self.position.get("size", self.cfg.get("position_size", 0.01)))
        pnl = (float(current_price) - entry) * (1.0 if side == "LONG" else -1.0) * size * (self.cfg.get("leverage", 1) if self.cfg else 1)
        return pnl
