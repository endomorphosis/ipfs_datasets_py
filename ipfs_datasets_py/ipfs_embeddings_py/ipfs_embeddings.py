from .ipfs_multiformats import *
from .ipfs_only_hash import *
import subprocess
import os

class ipfs_embeddings_py:
    def __init__(self, resources, metedata):
        self.multiformats = ipfs_multiformats_py(resources, metedata)
        self.ipfs_only_hash = ipfs_only_hash_py(resources, metedata)
        self.tei_https_endpoints = {}
        self.libp2p_endpoints = {}
        self.cid_queue = iter([])
        self.knn_queue = iter([])
        self.cid_index = {}
        self.knn_index = {}
        self.endpoint_status = {}
        return None
    
    def load_index(self, index):
        self.index = index
        return None 
    
    def add_tei_https_endpoint(self, model, endpoint, batch_size):
        if model not in self.tei_https_endpoints:
            self.tei_https_endpoints[model] = {}
        if endpoint not in self.tei_https_endpoints[model]:  
            self.tei_https_endpoints[model][endpoint] = batch_size
        return None
    
    def add_libp2p_endpoint(self, model, endpoint, batch_size):
        if model not in self.libp2p_endpoints:
            self.libp2p_endpoints[model] = {}
        if endpoint not in self.libp2p_endpoints[model]:  
            self.libp2p_endpoints[model][endpoint] = batch_size
        return None
    
    def rm_tei_https_endpoint(self, model, endpoint):
        if model in self.tei_https_endpoints and endpoint in self.tei_https_endpoints[model]:
            del self.tei_https_endpoints[model][endpoint]
            del self.endpoint_status[endpoint]
        return None
    
    def rm_libp2p_endpoint(self, model, endpoint):
        if model in self.libp2p_endpoints and endpoint in self.libp2p_endpoints[model]:
            del self.libp2p_endpoints[model][endpoint]
            del self.endpoint_status[endpoint]
        return None
    
    def test_tei_https_endpoint(self, model, endpoint):
        if model in self.tei_https_endpoints and endpoint in self.tei_https_endpoints[model]:
            return True
        return False

    def test_libp2p_endpoint(self, model, endpoint):
        if model in self.libp2p_endpoints and endpoint in self.libp2p_endpoints[model]:
            return True
        return False

    def get_tei_https_endpoint(self, model):
        if model in self.tei_https_endpoints:
            return self.tei_https_endpoints[model]
        return None

    def request_tei_https_endpoint(self, model, batch_size):
        if model in self.tei_https_endpoints:
            for endpoint in self.tei_https_endpoints[model]:
                if self.endpoint_status[endpoint] == 1:
                    return endpoint
        return None

    def index_ipfs(self, samples):
        if type(samples) is None:
            raise ValueError("samples must be a list")
        if type(samples) is str:
            samples = [samples]
        if type(samples) is iter:
            for this_sample in samples:
                this_sample_cid = self.multiformats.get_cid(this_sample)
                self.cid_index[this_sample_cid] = this_sample
            pass
        if type(samples) is list:
            for this_sample in samples:
                this_sample_cid = self.multiformats.get_cid(this_sample)
                self.cid_index[this_sample_cid] = this_sample
        return None
    
    def index_knn(self, samples):
        if type(samples) is None:
            raise ValueError("samples must be a list")
        if type(samples) is str:
            samples = [samples]
        if type(samples) is iter:
            for this_sample in samples:
                this_sample_cid = self.multiformats.get_cid(this_sample)
                self.knn_index[this_sample_cid] = this_sample
            pass
        if type(samples) is list:
            for this_sample in samples:
                this_sample_cid = self.multiformats.get_cid(this_sample)
                self.knn_index[this_sample_cid] = this_sample
        return None
    
    def queue_index_cid(self, samples):
        if type(samples) is None:
            raise ValueError("samples must be a list")
        if type(samples) is str:
            samples = [samples]
        if type(samples) is iter:
            for this_sample in samples:
                self.cid_queue.append(this_sample)
            pass
        if type(samples) is list:
            for this_sample in samples:
                self.cid_queue.append(this_sample)

        return None
    
    def choose_endpoint(self):
        filtered_endpoints = {}
        filtered_endpoints = {k: v for k, v in self.endpoint_status.items() if v == 1}
        if len(filtered_endpoints) == 0:
            return None
        else:
            return filtered_endpoints
        
    def https_index_cid(self, samples, endpoint):
        endpoint_chunk_size = self.tei_https_endpoints[endpoint]
        all_chunk = []
        this_chunk = []
        for i in range(samples):
            self
            ## request endpoint
            pass
        return None
    
    def pop_https_index_cid(self, samples):

        choose_endpoint = self.choose_endpoint()
        endpoint_chunk_size = self.tei_https_endpoints[choose_endpoint]
        all_chunk = []
        this_chunk = []
        for i in range(samples):
            this_chunk.append(self.cid_queue.pop())
            if i % endpoint_chunk_size == 0:
                all_chunk.append(this_chunk)
                this_chunk = []


    def test(self):
        self.add_tei_https_endpoint("BAAI/bge-m3", "62.146.169.111:80/embed",1)
        self.add_tei_https_endpoint("BAAI/bge-m3", "62.146.169.111:8080/embed",1)
        self.add_tei_https_endpoint("BAAI/bge-m3", "62.146.168.111:8081/embed",1)
        test_knn_index = {}
        test_cid_index = {}
        test_data = {
            "test1", "test2", "test3"
        }

        for data in test_data:
            test_cid_index = self.index_ipfs(data)
            test_knn_index = self.index_knn(data)
        

        print("test")

    def status(self):
        return self.endpointStatus
    
    def setStatus(self,endpoint , status):
        self.endpointStatus[endpoint] = status
        return None

if __name__ == '__main__':
    resources = {}
    metedata = {}
    ipfs_embeddings = ipfs_embeddings_py(resources, metedata)
    ipfs_embeddings.test()
    print("test")