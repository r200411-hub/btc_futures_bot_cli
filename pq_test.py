from core.parquet_logger import ParquetLogger
import pyarrow.parquet as pq


# 1) create logger
p = ParquetLogger("data/test_logger.pq")

# 2) write 5 artificial rows
for i in range(5):
    p.log({
        "timestamp": "2025-11-24 00:00:00",
        "price": 100+i,

        "fast_ema": 1.0,
        "slow_ema": 2.0,

        "fast_period": 10,
        "slow_period": 20,

        "ema_spread": 0.3,
        "vol_ema": 0.5,

        "regime": "BULL",
        "regime_confidence": 0.95,

        "brick_dir": "up",
        "brick_count": 12,

        "signal": "",
        "pos_side": "",
        "pnl": 0.0
    })

# IMPORTANT:
p.close()


# 3) read and print result
print("\n🔍 Parquet contents:")
print(pq.read_table("data/test_logger.pq"))

