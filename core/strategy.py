# core/strategy.py
from collections import deque

class Strategy:

    def __init__(self, cfg):
        self.cfg = cfg
        self.prices = deque(maxlen=2000)

        # EMA values (not period)
        self.fast = deque(maxlen=500)
        self.slow = deque(maxlen=500)

        self.bricks = []
        self.last_brick_cnt = 0
        self.last_price = None

        # --- dynamic EMA / volatility state ---
        self.vol_ema = None              # smoothed |Δprice|
        self.vol_alpha = 0.2             # smoothing factor for vol
        self.vol_low = cfg.get("vol_low", 10.0)   # tune for BTC
        self.vol_high = cfg.get("vol_high", 60.0) # tune for BTC

        self.fast_base = cfg["fast_ema"]         # e.g. 9
        self.slow_base = cfg["slow_ema"]         # e.g. 21
        self.fast_min = cfg.get("fast_min", 4)   # hard lower bound
        self.fast_max = cfg.get("fast_max", 20)  # hard upper bound
        self.slow_min = cfg.get("slow_min", 10)
        self.slow_max = cfg.get("slow_max", 50)

    # --- helpers ---

    def _update_volatility(self, price: float):
        """Update EMA of absolute price changes."""
        if self.last_price is None:
            self.vol_ema = 0.0
            return

        diff = abs(price - self.last_price)

        if self.vol_ema is None:
            self.vol_ema = diff
        else:
            a = self.vol_alpha
            self.vol_ema = a * diff + (1 - a) * self.vol_ema

    def _vol_factor(self):
        """
        Map current volatility to a scaling factor for EMA period.
        High vol → factor < 1 (shorter period)
        Low vol → factor > 1 (longer period)
        Clamped to [0.5, 1.5].
        """
        if self.vol_ema is None:
            return 1.0

        v = self.vol_ema

        # Normalize v into [0,1] between vol_low and vol_high
        if v <= self.vol_low:
            x = 0.0
        elif v >= self.vol_high:
            x = 1.0
        else:
            x = (v - self.vol_low) / (self.vol_high - self.vol_low)

        # Map x∈[0,1] → factor∈[1.5, 0.5]
        # x=0 (calm) => 1.5  (longer EMA)
        # x=1 (wild) => 0.5  (shorter EMA)
        factor = 1.5 - x   # linear map
        # safety clamp
        if factor < 0.5:
            factor = 0.5
        if factor > 1.5:
            factor = 1.5
        return factor

    def _dynamic_periods(self):
        """Compute effective EMA periods for this tick."""
        f = self._vol_factor()

        fast_eff = int(round(self.fast_base * f))
        slow_eff = int(round(self.slow_base * f))

        # clamp to safety ranges
        fast_eff = max(self.fast_min, min(self.fast_max, fast_eff))
        slow_eff = max(self.slow_min, min(self.slow_max, slow_eff))

        self._last_fast_period = fast_eff
        self._last_slow_period = slow_eff
        return fast_eff, slow_eff

    def _ema_step(self, prev, price, period):
        """One EMA step with dynamic period."""
        k = 2 / (period + 1)
        return price * k + prev * (1 - k)

    # --- main update ---

    def update(self, price):

        price = float(price)
        self.last_price = price
        self.prices.append(price)

        # 1) update volatility from price changes
        self._update_volatility(price)

        # 2) decide effective EMA lengths for this tick
        fast_period, slow_period = self._dynamic_periods()

        # 3) update EMAs with dynamic periods
        if len(self.fast) == 0:
            # seed with price
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

        # 4) build Renko bricks as before
        self.build_bricks(price)

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

            self.bricks = self.bricks[-200:]

    def signal(self):

        if len(self.fast) < 2 or len(self.slow) < 2:
            return None

        if len(self.bricks) < 3:
            return None

        # only once per new brick
        if len(self.bricks) == self.last_brick_cnt:
            return None

        self.last_brick_cnt = len(self.bricks)

        f, fp = self.fast[-1], self.fast[-2]
        s, sp = self.slow[-1], self.slow[-2]

        b, bp = self.bricks[-1], self.bricks[-2]

        if fp <= sp and f > s and b["dir"] == "up" and bp["dir"] == "up":
            return "LONG"

        if fp >= sp and f < s and b["dir"] == "down" and bp["dir"] == "down":
            return "SHORT"
    @property
    def fast_period(self):
        return getattr(self, "_last_fast_period", None)

    @property
    def slow_period(self):
        return getattr(self, "_last_slow_period", None)

    @property
    def vol(self):
        return self.vol_ema
