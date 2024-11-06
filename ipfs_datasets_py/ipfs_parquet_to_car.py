import subprocess
import json
import os
import asyncio 
import multiprocessing
import time
from multiprocessing import Pool

class ipfs_parquet_to_car_py:
    def __init__(self, resources, metadata):
        self.resources = resources
        self.metadata = metadata
        self.ipfs_parquet_to_car_py_version = "1.0.0"
        
    async def  __call__(self, src, dst):
        if os.path.isdir(src):
            return await self.run_batch(src, dst)
        else:
            return await self.run(src, dst)
        
    async def install(self):
        cmd = ["npm", "install", "ipfs_parquet_to_car_js"]
        try:
            subprocess.run(cmd, check=True) 
        except:
            return False
        return True
    
    async def update(self):
        cmd = ["npm", "update", "ipfs_parquet_to_car_js"]
        try:
            subprocess.run(cmd, check=True)
        except:
            return False
        return True
    
    async def test(self):
        ipfs_parquet_to_car_py_version_cmd = ["nodejs", "-e", "console.log(require('ipfs_parquet_to_car_js').version)"]
        ipfs_parquet_to_car_py_version = subprocess.run(ipfs_parquet_to_car_py_version_cmd, stdout=subprocess.PIPE)
        ipfs_parquet_to_car_py_version = ipfs_parquet_to_car_py_version.stdout.decode("utf-8").strip()
        if ipfs_parquet_to_car_py_version < self.ipfs_parquet_to_car_py_version:
            install = await self.install()
            if not install:
                return False
            else:
                return True
        return False
    
    async def run(self, src, dst):
        cmd = ["nodejs"]
        cmd.append(self.resources["ipfs_parquet_to_car.js"])
        cmd.append(src)
        cmd.append(dst)
        try:
            subprocess.run(cmd, check=True)
        except:
            return False
        return True
    
    async def run_batch(self, src, dst):
        files = os.listdir(src)
        cmds = []
        for i in range(len(files)):
            cmd = ["nodejs"]
            cmd.append(self.resources["ipfs_parquet_to_car.js"])
            cmd.append(src + "/" + files[i])
            cmd.append(dst + "/" + files[i].replace(".parquet", ".car"))
            cmds.append(cmd)
        with Pool(multiprocessing.cpu_count()) as p:
            p.map(subprocess.run, cmds)    
        return True
    
if __name__ == "__main__":
    resources = {
        "ipfs_parquet_to_car.js": "/mnt/data/ipfs_parquet_to_car.js"
    }
    metadata = {
        "name": "ipfs_parquet_to_car",
        "format": "parquet",
        "version": "0.0.1",
        "type": "transform",
        "language": "nodejs"
    }
    ipfs_parquet_to_car = ipfs_parquet_to_car_py(resources, metadata)
    ipfs_parquet_to_car.install()
    ipfs_parquet_to_car.test()
    asyncio.run(ipfs_parquet_to_car.run("/mnt/data/parquet", "/mnt/data/car"))
    import subprocess
import json
import os
import asyncio 
import multiprocessing
import time
from multiprocessing import Pool

class ipfs_parquet_to_car_py:
    def __init__(self, resources, metadata):
        self.resources = resources
        self.metadata = metadata
        self.ipfs_parquet_to_car_py_version = "1.0.0"
        
    async def  __call__(self, src, dst):
        if os.path.isdir(src):
            return await self.run_batch(src, dst)
        else:
            return await self.run(src, dst)
        
    async def install(self):
        cmd = ["npm", "install", "ipfs_parquet_to_car_js"]
        try:
            subprocess.run(cmd, check=True) 
        except:
            return False
        return True
    
    async def update(self):
        cmd = ["npm", "update", "ipfs_parquet_to_car_js"]
        try:
            subprocess.run(cmd, check=True)
        except:
            return False
        return True
    
    async def test(self):
        ipfs_parquet_to_car_py_version_cmd = ["nodejs", "-e", "console.log(require('ipfs_parquet_to_car_js').version)"]
        ipfs_parquet_to_car_py_version = subprocess.run(ipfs_parquet_to_car_py_version_cmd, stdout=subprocess.PIPE)
        ipfs_parquet_to_car_py_version = ipfs_parquet_to_car_py_version.stdout.decode("utf-8").strip()
        if ipfs_parquet_to_car_py_version < self.ipfs_parquet_to_car_py_version:
            install = await self.install()
            if not install:
                return False
            else:
                return True
        return False
    
    async def run(self, src, dst):
        cmd = ["nodejs"]
        cmd.append(self.resources["ipfs_parquet_to_car.js"])
        cmd.append(src)
        cmd.append(dst)
        try:
            subprocess.run(cmd, check=True)
        except:
            return False
        return True
    
    async def run_batch(self, src, dst):
        files = os.listdir(src)
        cmds = []
        for i in range(len(files)):
            cmd = ["nodejs"]
            cmd.append(self.resources["ipfs_parquet_to_car.js"])
            cmd.append(src + "/" + files[i])
            cmd.append(dst + "/" + files[i].replace(".parquet", ".car"))
            cmds.append(cmd)
        with Pool(multiprocessing.cpu_count()) as p:
            p.map(subprocess.run, cmds)    
        return True
ipfs_parquet_to_car_py = ipfs_parquet_to_car_py
ipfs_parquet_to_car = ipfs_parquet_to_car_py

if __name__ == "__main__":
    resources = {
        "ipfs_parquet_to_car.js": "/mnt/data/ipfs_parquet_to_car.js"
    }
    metadata = {
        "name": "ipfs_parquet_to_car",
        "format": "parquet",
        "version": "0.0.1",
        "type": "transform",
        "language": "nodejs"
    }
    ipfs_parquet_to_car = ipfs_parquet_to_car_py(resources, metadata)
    ipfs_parquet_to_car.install()
    ipfs_parquet_to_car.test()
    asyncio.run(ipfs_parquet_to_car.run("/mnt/data/parquet", "/mnt/data/car"))
    