import asyncio
import websockets
from datasets import DatasetDict
from datasets import load_dataset
from pandas import Timestamp

class orbit_kit:
	def __init__(self, meta=None):
		self.uri = "ws://localhost:8888"
		self.connected = False


	# def __call__(self, method, **kwargs):
	# 	if method == "orb_upload_table":
	# 		self.orb_upload_table(**kwargs)
	# 		return self.orb_upload_table(**kwargs)


	def orb_upload(self, data, key=None, time_series=False, **kwargs):
		asyncio.run(self._orb_upload_async(data, key, time_series, **kwargs))


	async def _orb_upload_async(self, data, key=None, time_series=False, **kwargs):
		try:
			if not isinstance(data, DatasetDict):
				raise ValueError("Dataset is invalid, Expected <class 'datasets.dataset_dict.DatasetDict'> but got: " + str(type(data)))

			unique_columns = []
			splits = data.keys()

			if key is not None and time_series is False:
				for split in splits:
					if not key in data[split].column_names:
						raise Exception("Feature is not in the dataset: " + str(data[split].column_names))
					
					if len(data[split].unique(key)) != data[split].num_rows:
						break
						# raise Exception("\'" + key + "\' is not a unique feature, Please choose a feature that contains no duplicate entries or set insert_index to True if the data has no unique feature")
					
					# Figure out when to go for key/value or document storage
					for feature in data[split].column_names:
						if len(data[split].unique(feature)) != data[split].num_rows:
							if feature in unique_columns:
								unique_columns.remove(feature)
							print("Data has duplicate entries in feature: " + feature)
						else:
							if feature not in unique_columns:
								unique_columns.append(feature)
							print("Data has no duplicate entries in feature: " + feature)

					# TODO:  Figure out how to deal with train, test, validation splits. Do i store them seperately or in one table? 
					print("Storing " + split + " dataset as: ")

					# TODO: Check with endo if this a good criteria to use to determine the storage type
					if len(unique_columns) > 1:
						# store as document ( multiple keys can be queried )
						print(" document ( multiple keys can be queried )")
						
						# clean up data
						# upload data 

						pass
					else:
						# data contains only one unique feature column ( single key can be queried )
						print(" key/value ( single key can be queried )")
						
						# clean up data
						# upload data
						pass



			elif time_series is True and key is not None:
					for split in splits:
						if not key in data[split].column_names:
							raise Exception("Feature is not in the dataset: " + str(data[split].column_names))

						# Check unique? 
	  
						print(type(data[split][key][0]))
			
						# This needs to check for all other datatypes that are dates or timestamps ( string timestamps? probably need to do this differently )
						if isinstance(data[split][key][0], Timestamp):
							print("Data is a time series")
						
						else:
							raise Exception("Data is not a time series")
						
						# clean up data
						# upload data
						
						
			# TODO: Handle being called without a key and time_series flag
			#       Should check if data isn't malformed and store it as indexed key/value
			else:
				# Store data as indexed key/value
				# Insert an index column to the data
				pass

		except Exception as e:
			print(e)

			pass