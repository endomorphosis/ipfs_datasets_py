const AWS = require('aws-sdk');
const fs = require('fs');
const path = require('path');
const AWS = require('aws-sdk');
const fs = require('fs');
const pathModule = require('path');
const tmp = require('tmp-promise');

class S3Kit {
    constructor(resources, meta = null) {
        this.config = null;
        this.session = null;
        this.bucket = null;
        this.bucket_files = null;
        this.cp_dir = this.s3_cp_dir;
        this.cp_file = this.s3_cp_file;
        this.rm_dir = this.s3_rm_dir;
        this.rm_file = this.s3_rm_file;
        this.ls_dir = this.s3_ls_dir;
        this.ls_file = this.s3_ls_file;
        this.mv_dir = this.s3_mv_dir;
        this.mv_file = this.s3_mv_file;
        this.dl_dir = this.s3_dl_dir;
        this.dl_file = this.s3_dl_file;
        this.ul_dir = this.s3_ul_dir;
        this.ul_file = this.s3_ul_file;
        this.mk_dir = this.s3_mk_dir;
        this.get_session = this.get_session;
        if (meta !== null) {
            if ("s3cfg" in meta) {
                if (meta['s3cfg'] !== null) {
                    this.config = meta['s3cfg'];
                    this.get_session(meta['s3cfg']);
                }
            }
        }
    }

    call(method, kwargs) {
        if (method === 'ls_dir') {
            this.method = 'ls_dir';
            return this.s3_ls_dir(kwargs);
        }
        if (method === 'rm_dir') {
            this.method = 'rm_dir';
            return this.s3_rm_dir(kwargs);
        }
        if (method === 'cp_dir') {
            this.method = 'cp_dir';
            return this.s3_cp_dir(kwargs);
        }
        if (method === 'mv_dir') {
            this.method = 'mv_dir';
            return this.s3_mv_dir(kwargs);
        }
        if (method === 'dl_dir') {
            this.method = 'dl_dir';
            return this.s3_dl_dir(kwargs);
        }
        if (method === 'ul_dir') {
            this.method = 'ul_dir';
            return this.s3_ul_dir(kwargs);
        }
        if (method === 'ls_file') {
            this.method = 'ls_file';
            return this.s3_ls_file(kwargs);
        }
        if (method === 'rm_file') {
            this.method = 'rm_file';
            return this.s3_rm_file(kwargs);
        }
        if (method === 'cp_file') {
            this.method = 'cp_file';
            return this.s3_cp_file(kwargs);
        }
        if (method === 'mv_file') {
            this.method = 'mv_file';
            return this.s3_mv_file(kwargs);
        }
        if (method === 'dl_file') {
            this.method = 'dl_file';
            return this.s3_dl_file(kwargs);
        }
        if (method === 'ul_file') {
            this.method = 'ul_file';
            return this.s3_ul_file(kwargs);
        }
        if (method === 'mk_dir') {
            this.method = 'mk_dir';
            return this.s3_mkdir(kwargs);
        }
        if (method === 'get_session') {
            this.method = 'get_session';
            return this.get_session(kwargs);
        }
        if (method === 'config_to_boto') {
            this.method = 'config_to_boto';
            return this.config_to_boto(kwargs);
        }
    }

    async s3_ls_dir(dir, bucket_name, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket_name,
            Prefix: dir
        };
    
        const data = await s3.listObjectsV2(params).promise();
        const objects = data.Contents.map(obj => {
            return {
                key: obj.Key,
                last_modified: new Date(obj.LastModified).getTime() / 1000,
                size: obj.Size,
                e_tag: obj.ETag
            };
        });
    
