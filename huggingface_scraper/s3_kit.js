import AWS from 'aws-sdk';
import fs from 'fs';
import path from 'path';
import os from 'os';
import util from 'util';
import { ObjectLockEnabled } from '@aws-sdk/client-s3';

export class S3Kit {
	constructor(resources, meta = null) {
		this.bucket = null;
		this.bucketFiles = null;
		this.cpDir = this.s3CpDir;
		this.cpFile = this.s3CpFile;
		this.rmDir = this.s3RmDir;
		this.rmFile = this.s3RmFile;
		this.lsDir = this.s3LsDir;
		this.lsFile = this.s3LsFile;
		this.mvDir = this.s3MvDir;
		this.mvFile = this.s3MvFile;
		this.dlDir = this.s3DlDir;
		this.dlFile = this.s3DlFile;
		this.ulDir = this.s3UlDir;
		this.ulFile = this.s3UlFile;
		this.mkDir = this.s3MkDir;
		this.getSession = this.getSession;
		if (meta !== null) {
			if ('s3cfg' in meta) {
				if (meta['s3cfg'] !== null) {
					this.config = meta['s3cfg'];
					this.getSession(meta['s3cfg']);
				}
			}
		}
		this.s3 = new AWS.S3(this.config);
	}

	call(method, kwargs) {
		if (method === 'ls_dir') {
			this.method = 'ls_dir';
			return this.s3LsDir(kwargs);
		}
		if (method === 'rm_dir') {
			this.method = 'rm_dir';
			return this.s3RmDir(kwargs);
		}
		if (method === 'cp_dir') {
			this.method = 'cp_dir';
			return this.s3CpDir(kwargs);
		}
		if (method === 'mv_dir') {
			this.method = 'mv_dir';
			return this.s3MvDir(kwargs);
		}
		if (method === 'dl_dir') {
			this.method = 'dl_dir';
			return this.s3DlDir(kwargs);
		}
		if (method === 'ul_dir') {
			this.method = 'ul_dir';
			return this.s3UlDir(kwargs);
		}
		if (method === 'ls_file') {
			this.method = 'ls_file';
			return this.s3LsFile(kwargs);
		}
		if (method === 'rm_file') {
			this.method = 'rm_file';
			return this.s3RmFile(kwargs);
		}
		if (method === 'cp_file') {
			this.method = 'cp_file';
			return this.s3CpFile(kwargs);
		}
		if (method === 'mv_file') {
			this.method = 'mv_file';
			return this.s3MvFile(kwargs);
		}
		if (method === 'dl_file') {
			this.method = 'dl_file';
			return this.s3DlFile(kwargs);
		}
		if (method === 'ul_file') {
			this.method = 'ul_file';
			return this.s3UlFile(kwargs);
		}
		if (method === 'mk_dir') {
			this.method = 'mk_dir';
			return this.s3MkDir(kwargs);
		}
		if (method === 'get_session') {
			this.method = 'get_session';
			return this.getSession(kwargs);
		}
		if (method === 'config_to_boto') {
			this.method = 'config_to_boto';
			return this.configToBoto(kwargs);
		}
	}

		
	async s3LsDir(dir, bucketName, kwargs) {
		let s3Config = kwargs && kwargs.s3cfg ? kwargs.s3cfg : this.config;
		let s3 = new AWS.S3(this.configToBoto(s3Config));
		let params = {
				Bucket: bucketName,
				Prefix: dir
		};
		return new Promise((resolve, reject) => {
				s3.listObjectsV2(params, function(err, data) {
				if (err) reject(err);
				else {
						let objects = data.Contents.map(obj => {
						return {
								key: obj.Key,
								last_modified: moment(obj.LastModified).unix(),
								size: obj.Size,
								e_tag: obj.ETag
						};
						});
						resolve(objects);
				}
				});
		});
		}

	async s3RmDir(dir, bucket, kwargs) {
		let s3Config = kwargs && kwargs.s3cfg ? kwargs.s3cfg : this.config;
		let s3 = new AWS.S3(this.configToBoto(s3Config));
		let params = {
				Bucket: bucket,
				Prefix: dir
		};
		return new Promise((resolve, reject) => {
				s3.listObjectsV2(params, function(err, data) {
				if (err) reject(err);
				else {
						let objects = data.Contents.map(obj => {
						return {
								key: obj.Key,
								e_tag: obj.ETag,
								last_modified: moment(obj.LastModified).unix(),
								size: obj.Size
						};
						});
						let deleteParams = {
						Bucket: bucket,
						Delete: {
								Objects: objects.map(obj => { return {Key: obj.key}; }),
								Quiet: false
						}
						};
						s3.deleteObjects(deleteParams, function(err, data) {
						if (err) reject(err);
						else resolve(objects);
						});
				}
				});
		});
		}
		
