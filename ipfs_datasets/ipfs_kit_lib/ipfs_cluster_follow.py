import sys
import os
import subprocess
import tempfile
import json

class ipfs_cluster_follow:
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

            if self.role == "leecher" or self.role == "worker" or self.role == "master":
                pass

    def ipfs_follow_start(self, **kwargs):
        if "cluster_name" in list(self.__dict__.keys()):
            cluster_name = self.cluster_name
        if "cluster_name" in kwargs:
            cluster_name = kwargs['cluster_name']
        try:
            if os.getuid() == 0:
                command1 = "systemctl start ipfs-cluster-follow"
                results1 = subprocess.check_output(command1, shell=True)
                results1 = results1.decode()
            else:
                results1 = "You need to be root to run this command"
        except Exception as e:
            results = str(e)
        finally:
            pass
        detect = "ps -ef | grep ipfs-cluster-follow | grep -v grep | awk '{print $2}'"
        detect_results = subprocess.check_output(detect, shell=True)
        detect_results = detect_results.decode()
        results2 = False

        if len(detect_results) == 0:
            homedir = os.path.expanduser("~")
            ls_file = os.listdir(homedir + "/.ipfs-cluster-follow/" + cluster_name)      
            if "api-socket" in ls_file:
                rm_command = "rm ~/.ipfs-cluster-follow/" + cluster_name + "/api-socket"
                rm_results = subprocess.check_output(rm_command, shell=True)
                rm_results = rm_results.decode()
                results2 = True   
            try:
                command2 = "/usr/local/bin/ipfs-cluster-follow " + cluster_name + " run"
                results2 = subprocess.Popen(command2, shell=True, stdout=subprocess.PIPE)
            except Exception as e:
                results = str(e)
            finally:
                pass

        results = {
            "systemctl": results1,
            "bash": results2
        }
        return results

    def ipfs_follow_stop(self, **kwargs):
        if "cluster_name" in list(self.__dict__.keys()):
            cluster_name = self.cluster_name
        if "cluster_name" in kwargs:
            cluster_name = kwargs['cluster_name']
        try:
            if os.getuid() == 0:
                command1 = "systemctl stop ipfs-cluster-follow"
                results1 = subprocess.check_output(command1, shell=True)
                results1 = results1.decode()
            else:
                results1 = "You need to be root to run this command"
        except Exception as e:
            results1 = str(e)
        finally:
            pass
        try:
            command2 = "ps -ef | grep ipfs-cluster-follow | grep -v grep | awk '{print $2}' | xargs kill -9"
            results2 = subprocess.check_output(command2, shell=True)
            results2 = results2.decode()
        except Exception as e:
            results2 = str(e)
        finally:
            pass

        try:
            command3 = "rm ~/.ipfs-cluster-follow/" + cluster_name + "/api-socket"
            results3 = subprocess.check_output(command3, shell=True)
            results3 = results3.decode()
        except Exception as e:
            results3 = str(e)
        finally:
            pass

        results = {
            "systemctl": results1,
            "bash": results2,
            "api-socket": results3
        }
        return results  

#    def ipfs_follow_run(self, **kwargs):
#        if "cluster_name" in list(self.keys()):
#            cluster_name = self.cluster_name
#        if "cluster_name" in kwargs:
#            cluster_name = kwargs['cluster_name']
#
#        command = "ipfs cluster-follow " + cluster_name + " run"
#        results = subprocess.check_output(command, shell=True)
#        results = results.decode()
#        return results

    def ipfs_follow_list(self, **kwargs):
        if "cluster_name" in list(self.__dict__.keys()):
            cluster_name = self.cluster_name
        if "cluster_name" in kwargs:
            cluster_name = kwargs['cluster_name']

        command = "ipfs-cluster-follow " + cluster_name + " list"
        results = subprocess.check_output(command, shell=True)
        results = results.decode()
        results_dict = {}
        if len(results) > 0:
            results = results.split("\n")
            for i in range(len(results)):

                while "  " in results[i]:
                    results[i] = results[i].replace("  ", " ")

                results[i] = results[i].split(" ")
                if len(results[i]) >= 2:
                    results[i] = {
                        results[i][1]: results[i][0]
                    }

            for i in range(len(results)):
                if type(results[i]) == dict:
                    key = list(results[i].keys())[0]
                    value = results[i][key]
                    results_dict[key] = value
                    
            return results_dict
        else:
            return False

    def ipfs_follow_info(self, **kwargs):
        results_dict = {}
        if "cluster_name" in list(self.__dict__.keys()):
            cluster_name = self.cluster_name
        if "cluster_name" in list(kwargs.keys()):
            cluster_name = kwargs['cluster_name']
        try:
            command = "ipfs-cluster-follow " + cluster_name + " info"
            results = subprocess.check_output(command, shell=True)
            results = results.decode()
            results = results.split("\n")
            if len(results) > 0:
                results_dict = {
                    "cluster_name": cluster_name,
                    "config_folder": results[2].split(": ")[1],
                    "config_source": results[3].split(": ")[1],
                    "cluster_peer_online": results[4].split(": ")[1],
                    "ipfs_peer_online": results[5].split(": ")[1],
                }

        except Exception as e:
            results = str(e)
        finally:
            pass
        
        return results_dict
        
    
    def ipfs_follow_run(self, **kwargs):
        if "cluster_name" in list(self.keys()):
            cluster_name = self.cluster_name
        if "cluster_name" in kwargs:
            cluster_name = kwargs['cluster_name']

        command = "ipfs-cluster-follow "+ cluster_name +" run"
        results = subprocess.check_output(command, shell=True)
        results = results.decode()
        results = results.split("\n")
        return results


    def test_ipfs_cluster_follow(self):
        detect = subprocess.check_output("which ipfs-cluster-follow", shell=True)
        detect = detect.decode()
        if len(detect) > 0:
            return True
        else:
            return False
        pass

if __name__ == "__main__":
    meta = {
        "cluster_name": "test"
    }
    this_ipfs_cluster_follow = ipfs_cluster_follow(meta)
    results = this_ipfs_cluster_follow.test_ipfs_cluster_follow()
    print(results)
    pass
