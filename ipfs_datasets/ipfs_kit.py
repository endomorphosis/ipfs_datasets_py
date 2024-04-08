import os
import sys
import json
import time
import logging
import asyncio
import io
import tempfile
import subprocess
import datetime
import requests
import urllib.request
import urllib.parse
import urllib.error
import urllib3
import shutil
import subprocess
parent_dir = os.path.dirname(os.path.dirname(__file__))
#ipfs_lib_dir = os.path.join(parent_dir, "ipfs_kit_lib")
#ipfs_lib_dir2 = os.path.join(os.path.dirname(__file__), "ipfs_kit_lib")
ipfs_transformers_dir = os.path.join(parent_dir, "ipfs_transformers")
#sys.path.append(ipfs_lib_dir)
#sys.path.append(ipfs_lib_dir2)
sys.path.append(ipfs_transformers_dir)
from ipfs_kit_lib import install_ipfs, ipfs, ipfs_cluster_ctl, ipfs_cluster_service, ipfs_cluster_follow, ipget

class ipfs_kit:
    def __init__(self, resources, meta=None):
        self.role = None
        self.ipfs_get_config = self.ipfs_get_config
        self.ipfs_set_config = self.ipfs_set_config
        self.ipfs_get_config_value = self.ipfs_get_config_value
        self.ipfs_set_config_value = self.ipfs_set_config_value
        self.test_install = self.test_install
        self.ipfs_get = self.ipget_download_object
        self.install_ipfs = install_ipfs.install_ipfs_daemon(None)

        if meta is not None:
            if "config" in meta:
                if meta['config'] is not None:
                    self.config = meta['config']
            if "role" in meta:
                if meta['role'] is not None:
                    self.role = meta['role']
                    if self.role not in  ["master","worker","leecher"]:
                        self.role = "leecher"
            if "cluster_name" in meta:
                if meta["cluster_name"] is not None:
                    self.cluster_name = meta['cluster_name']
                    pass
            if "ipfs_path" in meta:
                if meta["ipfs_path"] is not None:
                    self.ipfs_path = meta['ipfs_path']
                    pass
            if self.role == "leecher" or self.role == "worker" or self.role == "master":
                self.ipfs = ipfs.ipfs(resources, meta = meta)
                self.ipget = ipget.ipget(resources, meta = meta)
                pass
            if self.role == "worker":
                self.ipfs_cluster_follow = ipfs_cluster_follow.ipfs_cluster_follow(resources, meta = meta)
                pass
            if self.role == "master":
                self.ipfs_cluster_ctl = ipfs_cluster_ctl.ipfs_cluster_ctl(resources, meta = meta)
                self.ipfs_cluster_service = ipfs_cluster_service.ipfs_cluster_service(resources, meta = meta)
                pass


    def __call__(self, method, **kwargs):
        if method == "ipfs_kit_stop":
            return self.ipfs_kit_stop( **kwargs)
        if method == "ipfs_kit_start":
            return self.ipfs_kit_start( **kwargs)
        if method == "ipfs_kit_ready":
            return self.ipfs_kit_ready( **kwargs)
        if method == 'ipfs_get_pinset':
            return self.ipfs.ipfs_get_pinset(**kwargs)
        if method == "ipfs_follow_list":
            if self.role != "master":
                return self.ipfs_cluster_ctl.ipfs_follow_list(**kwargs)
            else:
                raise Exception("role is not master")
        if method == "ipfs_follow_ls":
            if self.role != "master":
                return self.ipfs_cluster_follow.ipfs_follow_ls(**kwargs)
            else:
                raise Exception("role is not master")
        if method == "ipfs_follow_info":
            if self.role != "master":
                return self.ipfs_cluster_follow.ipfs_follow_info(**kwargs)
            else:
                raise Exception("role is not master")
        if method == 'ipfs_cluster_get_pinset':
            return self.ipfs_cluster_get_pinset(**kwargs)
        if method == 'ipfs_ls_pinset':
            return self.ipfs.ipfs_ls_pinset(**kwargs)
        if method == 'ipfs_cluster_ctl_add_pin':
            if self.role == "master":
                return self.ipfs_cluster_ctl.ipfs_cluster_ctl_add_pin(**kwargs)
            else:
                raise Exception("role is not master")
        if method == 'ipfs_cluster_ctl_rm_pin':
            if self.role == "master":
                return self.ipfs_cluster_ctl.ipfs_cluster_ctl_rm_pin(**kwargs)
            else:
                raise Exception("role is not master")
        if method == 'ipfs_add_pin':
            return self.ipfs.ipfs_add_pin(**kwargs)
        if method == 'ipts_ls_pin':
            return self.ipfs.ipfs_ls_pin(**kwargs)
        if method == 'ipfs_remove_pin':
            return self.ipfs.ipfs_remove_pin(**kwargs)
        if method == 'ipfs_get':
            return self.ipfs.ipfs_get(**kwargs)
        if method == 'ipget_download_object':
            self.method = 'download_object'
            return self.ipget.ipget_download_object(**kwargs)
        if method == 'ipfs_upload_object':
            self.method = 'ipfs_upload_object'
            return self.ipfs.ipfs_upload_object(**kwargs)
        if method == 'load_collection':
            return self.load_collection(**kwargs)
        pass

    def ipfs_kit_ready(self, **kwargs):
        if "cluster_name" in kwargs:
            cluster_name = kwargs["cluster_name"]
        elif "cluster_name" in self.__dict__:
            cluster_name = self.cluster_name
        elif self.role != "leecher":
            raise Exception("cluster_name is not defined")

        ready = False
        ipfs_ready = False
        ipfs_cluster_ready = False
        
        command1 = "ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l"
        execute1 = subprocess.check_output(command1, shell=True)
        execute1 = execute1.decode().strip()
        if int(execute1) > 0:
            ipfs_ready = True

        if self.role == "master":
            return self.ipfs_cluster_service.ipfs_cluster_service_ready()
        elif self.role == "worker":
            data_ipfs_follow = self.ipfs_cluster_follow.ipfs_follow_info()
            if "cluster_peer_online" in data_ipfs_follow and "ipfs_peer_online in data_ipfs_follow":
                if data_ipfs_follow["cluster_name"] == cluster_name:
                    if data_ipfs_follow["cluster_peer_online"] == 'true' and data_ipfs_follow["ipfs_peer_online"] == 'true':
                        ipfs_cluster_ready = True
        if self.role == "leecher" and ipfs_ready == True:
            ready = True
        elif self.role != "leecher" and ipfs_ready == True and ipfs_cluster_ready == True:
            self.ipfs_follow_info = data_ipfs_follow
            ready = True
        else:
            ready = {
                "ipfs": ipfs_ready,
                "ipfs_cluster": ipfs_cluster_ready
            }
        return ready

    def load_collection(self, cid, **kwargs):
        if cid is None:
            raise Exception("collection is None")
        if "path" in kwargs:
            dst_path = kwargs["path"]
        else:
            dst_path = self.ipfs_path
            if not os.path.exists(dst_path):
                os.makedirs(dst_path)        
            dst_path = os.path.join(dst_path, "pins")
            if not os.path.exists(dst_path):
                os.makedirs(dst_path)        
            dst_path = os.path.join(dst_path, cid)
        get_pin = None
        try:
            ipget = self.ipget.ipget_download_object(cid = cid, path = dst_path)
        except Exception as e:
            ipget = str(e)
        finally:
            pass

        with open(dst_path, 'r') as f:
            collection = f.read()

        try:
            collection_json = json.loads(collection)
            collection = collection_json
        except Exception as e:
            collection_json = e
            pass
        finally:
            pass

        return collection

    def ipfs_add_pin(self, pin , **kwargs):
        if "path" in kwargs:
            dst_path = kwargs["path"]
        else:
            dst_path = self.ipfs_path
            if not os.path.exists(dst_path):
                os.makedirs(dst_path)        
            dst_path = os.path.join(dst_path, "pins")
            if not os.path.exists(dst_path):
                os.makedirs(dst_path)        
            dst_path = os.path.join(dst_path, pin)

        get_pin = None
        try:
            ipget = self.ipget.ipget_download_object(cid = pin, path = dst_path)
        except Exception as e:
            ipget = str(e)
        finally:
            pass

        result1 = None
        result2 = None
        if self.role == "master":
            result1 = self.ipfs_cluster_ctl.ipfs_cluster_ctl_add_pin(dst_path, **kwargs)
            result2 = self.ipfs.ipfs_add_pin(pin, **kwargs)
        elif self.role == "worker" or self.role == "leecher":
            result2 = self.ipfs.ipfs_add_pin(pin, **kwargs)

        results = {
            "ipfs_cluster_ctl_add_pin": result1,
            "ipfs_add_pin": result2
        }
        return results
    
    def ipfs_add_path(self, path , **kwargs):
        result1 = None
        result2 = None
        if self.role == "master":
            result2 = self.ipfs.ipfs_add_path(path, **kwargs)
            result1 = self.ipfs_cluster_ctl.ipfs_cluster_ctl_add_path(path, **kwargs)
        elif self.role == "worker" or self.role == "leecher":
            result2 = self.ipfs.ipfs_add_path(path, **kwargs)

        results = {
            "ipfs_cluster_ctl_add_path": result1,
            "ipfs_add_path": result2
        }
        return results
    
    def ipfs_ls_path(self, path , **kwargs):
        result1 = None
        result1 = self.ipfs.ipfs_ls_path(path, **kwargs)
        for i in range(len(result1)):
            if result1[i] == "":
                result1.pop(i)

        results = {
            "ipfs_ls_path": result1
        }
            
        return results
    
    def name_resolve(self, **kwargs):
        result1 = None
        result1 = self.ipfs.ipfs_name_resolve(**kwargs)
        results = {
            "ipfs_name_resolve": result1
        }
        return results


    def name_publish(self, path, **kwargs):
        result1 = None
        result1 = self.ipfs.ipfs_name_publish(path, **kwargs)
        results = {
            "ipfs_name_publish": result1
        }
        return results
    
    
    def ipfs_remove_path(self, path, **kwargs):

        ipfs_cluster_path = None
        ipfs_pins = None
        ipfs_cluster_pins = None
        result1 = None
        if self.role == "master":
            result1 = self.ipfs_cluster_ctl.ipfs_cluster_ctl_remove_path(path, **kwargs)
            result2 = self.ipfs.ipfs_remove_path(path, **kwargs)
        elif self.role == "worker" or self.role == "leecher":
            result2 = self.ipfs.ipfs_remove_path(path, **kwargs)

        results = {
            "ipfs_cluster_ctl_rm_path": result1,
            "ipfs_rm_path": result2
        }
        return results
    
    def ipfs_remove_pin(self, pin, **kwargs):
        result1 = None
        result2 = None
        if self.role == "master":
            result1 = self.ipfs_cluster_ctl.ipfs_cluster_ctl_remove_pin(pin, **kwargs)
            result2 = self.ipfs.ipfs_remove_pin(pin, **kwargs)
        elif self.role == "worker" or self.role == "leecher":
            result2 = self.ipfs.ipfs_remove_pin(pin, **kwargs)

        results = {
            "ipfs_cluster_ctl_rm_pin": result1,
            "ipfs_rm_pin": result2
        }
        return results

    def test_install(self, **kwargs):
        if self.role == "master":
            return {
                "ipfs_cluster_service": self.install_ipfs.ipfs_cluster_service_test_install(),
                "ipfs_cluster_ctl": self.install_ipfs.ipfs_cluster_ctl_test_install(),
                "ipfs": self.install_ipfs.ipfs_test_install()
            }
        elif self.role == "worker":
            return {
                "ipfs_cluster_follow": self.install_ipfs.ipfs_cluster_follow_test_install(),
                "ipfs": self.install_ipfs.ipfs_test_install()
            }
        elif self.role == "leecher":
            return self.install_ipfs.ipfs_test_install()
        else:
            raise Exception("role is not master, worker, or leecher")
        
    def ipfs_get_pinset(self, **kwargs):

        ipfs_pinset =  self.ipfs.ipfs_get_pinset(**kwargs)

        ipfs_cluster = None
        if self.role == "master":
            ipfs_cluster = self.ipfs_cluster_ctl.ipfs_cluster_get_pinset(**kwargs)
        elif self.role == "worker":
            ipfs_cluster = self.ipfs_cluster_follow.ipfs_follow_list(**kwargs)
        elif self.role == "leecher":
            pass

        results = {
            "ipfs_cluster": ipfs_cluster,
            "ipfs": ipfs_pinset
        }
        return results
            
    def ipfs_kit_stop(self, **kwargs):
        ipfs_cluster_service = None
        ipfs_cluster_follow = None
        ipfs = None

        if self.role == "master":
            try:
                ipfs_cluster_service = self.ipfs_cluster_service.ipfs_cluster_service_stop()
            except Exception as e:
                ipfs_cluster_service = str(e)
            try:
                ipfs = self.ipfs.daemon_stop()
            except Exception as e:
                ipfs = str(e)
        if self.role == "worker":
            try:
                ipfs_cluster_follow = self.ipfs_cluster_follow.ipfs_follow_stop()
            except Exception as e:
                ipfs_cluster_follow = str(e)
            try:
                ipfs = self.ipfs.daemon_stop()
            except Exception as e:
                ipfs = str(e)
        if self.role == "leecher":
            try:
                ipfs = self.ipfs.daemon_stop()
            except Exception as e:
                ipfs = str(e)
        
        return {
            "ipfs_cluster_service": ipfs_cluster_service,
            "ipfs_cluster_follow": ipfs_cluster_follow,
            "ipfs": ipfs
        }
        
    def ipfs_kit_start(self, **kwargs):
        ipfs_cluster_service = None
        ipfs_cluster_follow = None
        ipfs = None
        if self.role == "master":
            try:
                ipfs = self.ipfs.daemon_start()
            except Exception as e:
                ipfs = str(e)
            try:
                ipfs_cluster_service = self.ipfs_cluster_service.ipfs_cluster_service_start()
            except Exception as e:
                ipfs_cluster_service = str(e)
        if self.role == "worker":
            try:
                ipfs = self.ipfs.daemon_start()
            except Exception as e:
                ipfs = str(e)
            try:
                ipfs_cluster_follow = self.ipfs_cluster_follow.ipfs_follow_start()
            except Exception as e:
                ipfs_cluster_follow = str(e)
        if self.role == "leecher":
            try:
                ipfs = self.ipfs.daemon_start()
            except Exception as e:
                ipfs = str(e)

        return {
            "ipfs_cluster_service": ipfs_cluster_service,
            "ipfs_cluster_follow": ipfs_cluster_follow,
            "ipfs": ipfs
        }
    
    def ipfs_get_config(self, **kwargs):
        command = "ipfs config show"
        results = ""
        try:
            results = subprocess.check_output(command, shell=True)
            results = json.loads(results)
        except Exception as error:
            print("command failed")
            print(command)
            print(error)
        finally:
            self.ipfs_config = results

        return results
    
    def ipfs_set_config(self, new_config, **kwargs):
        with tempfile.NamedTemporaryFile(suffix=".json", dir="/tmp") as this_tempfile:
            json.dump(new_config, this_tempfile)
            filename = this_tempfile.name
            command = "ipfs config replace " + filename
            results = ""
            try:
                results = subprocess.check_output(command, shell=True)
                results = json.loads(results)
            except Exception as error:
                print("command failed")
                print(command)
                print(error)
            finally:
                self.ipfs_config = results

            return results
        
    def ipfs_get_config_value(self, key, **kwargs):
        command = None
        results = None
        try:
            command = self.ipfs_execute({
                "command": "config",
                "key": key
            })
            results = json.loads(command)
        except Exception as error:
            print("command failed")
            print(command)
            print(error)
        finally:
            pass
        
        query = "ipfs config " + key
        
        try:
            command = subprocess.check_output(query, shell=True)
            results = json.loads(command)
        except Exception as error:
            print("command failed")
            print(command)
            print(error)
            raise Exception("command failed")
        finally:
            return(results)

    def ipfs_set_config_value(self, key, value, **kwargs):
        command = None
        results = None
        try:
            command = self.ipfs_execute({
                "command": "config",
                "key": key,
                "value": value
            })
            results = json.loads(command)
        except Exception as error:
            print("command failed")
            print(command)
            print(error)
        finally:
            pass
        
        query = "ipfs config " + key + " " + value
        
        try:
            command = subprocess.check_output(query, shell=True)
            results = json.loads(command)
        except Exception as error:
            print("command failed")
            print(command)
            print(error)
            raise Exception("command failed")
        finally:
            return(results)
   

    def check_collection(self, collection):
        status = {}
        collection_keys = list(collection.keys())
        pinset_keys = list(self.pinset.keys())
        orphan_models = []
        orphan_pins = []
        active_pins = []
        active_models = []

        for this_model in collection_keys:
            if this_model != "cache":
                this_manifest = collection[this_model]
                this_id = this_manifest["id"]
                this_cache = this_manifest["cache"]
                this_ipfs_cache = this_cache["ipfs"]
                this_ipfs_cache_keys = list(this_ipfs_cache.keys())
                found_all = True

                for this_cache_basename in this_ipfs_cache_keys:
                    this_cache_item = this_ipfs_cache[this_cache_basename]
                    this_cache_item_path = this_cache_item["path"]
                    this_cache_item_url = this_cache_item["url"]

                    if this_cache_item_path in pinset_keys:
                        active_pins.append(this_cache_item_path)
                    else:
                        found_all = False

                if found_all:
                    active_models.append(this_model)
                else:
                    orphan_models.append(this_model)

        for this_pin in pinset_keys:
            if this_pin not in active_pins:
                orphan_pins.append(this_pin)

        status["orphan_models"] = orphan_models
        status["orphan_pins"] = orphan_pins
        status["active_pins"] = active_pins
        status["active_models"] = active_models

        return status
    
    def ipfs_upload_object(self, **kwargs):
        return self.upload_object(kwargs['file'])
    
    def ipget_download_object(self, **kwargs):
        return self.ipget.ipget_download_object(**kwargs)

    def update_collection_ipfs(collection, collection_path):
        this_collection_ipfs = None
        if this_collection_path is None:
            this_collection_path = collection_path

        command_1 = "ipfs add -r " + this_collection_path
        try:
            results_1 = subprocess.check_output(command_1, shell=True)
            results_1 = results_1.decode().split("\n")

            results_matrix = []
            for i in range(len(results_1)):
                results_matrix.append(results_1[i].split(" "))

            if len(results_matrix) == 2:
                this_collection_ipfs = results_matrix[-2][1]

            metadata = ["path=/collection.json"]
            argstring = ""
            for i in range(len(metadata)):
                argstring += " --metadata " + metadata[i]

            command_2 = "ipfs-cluster-ctl pin add " + this_collection_ipfs + argstring
            results_2 = subprocess.check_output(command_2, shell=True)

            if "cache" in collection.keys():
                collection["cache"]["ipfs"] = this_collection_ipfs
            else:
                collection["cache"] = {}
                collection["cache"]["ipfs"] = this_collection_ipfs
            return this_collection_ipfs
        
        except subprocess.CalledProcessError as e:
            print("ipfs add failed")
            print(command_1)
            print(e)
        except Exception as e:
            print("An error occurred")
            print(e)


if __name__ == "__main__":
    ipfs = ipfs_kit(None, None)
    results = ipfs.test_install()
    print(results)
    pass