        return objects
    }
    async s3_rm_dir(dir, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket,
            Prefix: dir
        };
    
        const data = await s3.listObjectsV2(params).promise();
        const directory = [];
    
        for (let obj of data.Contents) {
            const deleteParams = {
                Bucket: bucket,
                Key: obj.Key
            };
    
            await s3.deleteObject(deleteParams).promise();
    
            directory.push({
                key: obj.Key,
                e_tag: obj.ETag,
                last_modified: new Date(obj.LastModified).getTime() / 1000,
                size: obj.Size
            });
        }
    
        return directory;
    }


    async s3_cp_dir(src_path, dst_path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket,
            Prefix: src_path
        };
    
        const data = await s3.listObjectsV2(params).promise();
        const directory = {};
    
        for (let obj of data.Contents) {
            const src_key = obj.Key;
            const dst_key = src_key.replace(src_path, dst_path);
    
            if (src_key !== src_path) {
                const copyParams = {
                    Bucket: bucket,
                    CopySource: `${bucket}/${src_key}`,
                    Key: dst_key
                };
    
                const copyResult = await s3.copyObject(copyParams).promise();
    
                directory[obj.Key] = {
                    key: src_key,
                    e_tag: obj.ETag,
                    last_modified: new Date(copyResult.CopyObjectResult.LastModified).getTime() / 1000,
                    size: obj.Size
                };
            }
        }
    
        return directory;
    }

    async s3_mv_dir(src_path, dst_path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket,
            Prefix: src_path
        };
    
        const data = await s3.listObjectsV2(params).promise();
        const directory = {};
    
        for (let obj of data.Contents) {
            const src_key = obj.Key;
            const dst_key = src_key.replace(src_path, dst_path);
    
            if (src_key !== src_path) {
                const copyParams = {
                    Bucket: bucket,
                    CopySource: `${bucket}/${src_key}`,
                    Key: dst_key
                };
    
                const copyResult = await s3.copyObject(copyParams).promise();
    
                const deleteParams = {
                    Bucket: bucket,
                    Key: src_key
                };
    
                await s3.deleteObject(deleteParams).promise();
    
                directory[obj.Key] = {
                    key: src_key,
                    e_tag: obj.ETag,
                    last_modified: new Date(copyResult.CopyObjectResult.LastModified).getTime() / 1000,
                    size: obj.Size
                };
            }
        }
    
        return directory;
    }

    async s3_dl_dir(remote_path, local_path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket,
            Prefix: remote_path
        };
    
        const data = await s3.listObjectsV2(params).promise();
        const directory = {};
    
        for (let obj of data.Contents) {
            const getParams = {
                Bucket: bucket,
                Key: obj.Key
            };
    
            const request = await s3.getObject(getParams).promise();
            const filename = path.basename(obj.Key);
    
            if (!fs.existsSync(local_path)) {
                fs.mkdirSync(local_path, { recursive: true });
            }
    
            const local_file = path.join(local_path, filename);
            fs.writeFileSync(local_file, request.Body);
    
            directory[obj.Key] = {
                key: obj.Key,
                last_modified: new Date(obj.LastModified).getTime() / 1000,
                size: obj.Size,
                e_tag: obj.ETag,
            };
        }
    
        return directory;
    }

    async  s3_ul_dir(local_path, remote_path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const files = fs.readdirSync(local_path).map(file => path.join(local_path, file));
    
        const results = {};
        for (let upload_file of files) {
            if (fs.lstatSync(upload_file).isFile()) {
                const file_extension = path.extname(upload_file);
                const upload_file_data = fs.readFileSync(upload_file);
                const upload_key = path.join(remote_path, path.basename(upload_file));
    
                const putParams = {
                    Bucket: bucket,
                    Key: upload_key,
                    Body: upload_file_data
                };
    
                const response = await s3.putObject(putParams).promise();
    
                results[response.key] = {
                    key: response.key,
                    last_modified: new Date().getTime() / 1000,
                    size: upload_file_data.length,
                    e_tag: response.ETag,
                };
            } else {
                throw new Error("upload_file must be a file");
            }
        }
    
        return results;
    }

    async s3_ls_file(filekey, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }

        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket,
            Prefix: filekey
        };

        const data = await s3.listObjectsV2(params).promise();
        const objects = data.Contents;
        const directory = {};

        if (objects.length === 0) {
            return false;
        }

        for (let obj of objects) {
            directory[obj.Key] = {
                key: obj.Key,
                last_modified: new Date(obj.LastModified).getTime() / 1000,
                size: obj.Size,
                e_tag: obj.ETag,
            };
        }

        return directory;
    }

    async  s3_rm_file(this_path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket,
            Key: this_path
        };
    
        const headData = await s3.headObject(params).promise();
        const key = headData.Key;
        const last_modified = new Date(headData.LastModified).getTime() / 1000;
        const content_length = headData.ContentLength;
        const e_tag = headData.ETag;
    
        const deleteData = await s3.deleteObject(params).promise();
    
        const results = {
            "key": key,
            "e_tag": e_tag,
            "last_modified": last_modified,
            "size": content_length,
        };
    
        return results;
    }

    async  s3_cp_file(src_path, dst_path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }

        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const copyParams = {
            Bucket: bucket,
            CopySource: `${bucket}/${src_path}`,
            Key: dst_path
        };

        const copyData = await s3.copyObject(copyParams).promise();

        const headParams = {
            Bucket: bucket,
            Key: dst_path
        };

        const headData = await s3.headObject(headParams).promise();
        const key = dst_path;
        const content_length = headData.ContentLength;
        const e_tag = headData.ETag;
        const last_modified = new Date(headData.LastModified).getTime() / 1000;

        const results = {
            "key": key,
            "e_tag": e_tag,
            "last_modified": last_modified,
            "size": content_length,
        };

        return results;
    }

    async  s3_mv_file(src_path, dst_path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const copyParams = {
            Bucket: bucket,
            CopySource: `${bucket}/${src_path}`,
            Key: dst_path
        };
    
        const copyData = await s3.copyObject(copyParams).promise();
    
        const deleteParams = {
            Bucket: bucket,
            Key: src_path
        };
    
        const deleteData = await s3.deleteObject(deleteParams).promise();
    
        const headParams = {
            Bucket: bucket,
            Key: dst_path
        };
    
        const headData = await s3.headObject(headParams).promise();
        const key = dst_path;
        const content_length = headData.ContentLength;
        const e_tag = headData.ETag;
        const last_modified = new Date(headData.LastModified).getTime() / 1000;
    
        const results = {
            "key": key,
            "e_tag": e_tag,
            "last_modified": last_modified,
            "size": content_length,
        };
    
        return results;
    }

    async  s3_dl_file(remote_path, local_path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        if (remote_path.includes("s3://")) {
            remote_path = remote_path.replace("s3://", "");
            remote_path = remote_path.replace(`${bucket}/`, "");
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket,
            Key: remote_path
        };
    
        const response = await s3.getObject(params).promise();
        const data = response.Body;
    
        await fs.writeFile(local_path, data);
    
        const headData = await s3.headObject(params).promise();
        const key = remote_path;
        const last_modified = new Date(headData.LastModified).getTime() / 1000;
        const content_length = headData.ContentLength;
        const e_tag = headData.ETag;
    
        const results = {
            "key": key,
            "last_modified": last_modified,
            "size": content_length,
            "e_tag": e_tag,
            "local_path": local_path,
        };
    
        return results;
    }

    async  s3_ul_file(upload_file, path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        let file_extension;
        if (fs.existsSync(upload_file)) {
            file_extension = pathModule.extname(upload_file);
            upload_file = fs.readFileSync(upload_file);
        } else {
            upload_file = Buffer.from(upload_file);
            file_extension = pathModule.extname(path);
        }
        let thisTempFile = await new Promise((resolve, reject) => {
            tmpFile.createTempFile({  postfix: file_extension, dir: '/tmp' }, (err, path, fd, cleanupCallback) => {
                if (err) {
                    reject(err);
                } else {
                    resolve({ name: path, fd, removeCallback: cleanupCallback });
                }
            });
            fs.writeFileSync(tmpFile.name, fileData);
            
          });

    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket,
            Key: path,
            Body: upload_file
        };
    
        const response = await s3.putObject(params).promise();
        cleanup();
    
        const headParams = {
            Bucket: bucket,
            Key: path
        };
    
        const headData = await s3.headObject(headParams).promise();
        const key = path;
        const last_modified = new Date(headData.LastModified).getTime() / 1000;
        const content_length = headData.ContentLength;
        const e_tag = headData.ETag;
    
        const results = {
            "key": key,
            "last_modified": last_modified,
            "size": content_length,
            "e_tag": e_tag,
        };
    
        return results;
    }

    async  s3_mk_dir(path, bucket, kwargs = {}) {
        let s3_config;
        if ('s3cfg' in kwargs) {
            s3_config = kwargs['s3cfg'];
        } else {
            s3_config = this.config;
        }
    
        const s3 = new AWS.S3(this.config_to_boto(s3_config));
        const params = {
            Bucket: bucket,
            Key: path,
            Body: ''
        };
    
        const response = await s3.putObject(params).promise();
    
        const headParams = {
            Bucket: bucket,
            Key: path
        };
    
        const headData = await s3.headObject(headParams).promise();
        const key = path;
        const last_modified = new Date(headData.LastModified).getTime() / 1000;
        const content_length = headData.ContentLength;
        const e_tag = headData.ETag;
    
        const results = {
            "key": key,
            "last_modified": last_modified,
            "size": content_length,
            "e_tag": e_tag,
        };
    
        return results;
    }

    get_session(s3_config) {
        return new AWS.S3(s3_config);
    }

    async s3_upload_object(f, bucket, key, s3_config, progress_callback) {
        const s3 = this.get_session(s3_config);
        const params = {
            Bucket: bucket,
            Key: key,
            Body: fs.createReadStream(f)
        };

        return s3.upload(params, progress_callback).promise();
    }

    async s3_download_object(f, bucket, key, s3_config, progress_callback) {
        const s3 = this.get_session(s3_config);
        const params = {
            Bucket: bucket,
            Key: key
        };

        const fileStream = fs.createWriteStream(f);
        const s3Stream = s3.getObject(params).createReadStream();

        s3Stream.on('data', (chunk) => {
            progress_callback(chunk.length);
        });

        s3Stream.pipe(fileStream);

        return new Promise((resolve, reject) => {
            fileStream.on('finish', resolve);
            fileStream.on('error', reject);
        });
    }


    async upload_dir(dir, bucket, s3_config, progress_callback) {
        const s3 = this.get_session(s3_config);
        const files = await recursive(dir);

        for (const file of files) {
            const params = {
                Bucket: bucket,
                Key: path.relative(dir, file),
                Body: fs.createReadStream(file)
            };

            await s3.upload(params, progress_callback).promise();
        }
    }

    async download_dir(dir, bucket, s3_config, progress_callback) {
        const s3 = this.get_session(s3_config);
        const params = {
            Bucket: bucket,
            Prefix: dir
        };

        const data = await s3.listObjectsV2(params).promise();
        for (const object of data.Contents) {
            const params = {
                Bucket: bucket,
                Key: object.Key
            };

            const fileStream = fs.createWriteStream(path.join(dir, object.Key));
            const s3Stream = s3.getObject(params).createReadStream();

            s3Stream.on('data', (chunk) => {
                progress_callback(chunk.length);
            });

            s3Stream.pipe(fileStream);

            await new Promise((resolve, reject) => {
                fileStream.on('finish', resolve);
                fileStream.on('error', reject);
            });
        }
    }

    async s3_read_dir(dir, bucket, s3_config) {
        const s3 = this.get_session(s3_config);
        const params = {
            Bucket: bucket,
            Prefix: dir
        };

        const data = await s3.listObjectsV2(params).promise();
        const directory = {};

        for (const object of data.Contents) {
            const metadata = {
                "key": object.Key,
                "last_modified": new Date(object.LastModified).getTime() / 1000,
                "size": object.Size,
                "e_tag": object.ETag,
            };

            directory[object.Key] = metadata;
        }

        return directory;
    }

    get_session(s3_config) {
        if (!this.session) {
            this.session = new AWS.S3(this.config_to_boto(s3_config));
        }
        return this.session;
    }

    async s3_download_object(f, bucket, key, s3_config, progress_callback) {
        const s3 = this.get_session(s3_config);
        const params = {
            Bucket: bucket,
            Key: key
        };

        const fileStream = fs.createWriteStream(f);
        const s3Stream = s3.getObject(params).createReadStream();

        s3Stream.on('data', (chunk) => {
            progress_callback(chunk.length);
        });

        s3Stream.pipe(fileStream);

        return new Promise((resolve, reject) => {
            fileStream.on('finish', resolve);
            fileStream.on('error', reject);
        });
    }

    async s3_mkdir(dir, bucket, s3_config) {
        const s3 = this.get_session(s3_config);
        const params = {
            Bucket: bucket,
            Key: dir,
            Body: ''
        };

        return s3.putObject(params).promise();
    }


    config_to_boto(s3_config) {
        let results;

        if (s3_config.accessKey) {
            results = {
                service: 's3',
                accessKeyId: s3_config.accessKey,
                secretAccessKey: s3_config.secretKey,
                endpoint: s3_config.endpoint,
            };
        } else if (s3_config.aws_access_key_id) {
            results = {
                service: 's3',
                accessKeyId: s3_config.aws_access_key_id,
                secretAccessKey: s3_config.aws_secret_access_key,
                endpoint: s3_config.endpoint_url,
            };
        } else {
            throw new Error("s3_config must contain accessKey, secretKey, and endpoint");
        }

        this.config = results;
        return results;
    }

    async test() {
        const endpoint = "https://object.ord1.coreweave.com";
        const access_key = "OVEXCZJJQPUGXZOV";
        const secret_key = "H1osbJRy3903PTMqyOAGD6MIohi4wLXGscnvMEduh10";
        const host_bucket = "%(bucket)s.object.ord1.coreweave.com";
        let bucket = "swissknife-models";
        const dir = "bge-base-en-v1.5@hf";
        let config = {
            "accessKey": access_key,
            "secretKey": secret_key,
            "endpoint": endpoint,
        };
        config = this.config_to_boto(config);
        this.session = this.get_session(config);
        const s3 = new AWS.S3(config);
        const params = {
            Bucket: bucket,
            Prefix: dir
        };

        const data = await s3.listObjectsV2(params).promise();
        const directory = {};

        for (const object of data.Contents) {
            const metadata = {
                "key": object.Key,
                "last_modified": new Date(object.LastModified).getTime() / 1000,
                "size": object.Size,
                "e_tag": object.ETag,
            };

            directory[object.Key] = metadata;
        }

        return directory;
    }

    async test2() {
        const endpoint = "https://object.ord1.coreweave.com";
        const access_key = "OVEXCZJJQPUGXZOV";
        const secret_key = "H1osbJRy3903PTMqyOAGD6MIohi4wLXGscnvMEduh10";
        const host_bucket = "%(bucket)s.object.ord1.coreweave.com";
        let bucket = "cloudkit-beta";
        const keys = [
            'stablelm-zephyr-3b-GGUF-Q2_K@gguf/manifest.json',
            'stablelm-zephyr-3b-GGUF-Q2_K-Q2_K@gguf/README.md',
            'stablelm-zephyr-3b-GGUF-Q2_K-Q2_K@gguf/config.json',
            'stablelm-zephyr-3b-GGUF-Q2_K-Q2_K@gguf/manifest.json',
            'stablelm-zephyr-3b-GGUF-Q2_K-Q2_K@gguf/stablelm-zephyr-3b.Q2_K.gguf'
        ];
        let config = {
            "accessKey": access_key,
            "secretKey": secret_key,
            "endpoint": endpoint,
        };
        config = this.config_to_boto(config);
        this.session = this.get_session(config);

        const results = [];
        for (const key of keys) {
            const result = await this.s3_ls_file(key, bucket, config);
            results.push(result);
        }

        return results[0];
    }

    async test3() {
        const endpoint = "https://object.ord1.coreweave.com";
        const access_key = "OVEXCZJJQPUGXZOV";
        const secret_key = "H1osbJRy3903PTMqyOAGD6MIohi4wLXGscnvMEduh10";
        const host_bucket = "%(bucket)s.object.ord1.coreweave.com";
        let bucket = "cloudkit-beta";
        const key = 'Airoboros-c34B-3.1.2-GGUF-Q4_0-Q4_0@gguf/README.md';
        let config = {
            "accessKey": access_key,
            "secretKey": secret_key,
            "endpoint": endpoint,
        };
        config = this.config_to_boto(config);
        this.session = this.get_session(config);
        const results = await this.s3_ls_file(key, bucket, config);

        return results;
    }
}

// const S3Kit = require('./s3_kit'); // Assuming s3_kit is defined in s3_kit.js

// if (require.main === module) {
//     const test_this = new S3Kit(null);
//     test_this.test2();
//     test_this.test3();
// }
