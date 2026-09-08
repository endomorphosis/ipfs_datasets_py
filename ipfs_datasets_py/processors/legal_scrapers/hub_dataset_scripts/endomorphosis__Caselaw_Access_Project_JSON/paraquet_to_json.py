import pandas as pd
import pyarrow.parquet as pq
import os
import json
import pathlib

this_dir = os.path.dirname(os.path.abspath(__file__))
folders = []
for folder in os.listdir(this_dir):
    if os.path.isdir(os.path.join(this_dir, folder)):
        print(os.path.join(this_dir, folder))
        folders.append(os.path.join(this_dir, folder))

for this_folder in folders:
    this_path = this_folder
    print(this_path)
    for file in os.listdir(this_path):
        print(file)
        if file.endswith(".parquet"):
            this_file = os.path.join(this_path, file)
            print(this_file)
            # Read the Parquet file
            data = pq.read_table(this_file)

            # Convert to pandas DataFrame
            df = data.to_pandas()
            del data
            # Convert to JSON
            json_data = df.to_json(orient='records')
            del df
            json_data = json.loads(json_data)
            for i in json_data:
                id = i['id']
                data = json.dumps(i)
                with open(f'{this_path}/{id}.json', 'w') as f:
                    json.dump(data, f)
                    