	async s3CpDir(srcPath, dstPath, bucket, kwargs) {
		let s3Config = kwargs && kwargs.s3cfg ? kwargs.s3cfg : this.config;
		let s3 = new AWS.S3(this.configToBoto(s3Config));
		let params = {
			Bucket: bucket,
			Prefix: srcPath
		};
		return new Promise((resolve, reject) => {
			s3.listObjectsV2(params, function(err, data) {
				if (err) reject(err);
				else {
					let directory = {};
					let copyPromises = data.Contents.map(obj => {
						let srcKey = obj.Key;
						let dstKey = srcKey.replace(srcPath, dstPath);
						if (srcKey !== srcPath) {
							let copyParams = {
								Bucket: bucket,
								CopySource: bucket + '/' + srcKey,
								Key: dstKey
							};
							return s3.copyObject(copyParams).promise().then(copyData => {
								directory[obj.Key] = {
									key: srcKey,
									e_tag: obj.ETag,
									last_modified: moment(copyData.CopyObjectResult.LastModified).unix(),
									size: obj.Size
								};
							});
						}
					});
					Promise.all(copyPromises).then(() => resolve(directory));
				}
			});
		});
	}
	
	async s3MvDir(srcPath, dstPath, bucket, kwargs) {
			let s3Config = kwargs && kwargs.s3cfg ? kwargs.s3cfg : this.config;
			let s3 = new AWS.S3(this.configToBoto(s3Config));
			let params = {
				Bucket: bucket,
				Prefix: srcPath
			};
			return new Promise((resolve, reject) => {
				s3.listObjectsV2(params, function(err, data) {
					if (err) reject(err);
					else {
						let directory = {};
						let movePromises = data.Contents.map(obj => {
							let srcKey = obj.Key;
							let dstKey = srcKey.replace(srcPath, dstPath);
							if (srcKey !== srcPath) {
								let copyParams = {
									Bucket: bucket,
									CopySource: bucket + '/' + srcKey,
									Key: dstKey
								};
								return s3.copyObject(copyParams).promise().then(copyData => {
									let deleteParams = {
										Bucket: bucket,
										Key: srcKey
									};
									return s3.deleteObject(deleteParams).promise().then(() => {
										directory[obj.Key] = {
											key: srcKey,
											e_tag: obj.ETag,
											last_modified: moment(copyData.CopyObjectResult.LastModified).unix(),
											size: obj.Size
										};
									});
								});
							}
						});
						Promise.all(movePromises).then(() => resolve(directory));
					}
				});
			});
		}
		
	async s3DlDir(remotePath, localPath, bucket, kwargs) {
		let s3Config = kwargs && kwargs.s3cfg ? kwargs.s3cfg : this.config;
		let s3 = new AWS.S3(this.configToBoto(s3Config));
		let params = {
			Bucket: bucket,
			Prefix: remotePath
		};
		return new Promise((resolve, reject) => {
			s3.listObjectsV2(params, function(err, data) {
				if (err) reject(err);
				else {
					let directory = {};
					let downloadPromises = data.Contents.map(obj => {
						let getParams = {
							Bucket: bucket,
							Key: obj.Key
						};
						return s3.getObject(getParams).promise().then(data => {
							let filename = path.basename(obj.Key);
							if (!fs.existsSync(localPath)) {
								fs.mkdirSync(localPath, { recursive: true });
							}
							let localFile = path.join(localPath, filename);
							fs.writeFileSync(localFile, data.Body);
							directory[obj.Key] = {
								key: obj.Key,
								last_modified: moment(obj.LastModified).unix(),
								size: obj.Size,
								e_tag: obj.ETag
							};
						});
					});
					Promise.all(downloadPromises).then(() => resolve(directory));
				}
			});
		});
	}
	
