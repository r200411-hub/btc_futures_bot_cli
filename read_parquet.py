import pandas as pd
import pyarrow.parquet as pq

# Path to your Parquet file
parquet_file_path = 'data/tickdata.parquet'

# Read the Parquet file into a Pandas DataFrame
# df = pd.read_parquet(parquet_file_path)

# # Display the first few rows of the DataFrame
# print(df.head())



# Read the Parquet file into a PyArrow Table
table = pq.read_table(parquet_file_path)

# Convert the PyArrow Table to a Pandas DataFrame (optional)
df = table.to_pandas()

print(df)