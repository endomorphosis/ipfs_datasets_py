from setuptools import setup

setup(
	name='ipfs-datasets',
	version='0.0.1',
	packages=[
		'ipfs_datasets',
		'ipfs_datasets.ipfs_kit_lib',

	],
	install_requires=[
		'datasets',
		'urllib3',
		'requests',
		'boto3',
	]
)