from .ipfs_multiformats import *
from .ipfs_only_hash import *
import asyncio
import subprocess
import os
import datasets
from typing import Any, Callable, Iterator

class ipfs_embeddings_py:

    def __init__(self, resources: dict[str, Any], metadata: dict[str, Any]) -> None:
        self._get_cid:            Callable             = ipfs_multiformats_py(resources, metadata).get_cid
        self.ipfs_only_hash:      ipfs_only_hash_py    = ipfs_only_hash_py(resources, metadata)
        self.tei_https_endpoints: dict[str, str] = {}
        self.libp2p_endpoints:    dict[str, str] = {}
        self.cid_queue:           Iterator = iter([])
        self.knn_queue:           Iterator = iter([])
        self.cid_index:           dict[str, str] = {}
        self.knn_index:           dict[str, str] = {}
        self.endpoint_status:     dict[str, str] = {}

    def load_index(self, index: int) -> None:
        self.index = index

    def _add_endpoint(self, model: str, endpoint: str, batch_size: int, endpoints: dict[str, str]) -> None:
        if model not in endpoints:
            endpoints[model] = {}
        if endpoint not in endpoints[model]:
            endpoints[model][endpoint] = batch_size
        return endpoints

    def _rm_endpoint(self, model: str, endpoint: str, endpoints: dict[str, str]) -> dict[str, str]:
        if model in endpoints and endpoint in endpoints[model]:
            del self.endpoint_status[endpoint]
            del endpoints[model][endpoint]
            return endpoints

    def add_tei_https_endpoint(self, model: str, endpoint: str, batch_size: int) -> None:
        self.tei_https_endpoints = self._add_endpoint(model, endpoint, batch_size, self.tei_https_endpoints)

    def add_libp2p_endpoint(self, model: str, endpoint: str, batch_size: int) -> None:
        self.libp2p_endpoints = self._add_endpoint(model, endpoint, batch_size, self.libp2p_endpoints)

    def rm_tei_https_endpoint(self, model: str, endpoint: str) -> None:
        self.tei_https_endpoints = self._rm_endpoint(model, endpoint, self.tei_https_endpoints)

    def rm_libp2p_endpoint(self, model: str, endpoint: str) -> None:
        self.libp2p_endpoints = self._rm_endpoint(model, endpoint, self.libp2p_endpoints)

    def test_tei_https_endpoint(self, model: str, endpoint: str) -> bool:
        if model in self.tei_https_endpoints and endpoint in self.tei_https_endpoints[model]:
            return True
        return False

    def test_libp2p_endpoint(self, model: str, endpoint: str) -> bool:
        if model in self.libp2p_endpoints and endpoint in self.libp2p_endpoints[model]:
            return True
        return False

    def get_tei_https_endpoint(self, model: str) -> str | None:
        if model in self.tei_https_endpoints:
            return self.tei_https_endpoints[model]

    def request_tei_https_endpoint(self, model: str, batch_size: int) -> str | None:
        if model in self.tei_https_endpoints:
            for endpoint in self.tei_https_endpoints[model]:
                if self.endpoint_status[endpoint] == 1:
                    return endpoint

    @staticmethod
    def _make_samples_an_iterable(samples: Any) -> list[str]:
        type_samples = type(samples)
        if type_samples is None:
            raise ValueError("samples must be a list")
        if type_samples is str:
            samples = [samples]
        return samples

    def _add_samples_to_index(self, index: dict[str, str], samples: Any) -> None:
        if samples is iter:
            index.update({
                self._get_cid(this_sample): this_sample for this_sample in samples
            })
            pass
        if samples is list:
            index.update({
                self._get_cid(this_sample): this_sample for this_sample in samples
            })
        return index

    def index_ipfs(self, samples: Any) -> None:
        samples = self._make_samples_an_iterable(samples)
        self.cid_index = self._add_samples_to_index(self.cid_index, samples)

    def index_knn(self, samples: Any) -> None:
        samples = self._make_samples_an_iterable(samples)
        self.knn_index = self._add_samples_to_index(self.knn_index, samples)

    def queue_index_cid(self, samples: Any) -> None:
        samples = self._make_samples_an_iterable(samples)
        if samples is iter:
            for this_sample in samples:
                self.cid_queue.append(this_sample)
            pass
        if samples is list:
            for this_sample in samples:
                self.cid_queue.append(this_sample)
        return None

    def choose_endpoint(self) -> dict[str, str] | None:
        filtered_endpoints = {k: v for k, v in self.endpoint_status.items() if v == 1}
        return None if len(filtered_endpoints) == 0 else filtered_endpoints

    def https_index_cid(self, samples: Any, endpoint: str) -> None:
        endpoint_chunk_size = self.tei_https_endpoints[endpoint]
        all_chunk = []
        this_chunk = []
        for idx in range(samples):
            self
            ## request endpoint
            pass
        return None

    def pop_https_index_cid(self, samples: Any) -> None:
        choose_endpoint = self.choose_endpoint()
        endpoint_chunk_size = self.tei_https_endpoints[choose_endpoint]
        all_chunk = []
        this_chunk = []
        for idx in range(samples):
            this_chunk.append(self.cid_queue.pop())
            if idx % endpoint_chunk_size == 0:
                all_chunk.append(this_chunk)
                this_chunk = []

    def test(self) -> None:
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

    def status(self) -> dict[str, str]:
        return self.endpointStatus

    def setStatus(self, endpoint: str, status: str) -> None:
        self.endpointStatus[endpoint] = status

if __name__ == '__main__':
    resources = {}
    metadata = {}
    ipfs_embeddings = ipfs_embeddings_py(resources, metadata)
    ipfs_embeddings.test()
    print("test")
