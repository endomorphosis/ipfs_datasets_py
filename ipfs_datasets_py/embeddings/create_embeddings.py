import asyncio
import os


from aiohttp import ClientSession
import datasets
from datasets import load_dataset, Dataset


# Try to import ipfs_kit_py
try:
    from ipfs_kit_py.ipfs_kit import ipfs_kit
    print("✓ Successfully imported ipfs_kit from ipfs_kit_py")
except ImportError:
    print("⚠ Warning: Could not import ipfs_kit_py. Some functionality may be limited.")
    ipfs_kit = None


class create_embeddings:
    def __init__(self, resources, metadata):
        self.resources = resources
        self.metadata = metadata
        self.datasets = datasets
        self.index =  {}
        self.cid_list = []
        if len(list(metadata.keys())) > 0:
            for key in metadata.keys():
                setattr(self, key, metadata[key])

        # Initialize ipfs_kit if available
        if ipfs_kit:
            self.ipfs_kit = ipfs_kit(resources, metadata)
        else:
            print("⚠ Warning: ipfs_kit not initialized, creating placeholder")
            self.ipfs_kit = None
            
        if "https_endpoints" in resources.keys() and self.ipfs_kit:
            for endpoint in resources["https_endpoints"]:
                self.ipfs_kit.add_https_endpoint(endpoint[0], endpoint[1], endpoint[2])
        self.join_column = None
        self.tokenizer = {}

    def add_https_endpoint(self, model, endpoint, ctx_length):
        if self.ipfs_kit:
            return self.ipfs_kit.add_https_endpoint(model, endpoint, ctx_length)
        else:
            print("Error: ipfs_kit not initialized. Cannot add HTTPS endpoint.")
            return None

    async def index_dataset(self, dataset, split=None, column=None, dst_path=None, models=None):
        """Index a dataset to create embeddings"""
        if self.ipfs_kit:
            return await self.ipfs_kit.index_dataset(dataset, split, column, dst_path, models)
        else:
            print("Error: ipfs_kit not initialized. Cannot index dataset.")
            return None

    async def create_embeddings(self, dataset, split, column, dst_path, models):
        if self.ipfs_kit:
            await self.ipfs_kit.index_dataset(dataset, split, column, dst_path, models)
            return True
        else:
            print("Error: ipfs_kit not initialized. Cannot create embeddings.")
            return False
           
    async def __call__(self, dataset, split, column, dst_path, models):
        if self.ipfs_kit:
            await self.ipfs_kit.index_dataset(dataset, split, column, dst_path, models)
            return True
        else:
            print("Error: ipfs_kit not initialized. Cannot call create_embeddings.")
            return False

    async def test(self, dataset, split, column, dst_path, models):
        https_endpoints = [
            # ["Alibaba-NLP/gte-large-en-v1.5", "http://127.0.0.1:8080/embed", 8192],
            # ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://127.0.0.1:8082/embed", 32768],
            # # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8080/embed-large", 32000],
            # ["Alibaba-NLP/gte-large-en-v1.5", "http://127.0.0.1:8081/embed", 8192],
            # ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://127.0.0.1:8083/embed", 32768],
            # # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8081/embed-large", 32000],
            ["Alibaba-NLP/gte-large-en-v1.5", "http://62.146.169.111:8080/embed-small", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://62.146.169.111:8080/embed-medium", 32000],
            # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8080/embed-large", 32000],
            ["Alibaba-NLP/gte-large-en-v1.5", "http://62.146.169.111:8081/embed-small", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://62.146.169.111:8081/embed-medium", 32000],
            # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8081/embed-large", 32000],
            ["Alibaba-NLP/gte-large-en-v1.5", "http://62.146.169.111:8082/embed-small", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://62.146.169.111:8082/embed-medium", 32000],
            # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8082/embed-large", 32000],
            ["Alibaba-NLP/gte-large-en-v1.5", "http://62.146.169.111:8083/embed-small", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://62.146.169.111:8083/embed-medium", 32000],
            # ["Alibaba-NLP/gte-Qwen2-7B-instruct", "http://62.146.169.111:8083/embed-large", 32000],
        ]
        for endpoint in https_endpoints:
            self.add_https_endpoint(endpoint[0], endpoint[1], endpoint[2])
        await self.create_embeddings(dataset, split, column, dst_path, models)
        return True
    
# Alias for compatibility with other modules
CreateEmbeddingsProcessor = create_embeddings

if __name__ == "__main__":
    metadata = {
        "dataset": "TeraflopAI/Caselaw_Access_Project",
        "split": "train",
        "column": "text",
        "models": [
            "Alibaba-NLP/gte-large-en-v1.5",
            "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
            # "dunzhang/stella_en_1.5B-v5",
        ],
        "dst_path": "/storage/teraflopai/tmp"
    }
    resources = {
    }
    create_embeddings_batch = create_embeddings(resources, metadata)
    asyncio.run(create_embeddings_batch.test(metadata["dataset"], metadata["split"], metadata["column"], metadata["dst_path"], metadata["models"]))
