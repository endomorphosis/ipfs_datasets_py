import sys
import os
import subprocess
import tempfile
import json
import time

class ipget:
    def __init__(self, resources, meta=None):
        if meta is not None:
            if "config" in meta:
                if meta['config'] is not None:
                    self.config = meta['config']
            if "role" in meta:
                if meta['role'] is not None:
                    self.role = meta['role']
                    if self.role not in  ["master","worker","leecher"]:
                        raise Exception("role is not either master, worker, leecher")
                    else:
                        self.role = "leecher"
            
            if "cluster_name" in meta:
                if meta['cluster_name'] is not None:
                    self.cluster_name = meta['cluster_name']

            if "ipfs_path" in meta:
                if meta['ipfs_path'] is not None:
                    self.ipfs_path = meta['ipfs_path']

            if self.role == "leecher" or self.role == "worker" or self.role == "master":
                pass
        
    def ipget_download_object(self, **kwargs):
        # NOTE: Make sure this function can download both files and folders 
        if "cid" not in kwargs:
            raise Exception("cid not found in kwargs")
        if "path" not in kwargs:
            raise Exception("path not found in kwargs")
        if os.path.exists(kwargs['path']):
            pass
        #check if folder exists
        if not os.path.exists(os.path.dirname(kwargs['path'])):
            os.makedirs(os.path.dirname(kwargs['path']))
            
        command = "export IPFS_PATH=" + self.ipfs_path + " && ipfs get " + kwargs['cid'] + " -o " + kwargs['path']
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        start_time = time.time()
        timeout = 5

        while True:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                stdout.decode()
                stderr.decode()
                break

            if time.time() - start_time > timeout:
                process.kill()
                raise Exception("Command timed out")

            time.sleep(1)

        results, error = process.communicate()
        results = results.decode()

        mtime = os.stat(kwargs['path']).st_mtime
        filesize = os.stat(kwargs['path']).st_size
        metadata = {
            "cid": kwargs['cid'],
            "path": kwargs['path'],
            "mtime": mtime,
            "filesize": filesize
        }
        return metadata

# NOTE: Create test that feeds ipget_download_object with a CID and the path to local_path

    def test_ipget(self):
        detect = os.system("which ipget")
        if int(detect) > 0 or True:
            ipget_download_object = self.ipget_download_object(cid="QmccfbkWLYs9K3yucc6b3eSt8s8fKcyRRt24e3CDaeRhM1", path="/tmp/test")
            return True
        else:
            return False
        pass

if __name__ == "__main__":
    this_ipget = ipget(None, meta={"role":"leecher","ipfs_path":"/tmp/test/"})
    results = this_ipget.test_ipget()
    print(results)
    pass

# TODO:
# TEST THIS COMMAND FOR OTHER PATHS
# export IPFS_PATH=/mnt/ipfs/ipfs && ipfs get QmccfbkWLYs9K3yucc6b3eSt8s8fKcyRRt24e3CDaeRhM1 -o /tmp/test

