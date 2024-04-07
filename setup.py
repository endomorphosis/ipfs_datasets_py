from setuptools import setup

setup(
	name='ipfs-transformers',
	version='0.0.1',
	packages=[
		'ipfs_transformers',
		'ipfs_transformers.ipfs_kit_lib',

	],
	install_requires=[
		'transformers',
		'urllib3',
		'requests',
		'boto3',
	]
)