# core/executor_paper.py
import time
import uuid

class PaperExecutor:
    """
    Simple paper executor that records opens/closes locally.
    Interface:
      - open_position(side:str, price:float, size:float) -> dict (order)
      - close_position(position_id_or_side, price, reason) -> dict
      - get_open_positions() -> list
      - cancel_all()
    """

    def __init__(self, settings):
        self.settings = settings
        self.positions = []  # list of dicts
        self.trades = []
        self.order_counter = 0

    def _mkorder(self, side, price, size):
        self.order_counter += 1
        o = {
            "id": str(uuid.uuid4()),
            "side": side,
            "price": float(price),
            "size": float(size),
            "timestamp": time.time(),
            "status": "OPEN"
        }
        return o

    def open_position(self, side, price, size=None):
        size = size or self.settings.get("position_size", 0.01)
        order = self._mkorder(side, price, size)
        self.positions.append(order)
        print(f"📈 [PAPER] OPEN {side} id={order['id']} @ {price:.2f} size={size}")
        return order

    def close_position(self, identifier=None, price=None, reason="MANUAL"):
        """
        identifier can be position id or side string; closes the most recent matching open pos.
        """
        if not self.positions:
            return None

        # find position
        pos = None
        if identifier is None:
            pos = self.positions.pop()  # LIFO
        else:
            # try id match
            for i in range(len(self.positions)-1, -1, -1):
                p = self.positions[i]
                if p["id"] == identifier or p["side"] == identifier:
                    pos = self.positions.pop(i)
                    break

        if not pos:
            return None

        pnl = (float(price) - pos["price"]) * (1 if pos["side"] == "LONG" else -1)
        trade = {
            "id": pos["id"],
            "side": pos["side"],
            "entry": pos["price"],
            "exit": float(price),
            "size": pos["size"],
            "pnl": pnl,
            "reason": reason,
            "timestamp": time.time()
        }
        self.trades.append(trade)
        print(f"📉 [PAPER] CLOSE {trade['side']} id={trade['id']} @ {price:.2f} PnL={pnl:.4f} ({reason})")
        return trade

    def get_open_positions(self):
        return list(self.positions)

    def cancel_all(self):
        n = len(self.positions)
        self.positions = []
        print(f"⚠ [PAPER] Cancelled {n} open paper positions")
        return n
