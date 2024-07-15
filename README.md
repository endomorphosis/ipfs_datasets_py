# IPFS Huggingface Datasets

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

# IPFS Huggingface Bridge:

for transformers python library visit:
https://github.com/endomorphosis/ipfs_transformers/

for transformers js client visit:                          
https://github.com/endomorphosis/ipfs_transformers_js/

for orbitdb_kit nodejs library visit:
https://github.com/endomorphosis/orbitdb_kit/

for fireproof_kit nodejs library visit:
https://github.com/endomorphosis/fireproof_kit

for Faiss KNN index python library visit:
https://github.com/endomorphosis/ipfs_faiss/

for python model manager library visit: 
https://github.com/endomorphosis/ipfs_model_manager/

for nodejs model manager library visit: 
https://github.com/endomorphosis/ipfs_model_manager_js/

for nodejs ipfs huggingface scraper with pinning services visit:
https://github.com/endomorphosis/ipfs_huggingface_scraper/


Author - Benjamin Barber
QA - Kevin De Haan
