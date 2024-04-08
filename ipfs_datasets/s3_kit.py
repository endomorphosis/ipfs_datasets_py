from boto3 import resource
from boto3.session import Session
import datetime
import os
import sys
import io
import tempfile
import json

class s3_kit:
	def __init__(self, resources, meta=None):
		self.bucket = None
		self.bucket_files = None
		self.cp_dir = self.s3_cp_dir
		self.cp_file = self.s3_cp_file
		self.rm_dir = self.s3_rm_dir
		self.rm_file = self.s3_rm_file
		self.ls_dir = self.s3_ls_dir
		self.ls_file = self.s3_ls_file
		self.mv_dir = self.s3_mv_dir
		self.mv_file = self.s3_mv_file
		self.dl_dir = self.s3_dl_dir
		self.dl_file = self.s3_dl_file
		self.ul_dir = self.s3_ul_dir
		self.ul_file = self.s3_ul_file
		self.mk_dir = self.s3_mk_dir
		self.get_session = self.get_session
		if meta is not None:
			if "s3cfg" in meta:
				if meta['s3cfg'] is not None:
					self.config = meta['s3cfg']
					self.get_session(meta['s3cfg'])

	def __call__(self, method, **kwargs):
		if method == 'ls_dir':
			self.method = 'ls_dir'
			return self.s3_ls_dir(**kwargs)
		if method == 'rm_dir':
			self.method = 'rm_dir'
			return self.s3_rm_dir(**kwargs)
		if method == 'cp_dir':
			self.method = 'cp_dir'
			return self.s3_cp_dir(**kwargs)
		if method == 'mv_dir':
			self.method = 'mv_dir'
			return self.s3_mv_dir(**kwargs)
		if method == 'dl_dir':
			self.method = 'dl_dir'
			return self.s3_dl_dir(**kwargs)
		if method == 'ul_dir':
			self.method = 'ul_dir'
			return self.s3_ul_dir(**kwargs)
		if method == 'ls_file':
			self.method = 'ls_file'
			return self.s3_ls_file(**kwargs)
		if method == 'rm_file':
			self.method = 'rm_file'
			return self.s3_rm_file(**kwargs)
		if method == 'cp_file':
			self.method = 'cp_file'
			return self.s3_cp_file(**kwargs)
		if method == 'mv_file':
			self.method = 'mv_file'
			return self.s3_mv_file(**kwargs)
		if method == 'dl_file':
			self.method = 'dl_file'
			return self.s3_dl_file(**kwargs)
		if method == 'ul_file':
			self.method = 'ul_file'
			return self.s3_ul_file(**kwargs)
		if method == 'mk_dir':
			self.method = 'mk_dir'
			return self.s3_mkdir(**kwargs)
		if method == 'get_session':
			self.method = 'get_session'
			return self.get_session(**kwargs)
		if method == 'config_to_boto':
			self.method = 'config_to_boto'
			return self.config_to_boto(**kwargs)

	def s3_ls_dir(self, dir, bucket_name, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config

		bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket_name)
		bucket_objects = bucket.objects.filter(Prefix=dir)
		objects = []
		directory = {}
		for obj in bucket_objects:
			result = {}
			result['key'] = obj.key
			result['last_modified'] = datetime.datetime.timestamp(obj.last_modified)
			result['size'] = obj.size
			result['e_tag'] = obj.e_tag
			objects.append(result)
		return objects

	def s3_rm_dir(self, dir, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		objects = s3bucket.objects.filter(Prefix=dir)
		directory = []
		for obj in objects:
			this_key = obj.key
			this_etag = obj.e_tag
			last_modified = obj.last_modified
			size = obj.size
			request = obj.delete()
			results = {
				"key": this_key,
				"e_tag": this_etag,
				"last_modified": datetime.datetime.timestamp(last_modified),
				"size": size
			}
			directory.append(results)
		return directory
	
	
	def s3_cp_dir(self, src_path , dst_path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config

		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		objects = s3bucket.objects.filter(Prefix=src_path)
		directory = {}
		for obj in objects:
			src_key = obj.key
			dst_key = src_key.replace(src_path, dst_path)
			if src_key != src_path:
				request1 = obj.copy_from(
					CopySource={
						"Bucket": bucket,
						"Key": src_key,
					},
					Bucket=bucket,
					Key=dst_key,
				)

				last_modified = None
				size = None
				this_etag = obj.e_tag
				for item in request1:
					if item == "CopyObjectResult":
						for item2 in request1[item]:
							if item2 == "ETag":
								e_tag = request1[item][item2]
							elif item2 == "LastModified":
								last_modified = request1[item][item2]
				results = {
					"key": src_key,
					"e_tag": this_etag,
					"last_modified": datetime.datetime.timestamp(last_modified),
					"size": size
				}
				directory[obj.key] = results
		return directory
	
	def s3_mv_dir(self, src_path , dst_path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config

		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		objects = s3bucket.objects.filter(Prefix=src_path)
		directory = {}
		for obj in objects:
			src_key = obj.key
			dst_key = src_key.replace(src_path, dst_path)
			if src_key != src_path:
				request1 = obj.copy_from(
					CopySource={
						"Bucket": bucket,
						"Key": src_key,
					},
					Bucket=bucket,
					Key=dst_key,
				)

				last_modified = None
				size = None
				this_etag = obj.e_tag
				for item in request1:
					if item == "CopyObjectResult":
						for item2 in request1[item]:
							if item2 == "ETag":
								e_tag = request1[item][item2]
							elif item2 == "LastModified":
								last_modified = request1[item][item2]
				request2 = obj.delete(
				)
				results = {
					"key": src_key,
					"e_tag": this_etag,
					"last_modified": datetime.datetime.timestamp(last_modified),
					"size": size
				}
				directory[obj.key] = results
		return directory
	
	def s3_dl_dir(self, remote_path, local_path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config
		directory = {}
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		objects = s3bucket.objects.filter(Prefix=remote_path)
		for obj in objects:
			request = obj.get()
			data = request['Body'].read()
			filename = os.path.basename(obj.key)
			if not os.path.exists(local_path):
				os.makedirs(local_path)
			## split te local path string and make sure that all the sub folders exist
			local_path_split = local_path.split('/')
			for i in range(1, len(local_path_split)):
				local_path_check = os.path.join('/', *local_path_split[:i])
				if not os.path.exists(local_path_check):
					os.mkdir(local_path_check)

			local_file = os.path.join(local_path, filename)
			with open(local_file, 'wb') as this_file:
				this_file.write(data)
			results = {
				"key": obj.key,
				"last_modified": datetime.datetime.timestamp(obj.last_modified),
				"size": obj.size,
				"e_tag": obj.e_tag,
			}
			directory[obj.key] = results

		return directory
			
	def s3_ul_dir(self, local_path, remote_path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config		
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		objects = s3bucket.objects.filter(Prefix=remote_path).all()
		files = [os.path.join(local_path, file) for file in os.listdir(local_path)]

		results = {}
		for upload_file in files:
			if os.path.isfile(upload_file):
				file_extension = os.path.splitext(upload_file)[1]
				upload_file = open(upload_file, 'rb')
			else:
				raise Exception("upload_file must be a file")
			upload_key = os.path.join(remote_path, os.path.basename(upload_file.name))
			response = s3bucket.put_object(Key=upload_key, Body=upload_file)
			result = {
				"key": response.key,
				"last_modified": datetime.datetime.timestamp(response.last_modified),
				"size": response.content_length,
				"e_tag": response.e_tag,
			}
			results[response.key] = result
		return results
	
	def s3_ls_file(self, filekey, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		bucket_objects = s3bucket.objects.filter(Prefix=filekey)
		bucket_object_metadata = bucket_objects.all()
		objects = []
		directory = {}
		for obj in bucket_objects:
			objects.append(obj)
		if len(objects) == 0:
			return False
		for obj in objects:
			metadata = {
				"key": obj.key,
				"last_modified": datetime.datetime.timestamp(obj.last_modified),
				"size": obj.size,
				"e_tag": obj.e_tag,
			}
			directory[obj.key] = metadata
		return directory
	
	def s3_rm_file(self, this_path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		this_object = s3bucket.Object(this_path)
		key = this_object.key
		last_modified = this_object.last_modified
		content_length = this_object.content_length
		e_tag = this_object.e_tag
		request = this_object.delete(
			Key=this_path,
		)
		#print(request)
		results = {
			"key": key,
			"e_tag": e_tag,
			"last_modified": datetime.datetime.timestamp(last_modified),
			"size": content_length,
		}
		return results	

	def s3_cp_file(self, src_path, dst_path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		this_object = s3bucket.Object(src_path)
		request = this_object.copy_from(
			CopySource={
				"Bucket": bucket,
				"Key": src_path,
			},
			Bucket=bucket,
			Key=dst_path,
		)
		for item in request:
			if item == "CopyObjectResult":
				for item2 in request[item]:
					if item2 == "ETag":
						e_tag = request[item][item2]
					elif item2 == "LastModified":
						last_modified = request[item][item2]
		key = dst_path
		content_length = this_object.content_length
		results = {
			"key": dst_path,
			"e_tag": e_tag,
			"last_modified": datetime.datetime.timestamp(last_modified),
			"size": content_length,
		}
		return results
	
	def s3_mv_file(self, src_path, dst_path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		this_object = s3bucket.Object(src_path)
		request1 = this_object.copy_from(
			CopySource={
				"Bucket": bucket,
				"Key": src_path,
			},
			Bucket=bucket,
			Key=dst_path,
		)

		content_length = this_object.content_length
		for obj in request1:
			#print(obj)
			if obj == "CopyObjectResult":
				request_result = request1[obj]
				for result in request_result:
					#print(result)
					if result == "ETag":
						e_tag = request_result[result]
					elif result == "LastModified":
						last_modified = request_result[result]
						pass	
		request2 = this_object.delete(
		)
		results = {
			"key": dst_path,
			"e_tag": e_tag,
			"last_modified": datetime.datetime.timestamp(last_modified),
			"size": content_length,
		}
		return results
	
	
	def s3_dl_file(self, remote_path, local_path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config
		if "s3://" in remote_path:
			remote_path = remote_path.replace("s3://", "")
			remote_path = remote_path.replace(bucket + "/", "")
		
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		this_object = s3bucket.Object(remote_path)
		response = this_object.get()
		data = response['Body'].read()
		with open(local_path, 'wb') as this_file:
			this_file.write(data)
		results = {
			"key": remote_path,
			"last_modified": datetime.datetime.timestamp(this_object.last_modified),
			"size": this_object.content_length,
			"e_tag": this_object.e_tag,
			"local_path": local_path,
		}
		return results		
	
	def s3_ul_file(self, upload_file, path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config

		if os.path.isfile(upload_file):
			file_extension = os.path.splitext(upload_file)[1]
			upload_file = open(upload_file, 'rb')
		else:
			upload_file = io.BytesIO(upload_file)
			file_extension = os.path.splitext(path)[1]

		with tempfile.NamedTemporaryFile(suffix=file_extension, dir="/tmp") as this_temp_file:
			this_temp_file.write(upload_file.read())
			upload_file = this_temp_file.name

		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		response = s3bucket.put_object(Key=path, Body=upload_file)
		results = {
			"key": response.key,
			"last_modified": datetime.datetime.timestamp(response.last_modified),
			"size": response.content_length,
			"e_tag": response.e_tag,
		}
		return results
	
	def s3_mk_dir(self, path, bucket, **kwargs):
		if "s3cfg" in kwargs:
			s3_config = kwargs['s3cfg']
		else:
			s3_config = self.config
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		response = s3bucket.put_object(Key=path)
		results = {
			"key": response.key,
			"last_modified": datetime.datetime.timestamp(response.last_modified),
			"size": response.content_length,
			"e_tag": response.e_tag,
		}
		return results
	

	def s3_upload_object(self, f, bucket, key, s3_config, progress_callback):
		s3 = self.get_session(s3_config)
		return s3.upload_fileobj(
			f, 
			bucket, 
			key, 
			Callback=progress_callback
		)
	
	def s3_download_object(self, f, bucket, key, s3_config, progress_callback):
		s3 = self.get_session(s3_config)
		return s3.download_fileobj(
			bucket, 
			key, 
			f, 
			Callback=progress_callback
		)
	

	def upload_dir(self, dir, bucket, s3_config, progress_callback):
		s3 = self.get_session(s3_config)
		return s3.upload_file(
			dir, 
			bucket, 
			progress_callback
		)
	
	def download_dir(self, dir, bucket, s3_config, progress_callback):
		s3 = self.get_session(s3_config)
		return s3.download_file(
			bucket, 
			dir, 
			progress_callback
		)

	def s3_read_dir(self, dir, bucket, s3_config):
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		bucket_objects = bucket.objects.filter(Prefix=dir)
		bucket_object_metadata = bucket_objects.all()
		objects = []
		directory = {}
		for obj in bucket_object_metadata:
			objects.append(obj)
		for obj in objects:
			metadata = {
				"key": obj.key,
				"last_modified": datetime.datetime.timestamp(obj.last_modified),
				"size": obj.size,
				"e_tag": obj.e_tag,
			}
			directory[obj.key] = metadata
		return directory

	def s3_download_object(self, f, bucket, key, s3_config, progress_callback):
		s3 = self.get_session(s3_config)
		return s3.download_fileobj(
			bucket, 
			key, 
			f, 
			Callback=progress_callback
		)
	
	def s3_mkdir(self, dir, bucket, s3_config):
		s3bucket = resource(**self.config_to_boto(s3_config)).Bucket(bucket)
		return s3bucket.put_object(Key=dir)

	def get_session(self, s3_config):

		if "session" not in self.__dict__:
			self.session = Session().client(**self.config_to_boto(s3_config))
		return self.session 

	def config_to_boto(self, s3_config):
		if "accessKey" in s3_config.keys():
			results = dict(
				service_name = 's3',
				aws_access_key_id = s3_config['accessKey'],
				aws_secret_access_key = s3_config['secretKey'],
				endpoint_url = s3_config['endpoint'],
			)
			self.config = results
			return results
		elif "aws_access_key_id" in s3_config.keys():
			results = dict(
				service_name = 's3',
				aws_access_key_id = s3_config['aws_access_key_id'],
				aws_secret_access_key = s3_config['aws_secret_access_key'],
				endpoint_url = s3_config['endpoint_url'],
			)
			self.config = results
			return results
		else:
			raise Exception("s3_config must contain accessKey, secretKey, and endpoint")
