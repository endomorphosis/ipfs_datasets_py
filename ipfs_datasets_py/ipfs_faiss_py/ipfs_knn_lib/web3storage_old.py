import os
import sys
import json
import w3storage
import requests

class Web3StorageAPI:

    def __init__(self, resources, meta=None):
        if meta is not None:
            if "web3_api_key" in meta:
                if meta['web3_api_key'] is not None:
                    self.web3_api_key = meta['web3_api_key']
        if self.web3_api_key is not None:
            self.w3 = w3storage.API(token=self.web3_api_key)

        return
    def __call__(self, method, **kwargs):
        if method == 'download':
            return self.download(**kwargs)
        elif method == "upload":
            return self.upload(**kwargs)
        elif method == "init":
            return self.init(**kwargs)
        else:
            raise Exception('bad method: %s' % method)
        
    def list(self, **kwargs):
        some_uploads = self.w3.user_uploads(size=25)
        return some_uploads

    def download(self, cid, **kwargs):
        url = "https://" + cid + ".ipfs.w3s.link"
        print(url)
        results = requests.get(url)
        return results
    
    def upload(self, cname, file, data, **kwargs):
        
        if file is not None:
            with open( self.  cname, 'rb') as f:
                file_size = os.path.getsize(f.name)

            if file_size > 100000000:
                Exception("data size too large")
                # split file into .cars
                # upload each .car
                # return cid of last .car
                bytes_processed = 0
                while bytes_processed < file_size:
                    # upload .car
                    bytes_processed += 100000000
                    # return cid of last .car
            else:
                results = self.w3.post_upload(cname, open(file, 'rb'))
            return results
        elif data is not None:
            size = len(data)
            if size > 100000000:
                Exception("data size too large")
                # split file into .cars
                # upload each .car
                # return cid of last .car
                bytes_processed = 0
                while bytes_processed < size:
                    # upload .car
                    bytes_processed += 100000000
                    # return cid of last .car
            else:
                results = self.w3.post_upload(cname, data)
            return results

def main():
    cwd = os.getcwd()
    dir = os.path.dirname(__file__)
    test_api_key = {
        "api_key": ""
    }
    web3storage = Web3StorageAPI(None, meta=test_api_key)
    files = web3storage.list()
    results = web3storage.upload("test2.txt", data="hello world4")
    read = web3storage.download(results)

if __name__ == '__main__':
    #main()
    pass
