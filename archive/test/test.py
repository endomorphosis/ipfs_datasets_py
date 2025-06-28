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

def test_graphrag():
	"""Run the GraphRAG unit tests"""
	parent_dir = os.path.dirname(os.path.dirname(__file__))
	sys.path.append(parent_dir)

	from test.phase1.test_phase1 import run_phase1_tests

	# Run all Phase 1 tests including GraphRAG
	success = run_phase1_tests()

	print(f"GraphRAG tests {'passed' if success else 'failed'}")
	return success

def test_advanced_graphrag():
	"""Run only the advanced GraphRAG unit tests"""
	parent_dir = os.path.dirname(os.path.dirname(__file__))
	sys.path.append(parent_dir)

	import unittest
	from test.phase1.test_advanced_graphrag import TestAdvancedGraphRAGMethods

	# Create and run a test suite with just the advanced GraphRAG tests
	test_suite = unittest.TestSuite()
	test_suite.addTest(unittest.makeSuite(TestAdvancedGraphRAGMethods))

	test_runner = unittest.TextTestRunner(verbosity=2)
	result = test_runner.run(test_suite)

	print(f"Advanced GraphRAG tests {'passed' if result.wasSuccessful() else 'failed'}")
	return result.wasSuccessful()

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
	import argparse

	parser = argparse.ArgumentParser(description='Run IPFS Datasets Python tests')
	parser.add_argument('--test', choices=['all', 'base', 'ws', 'download', 'graphrag', 'advanced_graphrag'],
						default='all', help='Test to run')

	args = parser.parse_args()

	if args.test == 'base' or args.test == 'all':
		print("Running base tests...")
		test()

	if args.test == 'ws' or args.test == 'all':
		print("Running web storage tests...")
		ws_test()

	if args.test == 'download' or args.test == 'all':
		print("Running download tests...")
		download_test()

	if args.test == 'graphrag' or args.test == 'all':
		print("Running GraphRAG tests...")
		test_graphrag()

	if args.test == 'advanced_graphrag' or args.test == 'all':
		print("Running Advanced GraphRAG tests...")
		test_advanced_graphrag()
