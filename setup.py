from setuptools import setup

setup(
	version='0.0.1',
	packages=[
		'ipfs_datasets',
		'ipfs_datasets.model_manager',
        'ipfs_datasets.model_manager.ipfs_kit_lib',
		'ipfs_datasets.model_manager.orbitdb_kit_lib',
	],
	install_requires=[
		'datasets',
        "ipfs_model_manager@git+https://github.com/endomorphosis/ipfs_model_manager.git",
        "orbitdb_kit@git@git+https://github.com/endomorphosis/orbitdb_kit.git",
		"ipfs_kit@git+https://github.com/endomorphosis/ipfs_kit.git",
		"faiss",
		'urllib3',
		'requests',
		'boto3',
	]
)