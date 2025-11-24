# core/regime.py
from collections import deque
import statistics
import math

class MarketRegimeDetector:
    """
    Simple market regime detector using:
      - EMA spread (trend strength)
      - Renko direction consistency (chop vs trend)
      - Recent price volatility (spiky vs calm)
    """

    def __init__(self,
                 price_window=60,
                 brick_window=30,
                 min_trend_spread=20.0,
                 max_chop_flip_rate=0.4,
                 high_volatility_z=2.5):
        # Rolling price window for volatility
        self.prices = deque(maxlen=price_window)
        # Recent brick directions: 'up'/'down'
        self.bricks = deque(maxlen=brick_window)

        # thresholds
        self.min_trend_spread = float(min_trend_spread)
        self.max_chop_flip_rate = float(max_chop_flip_rate)
        self.high_volatility_z = float(high_volatility_z)

        # current state
        self.current_regime = "UNKNOWN"
        self.last_regime = None

        # diagnostics
        self.last_spread = 0.0
        self.last_vol = 0.0
        self.last_flip_rate = 0.0

    def _update_prices(self, price: float):
        self.prices.append(float(price))

    def _update_bricks_from_strategy(self, strategy):
        # strategy.renko_bricks is a list; we just look at directions
        if getattr(strategy, "renko_bricks", None):
            last = strategy.renko_bricks[-1]
            self.bricks.append(last.get("direction", "up"))

    def _compute_volatility(self):
        """Rough tick volatility via standard deviation of recent prices."""
        if len(self.prices) < 10:
            return 0.0

        diffs = []
        p_list = list(self.prices)
        for i in range(1, len(p_list)):
            diffs.append(p_list[i] - p_list[i-1])

        if len(diffs) < 5:
            return 0.0

        return statistics.pstdev(diffs)

    def _compute_flip_rate(self):
        """How often bricks flip direction in recent history."""
        if len(self.bricks) < 5:
            return 0.0

        flips = 0
        b_list = list(self.bricks)
        for i in range(1, len(b_list)):
            if b_list[i] != b_list[i-1]:
                flips += 1

        return flips / (len(b_list) - 1)

    def _compute_trend_spread(self, strategy):
        """EMA spread as simple trend strength proxy."""
        # strategy.fast & slow exist, use those safely
        if not getattr(strategy, "fast", None) or not getattr(strategy, "slow", None):
            return 0.0
        
        if len(strategy.fast) == 0 or len(strategy.slow) == 0:
            return 0.0
        
        f = strategy.fast[-1]
        s = strategy.slow[-1]

        # invalid numbers?
        if f is None or s is None:
            return 0.0
        return float(f - s)

    def update(self, price: float, strategy):
        """
        Call this once per tick AFTER strategy.update(price).
        """
        # protect stability
        try:
            price = float(price)
        except:
            return self.current_regime
        
        self._update_prices(price)
        self._update_bricks_from_strategy(strategy)

        # compute diagnostics
        #  compute diagnostics SAFELY
        try:
            spread = self._compute_trend_spread(strategy)
        except:
            spread = 0.0

        vol = self._compute_volatility()
        flip_rate = self._compute_flip_rate()

        self.last_spread = spread
        self.last_vol = vol
        self.last_flip_rate = flip_rate

        # basic z-score style classification for volatility
        # here we just compare vol to price scale
        vol_score = abs(vol)  # simple magnitude (you can refine later)

        # --- classify regime ---

        # default
        regime = "UNKNOWN"

        # high volatility => SPIKE (danger zone)
        if vol_score > self.high_volatility_z * max(1.0, abs(spread)):
            regime = "SPIKE"

        else:
            # trend detection via EMA spread & flip rate
            if abs(spread) >= self.min_trend_spread and flip_rate <= self.max_chop_flip_rate:
                if spread > 0:
                    regime = "BULL_TREND"
                else:
                    regime = "BEAR_TREND"
            else:
                # not strong trend
                if flip_rate > self.max_chop_flip_rate:
                    regime = "CHOPPY"
                else:
                    regime = "FLAT"

        self.last_regime = self.current_regime
        self.current_regime = regime
        # confidence score = normalized strength measure
        spread_strength = abs(spread) / max(1.0, vol_score)

        self.last_confidence = float( min(spread_strength, 10.0 ) )
        
        return regime

    # --- helper views for the bot ---

    def can_trade_long(self):
        """Restrict long entries to suitable regimes."""
        return self.current_regime in ("BULL_TREND",)

    def can_trade_short(self):
        """Restrict short entries to suitable regimes."""
        return self.current_regime in ("BEAR_TREND",)

    def is_danger(self):
        """Regimes where we should avoid opening new trades."""
        return self.current_regime in ("SPIKE", "CHOPPY")

    def summary(self):
        return {
            "regime": self.current_regime,
            "spread": self.last_spread,
            "vol": self.last_vol,
            "flip_rate": self.last_flip_rate,
        }
    @property
    def confidence(self):
        return getattr(self, "last_confidence", 0.0)
