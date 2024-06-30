from setuptools import setup

setup(
    name="ipfs_datasets",
	version='0.0.2',
	packages=[
		'ipfs_datasets'
	],
	install_requires=[
        'orbitdb_kit@git+https://github.com/endomorphosis/orbitdb_kit.git',
        'ipfs_kit@git+https://github.com/endomorphosis/ipfs_kit.git',
        'ipfs_model_manager@git+https://github.com/endomorphosis/ipfs_model_manager.git',
        'transformers',
        'numpy',
        'urllib3',
        'requests',
        'boto3',
	]
)