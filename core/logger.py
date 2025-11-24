import csv
import os
import time
from datetime import datetime,timezone

class MLLogger:

    def __init__(self, path):

        self.path = path

        exists = os.path.exists(path)

        # open in append, newline flush enabled
        self.f = open(path, "a", newline="", buffering=1)
        self.w = csv.writer(self.f)

        if not exists:
            self.w.writerow([
                "timestamp",
                "price",

                # EMA raw
                "fast_ema",
                "slow_ema",

                # dynamic EMA periods
                "fast_period",
                "slow_period",

                # EMA spread
                "ema_spread",

                # volatility index
                "vol_ema",

                # regime label
                "regime",

                # regime confidence
                "regime_confidence",

                # renko bricks
                "brick_dir",
                "brick_count",

                # signal
                "signal",

                # position
                "pos_side",

                # pnl
                "pnl"
            ])

    def log(self, price, strategy, trader, regime, signal):
        
        
        ts = datetime.now(timezone.utc).isoformat()


        # print(ts)
        spread = ""
        if strategy.fast and strategy.slow:
            spread = strategy.fast[-1] - strategy.slow[-1]

        pos = trader.position["type"] if trader.position else ""
        pnl = trader.calculate_pnl(price) if trader.position else 0.0

        self.w.writerow([
            ts,
            price,

            strategy.fast[-1] if strategy.fast else "",
            strategy.slow[-1] if strategy.slow else "",

            strategy.fast_period,
            strategy.slow_period,

            spread,

            strategy.vol,

            regime.current_regime,
            regime.confidence,

            strategy.bricks[-1]["dir"] if strategy.bricks else "",
            len(strategy.bricks),

            signal,
            pos,
            f"{pnl:.2f}"
        ])
