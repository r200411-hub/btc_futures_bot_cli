# core/logger.py
import csv
import os
from datetime import datetime, timezone

class MLLogger:
    def __init__(self, path):
        self.path = path
        exists = os.path.exists(path)
        # append text mode, line buffering
        self.f = open(path, "a", newline="", buffering=1)
        self.w = csv.writer(self.f)
        if not exists:
            self.w.writerow([
                "timestamp","price",
                "fast_ema","slow_ema",
                "fast_period","slow_period",
                "ema_spread","vol_ema",
                "regime","regime_confidence",
                "brick_dir","brick_count",
                "signal","pos_side","pnl"
            ])

    def log(self, price, strategy, trader, regime, signal):
        ts = datetime.now(timezone.utc).isoformat()
        spread = ""
        if getattr(strategy, "fast", None) and getattr(strategy, "slow", None):
            try:
                spread = strategy.fast[-1] - strategy.slow[-1]
            except Exception:
                spread = ""

        # SAFE position extraction
        pos = trader.position or {}
        pos_side = pos.get("side") or pos.get("type") or ""

        pnl = 0.0
        try:
            pnl = trader.calculate_pnl(price) if trader.position else 0.0
        except Exception:
            pnl = 0.0

        try:
            self.w.writerow([
                ts,
                price,
                strategy.fast[-1] if getattr(strategy, "fast", None) else "",
                strategy.slow[-1] if getattr(strategy, "slow", None) else "",
                getattr(strategy, "fast_period", None),
                getattr(strategy, "slow_period", None),
                spread,
                getattr(strategy, "vol", None),
                getattr(regime, "current_regime", ""),
                getattr(regime, "confidence", ""),
                (strategy.bricks[-1]["dir"] if strategy.bricks else ""),
                len(strategy.bricks),
                signal,
                pos_side,
                f"{pnl:.2f}"
            ])
        except Exception as e:
            print("LOGGER ERROR for CSV:", e)
