from setuptools import setup

setup(
    name="ipfs_datasets_py",
	version='0.0.5',
	packages=[
		'ipfs_datasets_py',
	],
	install_requires=[
        'orbitdb_kit_py',
        'ipfs_kit_py',
        'ipfs_model_manager_py',
        'ipfs_faiss_py',
        'transformers',
        'numpy',
        'urllib3',
        'requests',
        'boto3',
	]
)