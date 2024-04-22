import os 
import subprocess
import tempfile
import sys
import json
import time
import datetime
import shutil
import pathlib

class ipfs:
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
				self.commands = {

				}
				pass

	def daemon_start(self, **kwargs):
		if "cluster_name" in list(self.__dict__.keys()):
			cluster_name = self.cluster_name
		if "cluster_name" in kwargs:
			cluster_name = kwargs['cluster_name']
		
		results1 = None
		results2 = None
		ipfs_ready = False
		# NOTE: Change this so it tries to start the daemon via systemctl first, then tries to start it via bash
		#  		if systemctl
		# 		ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l

		# Run this if root and check if it passes 
		if(os.geteuid() == 0):
			try:
				command1 = "systemctl start ipfs"
				results1 = subprocess.check_output(command1, shell=True)
				results1 = results1.decode()
			
				command1 = "ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l"
				execute1 = subprocess.check_output(command1, shell=True)
				execute1 = execute1.decode().strip()
				if int(execute1) > 0:
					ipfs_ready = True
			
			except Exception as error:
				results1 = str(error)
			finally:
				pass

		# Run this if user is not root or root user fails check if it passes
		if(os.geteuid() != 0 or ipfs_ready == False):
			try:
				command2 = "export IPFS_PATH=" + self.ipfs_path + "ipfs/ && ipfs daemon --enable-gc --enable-pubsub-experiment " 
				results2 = subprocess.Popen(command2, shell=True, stdout=subprocess.PIPE)
				#os.system(command2)
			except Exception as error:
				results2 = str(error)
			finally:
				pass

		results = {
			"systemctl": results1,
			"bash": results2
		}

		return results

	def daemon_stop(self, **kwargs):
		if "cluster_name" in list(self.__dict__.keys()):
			cluster_name = self.cluster_name
		if "cluster_name" in kwargs:
			cluster_name = kwargs['cluster_name']
		
		results1 = None
		results2 = None
		ipfs_ready = False

		if(os.geteuid() == 0):
			try:
				command1 = "systemctl stop ipfs"
				results1 = subprocess.check_output(command1, shell=True)
				results1 = results1.decode()

				command1 = "ps -ef | grep ipfs | grep daemon | grep -v grep | wc -l"
				execute1 = subprocess.check_output(command1, shell=True)
				execute1 = execute1.decode().strip()
				if int(execute1) == 0:
					ipfs_ready = True

			except Exception as error:
				results1 = str(error)
			finally:
				pass

		if(os.geteuid() != 0 or ipfs_ready == False):
			try:
				command2 = "ps -ef | grep ipfs | grep daemon | grep -v grep | awk '{print $2}' | xargs kill -9" 
				results2 = subprocess.check_output(command2, shell=True)
				results2 = results2.decode()            
			except Exception as error:
				results2 = str(error)
			finally:
				pass
	
		results = {
			"systemctl": results1,
			"bash": results2
		}
				
		return results 

	def ipfs_resize(self, size, **kwargs):
		command1 = self.daemon_stop()
		command2 = "ipfs config --json Datastore.StorageMax " + size + "GB"
		results1 = subprocess.check_output(command2, shell=True)
		results1 = results1.decode()
		command3 = self.daemon_start()
		return results1

	def ipfs_ls_pin(self, **kwargs):
		if "hash" in kwargs:
			hash = kwargs['hash']
			request1 = None
			try:
				request1 = self.ipfs_execute({
					"command": "cat",
					"hash": hash
				})
			except Exception as error: 
				print(error)
				pass
			finally:
				if request1 != None:
					return request1
				pass
			if request1 == None:
				request2 = None
				try:
					command = "ipfs cat" + hash
					request2 = subprocess.check_output(command, shell=True)
				except Exception as error:
					print(error)
					pass
				finally:
					pass
				return request2
		raise Exception("hash not found")
	

	def ipfs_get_pinset(self, **kwargs):
		with tempfile.NamedTemporaryFile(suffix=".txt", dir="/tmp") as this_tempfile:
			command = "export IPFS_PATH=" + self.ipfs_path + "ipfs/ && ipfs pin ls -s > " + this_tempfile.name
			process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
			process.wait()
			results = process.stdout.read()
			results = results.decode()
			file_data = None
			file_data = this_tempfile.read()
			file_data = file_data.decode()
			pinset = {}
			parse_results = file_data.split("\n")
			for i in range(len(parse_results)):
				data = parse_results[i].split(" ")
				if len(data) > 1:
					pinset[data[0]] = data[1]

			return pinset


	def ipfs_add_pin(self, pin, **kwargs):
		dirname = os.path.dirname(__file__)
		try:    
			command1 = "export IPFS_PATH=" + self.ipfs_path + "ipfs/ && cd  "+ self.ipfs_path + "ipfs/ &&ipfs pin add " + pin 
			#result1 = subprocess.Popen(command1, shell=True, stdout=subprocess.PIPE)
			result1 = subprocess.check_output(command1, shell=True)
			result1 = result1.decode()
		except Exception as error:
			result1 = error
		finally:
			pass
		return result1

	def ipfs_mkdir(self, path, **kwargs):
		this_path_split = path.split("/")
		this_path = ""
		results = []
		for i in range(len(this_path_split)):
			this_path = this_path + this_path_split[i] + "/"
			command1 = 'export IPFS_PATH=' + self.ipfs_path + 'ipfs/ && ipfs files mkdir ' + this_path
			result1 = subprocess.Popen(command1, shell=True, stdout=subprocess.PIPE)
			result1.wait()
			result1 = result1.stdout.read()
			result1 = result1.decode()
			results.append(result1)

		return results

	def ipfs_add_path2(self, path, **kwargs):
		ls_dir = []
		if not os.path.exists(path):
			raise Exception("path not found")
		if os.path.isfile(path):
			ls_dir = [path]
			self.ipfs_mkdir(os.path.dirname(path), **kwargs)
		elif os.path.isdir(path):
			self.ipfs_mkdir(path, **kwargs)
			ls_dir = os.listdir(path)
			for i in range(len(ls_dir)):
				ls_dir[i] = path + "/" + ls_dir[i]
			
		results1 = []
		results2 = []
		for i in range(len(ls_dir)):
			argstring = ""
			argstring = argstring + " --to-files=" + ls_dir[i] + " "
			command1 = "ipfs add " + argstring + ls_dir[i]
			result1 = subprocess.Popen(command1, shell=True, stdout=subprocess.PIPE)
			result1.wait()
			result1 = result1.stdout.read()
			result1 = result1.decode()
			results1.append(result1)
						
		return results1

	def ipfs_add_path(self, path, **kwargs):
		argstring = ""
		ls_dir = path
		if not os.path.exists(path):
			raise Exception("path not found")
		if os.path.isfile(path):
			self.ipfs_mkdir(os.path.dirname(path), **kwargs)
		elif os.path.isdir(path):
			self.ipfs_mkdir(path, **kwargs)
		argstring = argstring + "--recursive --to-files=" + ls_dir + " "
		command1 = "ipfs add " + argstring + ls_dir
		result1 = subprocess.Popen(command1, shell=True, stdout=subprocess.PIPE)
		result1.wait()
		result1 = result1.stdout.read()
		result1 = result1.decode()
		result1 = result1.split("\n")
		results = {}
		for i in range(len(result1)):
			result_split = result1[i].split(" ")
			if len(result_split) > 1:
				results[result_split[2]] = result_split[1]
		return results
	
	def ipfs_remove_path(self, path, **kwargs):
		result1 = None
		result2 = None
		stats = self.ipfs_stat_path(path, **kwargs)
		if len(stats.keys()) == 0:
			raise Exception("path not found")
		pin = stats['pin']
		if stats["type"] == "file":
			command1 = "export IPFS_PATH=" + self.ipfs_path + "ipfs/ && ipfs files rm " + path
			result1 = subprocess.Popen(command1, shell=True, stdout=subprocess.PIPE)
			result1.wait()
			result1 = result1.stdout.read()
			result1 = result1.decode()
			command2 = "export IPFS_PATH=" + self.ipfs_path + "ipfs/ && ipfs pin rm " + pin
			result2 = subprocess.Popen(command2, shell=True, stdout=subprocess.PIPE)
			result2.wait()
			result2 = result2.stdout.read()
			result2 = result2.decode()
			result2 = result2.split("\n")
		elif stats["type"] == "directory":
			contents = self.ipfs_ls_path(path, **kwargs)
			for i in range(len(contents)):
				if len(contents[i]) > 0:
					result1 = self.ipfs_remove_path(path + "/" + contents[i], **kwargs)
			pass
		else:
			raise Exception("unknown path type")
		results = {
			"files_rm": result1,
			"pin_rm": result2
		}
		return results

	def ipfs_stat_path(self, path, **kwargs):
		try:
			stat1 = "export IPFS_PATH=" + self.ipfs_path + "ipfs/ && ipfs files stat " + path
			results1 = subprocess.Popen(stat1, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			results1.wait()
			results1 = results1.stdout.read()
			results1 = results1.decode()
			results1 = results1.split("\n")
		except Exception as error:
			error1 = str(error)
		finally:
			pass
		if len(results1) > 0 and isinstance(results1, list):
			pin = results1[0]
			size = float(results1[1].split(": ")[1])
			culumulative_size = float(results1[2].split(": ")[1])
			child_blocks = float(results1[3].split(": ")[1])
			type = results1[4].split(": ")[1]
			results = {
				"pin": pin,
				"size": size,
				"culumulative_size": culumulative_size,
				"child_blocks": child_blocks,
				"type": type
			}
			return results
		else:
			return False


	def ipfs_name_resolve(self, **kwargs):
		result1 = None
		try:
			command1 = "export IPFS_PATH=" + self.ipfs_path + "/ipfs/ && ipfs name resolve " + kwargs['path']
			result1 = subprocess.check_output(command1, shell=True)
			result1 = result1.decode()
		except Exception as e:
			result1 = str(e)
		finally:
			pass
		return result1

	def ipfs_name_publish(self, path, **kwargs):
		if not os.path.exists(path):
			raise Exception("path not found")
		results1 = None
		results2 = None
		try:    
			command1 = "export IPFS_PATH=" + self.ipfs_path + "/ipfs/ && ipfs add --cid-version 1 " + path
			results1 = subprocess.check_output(command1, shell=True)
			results1 = results1.decode().strip()
			cid = results1.split(" ")[1]
			fname = results1.split(" ")[2]
			results1 = {
				fname: cid
			}
		except Exception as e:
			results1 = str(e)
		finally:
			pass

		try:
			command2 = "export IPFS_PATH=" + self.ipfs_path + "/ipfs/ && ipfs name publish " + cid
			results2 = subprocess.check_output(command2, shell=True)
			results2 = results2.decode()
			results2 = results2.split(":")[0].split(" ")[-1]
		except Exception as e:
			results2 = str(e)
		finally:
			pass

		results = {
			"add": results1,
			"publish": results2
		}
		return results

	def ipfs_ls_path(self, path, **kwargs):
		try:
			stat1 = "export IPFS_PATH=" + self.ipfs_path + "ipfs/ && ipfs files ls " + path
			results1 = subprocess.Popen(stat1, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			results1.wait()
			results1 = results1.stdout.read()
			results1 = results1.decode()
			results1 = results1.split("\n")
		except Exception as error:
			results1 = str(error)
		finally:
			pass
		if len(results1) > 0 and isinstance(results1, list):
			return results1
		else:
			return False

	def ipfs_remove_pin(self, cid, **kwargs):
		try:
			command1 = "export IPFS_PATH=" + self.ipfs_path + "ipfs/ && ipfs pin rm " + cid
			result1 = subprocess.Popen(command1, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			result1.wait()
			stdout = result1.stdout.read()
			stderr = result1.stderr.read()
		except Exception as error:
			result1 = error
			result1 = str(result1)
		finally:
			pass
		stdout = stdout.decode()
		stderr = stderr.decode()
		if "unpinned" in stdout:
			result1 = True
		return result1
   
	def ipfs_get(self, hash, file, **kwargs):
		kwargs['hash'] = hash
		kwargs['file'] = file
		request = self.ipfs_execute("get", **kwargs)
		metadata = {}
		suffix = file.split(".")[-1]
		with open(file, "r") as this_file:
			results = this_file.read()
			metadata["hash"] = hash
			metadata["file_name"] = file
			metadata["file_size"] = len(results)
			metadata["file_type"] = suffix
			metadata["mtime"] = os.stat(file).st_mtime
			
		return metadata

	def ipfs_execute(self, command, **kwargs):
		if type(kwargs) is not dict:
			raise Exception("kwargs must be a dictionary")

		executable = "ipfs "
		options = ["add", "pin", "unpin", "get", "cat", "ls", "refs", "refs-local", "refs-local-recursive", "refs-remote", "refs-remote-recursive", "repo", "version"]

		if command == "add":
			execute = executable + "add " + kwargs['file']

		if "hash" not in kwargs:
			raise Exception("hash not found in kwargs")
		
		if command == "get":
			execute = executable + "get " + kwargs['hash'] + " -o " +  kwargs['file']
			pass
		
		if command == "pin":
			execute = executable + "pin add " + kwargs['hash']

		if command == "unpin":
			execute = executable + "pin rm " + kwargs['hash']

		if command == "cat":
			execute = executable + "cat " + kwargs['hash']

		if command == "ls":
			execute = executable + "ls " + kwargs['hash']

		if command == "refs":
			execute = executable + "refs " + kwargs['hash']

		if command == "refs-local":
			execute = executable + "refs local " + kwargs['hash']
		
		if command == "refs-local-recursive":
			execute = executable + "refs local --recursive " + kwargs['hash']

		if command == "refs-remote":
			execute = executable + "refs remote " + kwargs['hash']

		if command == "refs-remote-recursive":
			execute = executable + "refs remote --recursive " + kwargs['hash']

		if command == "repo":
			execute = executable + "repo " + kwargs['hash']

		if command == "version":
			execute = executable + "version " + kwargs['hash']

		try:
			output = subprocess.Popen(execute, shell=True, stdout=subprocess.PIPE) 
			output.wait()
			output = output.stdout.read()
			output = output.decode()
			print(f"stdout: {output}")
			return output
		except Exception as e:
			print(f"error: {e}")
			output = e
			return output

		

	def test_ipfs(self):
		detect = subprocess.check_output("which ipfs", shell=True)
		detect = detect.decode()
		if len(detect) > 0:
			return True
		else:
			return False
		pass    

if __name__ == "__main__":
	this_ipfs = ipfs(None)
	results = this_ipfs.test_ipfs()
	print(results)
	pass
