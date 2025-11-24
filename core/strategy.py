from collections import deque

class Strategy:

    def __init__(self, cfg):
        self.cfg = cfg
        self.prices = deque(maxlen=2000)
        self.fast = deque(maxlen=500)
        self.slow = deque(maxlen=500)
        self.bricks = []
        self.last_brick_cnt = 0

    def _ema(self, values, period):
        if len(values) < period:
            return None
        k = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for p in values[period:]:
            ema = p*k + ema*(1-k)
        return ema

    def update(self, price):

        self.prices.append(price)

        # update ema
        f = self._ema(list(self.prices), self.cfg["fast_ema"])
        s = self._ema(list(self.prices), self.cfg["slow_ema"])

        if f: self.fast.append(f)
        if s: self.slow.append(s)

        # build bricks
        self.build_bricks(price)

    def build_bricks(self, price):

        bsize = self.cfg["brick_size"]

        if not self.bricks:
            base = (price//bsize)*bsize
            self.bricks.append({"open":base,"close":base,"dir":"up"})
            return

        last = self.bricks[-1]
        diff = price - last["close"]

        if abs(diff) >= bsize:

            direction = "up" if diff>0 else "down"
            closes = int(abs(diff)//bsize)

            for _ in range(closes):
                new_price = last["close"] + (bsize if direction=="up" else -bsize)

                self.bricks.append({
                    "open":last["close"],
                    "close":new_price,
                    "dir":direction
                })

                last = self.bricks[-1]

            self.bricks = self.bricks[-200:]

    def signal(self):

        if len(self.fast)<2 or len(self.slow)<2 or len(self.bricks)<2:
            return None

        if len(self.bricks) == self.last_brick_cnt:
            return None

        self.last_brick_cnt = len(self.bricks)

        f,fp = self.fast[-1], self.fast[-2]
        s,sp = self.slow[-1], self.slow[-2]

        b, bp = self.bricks[-1], self.bricks[-2]

        if fp<=sp and f>s and b["dir"]=="up" and bp["dir"]=="up":
            return "LONG"

        if fp>=sp and f<s and b["dir"]=="down" and bp["dir"]=="down":
            return "SHORT"
