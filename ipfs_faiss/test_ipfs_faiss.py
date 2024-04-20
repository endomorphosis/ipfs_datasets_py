import datasets
from datasets import Dataset
from datasets import FaissIndex
from ipfs_datasets import auto_download_dataset , ipfs_dataset
from ipfs_faiss import auto_download_faiss_index, ipfs_load_faiss_index
from ipfs_transformers import AutoModel

# Load a dataset
dataset = auto_download_dataset('squad')
#dataset = ipfs_dataset('ipfs_CID')
#dataset = auto_download_dataset('ipfs_CID'
#    s3cfg={
#        "bucket": "cloud",
#        "endpoint": "https://storage.googleapis.com",
#        "secret_key": "",
#        "access_key": "",
#    }
#)

# Load a Faiss index
knnindex = auto_download_faiss_index('squad')
#knnindex = ipfs_load_faiss_index('ipfs_CID')
#knnindex = auto_download_faiss_index('ipfs_CID'
#   s3cfg={
#       "bucket": "cloud",
#       "endpoint": "https://storage.googleapis
#       "secret_key": "",
#       "access_key": "",
#   }
#)

# Load an embedding model
model = AutoModel.from_auto_download("bge-small-en-v1.5")  # 1.5GB
#model = AutoModel.from_ipfs("QmccfbkWLYs9K3yucc6b3eSt8s8fKcyRRt24e3CDaeRhM1")  # 1.5GB
#model = AutoModel.from_pretrained("bert-base-en-v1.5",
#    s3cfg={
#        "bucket": "cloud",
#        "endpoint": "https://storage.googleapis.com",
#        "secret_key": "",
#        "access_key": "",
#    }
#)

# Initialize a Faiss index
index = FaissIndex(dimension=768)

embeddings = dataset['embeddings']
# Suppose `embeddings` is a 2D numpy array containing your vectors
index.add(embeddings)

query = "What is the capital of France?"
# Suppose `query` is a string
# generate the embeddings for the query
query_vector = model.encode(query)
# You can then query the index
scores, neighbors = index.search(query_vectors, k=10)