# core/parquet_logger.py
import pyarrow as pa
import pyarrow.parquet as pq
import os
from datetime import datetime, timezone

class ParquetLogger:
    def __init__(self, path):
        self.path = path
        self.schema = pa.schema([
            ("timestamp", pa.string()),
            ("price", pa.float64()),
            ("fast_ema", pa.float64()),
            ("slow_ema", pa.float64()),
            ("fast_period", pa.int32()),
            ("slow_period", pa.int32()),
            ("ema_spread", pa.float64()),
            ("vol_ema", pa.float64()),
            ("regime", pa.string()),
            ("regime_confidence", pa.float64()),
            ("brick_dir", pa.string()),
            ("brick_count", pa.int32()),
            ("signal", pa.string()),
            ("pos_side", pa.string()),
            ("pnl", pa.float64())
        ])
        self.batch = []

    def log(self, row: dict):
        # Ensure timestamp is iso string
        if "timestamp" not in row or row["timestamp"] is None:
            row["timestamp"] = datetime.now(timezone.utc).isoformat()
        # Normalize keys that may be None -> keep as None (pyarrow accepts)
        self.batch.append(row)
        if len(self.batch) >= 200:
            self.flush()

    def flush(self):
        if not self.batch:
            return
        table = pa.Table.from_pylist(self.batch, schema=self.schema)
        if os.path.exists(self.path):
            old = pq.read_table(self.path)
            combined = pa.concat_tables([old, table])
            pq.write_table(combined, self.path)
        else:
            pq.write_table(table, self.path)
        self.batch = []

    def close(self):
        try:
            self.flush()
        except Exception:
            pass
