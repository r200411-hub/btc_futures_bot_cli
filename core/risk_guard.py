import time


class RiskGuard:

    def __init__(self,
                 max_exposure_seconds=120,
                 max_distance_pct=0.4,
                 max_slippage_pct=0.3,
                 on_risk=None):

        self.max_exposure_seconds = max_exposure_seconds
        self.max_distance_pct = max_distance_pct / 100
        self.max_slippage_pct = max_slippage_pct / 100

        self.on_risk = on_risk
        self.last_entry_time = None
        self.entry_price = None
        self.side = None


    def on_open(self, side, entry):
        self.side = side
        self.entry_price = entry
        self.last_entry_time = time.time()


    def reset(self):
        self.last_entry_time = None
        self.entry_price = None
        self.side = None


    def check(self, current_price):

        if self.last_entry_time is None:
            return

        # time exposure
        alive = time.time() - self.last_entry_time

        if alive > self.max_exposure_seconds:
            print(f"🚫 exposure timeout {alive:.1f}s")
            if self.on_risk:
                self.on_risk("EXPOSURE_TIMEOUT")
            self.reset()
            return

        if not self.entry_price:
            return

        # distance % from entry
        dist = abs(current_price - self.entry_price) / self.entry_price

        if dist > self.max_distance_pct:
            print(f"🚫 excessive distance {dist*100:.2f}%")
            if self.on_risk:
                self.on_risk("DISTANCE_MAX")
            self.reset()
            return
