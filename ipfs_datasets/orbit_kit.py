import asyncio
import base64
import PIL
import PIL.Image
import websockets
from datasets import DatasetDict
from datasets import load_dataset
import pandas
import json
import tqdm
from dateutil.parser import parse
import datetime

class orbit_kit:
	def __init__(self, meta=None):
		self.uri = "ws://localhost:8888"
		self.socket = None
		self.connected = False
		self.batch_size = 100


	# def __call__(self, method, **kwargs):
	# 	if method == "orb_upload_table":
	# 		self.orb_upload_table(**kwargs)
	# 		return self.orb_upload_table(**kwargs)


	def orb_upload(self, data, dataset_name, key=None, time_series=False, **kwargs):
		asyncio.run(self._orb_upload_async(data, dataset_name, key, time_series, **kwargs))
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


	def orb_download(self, cid):
		asyncio.run(self._orb_download(cid))
		"""
		This allows you to download a dataset from orbitdb. The data is stored as a hugging face dataset.
		
		:param cid: The content identifier of the dataset you want to download. This is the hash of the dataset stored on orbitdb.
		"""


	async def _orb_upload_async(self, data, dataset_name, key=None, time_series=False, **kwargs):
		try:
			if not isinstance(data, DatasetDict):
				raise ValueError("Dataset is invalid, Expected <class 'datasets.dataset_dict.DatasetDict'> but got: " + str(type(data)))

			self.socket = await websockets.connect(self.uri)

			data_set_check = await self._check_existing_datasets(data=data, dataset_name=dataset_name)
			if data_set_check == True:
				return

			# FOR NON TIME SERIES DATA WITH A KEY
			if key is not None and time_series is False:
				await self._upload_with_key(data, dataset_name, key)
				
			# --- STORE DATA AS TIMESERIES --- # ( Event key )
			elif time_series is True and key is not None:
				await self._upload_time_series(data, dataset_name, key)
							
			# --- STORE DATA AS INDEXED KEY/VALUE --- # ( no unique key )
			else:
				await self._upload_without_key(data, dataset_name)


		except Exception as e:
			print(e)

		finally:
			if self.socket is not None:
				await self.socket.close()
			self.socket = None



	async def _upload_with_key(self, data, dataset_name, key):
		splits = data.keys()

		# Gets the schema for the data (not used if document store is used)
		schema = self._schema_extractor(data)

		for split in splits:
			if not key in data[split].column_names:
				raise Exception("Feature: " + key + " is not in the dataset: " + str(data[split].column_names))
			
			if len(data[split].unique(key)) != data[split].num_rows:
				print("Data has duplicate entries in feature: " + key)
				raise Exception("The Feature you selected as a key is not unique, Please select a unique feature to store the data as key/value")
			
			with tqdm.tqdm(total=data[split].num_rows) as pbar:
				
				# Checks if data has multiple unique columns 
				unique_columns = self._check_multiple_unique(data[split])

				print("Starting upload of dataset")
				num_batches = data[split].num_rows // self.batch_size
				for i in range(num_batches):
					batch = data[split].select(range(i * self.batch_size, (i + 1) * self.batch_size))

					# --- STORE DATA AS DOCUMENT --- # ( single unique key )
					if len(unique_columns) == 1:
						docstore = {}
						for row in range(batch.num_rows):
							# TODO: Add the python object removal code here ( Remove python objects from the data for document store)
							for feature in batch.column_names:
								docstore.update({feature: batch[feature][row]})
 
							pbar.update(1)

							payload = {
								"job": "upload",
								"database_type": "document",
								"dataset_name": dataset_name,
								"key": key,
								"value": docstore
							}

							await self.socket.send(json.dumps(payload))
							await self.socket.recv()
				
				
					# --- STORE DATA AS KEY/VALUE --- # ( multiple unique keys )
					else:
						if all(not isinstance(value, dict) for value in batch[0].values()):
							pass
						else:
							# TODO: Write code to flatten the dictionary 
							pass

						payload = {
							"job": "upload",
							"database_type": "key_value",
							"dataset_name": dataset_name,
							"key": key,
							"value": {},
							"schema": schema
						}

						for row in range(batch.num_rows):
							for k, v in batch[row].items():
									payload["value"][k] = self._object_data_extract(v)

							pbar.update(1)

						await self.socket.send(json.dumps(payload))
						await self.socket.recv()



	async def _upload_time_series(self, data, dataset_name, key):
		splits = data.keys()

		# TODO: Not sure if event databases needs a schema! ( Remove if not needed )
		schema = self._schema_extractor(data)

		for split in splits:
			if not key in data[split].column_names:
				raise Exception("Feature: " + key + " is not in the dataset: " + str(data[split].column_names))
		
			# TODO: Clean this check for the timeseries types up
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
			elif isinstance(first_element, (pandas.Timestamp, pandas.core.series.Series)):
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
				num_batches = data[split].num_rows // self.batch_size
				for i in range(num_batches):
					batch = data[split].select(range(i * self.batch_size, (i + 1) * self.batch_size))

					payload = {
							"job": "upload",
							"database_type": "event",
							"dataset_name": dataset_name, # TODO: Data set names cant contain / so i need to resolve these 
							"key": key,
							"value": {},
							"schema": schema
						}

					for row in range(batch.num_rows):						
						for k, v in batch[row].items():
							payload["value"][k] = self._object_data_extract(v)
							
						pbar.update(1)

					await self.socket.send(json.dumps(payload))
					await self.socket.recv()




	async def _upload_without_key(self, data, dataset_name):
		key_idx = 0
		splits = data.keys()

		schema = self._schema_extractor(data)

		for split in splits:
			# Checks if data has multiple unique columns 
			unique_columns = self._check_multiple_unique(data[split])
				
			if len(unique_columns) > 1:
				print("Data has multiple unique columns") 
				# TODO: Better error messages Point out to the user that the data has multiple unique columns and prompt them to pass a key to store as key/value and they can check their data on the huggingface data explorer
				raise Exception("Your data has multiple unique columns, Please use the key parameter to select a primary key so the data can be stored in a more suitable key/value table.")
				
			if len(unique_columns) == 1:
				raise Exception("Your data has a unique column, Please use the key parameter to select a primary key so the data can be stored in a more suitable document store.")
				
			if len(unique_columns) == 0:
				pass

 
		print("Starting upload of dataset")
		with tqdm.tqdm(total=data[split].num_rows) as pbar:
			num_batches = data[split].num_rows // self.batch_size
			for i in range(num_batches):
				batch = data[split].select(range(i * self.batch_size, (i + 1) * self.batch_size))

				payload = {
						"job": "upload",
						"database_type": "indexed_key_value",
						"dataset_name": dataset_name,
						# "key": "id", # Check how to handle this i'm thinking of passing the column name as index
						"value": {},
						"schema": schema
				}

				for row in range(batch.num_rows):
					# TODO: Check if an inserted index is needed for indexed key/value data	
					payload["value"][key_idx] = {}

					for k, v in batch[row].items():
						payload["value"][key_idx][k] = self._object_data_extract(v)
					
					# Increments a key for the entire set
					key_idx += 1
					pbar.update(1)

				await self.socket.send(json.dumps(payload))
				await self.socket.recv()



	async def _orb_download(self, cid):
		self.socket = await websockets.connect(self.uri)
		# data_set_check = await self._check_existing_datasets(cid=cid)
		
		# For testing purposes
		data_set_check = True

		if data_set_check == True:
			pass
		else:
			print("Dataset not found on orbitdb")
			return
		
		try:
			socket = await websockets.connect(self.uri)
			payload = {
				"job": "download",
				"ipfs_address": cid,
			}

			await socket.send(json.dumps(payload))

			response = await socket.recv()

			print(response)			

		except Exception as e:
			print(e)



	#TODO: Test this function
	async def _check_existing_datasets(self, data=None, dataset_name=None, cid=None):
		try:
			# Not sure if this is the best way maybe check name first and then schema if it exists
			# if data is not None:
			# 	schema = self._schema_extractor(data)

			payload = {
				"job": "check_dataset",
				"dataset_name": dataset_name,
				# "schema": schema,
				"ipfs_address": cid
			}

			# TODO: Make sure the server handles these cases and returns the correct response
			await self.socket.send(json.dumps(payload))

			# REPONSE SHOULD CONTAIN THE SCHEMA IF FOUND AND THE IPFS ADDRESS IF FOUND
			response = await self.socket.recv()

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
		

		
	def _check_multiple_unique(self, data):
		unique_columns = []

		print("Checking for multiple unique columns")
		with tqdm.tqdm(total=len(data.column_names)) as pbar:
			for feature in data.column_names:
				try:
					data.unique(feature)
				except Exception as e:
					# Data type doesn't support unique check so skip it
					continue

				if len(data.unique(feature)) != data.num_rows:
					if feature in unique_columns:
						unique_columns.remove(feature)
				else:
					if feature not in unique_columns:
						unique_columns.append(feature)

				pbar.update(1)

		return unique_columns



	# FOR SOME REASON THE TIMESTAMP IS BEING PASSED AS SOME WEIRD FLOAT NUMBER INSTEAD OF THE TIMESTAMP OBJECT
	def _object_data_extract(self, value):
		# TODO: Keep expanding this for every datatype encountered
		if isinstance(value, PIL.Image.Image):
			image_bytes = value.tobytes()
			encoded_image = base64.b64encode(image_bytes).decode('utf-8')
			return encoded_image
		
		elif isinstance(value, datetime.datetime):
			return str(value)
		
		if isinstance(value, pandas.Timestamp):
			return str(value)
		
		else:
			return value

	
	
	def _schema_extractor(self, data):
		schema = {
			'columns': data.num_columns,
			'rows': data.num_rows,
			'data_types': {}
		}
		
		splits = data.keys()
		
		for split in splits:
			print("Checking dataset for schema: ")
			with tqdm.tqdm(total=len(data[split].column_names)) as pbar:
			
				for feature in data[split].column_names:
					data_type = data[split][feature][0]
					
					# TODO: Add all the SQL data types that i can encounter 
					# SQL DATATYPES
					# BLOB
					# TEXT	

					if isinstance(data_type, str):
						schema['data_types'].update({feature: 'TEXT'})
					
					elif isinstance(data_type, int):
						schema['data_types'].update({feature: 'INT'})
					
					elif isinstance(data_type, float):
						schema['data_types'].update({feature: 'FLOAT'})

					elif isinstance(data_type, bool):
						schema['data_types'].update({feature: 'BOOLEAN'})

					elif isinstance(data_type, datetime.datetime) or isinstance(data_type, pandas.Timestamp):
						# NEEDS ADDITIONAL CHECKING FOR TIMESTAMPS, DATES, TIME etc 
						schema['data_types'].update({feature: 'DATETIME'})

					elif isinstance(data_type, PIL.Image.Image):
						schema['data_types'].update({feature: 'BLOB'})

					# TODO: Add more data types here that fit the SQL scheme

					pbar.update(1)

				break

		return schema


	def _cid_resolver(self, cid):
		# TODO: Implement a way to resolve the cid to a dataset name or the other way around
		pass