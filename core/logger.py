import csv
import os
import time

class MLLogger:

    def __init__(self, file_path="data/ml_data.csv"):

        self.file_path = file_path
        
        # ensure folder exists
        folder = os.path.dirname(file_path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)

        # create file with header if missing
        if not os.path.exists(file_path):
            self._write_header()


    def _write_header(self):

        header = [
            "timestamp",
            "price",
            
            "ema_fast",
            "ema_slow",

            "renko_count",
            "renko_last_dir",

            "signal",

            "position",
            "entry_price",

            "pnl",

            "total_pnl"
        ]

        with open(self.file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)


    def log(self, price, strategy, trader, signal=None):

        row = [
            time.strftime('%Y-%m-%d %H:%M:%S'),
            price,

            strategy.fast[-1] if strategy.fast else None,
            strategy.slow[-1] if strategy.slow else None,

            len(strategy.bricks) if strategy.bricks else 0,
            strategy.bricks[-1]["dir"] if strategy.bricks else None,

            signal,

            trader.position["side"] if trader.position else None,
            trader.position["entry"] if trader.position else None,

            trader.last_pnl if hasattr(trader,"last_pnl") else None,
            trader.total
        ]

        with open(self.file_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)
