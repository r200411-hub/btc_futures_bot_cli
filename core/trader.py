import time
from core.parquet_logger import ParquetLogger


class TradeManager:

    def __init__(self, cfg):
        #self.pq = ParquetLogger()
        self.cfg = cfg
        self.position = None
        self.trades = []
        self.total = 0
        self.last_trade = 0

    def can_trade(self):
        return time.time()-self.last_trade > self.cfg["min_trade_gap"]

    """ def open(self, side, price):
        if self.position: return
        self.last_trade = time.time()
        self.position = {"side":side,"entry":price}
        print(f"\n📈 OPEN {side} @ {price}")
 """
    def open(self, side, price, size=None):
            if self.position: return
            self.last_trade = time.time()
            size = size or self.cfg.get("position_size", 1.0)
            self.position = {"side": side, "entry": price, "size": size}
            print(f"\n📈 OPEN {side} @ {price} size={size}")

    def close(self, price, reason=""):
        if not self.position: return
        
        entry = self.position["entry"]
        side = self.position["side"]

        pnl = (price-entry) * (1 if side=="LONG" else -1)

        self.total += pnl
       
       # self.pq.log(record)

        print(
            f"📉 CLOSE {side} @ {price} PnL={pnl:.2f} TOTAL={self.total:.2f} ({reason})"
        )

        self.position = None

        return pnl
    
    def calculate_pnl(self, market_price: float) -> float:
            """
            Return unrealized PnL for the current open position given market_price.
            Assumes self.position is None or contains keys: 'side', 'entry', optional 'size'.
            """
            if not self.position:
                return 0.0
            entry = float(self.position.get("entry", 0.0))
            side = self.position.get("side", "LONG")
            size = float(self.position.get("size", self.cfg.get("position_size", 1.0)))
            # For LONG: pnl = (market - entry) * size
            # For SHORT: pnl = (entry - market) * size  -> same as (market-entry)*( -1)
            pnl = (market_price - entry) * (1 if side.upper() == "LONG" else -1) * size
            return float(pnl)

    
    
