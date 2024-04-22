import os
import subprocess
import tempfile
import sys
import json

class ipfs_cluster_ctl:
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

            if self.role == "leecher" or self.role == "worker" or self.role == "master":
                pass
        
    def ipfs_cluster_ctl_add_pin(self, path, **kwargs):
        if not os.path.exists(path):
            raise Exception("path not found")
        ls_dir = os.path.walk(path)
        argstring = ""
        results = []
        for i in range(len(ls_dir)):
            argstring = argstring + " --metadata " + ls_dir[i]
            command = "ipfs-cluster-ctl pin add " + ls_dir[i] + argstring
            result = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
            result.wait()
            result = result.stdout.read()
            result = result.decode()
            results.append(result)
        return results

    
    def ipfs_cluster_ctl_remove_pin(self, path, **kwargs):
        if not os.path.exists(path):
            raise Exception("path not found")
        ls_dir = os.path.walk(path)
        argstring = ""
        results = []
        for i in range(len(ls_dir)):
            argstring = argstring + " --metadata " + ls_dir[i]
            command = "ipfs-cluster-ctl pin add " + ls_dir[i] + argstring
            result = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
            result.wait()
            result = result.stdout.read()
            result = result.decode()
            results.append(result)
        return results


    def ipfs_cluster_ctl_add_pin_recursive(self, path, **kwargs):
        if not os.path.exists(path):
            raise Exception("path not found")
        ls_dir = os.path.walk(path)
        argstring = ""
        results = []
        for i in range(len(ls_dir)):
            argstring = argstring + " --metadata " + ls_dir[i]
            command = "ipfs-cluster-ctl pin add -r " + ls_dir[i] + argstring
            result = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
            result.wait()
            result = result.stdout.read()
            result = result.decode()
            results.append(result)
        return results


    def ipfs_cluster_ctl_execute(self, args):
        executable = "ipfs-cluster-ctl "
        options = ["id", "peers", "add", "pin", "status", "recover", "version", "health", "ipfs" ]

        arg0 = args[0]
        arg1 = args[1]

        if args[0] in options:
            if args[0] != None:
                if args[1] != None:
                    command = executable + args[0] + " " + args[1]
                else:
                    command = executable + args[0]
            
            if args[0] == "peers":
                if args[1] not in ["ls", "rm"]:
                    raise Exception("invalid option")
                
            if args[0] == "pin":
                if args[1] not in ["add","rm","ls","update"]:
                    raise Exception("invalid option")
            
            if args[0] == "status":
                pass
            
            if args[0] == "recover":
                pass
            
            if args[0] == "health":
                if args[1] not in ["graph","metrics","alerts"]:
                    raise Exception("invalid option")
            
            if args[0] == "ipfs":
                if args[1] not in ["gc"]:
                    raise Exception("invalid option")
            
            if args[0] == "version":
                pass

            if args[0] == "add":                
                path = args[-1]
                options = args[1:-1]
                command = executable + "add "  + options.join(" ") + " " + path
                
        try:
            output = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
            print(f"stdout: {output.decode()}")
        except Exception as e:
            print(f"error: {e}")
            output = e
        
        return output
    
    def ipfs_cluster_get_pinset(self, **kwargs):
        with tempfile.NamedTemporaryFile(suffix=".txt", dir="/tmp") as this_tempfile:
            command = "ipfs-cluster-ctl pin ls > " + this_tempfile.name
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
            process.wait()
            results = process.stdout.read()
            results = results.decode()
            file_data = None
            file_data = this_tempfile.read()
            file_data = file_data.decode()
            self.cluster_pinset = file_data
            pinset = {}
            parse_results = file_data.split("\n")
            for i in range(len(parse_results)):
                results_list = parse_results[i].split(" | ")
                result_dict = {}
                for j in range(len(results_list)):
                    cell_split = results_list[j].split(":")
                    if(len(cell_split) > 1):
                        this_key = cell_split[0].replace(" ", "")
                        this_value = cell_split[1].replace(" ", "")
                        result_dict[this_key] = this_value
                if len(result_dict) > 1:
                    pinset[results_list[0]] = result_dict

            return pinset
    
    def ipfs_cluster_ctl_status(self):
        command = "ipfs-cluster-ctl status"
        results = subprocess.check_output(command, shell=True)
        results = results.decode()
        return results
    

    def test_ipfs_cluster_ctl(self):
        detect = os.system("which ipfs-cluster-ctl")
        if len(detect) > 0:
            return True
        else:
            return False
        pass

if __name__ == "__main__":
    this_ipfs_cluster_ctl = ipfs_cluster_ctl()
    results = this_ipfs_cluster_ctl.test_ipfs_cluster_ctl()
    print(results)
    pass