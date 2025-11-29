# core/strategy.py
from collections import deque

class Strategy:

    def __init__(self, cfg):
        self.cfg = cfg

        # FIXED EMA — No dynamic scaling
        self.fast_period_fixed = cfg["fast_ema"]     # 9
        self.slow_period_fixed = cfg["slow_ema"]     # 21

        # EMA buffers
        self.fast = deque(maxlen=500)
        self.slow = deque(maxlen=500)

        # Price history
        self.prices = deque(maxlen=2000)

        # Renko
        self.bricks = []
        self.last_brick_cnt = 0

        # Volatility (still tracked but DOES NOT change EMA)
        self.last_price = None
        self.vol_ema = None
        self.vol_alpha = 0.2

    # ------------------------------------------------------
    # VOLATILITY (tracking only – does NOT affect EMAs now)
    # ------------------------------------------------------
    def _update_volatility(self, price: float):
        if self.last_price is None:
            self.vol_ema = 0.0
        else:
            diff = abs(price - self.last_price)
            if self.vol_ema is None:
                self.vol_ema = diff
            else:
                a = self.vol_alpha
                self.vol_ema = a * diff + (1 - a) * self.vol_ema

    # ------------------------------------------------------
    # FIXED PERIODS
    # ------------------------------------------------------
    def _dynamic_periods(self):
        """Always return fixed periods."""
        return self.fast_period_fixed, self.slow_period_fixed

    def _ema_step(self, prev, price, period):
        k = 2 / (period + 1)
        return price * k + prev * (1 - k)

    # ------------------------------------------------------
    # MAIN UPDATE
    # ------------------------------------------------------
    def update(self, price):

        price = float(price)
        self.prices.append(price)
        self._update_volatility(price)
        self.last_price = price

        # GET FIXED PERIODS
        fast_period, slow_period = self._dynamic_periods()

        # SAVE TO LOGGING
        self._last_fast_period = fast_period
        self._last_slow_period = slow_period

        # UPDATE EMA (FIXED)
        if len(self.fast) == 0:
            self.fast.append(price)
        else:
            self.fast.append(
                self._ema_step(self.fast[-1], price, fast_period)
            )

        if len(self.slow) == 0:
            self.slow.append(price)
        else:
            self.slow.append(
                self._ema_step(self.slow[-1], price, slow_period)
            )

        # RENKO
        self.build_bricks(price)

    # ------------------------------------------------------
    # RENKO LOGIC
    # ------------------------------------------------------
    def build_bricks(self, price):

        bsize = self.cfg["brick_size"]

        if not self.bricks:
            base = (price // bsize) * bsize
            self.bricks.append({"open": base, "close": base, "dir": "up"})
            return

        last = self.bricks[-1]
        diff = price - last["close"]

        if abs(diff) >= bsize:

            direction = "up" if diff > 0 else "down"
            closes = int(abs(diff) // bsize)

            for _ in range(closes):
                new_price = last["close"] + (bsize if direction == "up" else -bsize)

                self.bricks.append({
                    "open": last["close"],
                    "close": new_price,
                    "dir": direction
                })

                last = self.bricks[-1]

            # Keep last 50 bricks
            self.bricks = self.bricks[-50:]

    # ------------------------------------------------------
    # SIGNAL LOGIC
    # ------------------------------------------------------
    def signal(self):

        if len(self.fast) < 2 or len(self.slow) < 2:
            return None

        if len(self.bricks) < 3:
            return None

        # Only one signal per new brick
        if len(self.bricks) == self.last_brick_cnt:
            return None

        self.last_brick_cnt = len(self.bricks)

        f, fp = self.fast[-1], self.fast[-2]
        s, sp = self.slow[-1], self.slow[-2]
        b, bp = self.bricks[-1], self.bricks[-2]

        # LONG
        if fp <= sp and f > s and b["dir"] == "up" and bp["dir"] == "up":
            return "LONG"

        # SHORT
        if fp >= sp and f < s and b["dir"] == "down" and bp["dir"] == "down":
            return "SHORT"

        return None

    # ------------------------------------------------------
    # PROPERTIES FOR LOGGING
    # ------------------------------------------------------
    @property
    def fast_period(self):
        return getattr(self, "_last_fast_period", None)

    @property
    def slow_period(self):
        return getattr(self, "_last_slow_period", None)

    @property
    def vol(self):
        return self.vol_ema
