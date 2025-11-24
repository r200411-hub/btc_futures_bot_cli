import pyarrow as pa
import pyarrow.parquet as pq
import os
from datetime import datetime


import pyarrow as pa
import pyarrow.parquet as pq
import os

class ParquetLogger:

    def __init__(self, filename="trades.parquet"):
        self.filename = filename

        self.schema = pa.schema([
            ("timestamp", pa.string()),
            ("side", pa.string()),
            ("action", pa.string()),
            ("price", pa.float64()),
            ("pnl", pa.float64()),
            ("brick_size", pa.float64()),
        ])

        if not os.path.exists(self.filename):

            empty_table = pa.Table.from_arrays(
                [
                    pa.array([], type=pa.string()),
                    pa.array([], type=pa.string()),
                    pa.array([], type=pa.string()),
                    pa.array([], type=pa.float64()),
                    pa.array([], type=pa.float64()),
                    pa.array([], type=pa.float64()),
                ],
                schema=self.schema,
            )

            pq.write_table(empty_table, self.filename)



    def log(self, record):

        row = {
            "timestamp":   [record[0]],
            "side":        [record[1]],
            "action":      [record[2]],
            "price":       [float(record[3])],
            "pnl":         [float(record[4])],
            "brick_size":  [float(record[5])],
        }

        table = pa.Table.from_pydict(row, schema=self.schema)

        # APPEND CORRECTLY
        existing = pq.read_table(self.filename)
        combined = pa.concat_tables([existing, table])

        pq.write_table(combined, self.filename)

        print("💾 stored in Parquet")

