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

    def open(self, side, price):
        if self.position: return
        self.last_trade = time.time()
        self.position = {"side":side,"entry":price}
        print(f"\n📈 OPEN {side} @ {price}")

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
    
    