	async s3UlDir(localPath, remotePath, bucket, kwargs) {
		let s3Config = kwargs && kwargs.s3cfg ? kwargs.s3cfg : this.config;
		let s3 = new AWS.S3(this.configToBoto(s3Config));
		let files = fs.readdirSync(localPath).map(file => path.join(localPath, file));
		let results = {};
		let uploadPromises = files.map(uploadFile => {
			if (fs.lstatSync(uploadFile).isFile()) {
				let uploadKey = path.join(remotePath, path.basename(uploadFile));
				let fileStream = fs.createReadStream(uploadFile);
				let uploadParams = {
					Bucket: bucket,
					Key: uploadKey,
					Body: fileStream
				};
				return s3.upload(uploadParams).promise().then(response => {
					results[response.Key] = {
						key: response.Key,
						last_modified: moment(response.LastModified).unix(),
						size: response.ContentLength,
						e_tag: response.ETag
					};
				});
			} else {
				throw new Error("uploadFile must be a file");
			}
		});
		return Promise.all(uploadPromises).then(() => results);
	}

	async s3LsFile(filekey, bucket, kwargs) {
		let s3Config = kwargs && kwargs.s3cfg ? kwargs.s3cfg : this.config;
		let s3 = new AWS.S3(this.configToBoto(s3Config));
		let params = {
			Bucket: bucket,
			Prefix: filekey
		};
		return new Promise((resolve, reject) => {
			s3.listObjectsV2(params, function(err, data) {
				if (err) reject(err);
				else {
					if (data.Contents.length === 0) resolve(false);
					else {
						let directory = {};
						data.Contents.forEach(obj => {
							directory[obj.Key] = {
								key: obj.Key,
								last_modified: moment(obj.LastModified).unix(),
								size: obj.Size,
								e_tag: obj.ETag
							};
						});
						resolve(directory);
					}
				}
			});
		});
	}

	async s3RmFile(thisPath, bucket, kwargs) {
		let s3Config = kwargs && kwargs.s3cfg ? kwargs.s3cfg : this.config;
		let s3 = new AWS.S3(this.configToBoto(s3Config));
		let params = {
			Bucket: bucket,
			Key: thisPath
		};
		return new Promise((resolve, reject) => {
			s3.deleteObject(params, function(err, data) {
				if (err) reject(err);
				else {
					resolve({
						key: thisPath,
						e_tag: data.DeleteMarker ? data.DeleteMarker : null,
						last_modified: moment().unix(),
						size: null
					});
				}
			});
		});
	}
		
	async s3CpFile(srcPath, dstPath, bucket, kwargs) {
		let s3Config = kwargs && kwargs.s3cfg ? kwargs.s3cfg : this.config;
		let s3 = new AWS.S3(this.configToBoto(s3Config));
		let params = {
			Bucket: bucket,
			CopySource: `${bucket}/${srcPath}`,
			Key: dstPath
		};
		return new Promise((resolve, reject) => {
			s3.copyObject(params, function(err, data) {
				if (err) reject(err);
				else {
					resolve({
						key: dstPath,
						e_tag: data.CopyObjectResult ? data.CopyObjectResult.ETag : null,
						last_modified: data.CopyObjectResult ? moment(data.CopyObjectResult.LastModified).unix() : null,
						size: null
					});
				}
			});
		});
	}

	async s3MvFile(srcPath, dstPath, bucket, kwargs = {}) {
		const s3Config = kwargs.s3cfg || this.config;
		const s3 = new AWS.S3(this.configToBoto(s3Config));
		const copyParams = {
			Bucket: bucket,
			CopySource: `${bucket}/${srcPath}`,
			Key: dstPath
		};
		const copyData = await s3.copyObject(copyParams).promise();
		const deleteParams = {
			Bucket: bucket,
			Key: srcPath
		};
		await s3.deleteObject(deleteParams).promise();
		return {
			key: dstPath,
			e_tag: copyData.CopyObjectResult.ETag,
			last_modified: moment(copyData.CopyObjectResult.LastModified).unix(),
			size: copyData.CopyObjectResult.ContentLength
		};
	}
		
	async s3DlFile(remotePath, localPath, bucket, kwargs = {}) {
		const s3Config = kwargs.s3cfg || this.config;
		const s3 = new AWS.S3(this.configToBoto(s3Config));
		if (remotePath.includes('s3://')) {
			remotePath = remotePath.replace('s3://', '').replace(`${bucket}/`, '');
		}
		const params = {
			Bucket: bucket,
			Key: remotePath
		};
		const data = await s3.getObject(params).promise();
		fs.writeFileSync(localPath, data.Body);
		return {
			key: remotePath,
			last_modified: moment(data.LastModified).unix(),
			size: data.ContentLength,
			e_tag: data.ETag,
			local_path: localPath
		};
	}


