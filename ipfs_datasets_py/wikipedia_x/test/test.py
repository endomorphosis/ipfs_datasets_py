import datasets

class test_ipfs_datasets_py:
    def __init__(self):
        self.db = {}
        return None

    def load_dataset(self, dataset_name):
        self.db[0] =  {}
        self.db[0]  = datasets.load_dataset(dataset_name)
        return self.db[0]

    def test(self, datasets):
        if type(datasets) is None:
            raise Exception("Error: datasets is None")
        
        if type(datasets) is str:
            datasets = [datasets]
        if type(datasets) is not list:
            raise Exception("Error: datasets is not a list")
    
        for dataset in datasets:
            self.load_dataset(dataset)
        return self.db

if __name__ == "__main__":
    load_these_datasets = ["laion/Wikipedia-X", "laion/Wikipedia-X-Full", "laion/Wikipedia-X-Concat", "laion/Wikipedia-X-M3"]
    test_ipfs_datasets_py = test_ipfs_datasets_py()
    test_ipfs_datasets_py.test(load_these_datasets)
    print("test complete")
    print (test_ipfs_datasets_py.db)
    exit(0)