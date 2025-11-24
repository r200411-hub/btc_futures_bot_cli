import pyarrow as pa
import pyarrow.parquet as pq
import os
from datetime import datetime


class ParquetLogger:

    def __init__(self, filename="trades.parquet"):

        self.filename = filename

        # schema definition (fixed)
        self.schema = pa.schema([
            ("timestamp", pa.string()),
            ("side", pa.string()),
            ("action", pa.string()),
            ("price", pa.float64()),
            ("pnl", pa.float64()),
            ("brick_size", pa.float64()),
        ])

        # Create empty file if doesn't exist
        if not os.path.exists(filename):
            empty = pa.Table.from_pydict({}, schema=self.schema)
            pq.write_table(empty, filename)


    def log(self, trade_record: tuple):

        # trade_record expected format:
        # (timestamp, side, action, price, pnl, brick_size)

        record_dict = {
            "timestamp":   [trade_record[0]],
            "side":        [trade_record[1]],
            "action":      [trade_record[2]],
            "price":       [float(trade_record[3])],
            "pnl":         [float(trade_record[4])],
            "brick_size":  [float(trade_record[5])],
        }

        table = pa.Table.from_pydict(record_dict, schema=self.schema)

        # append to file
        with pq.ParquetWriter(self.filename, self.schema, use_dictionary=True, compression="snappy") as writer:
            writer.write_table(table)

        print("💾 Parquet trade saved")
