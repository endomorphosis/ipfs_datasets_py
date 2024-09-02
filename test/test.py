import os
import sys

def test():
	parent_dir = os.path.dirname(os.path.dirname(__file__))
	sys.path.append(parent_dir)

	from datasets import load_dataset
	from ipfs_datasets_py import load_dataset

	# Test loading a dataset 
	dataset = load_dataset.from_auto_download("cifar10")
	

	# Test loading a dataset from IPFS
	# dataset = load_dataset.from_ipfs("QmQJzW8bQX2W5w8Zf2QzQD9k8zq5J3Z8qfX6X4V3V5W5W8")

def ws_test():
	parent_dir = os.path.dirname(os.path.dirname(__file__))
	sys.path.append(parent_dir)

	from datasets import load_dataset
	from orbit_kit import orbit_kit
	
	db = orbit_kit()

	# Test loading indexed key/value dataset
	data = load_dataset("cifar10")
	db.orb_upload(data, "cifar10")


	# Test loading a document dataset
	# data = load_dataset("CohereForAI/aya_collection_language_split", "japanese")
	# db.orb_upload(data, "CohereForAI-aya_collection_language_split", key="id")


	#Test loading a key/value dataset
	# Find multi-key unique dataset


	# Test loading a timeseries dataset
	# data = load_dataset("edarchimbaud/timeseries-1m-stocks")
	# db.orb_upload(data, "edarchimbaud-timeseries-1m-stocks", key='datetime', time_series=True)


def download_test():
	parent_dir = os.path.dirname(os.path.dirname(__file__))
	sys.path.append(parent_dir)
	from orbit_kit import orbit_kit


	db = orbit_kit()
	db.orb_download("cifar10")


	print("Done")

if __name__ == "__main__":
	# test()
	# ws_test()
	download_test()
