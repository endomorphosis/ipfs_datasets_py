
from datasets import load_dataset
import ipfs_embeddings_py.ipfs_embeddings as ipfs_embeddings

class test_ipfs_embeddings:
    def __init__(self):
        resources = {}
        metadata = {}
        self.dataset = {}
        self.ipfs_embeddings = ipfs_embeddings.ipfs_embeddings_py(resources, metadata)
        return None
    
    def process(self, dataset, output):
        num_rows = dataset.num_rows['data']
        processed_data = {}
        for i in range(num_rows):
            row = dataset['data'][i]
            data = row['data']
            processed_data[row] = self.ipfs_embeddings.add_tei_https_queue(data, self.callback())
        return None

    def callback(self, data):
        return None


    def test(self):
        load_these_datasets = ["laion/Wikipedia-X", "laion/Wikipedia-X-Full", "laion/Wikipedia-X-Concat", "laion/Wikipedia-X-M3"]
        self.dataset = load_dataset(load_these_datasets[0])
        print(len(self.dataset))
        self.ipfs_embeddings
        return None
    
if __name__ == '__main__':
    test = test_ipfs_embeddings()
    test.test()
    print("Test passed")
