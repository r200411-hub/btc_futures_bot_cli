# core/strategy.py
from collections import deque

class Strategy:
    """
    Renko + EMA strategy.
    - EMAs updated ONLY when a new Renko brick is formed (use renko close price).
    - Returns signals when a fresh EMA crossover occurs.
    """
    def __init__(self, cfg):
        self.cfg = cfg

        # fixed EMA periods from config
        self.fast_period_fixed = int(cfg.get("fast_ema", 9))
        self.slow_period_fixed = int(cfg.get("slow_ema", 21))

        # EMA storage (raw values)
        self.fast = deque(maxlen=500)
        self.slow = deque(maxlen=500)

        # price history (per-tick)
        self.prices = deque(maxlen=2000)

        # Renko bricks and bookkeeping
        self.bricks = []
        self.last_brick_cnt = 0

        # Volatility tracking (not used to change EMA here)
        self.last_price = None
        self.vol_ema = None
        self.vol_alpha = float(cfg.get("vol_alpha", 0.2))

        # last emitted signal (prevents repeated emission without a new crossover)
        self._last_emitted_signal = None

        # last saved ema values to detect fresh crossover
        self._last_fast = None
        self._last_slow = None

    # -------------------------
    # Volatility tracking (optional)
    # -------------------------
    def _update_volatility(self, price: float):
        if self.last_price is None:
            self.vol_ema = 0.0
            return
        diff = abs(price - self.last_price)
        if self.vol_ema is None:
            self.vol_ema = diff
        else:
            a = self.vol_alpha
            self.vol_ema = a * diff + (1 - a) * self.vol_ema

    # -------------------------
    # EMA helpers
    # -------------------------
    def _ema_step(self, prev, price, period):
        k = 2.0 / (period + 1.0)
        return price * k + prev * (1 - k)

    @property
    def fast_period(self):
        return self.fast_period_fixed

    @property
    def slow_period(self):
        return self.slow_period_fixed

    @property
    def vol(self):
        return self.vol_ema

    # -------------------------
    # Renko update
    # -------------------------
    def _update_bricks(self, price):
        """
        Returns True if a NEW renko brick was formed (we use that event to update EMA).
        Renko uses cfg['brick_size'].
        """
        bsize = float(self.cfg.get("brick_size", 10))
        # handle empty bricks
        if not self.bricks:
            base = (price // bsize) * bsize
            # initial brick with close==base (neutral up)
            self.bricks.append({"open": base, "close": base, "dir": "up"})
            return True

        last = self.bricks[-1]
        diff = price - last["close"]
        if abs(diff) < bsize:
            return False

        direction = "up" if diff > 0 else "down"
        closes = int(abs(diff) // bsize)
        for _ in range(closes):
            new_close = last["close"] + (bsize if direction == "up" else -bsize)
            self.bricks.append({
                "open": last["close"],
                "close": new_close,
                "dir": direction
            })
            last = self.bricks[-1]

        # keep a compact history
        self.bricks = self.bricks[-200:]
        return True

    # -------------------------
    # EMA update that runs only when renko brick forms
    # -------------------------
    def _update_emas_on_brick(self, brick_close_price):
        # seed if empty
        if len(self.fast) == 0:
            self.fast.append(brick_close_price)
            self.slow.append(brick_close_price)
        else:
            f = self._ema_step(self.fast[-1], brick_close_price, self.fast_period)
            s = self._ema_step(self.slow[-1], brick_close_price, self.slow_period)
            self.fast.append(f)
            self.slow.append(s)

    # -------------------------
    # Public tick update
    # -------------------------
    def update(self, price):
        """
        Called on each tick. EMAs are updated only when a new renko brick forms.
        """
        price = float(price)
        self.prices.append(price)
        self._update_volatility(price)
        self.last_price = price

        # check renko
        new_brick = self._update_bricks(price)
        if new_brick:
            # use the renko last close to update EMAs
            brick_close = self.bricks[-1]["close"]
            self._update_emas_on_brick(brick_close)

        # keep last emitted values for detection/logging
        if self.fast:
            self._last_fast = self.fast[-1]
        if self.slow:
            self._last_slow = self.slow[-1]

    # -------------------------
    # Signal logic
    # -------------------------
    def signal(self):
        """
        Emit 'LONG' or 'SHORT' only when a fresh crossover occurs (based on last two EMA values).
        Because EMAs only change on new bricks, this will fire once per crossover when a brick causes it.
        Also guard repeated emission: we won't repeat same signal until it goes away and reappears.
        """
        if len(self.fast) < 2 or len(self.slow) < 2:
            return None

        prev_fast, curr_fast = self.fast[-2], self.fast[-1]
        prev_slow, curr_slow = self.slow[-2], self.slow[-1]

        signal = None
        # bullish crossover
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            signal = "LONG"
        # bearish crossover
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            signal = "SHORT"
        else:
            signal = None

        # prevent repeating same signal if it was already emitted and not cleared
        if signal is not None and signal == self._last_emitted_signal:
            return None

        # if new signal, set last_emitted_signal (but we will clear on opposite crossover or when called externally)
        if signal is not None:
            self._last_emitted_signal = signal
            return signal

        # When no signal (EMAs not crossing), if the EMAs have separated (no longer supporting previous signal)
        # clear last_emitted_signal when the previous emitted signal condition has been invalidated.
        # This prevents getting stuck with last_emitted_signal set forever.
        if self._last_emitted_signal:
            # if last emitted was LONG but now fast < slow, clear it
            if self._last_emitted_signal == "LONG" and curr_fast <= curr_slow:
                self._last_emitted_signal = None
            if self._last_emitted_signal == "SHORT" and curr_fast >= curr_slow:
                self._last_emitted_signal = None

        return None