	async s3UlFile(uploadFile, path, bucket, kwargs = {}) {
		const s3Config = kwargs.s3cfg || this.config;
		const s3 = new AWS.S3(this.configToBoto(s3Config));
		let fileData;
		let fileExtension;
		if (fs.existsSync(uploadFile)) {
			fileData = fs.readFileSync(uploadFile);
			fileExtension = path.extname(uploadFile);
		} else {
			fileData = Buffer.from(uploadFile);
			fileExtension = path.extname(path);
		}
		let thisTempFile = await new Promise((resolve, reject) => {
			tmpFile.createTempFile({  postfix: '.json', dir: '/tmp' }, (err, path, fd, cleanupCallback) => {
					if (err) {
							reject(err);
					} else {
							resolve({ name: path, fd, removeCallback: cleanupCallback });
					}
			});
			fs.writeFileSync(tmpFile.name, fileData);
		});

		const params = {
			Bucket: bucket,
			Key: path,
			Body: fs.createReadStream(tmpFile.name)
		};
		const data = await s3.putObject(params).promise();
		return {
			key: data.Key,
			last_modified: moment(data.LastModified).unix(),
			size: data.ContentLength,
			e_tag: data.ETag
		};
	}
		
	async s3MkDir(path, bucket, kwargs = {}) {
		const s3Config = kwargs.s3cfg || this.config;
		const s3 = new AWS.S3(this.configToBoto(s3Config));
		const params = {
			Bucket: bucket,
			Key: path,
			Body: ''
		};
		const data = await s3.putObject(params).promise();
		return {
			key: data.Key,
			last_modified: moment(data.LastModified).unix(),
			size: data.ContentLength,
			e_tag: data.ETag
		};
	}

	async s3UploadObject(f, bucket, key, s3Config, progressCallback) {
		const s3 = this.getSession(s3Config);
		const params = {
			Bucket: bucket,
			Key: key,
			Body: fs.createReadStream(f)
		};
		return s3.upload(params, progressCallback).promise();
	}

	async s3DownloadObject(f, bucket, key, s3Config, progressCallback) {
		const s3 = this.getSession(s3Config);
		const params = {
			Bucket: bucket,
			Key: key
		};
		const fileStream = fs.createWriteStream(f);
		const downloadStream = s3.getObject(params).createReadStream();
		downloadStream.on('data', progressCallback);
		downloadStream.pipe(fileStream);
		return new Promise((resolve, reject) => {
			fileStream.on('finish', resolve);
			fileStream.on('error', reject);
		});
	}

	async uploadDir(dir, bucket, s3Config, progressCallback) {
		const s3 = this.getSession(s3Config);
		const files = fs.readdirSync(dir);
		for (const file of files) {
			const filePath = path.join(dir, file);
			const params = {
				Bucket: bucket,
				Key: file,
				Body: fs.createReadStream(filePath)
			};
			await s3.upload(params, progressCallback).promise();
		}
	}


	async downloadDir(dir, bucket, s3Config, progressCallback) {
		const s3 = this.getSession(s3Config);
		const params = {
			Bucket: bucket,
			Prefix: dir
		};
		const data = await s3.listObjectsV2(params).promise();
		for (const object of data.Contents) {
			const fileStream = fs.createWriteStream(path.join(dir, object.Key));
			const downloadStream = s3.getObject({ Bucket: bucket, Key: object.Key }).createReadStream();
			downloadStream.on('data', progressCallback);
			downloadStream.pipe(fileStream);
			await new Promise((resolve, reject) => {
				fileStream.on('finish', resolve);
				fileStream.on('error', reject);
			});
		}
	}

	async s3ReadDir(dir, bucket, s3Config) {
		const s3 = this.getSession(s3Config);
		const params = {
			Bucket: bucket,
			Prefix: dir
		};
		const data = await s3.listObjectsV2(params).promise();
		const directory = {};
		for (const object of data.Contents) {
			const metadata = {
				key: object.Key,
				last_modified: moment(object.LastModified).unix(),
				size: object.Size,
				e_tag: object.ETag
			};
			directory[object.Key] = metadata;
		}
		return directory;
	}

