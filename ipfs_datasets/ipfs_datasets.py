import os
class AutoDownloadModel():
	def __init__(self, collection=None, meta=None):
		if os.getuid() == 0:
			if meta is not None and type (meta) == dict:
				if "local_path" in meta:
					self.local_path = meta["local_path"]			
				else:
					self.local_path = "/huggingface/"
				if "ipfs_path" in meta:
					self.ipfs_path = meta["ipfs_path"]
				else:
					self.ipfs_path = "/ipfs/"
				if "s3_cfg" in meta:
					self.s3cfg = meta["s3_cfg"]
				else:
					self.s3cfg = None
				if "role" in meta:
					self.role = meta["role"]
				else:
					self.role = "leecher"
			else:
				self.local_path = "/huggingface/"
				self.ipfs_path = "/ipfs/"
				self.s3cfg = None
				self.role = "leecher"
				meta = {
					"local_path": self.local_path,
					"ipfs_path": self.ipfs_path,
					"s3_cfg": self.s3cfg,
					"role": self.role
				}
		else:
			if meta is not None and type (meta) == dict:
				if "local_path" in meta:
					self.local_path = meta["local_path"]
				else:
					self.local_path = os.path.join(os.getenv("HOME") , ".cache/huggingface/")
				if "ipfs_path" in meta:
					self.ipfs_path = meta["ipfs_path"]
				else:
					self.ipfs_path = os.path.join(os.getenv("HOME") , ".cache/ipfs/")
				if "s3_cfg" in meta:
					self.s3cfg = meta["s3_cfg"]
				else:
					self.s3cfg = None
				if "role" in meta:
					self.role = meta["role"]
				else:
					self.role = "leecher"
			else:
				self.local_path = os.path.join(os.getenv("HOME") , ".cache/huggingface/")
				self.ipfs_path = os.path.join(os.getenv("HOME") , ".cache/ipfs/")
				self.s3cfg = None
				self.role = "leecher"
				meta = {
					"local_path": self.local_path,
					"ipfs_path": self.ipfs_path,
					"s3_cfg": self.s3cfg,
					"role": self.role
				}
		from model_manager import model_manager as model_manager
		self.model_manager = model_manager(collection, meta)
		self.model_manager.load_collection_cache()
		self.model_manager.state()
				
	def download(self, **kwargs):
		# NOTE: Add kwarg for output directory where downloads are stored
		# if "local_path" in kwargs:
		# 	self.local_path = kwargs["local_path"]
		# if "ipfs_path" in kwargs:
		# 	self.ipfs_path = kwargs["ipfs_path"]
		dataset_name = None
		cid = None
		if "dataset_name" in kwargs:
			if "/" in kwargs["dataset_name"]:
				model_name = kwargs["dataset_name"].split("/")[1]
				pass
			elif "https://" in kwargs["dataset_name"]:
				model_name = kwargs["dataset_name"].split("/")[-1]
				pass
			else:
				model_name = kwargs["dataset_name"]
			pass
		elif "cid" in kwargs:
			cid = kwargs["cid"]
		if dataset_name != None:
			try:
				results = self.model_manager.download_model(dataset_name, **kwargs)
			except Exception as e:
				raise e
			finally:
				pass
			return os.path.join(self.local_path, dataset_name)
		else:
			try:
				results = self.model_manager.download_ipfs(cid, os.path.join(self.local_path, cid), **kwargs)
			except Exception as e:
				raise e
			finally:
				pass
			return os.path.join(self.local_path, cid)
		pass


class load_dataset(): 
	@staticmethod
	def from_auto_download(dataset_name, **kwargs):
		from datasets import load_dataset
		this_download = AutoDownloadModel()
		download_folder = this_download.download(dataset_name=dataset_name, **kwargs)
		return load_dataset(
			download_folder, 
			trust_remote_code=True,
			**kwargs
		)
 

	@staticmethod
	def from_ipfs(cid, **kwargs):
		from datasets import load_dataset
		this_download = AutoDownloadModel()
		download_folder = this_download.download(cid=cid, **kwargs)
		return load_dataset(
			download_folder, 
			trust_remote_code=True,
			**kwargs
		)

