import time, threading
from collections import deque


class SlowdownDetector:

    def __init__(self, window=40, threshold_factor=3.0, on_slow=None):
        """
        window = number of recent tick intervals
        threshold_factor = multiplier to define anomaly
        on_slow = callback on slowdown event
        """
        self.intervals = deque(maxlen=window)
        self.last_tick = time.time()
        self.threshold_factor = threshold_factor
        self.on_slow = on_slow
        self.running = False


    def mark(self):
        """call this on EACH on_price() execution"""
        now = time.time()
        delta = now - self.last_tick
        self.last_tick = now

        self.intervals.append(delta)


    def avg(self):
        if not self.intervals:
            return 0
        return sum(self.intervals) / len(self.intervals)


    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()


    def _loop(self):
        while self.running:

            if len(self.intervals) >= 10:

                avg = self.avg()
                latest = self.intervals[-1]

                if latest > avg * self.threshold_factor:
                    print(f"\n🐢 BOT SLOW-DOWN detected — latest tick={latest:.2f}s avg={avg:.2f}s")

                    if self.on_slow:
                        self.on_slow()

            time.sleep(3)
