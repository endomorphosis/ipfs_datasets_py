#from cloudkit_worker import dispatch_result, should_abort, TaskAbortion
import os
import sys
import json
import pathlib
import time
import tempfile
from s3_kit import s3_kit
from ipfs_kit import ipfs_kit
from ipfs_kit_lib.install_ipfs import install_ipfs as install_ipfs
import datetime
import hashlib
import requests
import shutil
import random
import test_fio
import subprocess
parent_dir = os.path.dirname(os.path.dirname(__file__))
ipfs_lib_dir = os.path.join(parent_dir, "ipfs_kit_lib")
sys.path.append(ipfs_lib_dir)
sys.path.append(parent_dir)

class model_manager:
    def __init__(self, resources=None, meta=None):
        local_path='/cloudkit_storage/'
        self.models = {}
        self.models["s3_models"] = []
        self.models["ipfs_models"] = []
        self.models["local_models"] = []
        self.models["https_models"] = []
        self.ipfs_collection = {}
        self.s3_collection = {}
        self.local_collection = {}
        self.https_collection = {}
        self.pinned = []
        self.fastest = None
        self.bandwidth = None
        self.this_model_path = None
        self.this_model = None
        self.this_model_name = None
        self.s3cfg = None
        if meta is not None and type (meta) == dict:
            if "s3cfg" in meta:
                self.s3cfg = meta["s3cfg"]
            if "ipfs_src" in meta:
                self.ipfs_src = meta["ipfs_src"]
            if "timing" in meta:
                self.timing = meta["timing"]
            if "cache" in meta:
                self.collection_cache = meta["cache"]
            if "history" in meta:
                self.model_history = meta["history"]
            if "role" in meta:
                self.role = meta["role"]
            if "cluster_name" in meta:
                self.cluster_name = meta["cluster_name"]
            if "local_path" in meta:
                self.local_path = meta["local_path"]
            else:
                self.local_path = self.ipfs_path + "cloudkit-models/"
            if "s3_cfg" in meta:
                self.s3cfg = meta["s3_cfg"]
            if "ipfs_path" in meta:
                self.ipfs_path = meta["ipfs_path"]
            else:
                self.ipfs_path = self.local_path + "ipfs/"
        else:
            self.local_path = self.ipfs_path + "cloudkit-models/"
            self.ipfs_path = "/ipfs/"
            self.s3cfg = None
            self.role = "leecher"
            self.cluster_name = "cloudkit_storage"
            self.cache = {
                "local": "/storage/cloudkit-models/collection.json",
                "s3": "s3://huggingface-models/collection.json",
                "ipfs": "QmXBUkLywjKGTWNDMgxknk6FJEYu9fZaEepv3djmnEqEqD",
                "https": "https://huggingface.co/endomorphosis/cloudkit-collection/resolve/main/collection.json"
            }
            meta = {
                "local_path": self.local_path,
                "ipfs_path": self.ipfs_path,
                "s3_cfg": self.s3cfg,
                "role": self.role,
                "cluster_name": self.cluster_name,
                "cache": self.cache,
            }

        homedir = os.path.expanduser("~")
        homedir_files = os.listdir(homedir)
        self.test_fio = test_fio.test_fio(None)
        self.s3_kit = s3_kit(resources, meta = meta)
        self.ipfs_kit = ipfs_kit(resources, meta = meta)
        self.install_ipfs = install_ipfs(resources, meta = meta)
        ipfs_path = self.ipfs_path
        if not os.path.exists(self.ipfs_path):
            os.makedirs(self.ipfs_path)
        if not os.path.exists(self.local_path):
            os.makedirs(self.local_path)
        ipfs_path_files = os.listdir(ipfs_path)
        # NOTE there is no systemctl daemon reload.
        # NOTE: Changed or to and in this if so install only runs if there is no ipfs in any of the possible locations
        # NOTE: make sure all instances of IPFS daemon are started either as a service or with os.system() or with process.popen()
        if ".ipfs" not in homedir_files and "ipfs" not in ipfs_path_files and os.path.exists(ipfs_path):
            self.install_ipfs.install_ipfs_daemon()
            self.install_ipfs.install_ipget()
            stats = self.test_fio.stats(self.ipfs_path)
            self.install_ipfs.config_ipfs(
                disk_stats = stats,
                ipfs_path = self.ipfs_path,
            )
            pass
        elif self.role == "master" and ".ipfs-cluster-service" not in homedir_files:
            self.install_ipfs.install_ipfs_cluster_service()
            self.install_ipfs.install_ipfs_cluster_ctl()
            self.install_ipfs.config_ipfs_cluster_service()
            self.install_ipfs.config_ipfs_cluster_ctl()
            pass
        elif self.role == "worker" and ".ipfs-cluster-follow" not in homedir_files:
            self.install_ipfs.install_ipfs_cluster_service()
            self.install_ipfs.install_ipfs_cluster_follow()
            self.install_ipfs.config_ipfs_cluster_service()
            self.install_ipfs.config_ipfs_cluster_follow()
            pass               
        
        self.ipfs_kit.ipfs_kit_stop()
        self.ipfs_kit.ipfs_kit_start()
        execute_ready = False
        while execute_ready != True:
            try:
                ready_ipfs_kit = self.ipfs_kit.ipfs_kit_ready()
                execute_ready = ready_ipfs_kit
            except Exception as e:
                execute_ready = str(e)

        self.models = {}
        self.last_update = 0.1
        self.history_models = {}
        self.pinned_models = {}
        self.collection = {}
        self.collection_pins = []
        self.zombies = {}
        self.expired = {}
        self.not_found = []
        self.ipfs_pinset = {
            "ipfs": {},
            "ipfs_cluster": {},
        }

    def __call__(self, method, **kwargs):
        if method == "load_collection":
            return self.load_collection(**kwargs)
        if method == "download_model":
            return self.download_model(**kwargs)
        if method == "load_collection_cache":
            return self.load_collection_cache(**kwargs)
        if method == "auto_download":
            return self.auto_download(**kwargs)
        if method == "ls_models":
            return self.ls_models(**kwargs)
        if method == "ls_s3_models":
            return self.ls_s3_models(**kwargs)
        if method == "check_local":
            return self.check_local(**kwargs)
        if method == "check_https":
            return self.check_https(**kwargs)
        if method == "check_s3":
            return self.check_s3(**kwargs)
        if method == "check_ipfs":
            return self.check_ipfs(**kwargs)
        if method == "download_https":
            return self.download_https(**kwargs)
        if method == "download_s3":
            return self.download_s3(**kwargs)
        if method == "download_ipfs":
            return self.download_ipfs(**kwargs)
        if method == "test":
            return self.test(**kwargs)

    def load_collection(self, **kwargs):
        try:
            self.https_collection = self.download_https('https://huggingface.co/endomorphosis/cloudkit-collection/resolve/main/collection.json', "/tmp/")
            with open(self.https_collection, 'r') as f:
                self.https_collection = json.load(f)
        except Exception as e:
            self.https_collection = e
            pass
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", dir="/tmp") as this_temp_file:
                results = self.ipfs_kit.ipfs_get(self.ipfs_src, this_temp_file.name)
                if results is not None and len(results) > 0:
                    with open(this_temp_file.name, 'r') as f:
                        self.ipfs_collection = json.load(f)
                else:
                    self.ipfs_collection = {
                        "error": "no results"
                    }

        except Exception as e:
            self.ipfs_collection = {
                "error": str(e)
            }
            pass
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", dir="/tmp") as this_temp_file:
                self.s3_kit.s3_dl_file('collection.json', this_temp_file.name, self.s3cfg["bucket"])
                with open(this_temp_file.name, 'r') as f:
                    self.s3_collection = json.load(f)
        except Exception as e:
            self.s3_collection = e
            pass
        if os.path.exists(os.path.join(self.ipfs_path,"collection.json")): 
            with open(os.path.join(self.ipfs_path,"collection.json"), 'r') as f:
                self.local_collection = json.load(f)
        try:
            ipfs_stop = self.ipfs_kit.ipfs_kit_stop()
        except Exception as e:
            ipfs_stop = e
        try:
            ipfs_start = self.ipfs_kit.ipfs_kit_start()
        except Exception as e:
            ipfs_start = e

        return {
            "ipfs_stop": ipfs_stop,
            "ipfs_start": ipfs_start,
            "ipfs_collection": self.ipfs_collection,
            "s3_collection": self.s3_collection,
            "local_collection": self.local_collection,
            "https_collection": self.https_collection
        }
       
    def download_https(self, https_src, model_path, **kwargs):
        suffix = "." + https_src.split("/")[-1].split(".")[-1]
        if (os.path.exists(model_path)):
            if os.path.isdir(model_path):
                dst_path = os.path.join(model_path, https_src.split("/")[-1])
                filename = https_src.split("/")[-1]
            else:
                filename = https_src.split("/")[-1]
                dirname = os.path.dirname(model_path)
                if len(filename.split(".")) < 1:
                    dst_path = os.path.join(dirname, filename)
                else:
                    dst_path = os.path.join(dirname, filename)
        else:
            dirname = os.path.dirname(model_path)
            filename = https_src.split("/")[-1]
            if os.path.exists(dirname):
                dst_path = os.path.join(dirname,filename)
            else:
                os.makedirs(dirname)
                dst_path = os.path.join(dirname,filename)
        
        with tempfile.NamedTemporaryFile(suffix=suffix, dir="/tmp", delete=False) as this_temp_file:
            file_metadata = os.stat(this_temp_file.name)
            tmp_filename = this_temp_file.name.split("/")[-1]
            command =  "aria2c -x 16 "+https_src+" -d /tmp -o "+ tmp_filename +" --allow-overwrite=true "
            os.system(command)
            if os.path.exists(dst_path):
                command2 = "rm " + dst_path
                os.system(command2)
                pass
            if("collection.json" not in dst_path and "README.md" not in dst_path):
                command3 = "mv /tmp/"+tmp_filename+" "+dst_path
                os.system(command3)

                if(os.path.exists(this_temp_file.name)):
                    command4 = "rm /tmp/"+tmp_filename
                    os.system(command4)

            else:
                command3 = "cp /tmp/"+tmp_filename+" "+dst_path
                os.system(command3)                

                if(os.path.exists(this_temp_file.name)):
                    command4 = "rm /tmp/"+tmp_filename
                    os.system(command4)

                # NOTE there is an issue where the file is not being copied to the correct location
                # the previous bug was that the file location was being moved twice in the autodownload and in the download function
                # this is a placeholder, until the program can be changed to move the move function out of here and into the autodownload function or vice versa
                # the bug was introduced when I realized that I had to move the entire subfolder, and made the change inside of the autodownload function

        return dst_path
    
    def download_s3(self, s3_src, filename_dst, **kwargs):
        if len (filename_dst.split(".")) > 1:
            try:
                #NOTE: This is creating the .md folder in the directory python is being run from. Commented it out to see if 
                #      fixes the issue. For some reason "suffix" here is derived from basename instead of filename_dst like in the ipfs download function
                #      TODO: Ask endo about this / test s3 download function

                # basename = os.path.basename(filename_dst)
                # dirname = os.path.dirname(filename_dst)
                # if not os.path.exists(dirname):
                #     os.mkdir(dirname)

                # NOTE: Changed to use filename_dst instead of basename so it's the same as the ipfs download function -fregg
                suffix = "." + filename_dst.split(".")[-1]
                with tempfile.NamedTemporaryFile(suffix=suffix, dir="/tmp", delete=False) as this_temp_file:
                    this_file_key = s3_src.split(self.s3cfg["bucket"]+"/")[1]
                    results = self.s3_kit.s3_dl_file(s3_src, this_temp_file.name, self.s3cfg["bucket"])
                    if results is not None and len(results) > 0:
                        shutil.move(results["local_path"], filename_dst)

                        # NOTE: Add removal logic here -fregg
                        if(os.path.exists(this_temp_file.name)):
                            command = "rm "+this_temp_file.name
                            os.system(command)

                        return filename_dst
                    else:
                        return False
            except Exception as e:
                # NOTE: Add removal logic here -fregg
                if(os.path.exists(this_temp_file.name)):
                    command = "rm "+this_temp_file.name
                    os.system(command)
                return e
        else:
            raise Exception("Invalid filename_dst, no `.` suffix found")
        
    def download_ipfs(self, ipfs_src, filename_dst, **kwargs):
        if len (filename_dst.split(".")) > 1:                
            try:
                #NOTE: This is creating the .md folder in the directory python is being run from. Commented it out to see if 
                # 		i'm not sure what the basename is doing. seems like it's not used and i cant really find the logic 
                # 		behind creating a folder for the md if it exists either. 

                # basename = os.path.basename(filename_dst)
                # if not os.path.exists(basename):
                #     os.mkdir(basename)
                
                # Checks if the suffix is a valid file extension and not the cache folder Probably needs some work to handle other ipfs_path locations
                if(".cache" not in filename_dst and "." in filename_dst ):
                    suffix = "." + filename_dst.split(".")[-1]
                    with tempfile.NamedTemporaryFile(suffix=suffix, dir="/tmp", delete=False) as this_temp_file:
                        results = self.ipfs_kit.ipfs_get(cid = ipfs_src, path = this_temp_file.name)
                        if "path" in list(results.keys()):
                            results_file_name = results["path"]
                            shutil.move(results_file_name, filename_dst)
                            
                            # NOTE: Add removal logic here -fregg
                            if(os.path.exists(this_temp_file.name)):
                                command = "rm "+this_temp_file.name
                                os.system(command)

                            return filename_dst
                        else:
                            raise Exception("No path in results or timeout")                              
                else:
                    # Download folder
                    with tempfile.TemporaryDirectory(dir="/tmp") as tempdir:
                        results = self.ipfs_kit.ipfs_get(cid = ipfs_src, path = tempdir)
                        
                        if os.path.exists(filename_dst):
                            pass
                        else:
                            os.mkdir(filename_dst)

                        if filename_dst[-1] == "/":
                            pass
                        else:
                            filename_dst = filename_dst + "/"

                        for file in os.scandir(tempdir):
                            if file.is_file():
                                shutil.move(file.path, filename_dst + file.name)

                    return filename_dst
                    
            except Exception as e:
                print("Exception thrown remove files")
                if(this_temp_file != None):
                    if(os.path.exists(this_temp_file.name)):
                        command = "rm "+this_temp_file.name
                        os.system(command)
                return e
            
        else:
            #raise Exception("Invalid filename_dst, no `.` suffix found") 
            pass

    def download_model(self, model, **kwargs):
        ipfs_timestamp = None
        s3_timestamp = None
        local_timestamp = None
        https_timestamp = None

        if type(self.ipfs_collection) == dict and "cache" in list(self.ipfs_collection.keys()):
            if "timestamp" in self.ipfs_collection["cache"]:
                ipfs_timestamp = self.ipfs_collection["cache"]["timestamp"]
            if ipfs_timestamp is None:
                ipfs_timestamp = datetime.datetime.now().timestamp()
        if type(self.s3_collection) == dict  and "cache" in list(self.s3_collection.keys()):
            if "timestamp" in self.s3_collection["cache"]:
                s3_timestamp = self.s3_collection["cache"]["timestamp"]
            if s3_timestamp is None:
                s3_timestamp = self.s3_kit.s3_ls_file(self.collection_cache["s3"].split("/")[-1], self.collection_cache["s3"].split("/")[-2])
                key = list(s3_timestamp.keys())[0]
                s3_timestamp = s3_timestamp[key]["last_modified"]
                pass
        if type(self.local_collection) == dict and "cache" in list(self.local_collection.keys()):
            if "timestamp" in self.local_collection["cache"]:
                local_timestamp = self.local_collection["cache"]["timestamp"]
            if local_timestamp is None:
                local_timestamp = os.path.getmtime(self.collection_cache["local"])
                pass
        if type(self.https_collection) == dict and "cache" in list(self.https_collection.keys()):
            if "timestamp" in self.https_collection["cache"]:
                https_timestamp = self.https_collection["cache"]["timestamp"]
            if https_timestamp is None:
                https_timestamp = datetime.datetime.now().timestamp()

        timestamps = {
            "ipfs": ipfs_timestamp,
            "s3": s3_timestamp,
            "local": local_timestamp,
            "https": https_timestamp
        }

        if not all(value is None for value in timestamps.values()):
            timestamps = {k: v for k, v in timestamps.items() if v is not None}    
            newest = max(timestamps, key=timestamps.get)
        else:
            raise Exception("No collection cache found")

        ipfs_model_data = None
        s3_model_data = None
        local_model_data = None
        https_model_data = None
    
        if type(self.ipfs_collection) == dict and model in self.ipfs_collection:
            ipfs_model_data = self.ipfs_collection[model]
        else:
            ipfs_model_data = None
        if type(self.s3_collection) == dict and model in self.s3_collection:
            s3_model_data = self.s3_collection[model]
        else:
            s3_model_data = None
        if type(self.local_collection) == dict and model in self.local_collection:
            local_model_data = self.local_collection[model]
        else:
            local_model_data = None
        if type(self.https_collection) == dict and model in self.https_collection:
            https_model_data = self.https_collection[model]
        else:
            https_model_data = None

        model_data = {
            "ipfs": ipfs_model_data,
            "s3": s3_model_data,
            "local": local_model_data,
            "https": https_model_data
        }

        if all(value is None for value in model_data.values()):
            raise Exception("Model not found")
        
        this_model = None

        if model_data[newest] is not None:

            # NOTE: Add check for disk space before downloading  
            if(model_data[newest]["hwRequirements"]["diskUsage"] > shutil.disk_usage("/tmp").free):
                raise Exception("Not enough disk space to download model")
            else:
                this_model = self.auto_download(model_data[newest], **kwargs)
        else:
            while this_model is None and len(timestamps) > 0:
                timestamps.pop(newest)
                newest = max(timestamps, key=timestamps.get)
            
            if model_data[newest] is not None:
                
                # NOTE: Add check for disk space before downloading  
                if(model_data[newest]["hwRequirements"]["diskUsage"] > shutil.disk_usage("/tmp").free):
                    raise Exception("Not enough disk space to download model")
                else:
                    this_model = self.auto_download(model_data[newest], **kwargs)

            if this_model is None:
                raise Exception("Model not found")
            self.models["local_models"][this_model["id"]] = datetime.datetime.now().timestamp()    
        return this_model
    
    def check_local(self, manifest, **kwargs):
        folder_data = manifest["folderData"]
        cache = manifest["cache"]
        local = cache["local"]
        check_filenames = {}
        local_files = list(local.keys())
        local_path = self.local_path + "/" + manifest["id"] + "/"
        for local_file in local_files:
            this_file = local[local_file]
            ## remove the first character if it is a "/"
            this_file_url = this_file["url"]
            this_file_path = this_file["path"]
            if this_file_path[0] == "/":
                this_local_file = this_file_path[1:]
            else:
                this_local_file = this_file_path
            this_file_path = os.path.join(local_path,this_local_file)
            if os.path.exists(this_file_path):
                this_file_mtime = os.path.getmtime(this_file_path)
                check_filenames[local_file] = this_file_mtime
            else:
                check_filenames[local_file] = False

        check_filenames["/manifest.json"] = True
        if all(check_filenames.values()):
            del check_filenames["/manifest.json"]
            oldest_file_timestamp = min(check_filenames.values())
            return oldest_file_timestamp
        else:
            return False

    def check_https(self, manifest, **kwargs):
        folder_data = manifest["folderData"]
        cache = manifest["cache"]
        https = cache["https"]
        https_files = list(https.keys())
        check_filenames = {}
        for https_file in https_files:
            this_https_file = https[https_file]
            if "url" in list(this_https_file.keys()) and https_file != "/manifest.json":
                this_https_url = this_https_file["url"]
                try:
                    results = requests.head(this_https_url)
                    if results.status_code == 200 or results.status_code == 302:
                        check_filenames[https_file] = datetime.datetime.now().timestamp()
                    else:
                        check_filenames[https_file] = False
                except Exception as e:
                    check_filenames[https_file] = False
                    pass
            else:
                check_filenames[https_file] = False

        check_filenames["/manifest.json"] = True
        if all(check_filenames.values()):
            return datetime.datetime.now().timestamp()
        else:
            return False
        
    def check_s3(self, manifest, **kwargs):
        folder_data = manifest["folderData"]
        files = list(folder_data.keys())
        cache = manifest["cache"]
        s3 = cache["s3"]
        s3_files = list(s3.keys())
        check_filenames = {}
        if s3_files != None:
            for s3_file in s3_files:
                this_s3_cache = s3[s3_file]
                this_s3_path = this_s3_cache["path"]
                this_s3_url = this_s3_cache["url"]
                if "s3://" in this_s3_url:
                    this_s3_split = this_s3_url.split("/")
                    this_s3_bucket = this_s3_split[2]
                    this_s3_key = this_s3_split[3:]
                    this_s3_key = "/".join(this_s3_key)
                elif this_s3_url[0] == "/":
                    this_s3_split = this_s3_path.split("/")
                    this_s3_bucket = this_s3_split[2]
                    this_s3_key = this_s3_split[3:]
                    this_s3_key = "/".join(this_s3_key)
                    
            try:
                results = self.s3_kit.s3_ls_file(this_s3_key , this_s3_bucket)
                if results is not None and results is not False and len(results) > 0:
                    results_keys = list(results.keys())
                    filename = results_keys[0]
                    file_metadata = results[filename]
                    mtime = file_metadata["last_modified"]                    
                    check_filenames[s3_file] = mtime 
                else:
                    check_filenames[s3_file] = False
            except Exception as e:
                check_filenames[s3_file] = e
                pass

        check_filenames["/manifest.json"] = True
        if all(check_filenames.values()):
            del check_filenames["/manifest.json"]
            oldest_file_timestamp = min(check_filenames.values())
            return oldest_file_timestamp
        else:
            return False
    
    def check_ipfs(self, manifest, **kwargs):
        folder_data = manifest["folderData"]
        cache = manifest["cache"]
        ipfs = cache["ipfs"]
        ipfs_files = list(ipfs.keys())
        check_filenames = {}
        ipfs_pinset = list(self.ipfs_pinset["ipfs"].keys())
        for ipfs_file in ipfs_files:
            this_ipfs_cache = ipfs[ipfs_file]
            if "path" in list(this_ipfs_cache.keys()) and ipfs_file != "/manifest.json":
                this_ipfs_cid = this_ipfs_cache["path"]
                try:
                    if this_ipfs_cid in ipfs_pinset:
                        check_filenames[ipfs_file] = datetime.datetime.now().timestamp()
                    else:
                        check_filenames[ipfs_file] = False
                except Exception as e:
                    check_filenames[ipfs_file] = False
                    pass
            else:
                check_filenames[ipfs_file] = False    

        check_filenames["/manifest.json"] = True
        if all(check_filenames.values()):
            return datetime.datetime.now().timestamp()
        else:
            return False

    def load_collection_cache(self, **kwargs):
        if "cache" in kwargs:
            cache = kwargs["cache"]
        else:
            cache = {
                "local": "/storage/cloudkit-models/collection.json",
                "s3": "s3://cloudkit-beta/collection.json",
                "ipfs": "QmXBUkLywjKGTWNDMgxknk6FJEYu9fZaEepv3djmnEqEqD",
                "https": "https://huggingface.co/endomorphosis/cloudkit-collection/resolve/main/collection.json"
            }
        timestamp_0 = time.time()
        if os.path.exists(cache["local"]):
            with open(cache["local"], 'r') as f:
                collection = json.load(f)
                self.local_collection = collection
        try:
            https_download = self.download_https(cache["https"], '/tmp/collection.json')
            if os.path.exists("./collection.json/collection.json"):
                shutil.move("./collection.json/collection.json", "/tmp/collection.json")
                shutil.rmtree("./collection.json")
            if os.path.exists(https_download):
                with open(https_download, 'r') as f:
                    this_collection = json.load(f)
                    self.https_collection = this_collection
            elif os.path.exists('/tmp/collection.json'):
                with open('/tmp/collection.json', 'r') as f:
                    this_collection = json.load(f)
                    self.https_collection = this_collection
        except Exception as e:
            print(e)
            pass
        timestamp_1 = time.time()
        try:
            ipfs_download = self.download_ipfs(cache["ipfs"], '/tmp/collection.json')
            with open(ipfs_download, 'r') as f:
                this_collection = json.load(f)
                self.ipfs_collection = this_collection
        except Exception as e:
            ipfs_download = None
            print(e)
            pass
        timestamp_2 = time.time()
        try:
            s3_download = self.download_s3(cache["s3"], '/tmp/collection.json')
            with open(s3_download, 'r') as f:
                this_collection = json.load(f)
                self.s3_collection = this_collection
        except Exception as e:
            s3_download = None
            print(e)
            pass
        timestamp_3 = time.time()

        timestamps = {
            "https": timestamp_1 - timestamp_0,
            "ipfs": timestamp_2 - timestamp_1,
            "s3": timestamp_3 - timestamp_2
        }

        fastest = min(timestamps, key=timestamps.get)
        self.fastest = fastest
        file_size = os.stat('/tmp/collection.json').st_size
        bandwidth = file_size / timestamps[fastest]
        self.bandwidth = bandwidth

        md5_local = hashlib.md5(json.dumps(self.local_collection).encode()).hexdigest()
        md5_ipfs = hashlib.md5(json.dumps(self.ipfs_collection).encode()).hexdigest()
        md5_s3 = hashlib.md5(json.dumps(self.s3_collection).encode()).hexdigest()
        md5_https = hashlib.md5(json.dumps(self.https_collection).encode()).hexdigest()
        if md5_local == md5_ipfs and md5_local == md5_s3 and md5_local == md5_https:
            if fastest == "ipfs" and len(list(self.ipfs_collection.keys())) > 0:
                self.collection = self.ipfs_collection
            elif fastest == "s3" and len(list(self.s3_collection.keys())) > 0:
                self.collection = self.s3_collection
            elif fastest == "https" and len(list(self.https_collection.keys())) > 0:
                self.collection = self.https_collection
            elif fastest == "local" and len(list(self.local_collection.keys())) > 0:
                self.collection = self.local_collection
            elif len(list(self.local_collection.keys())) > 0:
                self.collection = self.local_collection
            else:
                raise Exception("No collection found")
        if "cache" in list(self.local_collection.keys()):
            local_collection_cache = self.local_collection["cache"]
        else:
            local_collection_cache = {}
        if "cache" in list(self.ipfs_collection.keys()):
            ipfs_collection_cache = self.ipfs_collection["cache"]
        else:
            ipfs_collection_cache = {}
        if "cache" in list(self.s3_collection.keys()):
            s3_collection_cache = self.s3_collection["cache"]
        else:
            s3_collection_cache = {}
        if "cache" in list(self.https_collection.keys()):
            https_collection_cache = self.https_collection["cache"]
        else:
            https_collection_cache = {}

        if "timestamp" in local_collection_cache or "timestamp" in ipfs_collection_cache  or "timestamp" in s3_collection_cache or "timestamp" in https_collection_cache:
            modified = {}
            if "timestamp" in local_collection_cache:
                local_timestamp = local_collection_cache["timestamp"]
                modified["local"] = local_timestamp
            if "timestamp" in ipfs_collection_cache:
                ipfs_timestamp = ipfs_collection_cache["timestamp"]
                modified["ipfs"] = ipfs_timestamp
            if "timestamp" in s3_collection_cache:
                s3_timestamp = s3_collection_cache["timestamp"]
                modified["s3"] = s3_timestamp
            if "timestamp" in https_collection_cache:
                https_timestamp = https_collection_cache["timestamp"]
                modified["https"] = https_timestamp
            
            newest = max(modified, key=modified.get)
            object_name = newest + "_collection"
            self.collection = self.__dict__[object_name]
        else:
            sizes = {}
            sizes["local"] = len(json.dumps(self.local_collection))
            sizes["ipfs"] = len(json.dumps(self.ipfs_collection))
            sizes["s3"] = len(json.dumps(self.s3_collection))
            sizes["https"] = len(json.dumps(self.https_collection))
            largest = max(sizes, key=sizes.get)
            object_name = largest + "_collection"
            self.collection = self.__dict__[object_name]
        if os.path.exists(cache["local"]):
            with open(cache["local"], 'r') as f:
                collection = json.load(f)
                self.local_collection = collection
        return self.collection 

    def auto_download(self, manifest, **kwargs):
        ls_models = self.ls_models()
        this_model_manifest = manifest
        self.history_models[this_model_manifest["id"]] = datetime.datetime.now().timestamp()
        this_model_manifest_cache = this_model_manifest["cache"]
        this_model_manifest_folder_data = this_model_manifest["folderData"]
        s3_test = False
        ipfs_test = False
        https_test = False
        local_test = False
        try:
            if os.path.exists(this_model_manifest_cache["local"]["/README.md"]["path"]):
                local_test = True
                basename = os.path.basename(this_model_manifest_cache["local"]["/README.md"]["path"])
                for file in this_model_manifest_folder_data:
                    if file not in os.listdir(basename):
                        local_test = False
                        break
        except Exception as e:
            local_test = False
            pass
        timestamp_0 = datetime.datetime.now().timestamp()
        try:
            ipfs_test = False
            with tempfile.NamedTemporaryFile(suffix=".md", dir="/tmp") as this_temp_file:
                if "/README.md" in list(this_model_manifest_cache["ipfs"].keys()):
                    ipfs_test_file = self.download_ipfs(this_model_manifest_cache["ipfs"]["/README.md"]["path"], this_temp_file.name)
                    with open(ipfs_test_file, 'r') as f:
                        ipfs_test = f.read()
                    if len(ipfs_test) > 0:
                        ipfs_test = True
                    else:
                        ipfs_test = False
        except Exception as e:
            ipfs_test = e
            pass       
        timestamp_1 = datetime.datetime.now().timestamp()
        try:
            with tempfile.NamedTemporaryFile(suffix=".md", dir="/tmp") as this_temp_file:
                if "/README.md" in list(this_model_manifest_cache["s3"].keys()):
                    if "s3://" in this_model_manifest_cache["s3"]["/README.md"]["url"]:
                        s3_test = self.download_s3(this_model_manifest_cache["s3"]["/README.md"]["url"], this_temp_file.name)
                    else:
                        s3_test = self.download_s3(this_model_manifest_cache["s3"]["/README.md"]["path"], this_temp_file.name)
                    s3_test = str(s3_test)
                    if "error" not in s3_test:
                        with open(this_temp_file.name, 'r') as f:
                            s3_test = f.read()
                        if len(s3_test) > 0:
                            s3_test = True
                        else:
                            s3_test = False
                    else:
                        s3_test = False
        except Exception as e:
            s3_test = e
            pass
        timestamp_2 = datetime.datetime.now().timestamp()
        try:
            with tempfile.NamedTemporaryFile(suffix=".md", dir="/tmp") as this_temp_file:
                if "/README.md" in list(this_model_manifest_cache["https"].keys()):
                    https_url = this_model_manifest_cache["https"]["/README.md"]["url"]
                    https_test_file = self.download_https(https_url, this_temp_file.name)
                    with open(https_test_file, 'r') as f:
                        https_test = f.read()
                    if len(https_test) > 0:
                        https_test = True
                    else:
                        https_test = False
        except Exception as e:
            https_test = e
            pass
        timestamp_3 = datetime.datetime.now().timestamp()

        timestamps = {
            "ipfs": timestamp_1 - timestamp_0,
            "s3": timestamp_2 - timestamp_1,
            "https": timestamp_3 - timestamp_2,
            "local": 0
        }
        test = {
            "ipfs": ipfs_test,
            "s3": s3_test,
            "https": https_test,
            "local": local_test
        }
        download_src = None
        fastest = min(timestamps, key=timestamps.get)
        while test[fastest] == False or test[fastest] != True:
            timestamps.pop(fastest)
            fastest = min(timestamps, key=timestamps.get)
        if test[fastest] == True:
            download_src = fastest
        else:
            download_src = None
            pass
        if download_src is None:
            raise Exception("Model not found")
        else:
            file_list = this_model_manifest_folder_data.keys()
            file_success = {}
            for file in file_list:
                if not file.startswith("/"):
                    file = "/" + file
                if "." not in file:
                    os.makedirs("/tmp/"+file, exist_ok=True)
                    suffix = None
                else:
                    suffix = "." + file.split(".")[-1]
                    pass
                this_download_src = download_src
                this_file_size = this_model_manifest_folder_data[file]["size"]
                if "md5" in list(this_model_manifest_folder_data[file].keys()):
                    this_file_md5 = this_model_manifest_folder_data[file]["md5"]
                else:
                    this_file_md5 = None
                    
                this_tmp_file = os.path.join("/tmp/", "/".join(file.split("/")[1:]))
                this_local_file = os.path.join(os.path.join( self.local_path , this_model_manifest["id"]), this_model_manifest_cache["local"][file]["path"][1:])
                this_local_file_size = None
                this_local_file_md5 = None
                if os.path.exists(this_local_file):
                    this_local_file_size = os.stat(this_local_file).st_size
                    this_local_file_md5 = subprocess.run(["md5sum", this_local_file], capture_output=True)
                    this_local_file_md5 = this_local_file_md5.stdout.decode().split(" ")[0]

                    pass
                if ((file == "/README.md" or file == "/manifest.json") or (this_file_size == this_local_file_size or this_file_size == None) and (this_file_md5 == this_local_file_md5 or this_file_md5 == None)):
                    file_success[file] = True
                    pass
                else:
                    if this_download_src == "ipfs":
                        this_file_path = this_model_manifest_cache["ipfs"][file]["path"]
                        this_file_url = this_model_manifest_cache["ipfs"][file]["url"]
                        with tempfile.NamedTemporaryFile(suffix=suffix, dir="/tmp") as this_temp_file:
                            ipfs_download_file = self.download_ipfs(this_file_path, this_temp_file.name)
                            if ipfs_download_file != None and len(ipfs_download_file) > 0:
                                ipfs_download_size = os.stat( this_temp_file.name).st_size
                                ipfs_download_md5 = subprocess.run(["md5sum",  this_temp_file.name], capture_output=True)
                                ipfs_download_md5 = ipfs_download_md5.stdout.decode().split(" ")[0]
                                if ipfs_download_size != this_file_size:
                                    file_success[file] = "file size mismatch"
                                    this_download_src = "s3"
                                else:
                                    file_success[file] = True
                                if this_file_md5 != ipfs_download_md5:
                                    file_success[file] = "md5 mismatch"
                                    this_download_src = "s3"
                                    #raise Exception("MD5 mismatch")
                                    pass
                                if(os.path.exists(ipfs_download_file) and https_download_file != this_tmp_file):
                                    command = "mv " + ipfs_download_file + " " + this_tmp_file
                                    os.system(command)
                                    pass
                                elif(os.path.exists(this_temp_file.name) and not os.path.exists(this_tmp_file)):
                                    command = "mv " + this_temp_file.name + " " + this_tmp_file
                                    os.system(command)
                                    pass
                                else:
                                    pass
                            else:
                                this_download_src = "s3"
                                pass
                    if this_download_src == "s3":
                        this_file_path = this_model_manifest_cache["s3"][file]["path"]
                        this_file_url = this_model_manifest_cache["s3"][file]["url"]
                        with tempfile.NamedTemporaryFile(suffix=suffix, dir="/tmp") as this_temp_file:
                            s3_download_file = self.download_s3(this_file_path, this_temp_file.name)
                            s3_download_size = os.stat( this_temp_file.name).st_size
                            s3_download_md5 = subprocess.run(["md5sum",  this_temp_file.name], capture_output=True)
                            s3_download_md5 = s3_download_md5.stdout.decode().split(" ")[0]
                            if s3_download_file != None and len(s3_download_file) > 0:

                                if s3_download_size != this_file_size:
                                    file_success[file] = "file size mismatch"
                                    this_download_src = "https"
                                else:
                                    file_success[file] = True
                                if this_file_md5 != s3_download_md5:
                                    file_success[file] = "md5 mismatch"
                                    this_download_src = "https"
                                    #raise Exception("MD5 mismatch")
                                    pass

                                if(os.path.exists(s3_download_file) and s3_download_file != this_tmp_file):
                                    command = "mv " + s3_download_file + " " + this_tmp_file
                                    os.system(command)
                                    pass
                                elif(os.path.exists(this_temp_file.name) and not os.path.exists(this_tmp_file)):
                                    command = "mv " + this_temp_file.name + " " + this_tmp_file
                                    os.system(command)
                                    pass
                                else:
                                    pass
                            else:
                                this_download_src = "https"
                                pass
                    if this_download_src == "https" and file != "manifest.json":
                        this_file_path = this_model_manifest_cache["https"][file]["path"]
                        this_file_url = this_model_manifest_cache["https"][file]["url"]
                        with tempfile.NamedTemporaryFile(suffix=suffix, dir="/tmp") as this_temp_file:
                            https_download_file = self.download_https(this_file_url, this_temp_file.name)
                            https_download_size = os.stat(this_temp_file.name).st_size
                            https_download_md5 = subprocess.run(["md5sum", this_temp_file.name], capture_output=True)
                            https_download_md5 = https_download_md5.stdout.decode().split(" ")[0]
                            if https_download_size != this_file_size:
                                file_success[file] = "file size mismatch"
                            else:
                                file_success[file] = True
                            if this_file_md5 != https_download_md5:
                                file_success[file] = "md5 mismatch"
                                #raise Exception("MD5 mismatch")
                                pass
                            if(os.path.exists(https_download_file) and https_download_file != this_tmp_file):
                                command = "mv " + https_download_file + " " + this_tmp_file
                                os.system(command)
                                pass
                            elif(os.path.exists(this_temp_file.name) and not os.path.exists(this_tmp_file)):
                                command = "mv " + this_temp_file.name + " " + this_tmp_file
                                os.system(command)
                                pass
                            else:
                                pass
                    elif this_download_src == "https" and file == "manifest.json":
                        file_success[file] = True
                        with open(this_tmp_file, 'w') as f:
                            json.dump(this_model_manifest, f)
            
            #check that every key in file_success is True
            if all(file_success.values()):
                if not os.path.exists(os.path.join(self.local_path, this_model_manifest["id"])):
                    os.makedirs(os.path.join(self.local_path , this_model_manifest["id"]), exist_ok=True)
                for file in file_list:
                    if file.startswith("/"):
                        file = file[1:]
                    src_path = os.path.join("/tmp/", file)
                    dst_path = os.path.join(os.path.join(self.local_path, this_model_manifest["id"]), file)
                    this_tmp_file = os.path.join("/tmp/", file)
                    if not os.path.exists(os.path.dirname(dst_path)):
                        os.makedirs(os.path.dirname(dst_path))
                    if not os.path.exists(dst_path) and os.path.exists(src_path):
                        if os.path.isdir(src_path):
                            shutil.copytree(src_path, os.path.dirname(dst_path))
                            shutil.rmtree(src_path)
                        else:
                            shutil.move(src_path, dst_path)
                    pass
                return this_model_manifest
            else:
                raise Exception("Model not found")
        
    def ls_models(self, **kwargs):
        collection_sources = {}
        ipfs_timestamp = None
        s3_timestamp = None
        local_timestamp = None
        https_timestamp = None
        ipfs_keys = []
        s3_keys = []
        local_keys = []
        https_keys = []
        if self.ipfs_collection != None and type(self.s3_collection) == dict:
            ipfs_keys = list(self.ipfs_collection.keys())
        if self.s3_collection != None and type(self.s3_collection) == dict:
            s3_keys = list(self.s3_collection.keys())
        if self.local_collection != None and type(self.s3_collection) == dict:
            local_keys = list(self.local_collection.keys())
        if self.https_collection != None and type(self.s3_collection) == dict:
            https_keys = list(self.https_collection.keys())
        all_keys = ipfs_keys + s3_keys + local_keys + https_keys
        all_keys = list(set(all_keys))
        ## filter the list all_keys to remove "cache" and "error"
        if "cache" in all_keys:
            all_keys.remove("cache")
        if "error" in all_keys:
            all_keys.remove("error")
        return all_keys
        
    def ls_s3_models(self, **kwargs):
        ls_models = self.ls_models()
        s3_models = {}
        timestamps = {}
        if type(self.ipfs_collection) == dict and "cache" in self.ipfs_collection :
            if "timestamp" in self.ipfs_collection["cache"]:
                ipfs_timestamp = self.ipfs_collection["cache"]["timestamp"]
                timestamps["ipfs"] = ipfs_timestamp
        if type(self.s3_collection) == dict and "cache" in self.s3_collection:
            if "timestamp" in self.s3_collection["cache"]:
                s3_timestamp = self.s3_collection["cache"]["timestamp"]
                timestamps["s3"] = s3_timestamp
        if type(self.local_collection) == dict and "cache" in self.local_collection:
            if "timestamp" in self.local_collection["cache"]:
                local_timestamp = self.local_collection["cache"]["timestamp"]
                timestamps["local"] = local_timestamp
        if type(self.https_collection) == dict and "cache" in self.https_collection:
            if "timestamp" in self.https_collection["cache"]:
                https_timestamp = self.https_collection["cache"]["timestamp"]
                timestamps["https"] = https_timestamp

        if len(timestamps.keys()) != 0:
            newest = max(timestamps, key=timestamps.get)
            if newest == "local":
                this_collection = self.local_collection
            elif newest == "s3":
                this_collection = self.s3_collection
            elif newest == "ipfs":
                this_collection = self.ipfs_collection
            elif newest == "https":
                this_collection = self.https_collection
        else:
            if "error" not in self.local_collection:
                this_collection = self.local_collection
            elif "error" not in self.s3_collection:
                this_collection = self.s3_collection
            elif "error" not in self.https_collection:
                this_collection = self.https_collection
            elif "error" not in self.ipfs_collection:
                this_collection = self.ipfs_collection

        for model in ls_models:
            if model in this_collection and model != "cache" and model != "error":
                this_folder_data = this_collection[model]["folderData"]
                results = self.check_s3(this_collection[model])
                if results != None and results is not False:
                    s3_models[model] = results
                    pass
            elif model in self.local_collection and model != "cache" and model != "error":
                this_folder_data = self.local_collection[model]["folderData"]
                results = self.check_s3(self.local_collection[model])
                if results != None and results is not False:
                    s3_models[model] = results
            elif model in self.s3_collection and model != "cache" and model != "error":
                this_folder_data = self.s3_collection[model]["folderData"]
                results = self.check_s3(self.s3_collection[model])
                if results != None and results is not False:
                    s3_models[model] = results
            elif model in self.ipfs_collection and model != "cache" and model != "error":
                this_folder_data = self.ipfs_collection[model]["folderData"]
                if self.check_s3(self.ipfs_collection[model]):
                    s3_models[model] = results
            elif model in self.https_collection and model != "cache" and model != "error":
                this_folder_data = self.https_collection[model]["folderData"]
                results = self.check_s3(self.https_collection[model])
                if results != None and results is not False:
                    s3_models[model] = results
                else:
                    pass

        self.s3_models = s3_models
        return s3_models  

    def ls_https_models(self, **kwargs):
        ls_models = self.ls_models()
        https_models = {}
        timestamps = {}

        if type(self.ipfs_collection) == dict and "cache" in self.ipfs_collection :
            if "timestamp" in self.ipfs_collection["cache"]:
                ipfs_timestamp = self.ipfs_collection["cache"]["timestamp"]
                timestamps["ipfs"] = ipfs_timestamp
        if type(self.s3_collection) == dict and "cache" in self.s3_collection:
            if "timestamp" in self.s3_collection["cache"]:
                s3_timestamp = self.s3_collection["cache"]["timestamp"]
                timestamps["s3"] = s3_timestamp
        if type(self.local_collection) == dict and "cache" in self.local_collection:
            if "timestamp" in self.local_collection["cache"]:
                local_timestamp = self.local_collection["cache"]["timestamp"]
                timestamps["local"] = local_timestamp
        if type(self.https_collection) == dict and "cache" in self.https_collection:
            if "timestamp" in self.https_collection["cache"]:
                https_timestamp = self.https_collection["cache"]["timestamp"]
                timestamps["https"] = https_timestamp

        if len(timestamps.keys()) != 0:
            newest = max(timestamps, key=timestamps.get)
            if newest == "local":
                this_collection = self.local_collection
            elif newest == "s3":
                this_collection = self.s3_collection
            elif newest == "ipfs":
                this_collection = self.ipfs_collection
            elif newest == "https":
                this_collection = self.https_collection
        else:
            if "error" not in self.local_collection:
                this_collection = self.local_collection
            elif "error" not in self.s3_collection:
                this_collection = self.s3_collection
            elif "error" not in self.https_collection:
                this_collection = self.https_collection
            elif "error" not in self.ipfs_collection:
                this_collection = self.ipfs_collection

        for model in ls_models:
            if model in this_collection and model != "cache" and model != "error":
                this_folder_data = this_collection[model]["folderData"]
                results = self.check_https(this_collection[model])
                if results != None and results is not False:
                    https_models[model] = results
                else:
                    pass
            elif model in self.local_collection and model != "cache" and model != "error":
                this_folder_data = self.local_collection[model]["folderData"]
                results = self.check_https(self.local_collection[model])
                if results != None and results is not False:
                    https_models[model] = results
                else:
                    pass
            elif model in self.s3_collection and model != "cache" and model != "error":
                this_folder_data = self.s3_collection[model]["folderData"]
                results = self.check_https(self.s3_collection[model])
                if results != None and results is not False:
                    https_models[model] = results
                else:
                    pass
            elif model in self.ipfs_collection and model != "cache" and model != "error":
                this_folder_data = self.s3_collection[model]["folderData"]
                results = self.check_https(self.ipfs_collection[model])
                if results != None and results is not False:
                    https_models[model] = results
                else:
                    pass
            elif model in self.https_collection and model != "cache" and model != "error":
                this_folder_data = self.https_collection[model]["folderData"]
                results = self.check_https(self.https_collection[model])
                if results != None and results is not False:
                    https_models[model] = results
                else:
                    pass

        self.https_models = https_models
        return https_models  

            
    def ls_ipfs_models(self, **kwargs):
        ls_models = self.ls_models()
        ipfs_models = {}
        timestamps = {}
        if type(self.ipfs_collection) == dict and "cache" in self.ipfs_collection:
            if "timestamp" in self.ipfs_collection["cache"]:
                ipfs_timestamp = self.ipfs_collection["cache"]["timestamp"]
                timestamps["ipfs"] = ipfs_timestamp
        if type(self.s3_collection) == dict and "cache" in self.s3_collection:
            if "timestamp" in self.s3_collection["cache"]:
                s3_timestamp = self.s3_collection["cache"]["timestamp"]
                timestamps["s3"] = s3_timestamp
        if type(self.local_collection) == dict and "cache" in self.local_collection:
            if "timestamp" in self.local_collection["cache"]:
                local_timestamp = self.local_collection["cache"]["timestamp"]
                timestamps["local"] = local_timestamp
        if type(self.https_collection) == dict and "cache" in self.https_collection:
            if "timestamp" in self.https_collection["cache"]:
                https_timestamp = self.https_collection["cache"]["timestamp"]
                timestamps["https"] = https_timestamp

        if len(timestamps.keys()) != 0:
            newest = max(timestamps, key=timestamps.get)
            if newest == "local":
                this_collection = self.local_collection
            elif newest == "s3":
                this_collection = self.s3_collection
            elif newest == "ipfs":
                this_collection = self.ipfs_collection
            elif newest == "https":
                this_collection = self.https_collection
        else:
            if "error" not in self.local_collection:
                this_collection = self.local_collection
            elif "error" not in self.s3_collection:
                this_collection = self.s3_collection
            elif "error" not in self.https_collection:
                this_collection = self.https_collection
            elif "error" not in self.ipfs_collection:
                this_collection = self.ipfs_collection


        for model in ls_models:
            if model in list(this_collection.keys()) and model != "cache" and model != "error":
                this_folder_data = this_collection[model]["folderData"]
                results = self.check_ipfs(this_collection[model])
                if results is not None and results is not False:
                    ipfs_models[model] = results
                else:
                    pass
            elif model in list(self.local_collection.keys()) and model != "cache" and model != "error":
                this_folder_data = self.local_collection[model]["folderData"]
                results = self.check_ipfs(self.local_collection[model])
                if results is not None and results is not False:
                    ipfs_models[model] = results
                else:
                    pass
            elif model in list(self.s3_collection.keys()) and model != "cache" and model != "error":
                this_folder_data = self.s3_collection[model]["folderData"]
                results = self.check_ipfs(self.s3_collection[model])
                if results is not None and results is not False:
                    ipfs_models[model] = results
                else:
                    pass
            elif model in list(self.ipfs_collection.keys()) and model != "cache" and model != "error":
                this_folder_data = self.ipfs_collection[model]["folderData"]
                results = self.check_ipfs(self.ipfs_collection[model])
                if results is not None and results is not False:
                    ipfs_models[model] = results
                else:
                    pass
            elif model in list(self.https_collection.keys()) and model != "cache" and model != "error":
                this_folder_data = self.https_collection[model]["folderData"]
                results = self.check_ipfs(self.https_collection[model])
                if results is not None and results is not False:
                    ipfs_models[model] = results
                else:
                    pass

        self.ipfs_models = ipfs_models
        return ipfs_models  
            

    def ls_local_models(self, **kwargs):
        ls_models = self.ls_models()
        local_models = {}
        timestamps = {}

        if type(self.ipfs_collection) == dict and "cache" in self.ipfs_collection :
            if "timestamp" in self.ipfs_collection["cache"]:
                ipfs_timestamp = self.ipfs_collection["cache"]["timestamp"]
                timestamps["ipfs"] = ipfs_timestamp
        if type(self.s3_collection) == dict and "cache" in self.s3_collection:
            if "timestamp" in self.s3_collection["cache"]:
                s3_timestamp = self.s3_collection["cache"]["timestamp"]
                timestamps["s3"] = s3_timestamp
        if type(self.local_collection) == dict and "cache" in self.local_collection:
            if "timestamp" in self.local_collection["cache"]:
                local_timestamp = self.local_collection["cache"]["timestamp"]
                timestamps["local"] = local_timestamp
        if type(self.https_collection) == dict and "cache" in self.https_collection:
            if "timestamp" in self.https_collection["cache"]:
                https_timestamp = self.https_collection["cache"]["timestamp"]
                timestamps["https"] = https_timestamp

        if len(timestamps.keys()) != 0:
            newest = max(timestamps, key=timestamps.get)
            if newest == "local":
                this_collection = self.local_collection
            elif newest == "s3":
                this_collection = self.s3_collection
            elif newest == "ipfs":
                this_collection = self.ipfs_collection
            elif newest == "https":
                this_collection = self.https_collection
        else:
            if "error" not in self.local_collection:
                this_collection = self.local_collection
            elif "error" not in self.s3_collection:
                this_collection = self.s3_collection
            elif "error" not in self.https_collection:
                this_collection = self.https_collection
            elif "error" not in self.ipfs_collection:
                this_collection = self.ipfs_collection

        for model in ls_models:
            if model in this_collection and model != "cache" and model != "error":
                this_folder_data = this_collection[model]["folderData"]
                results = self.check_local(this_collection[model])
                if results is not None and results is not False:
                    local_models[model] = results
                    pass
            elif model in self.local_collection and model != "cache" and model != "error":
                this_folder_data = self.local_collection[model]["folderData"]
                results = self.check_local(self.local_collection[model])
                if results is not None and results is not False:
                    local_models[model] = results
                    pass
            elif model in self.s3_collection and model != "cache" and model != "error":
                this_folder_data = self.s3_collection[model]["folderData"]
                results = self.check_local(self.s3_collection[model])
                if results is not None and results is not False:
                    local_models[model] = results
                    pass
            elif model in self.ipfs_collection and model != "cache" and model != "error":
                this_folder_data = self.ipfs_collection[model]["folderData"]
                results = self.check_local(self.ipfs_collection[model])
                if results is not None and results is not False:
                    local_models[model] = results
                    pass
            elif model in self.https_collection and model != "cache" and model != "error":
                this_folder_data = self.https_collection[model]["folderData"]
                results = self.check_local(self.https_collection[model])
                if results is not None and results is not False:
                    local_models[model] = results
                    pass

        self.local_models = local_models
        return local_models  
        
    def state(self, **kwargs):
        timestamp = datetime.datetime.now()
        one_hour_ago = timestamp - datetime.timedelta(hours=1)
        one_day_ago = timestamp - datetime.timedelta(days=1)
        ten_days_ago = timestamp - datetime.timedelta(days=100)
        timestamp = datetime.datetime.timestamp(timestamp)
        one_hour_ago = datetime.datetime.timestamp(one_hour_ago)
        one_day_ago = datetime.datetime.timestamp(one_day_ago)
        ten_days_ago = datetime.datetime.timestamp(ten_days_ago) 
        try:
            if os.path.exists(os.path.join(self.ipfs_path,"state.json")):
                state_mtime = os.path.getmtime(os.path.join(self.ipfs_path,"state.json"))
                if state_mtime > one_day_ago:
                    self.last_update = state_mtime
                    with open(os.path.join(self.ipfs_path,"state.json"), 'r') as f:
                        self.models = json.load(f)
                        self.last_update = timestamp
            else: 
                command = "touch " + os.path.join(self.ipfs_path,"state.json")
                os.system(command)

        except Exception as e:
            self.models = {}
            pass
        
        if "src" in kwargs:
            src = kwargs["src"]
        else:
            src = "all"
        if src != "all":
            if src == "s3":
                self.models["s3_models"] = self.ls_s3_models()
            elif src == "ipfs":
                self.ipfs_pinset = self.ipfs_kit.ipfs_get_pinset()
                self.models["ipfs_models"] = self.ls_ipfs_models()
            elif src == "local":
                self.models["local_models"] = self.ls_local_models()
            elif src == "https":
                self.models["https_models"] = self.ls_https_models()
        else:                    
            if self.last_update < ten_days_ago:
                self.load_collection()
                self.models["s3_models"] = self.ls_s3_models()
                self.models["ipfs_models"] = self.ls_ipfs_models()
                self.models["local_models"] = self.ls_local_models()
                self.models["https_models"] = self.ls_https_models()
                self.ipfs_pinset = self.ipfs_kit.ipfs_get_pinset()
                #del self.models["s3Models"]
                #del self.models["ipfsModels"]
                #del self.models["localModels"]
                #del self.models["httpsModels"]
                self.last_update = timestamp

        if "s3Models" in list(self.models.keys()):
            self.models["s3_models"] = self.models["s3Models"]
            del self.models["s3Models"]
        if "ipfsModels" in list(self.models.keys()):
            self.models["ipfs_models"] = self.models["ipfsModels"]
            del self.models["ipfsModels"]
        if "httpsModels" in list(self.models.keys()):
            self.models["https_models"] = self.models["httpsModels"]
            del self.models["httpsModels"]
        if "localModels" in list(self.models.keys()):
            self.models["local_models"] = self.models["localModels"]
            del self.models["localModels"]


        for model in self.collection:
            if model != "cache":
                this_model = self.collection[model]
                cache = this_model["cache"]
                if "ipfs" in list(cache.keys()):
                    ipfs = cache["ipfs"]
                    for file in ipfs:
                        this_file = ipfs[file]
                        if "path" in list(this_file.keys()):
                            path = this_file["path"]
                            if path not in self.collection_pins:
                                if path in list(self.ipfs_pinset["ipfs"].keys()):
                                    pin_type = self.ipfs_pinset["ipfs"][path]
                                    if pin_type != "indirect":
                                        self.collection_pins.append(path)


        stringified_models = json.dumps(self.models)
        models_md5 = hashlib.md5(stringified_models.encode()).hexdigest()
        try:
            with open (os.path.join(self.ipfs_path,"state.json"), 'r' ) as f:
                state_json = json.load(f)
                state_json_md5 = hashlib.md5(json.dumps(state_json).encode).hexdigest()
                       
        except Exception as e:
            ## cannot read state.json
            with open (os.path.join(self.ipfs_path,"state.json"), 'w') as f:
                json.dump(self.models, f)
            with open (os.path.join(self.ipfs_path,"state.json"), 'r' ) as f:
                state_json_md5 = hashlib.md5(f.read().encode()).hexdigest()
            pass

        if models_md5 != state_json_md5:
            with open (os.path.join(self.ipfs_path,"state.json"), 'w') as f:
                json.dump(self.models, f)

        return self.models

    def evict_local(self, model, **kwargs):
        local_model_path = os.path.join(self.local_path, model)
        if os.path.exists(local_model_path):
            shutil.rmtree(local_model_path)
        return True
    
    def evict_s3(self, model, **kwargs):
        s3_model_path = self.collection[model]["cache"]["s3"]
        s3_model_path = s3_model_path[0]["url"]
        s3_model_path = s3_model_path.split("/")
        s3_model_bucket = s3_model_path[2:3][0]
        s3_model_dir = s3_model_path[3:4][0]
        results = self.s3_kit.s3_rm_dir(s3_model_dir, s3_model_bucket)
        return results

    def evict_models(self, **kwargs):
        ls_models = self.ls_models()
        history = self.history()
        current_timestamp = datetime.datetime.now().timestamp()
        for model in ls_models:
            if model in self.models["local_models"]:
                this_model_timestamp = self.models["local_models"][model]
                this_history_timestamp = datetime.datetime.timestamp(history[model]).timestamp()
                if current_timestamp - this_model_timestamp > self.timing["local_time"] and current_timestamp - this_history_timestamp > self.timing["local_time"]:
                    self.evict_local(model)
                    self.models["local_models"].pop(model)

            elif model in self.models["s3_models"]:
                this_model_timestamp = self.models["s3_models"][model]
                this_history_timestamp = datetime.datetime.timestamp(history[model]).timestamp()
                if current_timestamp - this_model_timestamp > self.timing["s3_time"] and current_timestamp - this_history_timestamp > self.timing["s3_time"]:
                    self.evict_s3(model)
                    self.models["s3_models"].pop(model)
        
        for model in self.models["local_models"]:
            if model not in ls_models:
                self.evict_local(model)
                self.models["local_models"].pop(model)

        for model in self.models["s3_models"]:
            if model not in ls_models:
                self.evict_s3(model)
                self.models["s3_models"].pop(model)

        results =  {
            "s3_models": self.models["s3_models"] ,
            "ipfs_models": self.models["ipfs_models"],
            "local_models": self.models["local_models"],
            "https_models": self.models["https_models"]
        }
        return results 
    
    def check_history_models(self, **kwargs):
        ls_models = self.ls_models()
        current_timestamp = datetime.datetime.now()
        current_timestamp = datetime.datetime.timestamp(current_timestamp)
        if len(self.history_models.keys()) == 0:
            if os.path.exists(os.path.join(self.ipfs_path,"history.json")):
                try:
                    with open(os.path.join(self.ipfs_path,"history.json"), 'r') as f:
                        self.history_models = json.load(f)
                except Exception as e:
                    with open(os.path.join(self.ipfs_path,"history.json"), 'w') as f:
                        json.dump({}, f)
                finally:
                    pass
            
        for model in ls_models:
            if model not in self.history_models.keys():
                self.history_models[model] = None
            
            if self.history_models[model] is not None:
                this_model_timestamp = datetime.datetime.timestamp(self.history[model])
                if current_timestamp - this_model_timestamp > 60:
                    self.history_models[model] = None

        for model in self.history_models:
            if model not in ls_models:
                self.history_models.pop(model)

        if os.path.exists(os.path.join(self.ipfs_path,"history.json")):
            history_json_mtime = os.path.getmtime(os.path.join(self.ipfs_path,"history.json"))    
            if current_timestamp - history_json_mtime > 60:
                with open(os.path.join(self.ipfs_path,"history.json"), 'w') as f:
                    json.dump(self.history_models, f)
        else:
            with open(os.path.join(self.ipfs_path,"history.json"), 'w') as f:
                json.dump(self.history_models, f)

        return self.history_models
    
    def check_zombies(self, **kwargs):
        ls_models = self.ls_models()
        local_files = os.walk(self.local_path)
        ls_local_files = []
        ipfs_files = []
        local_files = list(local_files)
        for root, dirs, files in local_files:
            for file in files:
                tmp_filename = root + "/" + file
                tmp_filename = tmp_filename.split("/")
                tmp_filename = "/".join(tmp_filename[3:])
                #tmp_filename = os.path.join(root, file).replace(self.local_path, "")
                split_tmp_filename = tmp_filename.split("/")
                if len(split_tmp_filename) > 1 and "ipfs" not in tmp_filename and "cloudkit" not in tmp_filename:
                    ls_local_files.append(tmp_filename)

        collection_files = []
        zombies = {}

        collection_files.append("collection.json")
        for model in self.collection:
            if model != "cache":
                this_model = self.collection[model]
                this_folder_name = this_model["id"]
                this_folder_data = this_model["folderData"]
                for file in this_folder_data:
                    collection_files.append(this_folder_name + file)

        s3_files = self.s3_kit.s3_ls_dir("",self.s3cfg["bucket"])

        s3_file_names = []
        for file in s3_files:
            s3_file_names.append(file["key"])
        
        ipfs_files = self.ipfs_kit.ipfs_ls_path("/")
        ipfs_file_names = []
        for file in ipfs_files["ipfs_ls_path"]:
            ipfs_file_names.append(file["name"])

        collection_pins = self.collection_pins
        

        compare_s3_files = [x for x in s3_file_names if x not in collection_files]
        zombies["s3"] = compare_s3_files
        compare_local_files = [x for x in ls_local_files if x not in collection_files]
        zombies["local"] = compare_local_files
        compare_ipfs_files = [x for x in ipfs_file_names if x not in collection_files]
        compare_ipfs_pins = [x for x in collection_pins if x not in self.ipfs_pinset]
        zombies["ipfs"] = compare_ipfs_pins
        zombies["ipfs_files"] = compare_ipfs_files
        self.zombies = zombies
        return zombies
    
    def rand_history(self, **kwargs):
        history = self.history_models
        two_weeks_ago = datetime.datetime.now() - datetime.timedelta(days=14)
        two_weeks_ago = datetime.datetime.timestamp(two_weeks_ago)
        two_days_ago = datetime.datetime.now() - datetime.timedelta(days=2)
        two_days_ago = datetime.datetime.timestamp(two_days_ago)
        now = datetime.datetime.now().timestamp()
        for model in list(history.keys()):
            random_float = random.random()
            random_timestamp = ((now - two_weeks_ago) * random_float) + two_weeks_ago
            history[model] = random_timestamp

        self.history_models = history
        return history
    
    def check_expired(self, **kwargs):
        ls_models = self.ls_models()
        current_timestamp = datetime.datetime.now().timestamp()
        expired = {
            "local" : [],
            "s3" : [],
            "ipfs": [],
        }

        for model in ls_models:
            if "local_models" in self.models:            
                if model in self.models["local_models"]:
                    this_model_timestamp = self.models["local_models"][model]
                    if current_timestamp - this_model_timestamp > self.timing["local_time"] and current_timestamp - self.history_models[model] > self.timing["local_time"]:
                        expired["local"].append(model)
            if "s3Models" in self.models:
                if model in self.models["s3Models"]:
                    this_model_timestamp = self.models["s3Models"][model]
                    if current_timestamp - this_model_timestamp > self.timing["s3_time"] and current_timestamp - self.history_models[model] > self.timing["s3_time"]:
                        expired["s3"].append(model)
            if "s3_models" in self.models:
                if model in self.models["s3_models"]:
                    this_model_timestamp = self.models["s3_models"][model]
                    if current_timestamp - this_model_timestamp > self.timing["s3_time"] and current_timestamp - self.history_models[model] > self.timing["s3_time"]:
                        expired["s3"].append(model)

        self.expired = expired
        return self.expired
    
    def check_pinned_models(self, **kwargs):
        ls_models = self.ls_models()

        while len(self.pinned_models.keys()) < 5:
            random_number = random.random()
            calculate = round(random_number * len(ls_models))
            if calculate < len(ls_models):
                chosen_model = ls_models[calculate]
                self.pinned_models[chosen_model] = datetime.datetime.now().timestamp()
        ## remove later and get data from orchestrator
 
        return self.pinned
    
    def check_not_found(self, **kwargs):
        ls_models = self.ls_models()
        not_found = {
            "local" : [],
            "s3" : [],
        }
        
        for model in list(self.history_models.keys()):
            current_time = datetime.datetime.now().timestamp()
            time_delta = current_time - self.history_models[model]
            if time_delta < self.timing["local_time"]:
                if "local_models" in list(self.models.keys()):
                    if model not in list(self.models["local_models"].keys()):
                        not_found["local"].append(model)

                if "s3_models" in list(self.models.keys()):
                    if model not in list(self.models["s3_models"].keys()):
                        not_found["s3"].append(model)

        for model in self.pinned_models:
            if "local_models" in list(self.models.keys()):
                if model not in list(self.models["local_models"].keys()):
                    not_found["local"].append(model)
            
            if "s3_models" in list(self.models.keys()):
                if model not in list(self.models["s3_models"].keys()):
                    not_found["s3"].append(model)

        self.not_found = not_found
        return self.not_found
    
    def download_missing(self, **kwargs):
        current_timestamp = datetime.datetime.now().timestamp()
        not_found = self.check_not_found()
        for model in not_found["local"]:
            if model in self.pinned_models:
                self.download_model(model)
                self.models["local_models"][model] = datetime.datetime.now().timestamp()    
            elif self.history_models[model] > current_timestamp - self.timing["local_time"]:
                self.download_model(model)
                self.models["local_models"][model] = datetime.datetime.now().timestamp()    
        for model in not_found["s3"]:
            if model in self.pinned_models:
                self.s3_kit.s3_ul_dir(self.local_path + "/" + model, self.s3cfg["bucket"], self.models["s3_models"][model]["folderData"])
                self.models["s3_models"][model] = datetime.datetime.now().timestamp()
            elif self.history_models[model] > current_timestamp - self.timing["s3_time"]:
                self.s3_kit.s3_ul_dir(self.local_path + "/" + model, self.s3cfg["bucket"], self.models["s3_models"][model]["folderData"])
                self.models["s3_models"][model] = datetime.datetime.now().timestamp()
        return None

    def evict_expired_models(self, **kwargs):
        current_timestamp = datetime.datetime.now().timestamp() 
        expired = self.expired
        for model in expired["local"]:
            self.evict_local(model)
            self.models["local_models"].pop(model)
        for model in expired["s3"]:
            self.evict_s3(model)
            self.models["s3_models"].pop(model)
        return None

    def evict_zombies(self, **kwargs):
        zombies = self.zombies
        for file in zombies["local"]:
            os.remove(os.path.join(self.local_path, file))
        for file in zombies["s3"]:
            self.s3_kit.s3_rm_file(file, self.s3cfg["bucket"])
        return None

    def test(self, **kwargs):
        self.load_collection_cache()
        self.state()
        #self.state(src = "s3")
        self.state(src = "local")
        #self.state(src = "ipfs")
        #self.state(src = "https")
        self.check_pinned_models()
        self.check_history_models()
        self.rand_history()
        self.check_zombies()
        self.check_expired()
        self.check_not_found()
        #self.download_model('gte-small')
        #self.download_model('stablelm-zephyr-3b-GGUF-Q2_K')
        self.download_missing()
        self.evict_expired_models()
        self.evict_zombies()
        return self
    