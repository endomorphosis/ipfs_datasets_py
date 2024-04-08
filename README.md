# Data Economy Hackathon
IPFS Huggingface Bridge

for huggingface transformers python library visit
https://github.com/endomorphosis/ipfs_transformers

for transformers.js visit:
https://github.com/endomorphosis/ipfs_transformers_js

for orbitdbkit nodejs library visit
https://github.com/endomorphosis/orbitdb-benchmark/

Author - Benjamin Barber
QA - Kevin De Haan

# About

This is a model manager and wrapper for huggingface, looks up a index of models from an collection of models, and will download a model from either https/s3/ipfs, depending on which source is the fastest.

# How to use
~~~shell
pip install .
~~~

look run ``python3 example.py`` for examples of usage.

this is designed to be a drop in replacement, which requires only 2 lines to be changed

In your python script
~~~shell
from datasets import load_dataset
from ipfs_datasets import load_dataset
dataset = load_dataset.from_auto_download("bge-small-en-v1.5")  
~~~

or 

~~~shell
from datasets import load_dataset
from ipfs_datasets import load_dataset
dataset = load_dataset.from_ipfs("QmccfbkWLYs9K3yucc6b3eSt8s8fKcyRRt24e3CDaeRhM1")
~~~

or to use with with s3 caching 
~~~shell
from datasets import load_dataset
from ipfs_datasets import load_dataset
dataset = load_dataset.from_auto_download(
    dataset_name="common-crawl",
    s3cfg={
        "bucket": "cloud",
        "endpoint": "https://storage.googleapis.com",
        "secret_key": "",
        "access_key": ""
    }
)
~~~

# To scrape huggingface

with interactive prompt:

~~~shell
node scraper.js [source] [model name]
~~~

~~~shell
node scraper.js 
~~~

import a model already defined:

~~~shell
node scraper.js hf "datasetname" (as defined in your .json files)
~~~

import all models previously defined:

~~~shell
node scraper.js hf 
~~~

## TODO integrate orbitDB

## TODO integrate ipfs_knn_kit

## TODO integrate bacalhau dockerfile