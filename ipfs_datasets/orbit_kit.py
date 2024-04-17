import asyncio
import websockets
from datasets import DatasetDict
from datasets import load_dataset
import pandas as pd
import json
import tqdm
from dateutil.parser import parse
import datetime


class orbit_kit:
	def __init__(self, meta=None):
		self.uri = "ws://localhost:8888"
		self.connected = False


	# def __call__(self, method, **kwargs):
	# 	if method == "orb_upload_table":
	# 		self.orb_upload_table(**kwargs)
	# 		return self.orb_upload_table(**kwargs)


	def orb_upload(self, data, key=None, time_series=False, **kwargs):
		
		# TODO: Clean this up and make it better 
		"""
		This allows you to upload a hugging face dataset to orbitdb. The data can be uploaded as a document, key/value or time series data.
		Or if your data has no unique features it can be stored as indexed key/value data.
		
		:param data: The dataset to be uploaded to orbitdb this expects a dataset object <class 'datasets.dataset_dict.DatasetDict'>
		
		:param key: The primary key to be used for the data you want to store. This needs to be a unique feature and can't contain 
		duplicate entries. If your data has no unique features you dont have to pass a key. The data will then be stored as indexed key/value data.

		:param time_series: If your data is time series you can set time_series to True and the data will be stored as time series data.
		The key parameter is required for time series data. Should be the feature column that contains your timestamp or datetime.
		The data will be stored in an event database
		"""

		asyncio.run(self._orb_upload_async(data, key, time_series, **kwargs))


	#TODO: Test this function
	async def _check_existing_datasets(self, data=None, cid=None):
		try:
			socket = await websockets.connect(self.uri)
			
			# TODO: Add schema extraction from the data set to check against on the server
			# Check what the schema is of the dataset and compare it to the one on the server

			payload = {
				"job": "check_dataset",
				"dataset_name": data,
				"ipfs_address": cid
			}

			# TODO: Make sure the server handles these cases and returns the correct response
			await socket.send(json.dumps(payload))

			# REPONSE SHOULD CONTAIN THE SCHEMA IF FOUND AND THE IPFS ADDRESS IF FOUND
			response = await socket.recv()

			if response == "dataset_found":
				if response.schema == data.schema:
					print("Data set exists and is up to date")
					return True
				elif response.schema != data.schema:
					print("Data set exists but is outdated")
					# TODO: Make sure the hugging face one is newer than the one on the server

					if cid is not None:
						print('Downloading dataset from orbitdb, a newer version is available on hugging face')
						return True
					else:
						print('Updating existing dataset on orbitdb with the newer version from hugging face')
						return False
				else:
					return True
				
			if response == "dataset_not_found":
				return False
		
		except Exception as e:
			print(e)
			print("Aborting upload")
			return True
		
		finally:
			await socket.close()
			print("Socket closed")


	async def _orb_upload_async(self, data, key=None, time_series=False, **kwargs):
		try:
			if not isinstance(data, DatasetDict):
				raise ValueError("Dataset is invalid, Expected <class 'datasets.dataset_dict.DatasetDict'> but got: " + str(type(data)))

			# Connect to the websocket server and check if the data set exists on orbit db if so check which is newer
			# data_set_check = await self._check_existing_datasets(data=data)
			# if data_set_check == True:
			# 	return

			unique_columns = []
			splits = data.keys()
			batch_size = 100

			# Open a websocket connection
			# socket = await websockets.connect(self.uri)

			# FOR NON TIME SERIES DATA WITH A KEY
			if key is not None and time_series is False:
				for split in splits:
					if not key in data[split].column_names:
						raise Exception("Feature: " + key + " is not in the dataset: " + str(data[split].column_names))
					
					if len(data[split].unique(key)) != data[split].num_rows:
						# Cant store data with key as primary key because it's not unique. Storing the data as indexed key/value
						print("Data has duplicate entries in feature: " + key)
						break
					
					with tqdm.tqdm(total=data[split].num_rows) as pbar:
						# Checks if data has multiple unique columns 
						for feature in data[split].column_names:
							if len(data[split].unique(feature)) != data[split].num_rows:
								if feature in unique_columns:
									unique_columns.remove(feature)
								print("Data has duplicate entries in feature: " + feature)
							else:
								if feature not in unique_columns:
									unique_columns.append(feature)
								print("Data has no duplicate entries in feature: " + feature)


						print("Starting upload of dataset")
						# Batch data for better pipelining, WSS can start work earlier
						num_batches = data[split].num_rows // batch_size
						for i in range(num_batches):
							batch = data[split].select(range(i * batch_size, (i + 1) * batch_size))

							# --- STORE DATA AS DOCUMENT --- # ( single unique key )
							if len(unique_columns) == 1:
								for row in range(batch.num_rows):
									docstore = {}
									for feature in batch.column_names:
										docstore.update({feature: batch[feature][row]})
								
									# Needs collection name to be grouped should get the dataset name
		 							# Pass the name of the dataset or make a 
									payload = {
										"job": "upload_document",
										"data": docstore
									}
									pbar.update(1)
									# await socket.send(json.dumps(payload))
						
						
							# --- STORE DATA AS KEY/VALUE --- # ( multiple unique keys )
							else:
								if all(not isinstance(value, dict) for value in batch[0].values()):
									pass
								else:
									# TODO: Write code to flatten the dictionary 
									pass

								for row in range(batch.num_rows):
									# Needs a collection name to be grouped should get the dataset name								
									payload = {
										"job": "upload_key_value",
										"key": batch[key][row],
										"value": {k: v for k, v in batch[row].items() if k != key} # Removes the key column from the value dictionary
									}
									
									pbar.update(1)
									# await socket.send(json.dumps(payload))
								
								pass


			# FOR TIME SERIES DATA
			elif time_series is True and key is not None:
					for split in splits:
						if not key in data[split].column_names:
							raise Exception("Feature: " + key + " is not in the dataset: " + str(data[split].column_names))
					
						# Grabs the first element and checks it's type and then casts it to a datetime object to see if it's a time series
						first_element = data[split][key][0]
						if isinstance(first_element, str):
							try:
								parse(first_element)
								print("Data is a time series")
							except ValueError:
								print("Data is not a time series")
						elif isinstance(first_element, (int, float)):
							try:
								datetime.datetime.fromtimestamp(first_element)
								print("Data is a time series")
							except ValueError:
								print("Data is not a time series")
						elif isinstance(first_element, (pd.Timestamp, pd.core.series.Series)):
							try:
								first_element.to_pydatetime()
								print("Data is a time series")
							except Exception:
								print("Data is not a time series")
						elif isinstance(first_element, int):
							try:
								datetime.datetime.fromtimestamp(first_element, datetime.timezone.utc)
								print("Data is a time series")
							except ValueError:
								print("Data is not a time series")
						

						print("Starting upload of dataset")
						with tqdm.tqdm(total=data[split].num_rows) as pbar:
							# Batch data for better pipelining, WSS can start work earlier
							num_batches = data[split].num_rows // batch_size
							for i in range(num_batches):
								batch = data[split].select(range(i * batch_size, (i + 1) * batch_size))

								for row in range(batch.num_rows):
									# Needs a collection name to be grouped should get the dataset name								
									payload = {
										"job": "upload_time_series",
										"key": batch[key][row],
										"value": {k: v for k, v in batch[row].items() if k != key} # Removes the key column from the value dictionary
									}
									
									pbar.update(1)
									
									# await socket.send(json.dumps(payload))
	   					

						
			# FOR NON TIME SERIES DATA WITHOUT A KEY OR NON UNIQUE FIELD
			else:
				# Stores the index as the key (keeping this out of the loop so i maintain a single incrementing key for all the data)
				key_idx = 0

				for split in splits:
					# Checks if data has multiple unique columns 
					for feature in data[split].column_names:
						try:
							data[split].unique(feature)
						except Exception as e:
							# Data type doesn't support unique check so skip it 
							continue

						if len(data[split].unique(feature)) != data[split].num_rows:
							if feature in unique_columns:
								unique_columns.remove(feature)
							print("Data has duplicate entries in feature: " + feature)
						else:
							if feature not in unique_columns:
								unique_columns.append(feature)
							print("Data has no duplicate entries in feature: " + feature)
						
					if len(unique_columns) > 1:
						print("Data has multiple unique columns") 
						# TODO: Better error messages Point out to the user that the data has multiple unique columns and prompt them to pass a key to store as key/value and they can check their data on the huggingface data explorer
						raise Exception("Your data has multiple unique columns, Please use the key parameter to select a primary key so the data can be stored in a more suitable key/value table.")
						
					if len(unique_columns) == 1:
						raise Exception("Your data has a unique column, Please use the key parameter to select a primary key so the data can be stored in a more suitable document store.")
						
					if len(unique_columns) == 0:
						pass

				# batch the data 
				print("Starting upload of dataset")
				with tqdm.tqdm(total=data[split].num_rows) as pbar:
					# Batch data for better pipelining, WSS can start work earlier
					num_batches = data[split].num_rows // batch_size
					for i in range(num_batches):
						batch = data[split].select(range(i * batch_size, (i + 1) * batch_size))

						for row in range(batch.num_rows):
							# Needs a collection name to be grouped should get the dataset name
							# Not sure how the indexed key/value data will look like so i added some key to insert but it might not be needed 
							payload = {
								"job": "upload_time_series",
								"key": key_idx,
								"value": {k: v for k, v in batch[row].items()} # Removes the key column from the value dictionary
							}
							# Increment the key index ( not using i because i want a single incrementing key 
							# for all the data in the dataset regardless of the split or batch) 
							key_idx += 1

							pbar.update(1)
							
							# await socket.send(json.dumps(payload))
	   
		except Exception as e:
			print(e)



	async def orb_download(self, cid):
		data_set_check = await self._check_existing_datasets(cid=cid)

		
		if data_set_check == True:
			# Run download code here
			# socket = await websockets.connect(self.uri)
			pass

	
	def _schema_extractor(self, data):
		# TODO: Implement a way to extract the schema from the data set
		pass


	def _cid_resolver(self, cid):
		# TODO: Implement a way to resolve the cid to a dataset name or the other way around
		pass