	async s3DownloadObject(f, bucket, key, s3Config, progressCallback) {
		const s3 = this.getSession(s3Config);
		const params = {
			Bucket: bucket,
			Key: key
		};
		const fileStream = fs.createWriteStream(f);
		const downloadStream = s3.getObject(params).createReadStream();
		downloadStream.on('data', progressCallback);
		downloadStream.pipe(fileStream);
		return new Promise((resolve, reject) => {
			fileStream.on('finish', resolve);
			fileStream.on('error', reject);
		});
	}


	async s3Mkdir(dir, bucket, s3Config) {
		const s3 = this.getSession(s3Config);
		const params = {
			Bucket: bucket,
			Key: dir,
			Body: ''
		};
		return s3.putObject(params).promise();
	}

	async getSession(s3Config) {
		if (!this.session) {
			this.session = new AWS.S3(this.configToBoto(s3Config));
		}
		return this.session;
	}

	async configToBoto(s3Config) {
		if (Object.keys(s3Config).includes('accessKey')) {
			const results = {
				accessKeyId: s3Config['accessKey'],
				secretAccessKey: s3Config['secretKey'],
				endpoint: s3Config['endpoint']
			};
			this.config = results;
			return results;
		} else if (Object.keys(s3Config).includes('aws_access_key_id')) {
			const results = {
				accessKeyId: s3Config['aws_access_key_id'],
				secretAccessKey: s3Config['aws_secret_access_key'],
				endpoint: s3Config['endpoint_url']
			};
			this.config = results;
			return results;
		} else {
			throw new Error("s3_config must contain accessKey, secretKey, and endpoint");
		}
	}

	async test() {
		const endpoint = "https://object.ord1.coreweave.com";
		const accessKey = "OVEXCZJJQPUGXZOV";
		const secretKey = "H1osbJRy3903PTMqyOAGD6MIohi4wLXGscnvMEduh10";
		const bucket = "swissknife-models";
		const dir = "bge-base-en-v1.5@hf";
		const config = {
			accessKey: accessKey,
			secretKey: secretKey,
			endpoint: endpoint,
		};
		this.configToBoto(config);
		const s3 = this.getSession(config);
		const params = {
			Bucket: bucket,
			Prefix: dir
		};
		const data = await thiss3.listObjectsV2(params).promise();
		const directory = {};
		data.Contents.forEach((obj) => {
			directory[obj.Key] = {
				key: obj.Key,
				last_modified: obj.LastModified,
				size: obj.Size,
				e_tag: obj.ETag,
			};
		});
		return directory;
	}


	async test2() {
		const endpoint = "https://object.ord1.coreweave.com";
		const accessKey = "OVEXCZJJQPUGXZOV";
		const secretKey = "H1osbJRy3903PTMqyOAGD6MIohi4wLXGscnvMEduh10";
		const bucket = "cloudkit-beta";
		const keys = [
			'stablelm-zephyr-3b-GGUF-Q2_K@gguf/manifest.json',
			'stablelm-zephyr-3b-GGUF-Q2_K-Q2_K@gguf/README.md',
			'stablelm-zephyr-3b-GGUF-Q2_K-Q2_K@gguf/config.json',
			'stablelm-zephyr-3b-GGUF-Q2_K-Q2_K@gguf/manifest.json',
			'stablelm-zephyr-3b-GGUF-Q2_K-Q2_K@gguf/stablelm-zephyr-3b.Q2_K.gguf'
		];
		const config = {
			accessKeyId: accessKey,
			secretAccessKey: secretKey,
			endpoint: endpoint,
		};
		const s3 = new AWS.S3(config);
		const results = [];
		for (const key of keys) {
			const params = {
				Bucket: bucket,
				Key: key
			};
			const data = await s3.getObject(params).promise();
			results.push(data);
		}
		return results;
	}

	async test3() {
		const endpoint = "https://object.ord1.coreweave.com";
		const accessKey = "OVEXCZJJQPUGXZOV";
		const secretKey = "H1osbJRy3903PTMqyOAGD6MIohi4wLXGscnvMEduh10";
		const bucket = "cloudkit-beta";
		const key = 'Airoboros-c34B-3.1.2-GGUF-Q4_0-Q4_0@gguf/README.md';
		const config = {
			accessKeyId: accessKey,
			secretAccessKey: secretKey,
			endpoint: endpoint,
		};
		const s3 = new AWS.S3(config);
		const params = {
			Bucket: bucket,
			Key: key
		};
		const data = await s3.getObject(params).promise();
		return data;
	}
}


async function main() {
		const testThis = new S3Kit();
		await testThis.test();
		await testThis.test2();
		await testThis.test3();
}

//main();