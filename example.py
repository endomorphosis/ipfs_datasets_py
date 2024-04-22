import sys
import os

parent_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(parent_dir)

from datasets import load_dataset
from ipfs_datasets import load_dataset

# Test loading a dataset 
dataset = load_dataset.from_auto_download("cifar10")
print(dir(dataset))
## OPTIONAL S3 Caching ##

#model = T5Model.from_auto_download(
#    model_name="google-bert/t5_11b_trueteacher_and_anli",
#    s3cfg={
#        "bucket": "cloud",
#        "endpoint": "https://storage.googleapis.com",
#        "secret_key": "",
#        "access_key": "",
#    }
#)
#print(dir(model))
