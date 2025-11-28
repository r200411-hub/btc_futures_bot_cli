import time
import random
import uuid

class PaperTradeExecutor:
    """
    Full realistic paper trading engine.
    Matches interface expected by TradeManager:

        open_order(side, price)
        close_order(price, reason)
        update(price)
        get_position()
        calculate_pnl(price)

    """

    def __init__(self, settings):
        self.s = settings

        # only ONE position allowed (as per your bot logic)
        self.position = None

        self.total_pnl = 0.0
        self.last_price = None

        self.last_open_ts = 0
        self.trailing_active = False
        self.trailing_stop = None

    # -------------------------------
    # Utility: simulate fees + slippage
    # -------------------------------
    def _slip(self, price):
        slip_pct = self.s.get("sim_slippage_pct", 0.0005)
        spread = self.s.get("sim_spread_usd", 1.0)

        if self.s.get("sim_random_slippage", True):
            slip = price * slip_pct * random.uniform(0.5, 1.5)
        else:
            slip = price * slip_pct

        # final adjusted execution price
        return price + spread + slip if self.position_side == "LONG" else price - spread - slip

    def _fee(self, price, size):
        fee_rate = self.s.get("fee_taker_pct", 0.0005)
        return price * size * fee_rate

    # -------------------------------
    # OPEN ORDER
    # -------------------------------
    def open_order(self, side, price):

        if self.position:
            return None  # one position only

        now = time.time()
        gap = self.s.get("min_trade_gap_s", 0.5)
        if now - self.last_open_ts < gap:
            return None

        exec_price = price
        size = self.s.get("position_size", 0.01)

        # simulate latency
        latency = self.s.get("sim_latency_ms", 0)
        if latency:
            time.sleep(latency / 1000)

        # slippage
        if self.s.get("simulate_live", True):
            slip = self.s.get("sim_slippage_pct", 0.0005)
            exec_price *= (1 + slip) if side == "LONG" else (1 - slip)

        self.position = {
            "id": str(uuid.uuid4()),
            "side": side,
            "entry": exec_price,
            "size": size,
            "ts": now
        }

        self.last_open_ts = now
        self.trailing_active = False
        self.trailing_stop = None
        self.last_price = exec_price

        print(f"📘 PAPER OPEN {side} @ {exec_price:.2f} size={size}")
        return self.position

    # -------------------------------
    # CLOSE ORDER
    # -------------------------------
    def close_order(self, price, reason="MANUAL"):
        if not self.position:
            return None

        pos = self.position
        exec_price = price

        # simulate slippage again
        slip = self.s.get("sim_slippage_pct", 0.0005)
        exec_price *= (1 - slip) if pos["side"] == "LONG" else (1 + slip)

        # compute PnL
        direction = 1 if pos["side"] == "LONG" else -1
        pnl = (exec_price - pos["entry"]) * direction * pos["size"]

        # subtract taker fee
        pnl -= self._fee(exec_price, pos["size"])

        self.total_pnl += pnl

        out = {
            "id": pos["id"],
            "side": pos["side"],
            "entry": pos["entry"],
            "exit": exec_price,
            "size": pos["size"],
            "pnl": pnl,
            "reason": reason,
            "ts": time.time()
        }

        print(f"📕 PAPER CLOSE {pos['side']} @ {exec_price:.2f}  PnL={pnl:.4f} ({reason})")

        self.position = None
        return out

    # -------------------------------
    # UPDATE on every tick
    # -------------------------------
    def update(self, price):

        self.last_price = price

        if not self.position:
            return None

        pos = self.position

        direction = 1 if pos["side"] == "LONG" else -1
        pnl = (price - pos["entry"]) * direction * pos["size"]

        # trailing stop
        if self.s.get("enable_trailing", True):
            trail = self.s.get("trailing_pts", 150)

            if pos["side"] == "LONG":
                # move trailing stop upwards
                if self.trailing_stop is None:
                    self.trailing_stop = price - trail
                else:
                    self.trailing_stop = max(self.trailing_stop, price - trail)

                if price <= self.trailing_stop:
                    return self.close_order(price, "TRAILING")
            else:
                # short side trailing
                if self.trailing_stop is None:
                    self.trailing_stop = price + trail
                else:
                    self.trailing_stop = min(self.trailing_stop, price + trail)

                if price >= self.trailing_stop:
                    return self.close_order(price, "TRAILING")

        # exposure timer
        max_exp = self.s.get("max_exposure_seconds", 180)
        if time.time() - pos["ts"] > max_exp:
            return self.close_order(price, "TIME_LIMIT")

        return pnl

    # -------------------------------
    # EXPOSE POSITION TO BOT
    # -------------------------------
    def get_position(self):
        return self.position

    def calculate_pnl(self, price):
        if not self.position:
            return 0.0

        pos = self.position
        direction = 1 if pos["side"] == "LONG" else -1
        return (price - pos["entry"]) * direction * pos["size"]
