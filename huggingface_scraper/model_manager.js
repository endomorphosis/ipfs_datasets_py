import fs from 'fs';
import os from 'os';
import path from 'path';
import util from 'util';
import { promisify } from 'util';
import { exec } from 'child_process';
//from './s3_kit.js' import S3Kit;
//import AWS from 'aws-sdk';
//import { S3 } from 'aws-sdk';
//import ipfsClient from 'ipfs-http-client';
import * as test_fio from './test_fio.js';
import * as s3_kit from './s3_kit.js';
import * as ipfs_kit from './ipfs_kit.js';
import * as install_ipfs from './ipfs_kit_lib/install_ipfs.js';
import fsExtra from 'fs-extra';
import crypto from 'crypto';
import rimraf from 'rimraf';
import _ from 'lodash';
import * as temp_file from "./tmp_file.js";

//const s3 = new AWS.S3();
//const ipfs = ipfsClient('http://localhost:5001');
const readFile = util.promisify(fs.readFile);
const writeFile = util.promisify(fs.writeFile);
const stat = util.promisify(fs.stat);
const moveFile = util.promisify(fs.rename);
const rimrafAsync = util.promisify(rimraf);
const tmpFile = new temp_file.TempFileManager()

class ModelManager {
    constructor(resources = null, meta = null) {
        let localPatAnonh
        this.models = {
            "s3_models": [],
            "ipfs_models": [],
            "local_models": [],
            "https_models": []
        };
        this.ls_https_models = this.ls_https_models.bind(this);
        this.ls_ipfs_models = this.ls_ipfs_models.bind(this);
        this.ls_local_models = this.ls_local_models.bind(this);
        this.ls_s3_models = this.ls_s3_models.bind(this);
        this.tmpFile = tmpFile;
        this.ipfsCollection = {};
        this.s3Collection = {};
        this.localCollection = {};
        this.httpsCollection = {};
        this.pinned = [];
        this.fastest = null;
        this.bandwidth = null;
        this.thisModelPath = null;
        this.thisModel = null;
        this.thisModelName = null;
        this.s3cfg = null;
        let username = os.userInfo().username;
        let localPath
        if (username === "root") {
            this.localPath = "/root/";
            localPath = this.localPath;
        } else {
            this.localPath = path.join(os.homeDir(), username);
            localPath = this.localPath;
        }
        if (meta !== null && typeof meta === 'object') {
            this.s3cfg = meta.s3cfg || null;
            this.ipfsSrc = meta.ipfs_src || null;
            this.timing = meta.timing || null;
            this.collectionCache = meta.cache || null;
            this.modelHistory = meta.history || null;
            this.role = meta.role || null;
            this.clusterName = meta.cluster_name || null;
            if (Object.keys(meta).includes("local_path")){
                this.localPath = meta.local_path;
            }
            else {
                this.localpath = path.join(localPath, ".cache/huggingface");
                meta.local_path = path.join(localPath, ".cache/huggingface");
            }
            if (Object.keys(meta).includes("ipfs_path")){
                this.ipfsPath = meta.ipfs_path || path.join(this.localPath  , ".cache/ipfs");
                meta.ipfs_path = meta.ipfs_path || path.join(this.localPath  , ".cache/ipfs");
            }
            else{
                this.ipfsPath = path.join(this.localPath, ".cache/ipfs");
                meta.ipfs_path = path.join(this.localPath, ".cache/ipfs");
            }
            this.ipfsPath = meta.ipfs_path || (this.localPath + "/.cache/ipfs");
            this.s3cfg = meta.s3_cfg || null;
        } 
        else {
            this.localPath = path.join(this.ipfsPath , "cloudkit-models");
            // get the username of the current user and determine if its root
            this.s3cfg = null;
            this.role = "leecher";
            this.clusterName = "cloudkit_storage";
            this.cache = {
                "local": "/storage/cloudkit-models/collection.json",
                "s3": "s3://huggingface-models/collection.json",
                "ipfs": "QmXBUkLywjKGTWNDMgxknk6FJEYu9fZaEepv3djmnEqEqD",
                "https": "https://huggingface.co/endomorphosis/cloudkit-collection/resolve/main/collection.json"
            };
            meta = {
                "local_path": this.localPath || localPath,
                "ipfs_path": this.ipfsPath,
                "s3_cfg": this.s3cfg,
                "role": this.role,
                "cluster_name": this.clusterName,
                "cache": this.cache,
            };
        }

        let homeDir = os.homedir();
        let homeDirFiles = fs.readdirSync(homeDir);
        this.testFio = new test_fio.TestFio();
        this.s3Kit = new s3_kit.S3Kit(resources, meta);
        let installIpfs = new install_ipfs.InstallIPFS(resources, meta);
        this.ipfsKit = new ipfs_kit.IpfsKit(resources, meta);
        this.installIpfs = installIpfs;
        let ipfsPath = this.ipfsPath;
        if (!fs.existsSync(this.ipfsPath)) {
            fs.mkdirSync(this.ipfsPath, { recursive: true });
        }
        if (!fs.existsSync(this.localPath)) {
            fs.mkdirSync(this.localPath, { recursive: true });
        }
        let ipfsPathFiles = fs.readdirSync(ipfsPath);
        if (!ipfsPathFiles.includes('ipfs') || !fs.existsSync(ipfsPath)) {
            this.installIpfs.installIpfsDaemon();
            this.installIpfs.installIpget();
            let stats = this.testFio.stats(this.ipfsPath);
            this.installIpfs.configIpfs({
                diskStats: stats,
                ipfsPath: this.ipfsPath,
            });
        }            
        if (this.role === "master" && !homeDirFiles.includes('.ipfs-cluster-service')) {
            this.installIpfs.installIPFSClusterService();
            this.installIpfs.installIPFSClusterCtl();
            this.installIpfs.configIPFSClusterService();
            this.installIpfs.configIpfsClusterCtl();
        } else if (this.role === "worker" && !homeDirFiles.includes('.ipfs-cluster-follow')) {
            this.installIpfs.installIPFSClusterService();
            this.installIpfs.installIPFSClusterFollow();
            this.installIpfs.configIPFSClusterService();
            this.installIpfs.configIPFSClusterFollow();
        }

        this.ipfsKit.ipfsKitStop();
        this.ipfsKit.ipfsKitStart();
        let executeReady = false;
        while (executeReady != true) {
            try {
                let readyIpfsKit = this.ipfsKit.ipfsKitReady();
                if (Object.keys(readyIpfsKit).every(k => readyIpfsKit[k] === true) || readyIpfsKit === true){
                    executeReady = true
                }
                else{
                    executeReady = false
                }
            } catch (e) {
                executeReady = e.toString();
            }
        }

        this.models = {};
        this.lastUpdate = 0.1;
        this.historyModels = {};
        this.pinnedModels = {};
        this.collection = {};
        this.collectionPins = [];
        this.zombies = {};
        this.expired = {};
        this.notFound = [];
        this.ipfsPinset = {
            "ipfs": {},
            "ipfs_cluster": {},
        };
    }

    async call(method, kwargs) {
        switch (method) {
            case "loadCollection":
                return this.loadCollection(kwargs);
            case "download_model":
                return this.downloadModel(kwargs);
            case "loadCollection_cache":
                return this.loadCollectionCache(kwargs);
            case "auto_download":
                return this.autoDownload(kwargs);
            case "ls_models":
                return this.ls_models(kwargs);
            case "ls_s3_models":
                return this.ls_s3_models(kwargs);
            case "check_local":
                return this.checkLocal(kwargs);
            case "check_https":
                return this.checkHttps(kwargs);
            case "check_s3":
                return this.checkS3(kwargs);
            case "check_ipfs":
                return this.checkIpfs(kwargs);
            case "download_https":
                return this.downloadHttps(kwargs);
            case "download_s3":
                return this.downloadS3(kwargs);
            case "download_ipfs":
                return this.downloadIpfs(kwargs);
            case "test":
                return this.test(kwargs);
            default:
                throw new Error(`Method ${method} not found`);
        }
    }

    async loadCollection(kwargs) {
        try {
            this.httpsCollection = await this.downloadHttps('https://huggingface.co/endomorphosis/cloudkit-collection/resolve/main/collection.json', "/tmp/");
            this.httpsCollection = JSON.parse(fs.readFileSync(this.httpsCollection, 'utf8'));
        } catch (e) {
            this.httpsCollection = e;
        }
    
        try {
            let thisTempFile = await new Promise((resolve, reject) => {
                this.tmpFile.createTempFile({  postfix: '.json', dir: '/tmp' }, (err, path, fd, cleanupCallback) => {
                    if (err) {
                        reject(err);
                    } else {
                        resolve({ name: path, fd, removeCallback: cleanupCallback });
                    }
                });
            });
    
            let results = await this.ipfsKit.ipfsGet(this.ipfsSrc, thisTempFile.name);
            if (results && results.length > 0) {
                this.ipfsCollection = JSON.parse(fs.readFileSync(thisTempFile.name, 'utf8'));
            } else {
                this.ipfsCollection = { "error": "no results" };
            }
        } catch (e) {
            this.ipfsCollection = { "error": e.toString() };
        }
    
        try {
            let thisTempFile = await new Promise((resolve, reject) => {
                tmpFile.createTempFile({  postfix: '.json', dir: '/tmp' }, (err, path, fd, cleanupCallback) => {
                    if (err) {
                        reject(err);
                    } else {
                        resolve({ name: path, fd, removeCallback: cleanupCallback });
                    }
                });
            });
    
            await this.s3Kit.s3DlFile('collection.json', thisTempFile.name, this.s3cfg["bucket"]);
            this.s3Collection = JSON.parse(fs.readFileSync(thisTempFile.name, 'utf8'));
        } catch (e) {
            this.s3Collection = e;
        }
    
        if (fs.existsSync(path.join(this.ipfsPath, "collection.json"))) {
            this.localCollection = JSON.parse(fs.readFileSync(path.join(this.ipfsPath, "collection.json"), 'utf8'));
        }
    
        let ipfsStop, ipfsStart;
        try {
            ipfsStop = await this.ipfsKit.ipfsKitStop();
        } catch (e) {
            ipfsStop = e;
        }
    
        try {
            ipfsStart = await this.ipfsKit.ipfsKitStart();
        } catch (e) {
            ipfsStart = e;
        }
    
        return {
            "ipfs_stop": ipfsStop,
            "ipfs_start": ipfsStart,
            "ipfs_collection": this.ipfsCollection,
            "s3_collection": this.s3Collection,
            "local_collection": this.localCollection,
            "https_collection": this.httpsCollection
        };
    }

    async downloadHttps(httpsSrc, modelPath, kwargs) {
        let suffix = "." + httpsSrc.split("/").pop().split(".").pop();
        let dstPath, filename, dirname;

        if (fs.existsSync(modelPath)) {
            if (fs.lstatSync(modelPath).isDirectory()) {
                filename = httpsSrc.split("/").pop();
                dstPath = path.join(modelPath, filename);
            } else {
                filename = httpsSrc.split("/").pop();
                dirname = path.dirname(modelPath);
                dstPath = path.join(dirname, filename);
            }
        } else {
            dirname = path.dirname(modelPath);
            filename = httpsSrc.split("/").pop();
            if (fs.existsSync(dirname)) {
                dstPath = path.join(dirname, filename);
            } else {
                fs.mkdirSync(dirname, { recursive: true });
                dstPath = path.join(dirname, filename);
            }
        }
        try{
            let thisTempFile = await new Promise((resolve, reject) => {
                this.tmpFile.createTempFile({  postfix: suffix, dir: '/tmp' }, async (err, path, fd, cleanupCallback) => {                    
                    if (err) {
                        console.log(err);
                        reject(err);
                    } else {  
                        let tmpFilename = path.split("/").pop();
                        let command = `aria2c -x 16 ${httpsSrc} -d /tmp -o ${tmpFilename} --allow-overwrite=true`;          
                        await execsync(command).then((results) => {
                            console.log(results)
                            resolve({ name: path, fd, removeCallback: cleanupCallback });
                        }).catch((e) => {
                            console.log(e);
                            reject(e);
                        });
                    }   
                });
            });
        }
        catch(e){
            console.log(e);
        }


        if (fs.existsSync(dstPath)) {
            let command2 = `rm ${dstPath}`;
            await exec(command2);
        }

        if (!dstPath.includes("collection.json") && !dstPath.includes("README.md")) {
            let command3 = `mv /tmp/${tmpFilename} ${dstPath}`;
            await exec(command3);

            if (fs.existsSync(thisTempFile.name)) {
                let command4 = `rm /tmp/${tmpFilename}`;
                await exec(command4);
            }
        } else {
            let command3 = `cp /tmp/${tmpFilename} ${dstPath}`;
            await exec(command3);

            if (fs.existsSync(thisTempFile.name)) {
                let command4 = `rm /tmp/${tmpFilename}`;
                await exec(command4);
            }
        }

        return dstPath;
    }

    async downloadS3(s3Src, filenameDst, kwargs) {
        if (filenameDst.split(".").length > 1) {
            try {
                let suffix = "." + filenameDst.split(".").pop();
                let thisTempFile = await new Promise((resolve, reject) => {
                    tmpFile.createTempFile({  postfix: suffix, dir: '/tmp' }, (err, path, fd, cleanupCallback) => {
                        if (err) {
                            reject(err);
                        } else {
                            resolve({ name: path, fd, removeCallback: cleanupCallback });
                        }
                    });
                });
    
                let thisFileKey = s3Src.split(s3cfg["bucket"] + "/")[1];

                let params = {
                    Bucket: s3cfg["bucket"],
                    Key: thisFileKey
                };

                let file = fs.createWriteStream(thisTempFile.name);
                let stream = s3.getObject(params).createReadStream().pipe(file);

                await new Promise((resolve, reject) => {
                    stream.on('finish', resolve);
                    stream.on('error', reject);
                });

                let results = fs.existsSync(thisTempFile.name);
                if (results) {
                    fs.renameSync(thisTempFile.name, filenameDst);

                    if (fs.existsSync(thisTempFile.name)) {
                        fs.unlinkSync(thisTempFile.name);
                    }

                    return filenameDst;
                } else {
                    return false;
                }
            } catch (e) {
                if (fs.existsSync(thisTempFile.name)) {
                    fs.unlinkSync(thisTempFile.name);
                }
                return e;
            }
        } else {
            throw new Error("Invalid filenameDst, no `.` suffix found");
        }
    }

    async downloadIpfs(ipfsSrc, filenameDst, kwargs) {
        if (filenameDst.split(".").length > 1) {
            try {
                if (!filenameDst.includes(".cache") && filenameDst.includes(".")) {
                    let suffix = "." + filenameDst.split(".").pop();
                    let thisTempFile = await new Promise((resolve, reject) => {
                        tmpFile.createTempFile({  postfix: suffix, dir: '/tmp' }, (err, path, fd, cleanupCallback) => {
                            if (err) {
                                reject(err);
                            } else {
                                resolve({ name: path, fd, removeCallback: cleanupCallback });
                            }
                        });
                    });
        
                    let results = await ipfs.get(ipfsSrc, { timeout: 10000 });
                    if (results.path) {
                        fs.renameSync(results.path, filenameDst);

                        if (fs.existsSync(thisTempFile.name)) {
                            fs.unlinkSync(thisTempFile.name);
                        }

                        return filenameDst;
                    } else {
                        throw new Error("No path in results or timeout");
                    }
                } else {
                    let tempDir = tmp.dirSync({ dir: '/tmp' });
                    let results = await ipfs.get(ipfsSrc, { timeout: 10000 });

                    if (results.path) {
                        fs.renameSync(results.path, filenameDst);
                        return filenameDst;
                    }
                }
            } catch (e) {
                console.log("Exception thrown remove files");
                if (fs.existsSync(thisTempFile.name)) {
                    fs.unlinkSync(thisTempFile.name);
                }
                return e;
            }
        } else {
            // throw new Error("Invalid filenameDst, no `.` suffix found");
        }
    }


    async downloadModel(model, kwargs) {
        let ipfsTimestamp = null;
        let s3Timestamp = null;
        let localTimestamp = null;
        let httpsTimestamp = null;

        if (typeof this.ipfsCollection === 'object' && this.ipfsCollection.hasOwnProperty('cache')) {
            if (this.ipfsCollection.cache.hasOwnProperty('timestamp')) {
                ipfsTimestamp = this.ipfsCollection.cache.timestamp;
            }
            if (ipfsTimestamp === null) {
                ipfsTimestamp = Date.now();
            }
        }

        // Assuming s3_kit.s3_ls_file is an async function
        if (typeof this.s3Collection === 'object' && this.s3Collection.hasOwnProperty('cache')) {
            if (this.s3Collection.cache.hasOwnProperty('timestamp')) {
                s3Timestamp = this.s3Collection.cache.timestamp;
            }
            if (s3Timestamp === null) {
                let s3File = path.basename(this.collectionCache.s3);
                let s3Dir = path.dirname(this.collectionCache.s3);
                s3Timestamp = await this.s3_kit.s3_ls_file(s3File, s3Dir);
                let key = Object.keys(s3Timestamp)[0];
                s3Timestamp = s3Timestamp[key].last_modified;
            }
        }

        if (typeof this.localCollection === 'object' && this.localCollection.hasOwnProperty('cache')) {
            if (this.localCollection.cache.hasOwnProperty('timestamp')) {
                localTimestamp = this.localCollection.cache.timestamp;
            }
            if (localTimestamp === null) {
                localTimestamp = fs.statSync(this.collectionCache.local).mtimeMs;
            }
        }

        if (typeof this.httpsCollection === 'object' && this.httpsCollection.hasOwnProperty('cache')) {
            if (this.httpsCollection.cache.hasOwnProperty('timestamp')) {
                httpsTimestamp = this.httpsCollection.cache.timestamp;
            }
            if (httpsTimestamp === null) {
                httpsTimestamp = Date.now();
            }
        }

        let timestamps = {
            ipfs: ipfsTimestamp,
            s3: s3Timestamp,
            local: localTimestamp,
            https: httpsTimestamp
        };

        if (!Object.values(timestamps).every(v => v === null)) {
            timestamps = Object.fromEntries(Object.entries(timestamps).filter(([k, v]) => v !== null));
            let newest = Object.keys(timestamps).reduce((a, b) => timestamps[a] > timestamps[b] ? a : b);
        } else {
            throw new Error("No collection cache found");
        }

        let ipfsModelData = null;
        let s3ModelData = null;
        let localModelData = null;
        let httpsModelData = null;

        if (typeof this.ipfsCollection === 'object' && this.ipfsCollection.hasOwnProperty(model)) {
            ipfsModelData = this.ipfsCollection[model];
        }
        if (typeof this.s3Collection === 'object' && this.s3Collection.hasOwnProperty(model)) {
            s3ModelData = this.s3Collection[model];
        }
        if (typeof this.localCollection === 'object' && this.localCollection.hasOwnProperty(model)) {
            localModelData = this.localCollection[model];
        }
        if (typeof this.httpsCollection === 'object' && this.httpsCollection.hasOwnProperty(model)) {
            httpsModelData = this.httpsCollection[model];
        }

        let modelData = {
            ipfs: ipfsModelData,
            s3: s3ModelData,
            local: localModelData,
            https: httpsModelData
        };

        if (Object.values(modelData).every(v => v === null)) {
            throw new Error("Model not found");
        }

        let thisModel = null;

        if (modelData[newest] !== null) {
            if (modelData[newest].hwRequirements.diskUsage > os.freemem()) {
                throw new Error("Not enough disk space to download model");
            } else {
                thisModel = await this.autoDownload(modelData[newest], kwargs);
            }
        } else {
            while (thisModel === null && Object.keys(timestamps).length > 0) {
                delete timestamps[newest];
                newest = Object.keys(timestamps).reduce((a, b) => timestamps[a] > timestamps[b] ? a : b);
            }

            if (modelData[newest] !== null) {
                if (modelData[newest].hwRequirements.diskUsage > os.freemem()) {
                    throw new Error("Not enough disk space to download model");
                } else {
                    thisModel = await this.autoDownload(modelData[newest], kwargs);
                }
            }

            if (thisModel === null) {
                throw new Error("Model not found");
            }
            this.models.local_models[thisModel.id] = Date.now();
        }
        return thisModel;
    }

    async checkLocal(manifest, kwargs) {
        let folderData = manifest["folderData"];
        let cache = manifest["cache"];
        let local = cache["local"];
        let checkFilenames = {};
        let localFiles = Object.keys(local);
        let localPath = this.localPath + "/" + manifest["id"] + "/";
        for (let localFile of localFiles) {
            let thisFile = local[localFile];
            // remove the first character if it is a "/"
            let thisFileUrl = thisFile["url"];
            let thisFilePath = thisFile["path"];
            let thisLocalFile;
            if (thisFilePath[0] == "/") {
                thisLocalFile = thisFilePath.slice(1);
            } else {
                thisLocalFile = thisFilePath;
            }
            thisFilePath = path.join(localPath, thisLocalFile);
            if (fs.existsSync(thisFilePath)) {
                let thisFileMtime = fs.statSync(thisFilePath).mtimeMs;
                checkFilenames[localFile] = thisFileMtime;
            } else {
                checkFilenames[localFile] = false;
            }
        }

        checkFilenames["/manifest.json"] = true;
        if (Object.values(checkFilenames).every(Boolean)) {
            delete checkFilenames["/manifest.json"];
            let oldestFileTimestamp = Math.min(...Object.values(checkFilenames));
            return oldestFileTimestamp;
        } else {
            return false;
        }
    }


    async checkHttps(manifest, kwargs) {
        let folderData = manifest["folderData"];
        let cache = manifest["cache"];
        let https = cache["https"];
        let httpsFiles = Object.keys(https);
        let checkFilenames = {};
        for (let httpsFile of httpsFiles) {
            let thisHttpsFile = https[httpsFile];
            if ("url" in thisHttpsFile && httpsFile != "/manifest.json") {
                let thisHttpsUrl = thisHttpsFile["url"];
                try {
                    let results = await axios.head(thisHttpsUrl);
                    if (results.status === 200 || results.status === 302) {
                        checkFilenames[httpsFile] = Date.now();
                    } else {
                        checkFilenames[httpsFile] = false;
                    }
                } catch (e) {
                    checkFilenames[httpsFile] = false;
                }
            } else {
                checkFilenames[httpsFile] = false;
            }
        }

        checkFilenames["/manifest.json"] = true;
        if (Object.values(checkFilenames).every(Boolean)) {
            return Date.now();
        } else {
            return false;
        }
    }

    async checkS3(manifest, kwargs) {
        let folderData = manifest["folderData"];
        let files = Object.keys(folderData);
        let cache = manifest["cache"];
        let s3Cache = cache["s3"];
        let s3Files = Object.keys(s3Cache);
        let checkFilenames = {};
        if (s3Files !== null) {
            for (let s3File of s3Files) {
                let thisS3Cache = s3Cache[s3File];
                let thisS3Path = thisS3Cache["path"];
                let thisS3Url = thisS3Cache["url"];
                let thisS3Split, thisS3Bucket, thisS3Key;
                if (thisS3Url.includes("s3://")) {
                    thisS3Split = thisS3Url.split("/");
                    thisS3Bucket = thisS3Split[2];
                    thisS3Key = thisS3Split.slice(3).join("/");
                } else if (thisS3Url[0] === "/") {
                    thisS3Split = thisS3Path.split("/");
                    thisS3Bucket = thisS3Split[2];
                    thisS3Key = thisS3Split.slice(3).join("/");
                }

                try {
                    let results = await this.s3Kit.s3LsFile(thisS3Key, thisS3Bucket);
                    if (results !== null && results !== false && Object.keys(results).length > 0) {
                        let filename = Object.keys(results)[0];
                        let fileMetadata = results[filename];
                        let mtime = new Date(fileMetadata["LastModified"]).getTime();
                        checkFilenames[s3File] = mtime;
                    } else {
                        checkFilenames[s3File] = false;
                    }
                } catch (e) {
                    checkFilenames[s3File] = e;
                }
            }
        }

        checkFilenames["/manifest.json"] = true;
        if (Object.values(checkFilenames).every(Boolean)) {
            delete checkFilenames["/manifest.json"];
            let oldestFileTimestamp = Math.min(...Object.values(checkFilenames));
            return oldestFileTimestamp;
        } else {
            return false;
        }
    }


    async checkIpfs(manifest, kwargs) {
        let folderData = manifest["folderData"];
        let cache = manifest["cache"];
        let ipfsCache = cache["ipfs"];
        let ipfsFiles = Object.keys(ipfsCache);
        let checkFilenames = {};
        let ipfsPinset = Object.keys(this.ipfsPinset["ipfs"]);
        for (let ipfsFile of ipfsFiles) {
            let thisIpfsCache = ipfsCache[ipfsFile];
            if ("path" in thisIpfsCache && ipfsFile != "/manifest.json") {
                let thisIpfsCid = thisIpfsCache["path"];
                try {
                    if (ipfsPinset.includes(thisIpfsCid)) {
                        checkFilenames[ipfsFile] = Date.now();
                    } else {
                        checkFilenames[ipfsFile] = false;
                    }
                } catch (e) {
                    checkFilenames[ipfsFile] = false;
                }
            } else {
                checkFilenames[ipfsFile] = false;
            }
        }

        checkFilenames["/manifest.json"] = true;
        if (Object.values(checkFilenames).every(Boolean)) {
            return Date.now();
        } else {
            return false;
        }
    }

    async loadCollectionCache(cache = {
        local: "/storage/cloudkit-models/collection.json",
        s3: "s3://cloudkit-beta/collection.json",
        ipfs: "QmXBUkLywjKGTWNDMgxknk6FJEYu9fZaEepv3djmnEqEqD",
        https: "https://huggingface.co/endomorphosis/cloudkit-collection/resolve/main/collection.json"
    }){
        let timestamp_0 = Date.now();
        if (fs.existsSync(cache.local)) {
            let data = await readFile(cache.local);
            this.local_collection = JSON.parse(data);
        }
        try {
            let https_collection = await this.downloadHttps(cache.https, '/tmp/collection.json');
            // if (fs.existsSync("./collection.json/collection.json")) {
            //     await moveFile("./collection.json/collection.json", "/tmp/collection.json");
            //     await rimraf("./collection.json");
            // }
            if (fs.existsSync(https_collection)) {
                let data = await fs.readFileSync(cache.https, 'utf8');
                this.https_collection = JSON.parse(data);
            } else if (fs.existsSync('/tmp/collection.json')) {
                let data = await readFile('/tmp/collection.json');
                this.https_collection = JSON.parse(data);
            }
        } catch (e) {
            console.log(e);
        }
        let timestamp_1 = Date.now();
        try {
            let ipfs_download = await this.downloadIpfs(cache.ipfs, '/tmp/collection.json');
            let data = await readFile(ipfs_download);
            this.ipfs_collection = JSON.parse(data);
        } catch (e) {
            console.log(e);
        }
        let timestamp_2 = Date.now();
        try {
            let s3_download = await this.downloadS3(cache.s3, '/tmp/collection.json');
//            let s3_download = await this.download_s3(cache.s3, '/tmp/collection.json');
            let data = await readFile(s3_download);
            this.s3_collection = JSON.parse(data);
        } catch (e) {
            console.log(e);
        }
        let timestamp_3 = Date.now();

        let timestamps = {
            https: timestamp_1 - timestamp_0,
            ipfs: timestamp_2 - timestamp_1,
            s3: timestamp_3 - timestamp_2
        };

        let fastest = Object.keys(timestamps).reduce((a, b) => timestamps[a] < timestamps[b] ? a : b);
        this.fastest = fastest;
        let file_size = (await stat('/tmp/collection.json')).size;
        this.bandwidth = file_size / timestamps[fastest];

        let md5_local = crypto.createHash('md5').update(JSON.stringify(this.local_collection)).digest("hex");
        let md5_ipfs = crypto.createHash('md5').update(JSON.stringify(this.ipfs_collection)).digest("hex");
        let md5_s3 = crypto.createHash('md5').update(JSON.stringify(this.s3_collection)).digest("hex");
        let md5_https = crypto.createHash('md5').update(JSON.stringify(this.https_collection)).digest("hex");


        if (md5_local === md5_ipfs && md5_local === md5_s3 && md5_local === md5_https) {
            if (fastest === "ipfs" && Object.keys(this.ipfs_collection).length > 0) {
                this.collection = this.ipfs_collection;
            } else if (fastest === "s3" && Object.keys(this.s3_collection).length > 0) {
                this.collection = this.s3_collection;
            } else if (fastest === "https" && Object.keys(this.https_collection).length > 0) {
                this.collection = this.https_collection;
            } else if (fastest === "local" && Object.keys(this.local_collection).length > 0) {
                this.collection = this.local_collection;
            } else if (Object.keys(this.local_collection).length > 0) {
                this.collection = this.local_collection;
            } else {
                throw new Error("No collection found");
            }
        }

        let local_collection_cache = this.local_collection.cache || {};
        let ipfs_collection_cache = this.ipfs_collection.cache || {};
        let s3_collection_cache = this.s3_collection.cache || {};
        let https_collection_cache = this.https_collection.cache || {};

        let modified = {};
        if (local_collection_cache.timestamp) {
            modified.local = local_collection_cache.timestamp;
        }
        if (ipfs_collection_cache.timestamp) {
            modified.ipfs = ipfs_collection_cache.timestamp;
        }
        if (s3_collection_cache.timestamp) {
            modified.s3 = s3_collection_cache.timestamp;
        }
        if (https_collection_cache.timestamp) {
            modified.https = https_collection_cache.timestamp;
        }

        if (Object.keys(modified).length > 0) {
            let newest = Object.keys(modified).reduce((a, b) => modified[a] > modified[b] ? a : b);
            this.collection = this[newest + "_collection"];
        } else {
            let sizes = {
                local: JSON.stringify(this.local_collection).length,
                ipfs: JSON.stringify(this.ipfs_collection).length,
                s3: JSON.stringify(this.s3_collection).length,
                https: JSON.stringify(this.https_collection).length
            };
            let largest = Object.keys(sizes).reduce((a, b) => sizes[a] > sizes[b] ? a : b);
            this.collection = this[largest + "_collection"];
        }

        if (fs.existsSync(cache.local)) {
            let data = await readFile(cache.local);
            this.local_collection = JSON.parse(data);
        }

        return this.collection;
    }


    async auto_download(manifest, kwargs) {
        let ls_models = this.ls_models();
        let this_model_manifest = manifest;
        this.history_models[this_model_manifest["id"]] = Date.now();
        let this_model_manifest_cache = this_model_manifest["cache"];
        let this_model_manifest_folder_data = this_model_manifest["folderData"];
        let s3_test = false;
        let ipfs_test = false;
        let https_test = false;
        let local_test = false;

        // Local test
        try {
            if (fs.existsSync(this_model_manifest_cache["local"]["/README.md"]["path"])) {
                local_test = true;
                let basename = path.basename(this_model_manifest_cache["local"]["/README.md"]["path"]);
                for (let file of this_model_manifest_folder_data) {
                    if (!fs.existsSync(path.join(basename, file))) {
                        local_test = false;
                        break;
                    }
                }
            }
        } catch (e) {
            local_test = false;
        }

        let timestamp_0 = Date.now();

        // IPFS test
        try {
            ipfs_test = false;
            let thisTempFile = await new Promise((resolve, reject) => {
                tmpFile.createTempFile({ postfix: '.md' , dir: '/tmp' }, (err, path, fd, cleanupCallback) => {
                    if (err) {
                        reject(err);
                    } else {
                        resolve({ name: path, fd, removeCallback: cleanupCallback });
                    }
                });
            });

            if ("/README.md" in Object.keys(this_model_manifest_cache["ipfs"])) {
                let ipfs_test_file = await this.download_ipfs(this_model_manifest_cache["ipfs"]["/README.md"]["path"], this_temp_file.name);
                let ipfs_test = fs.readFileSync(ipfs_test_file, 'utf8');
                ipfs_test = ipfs_test.length > 0;
            }
        } catch (e) {
            ipfs_test = e;
        }

        let timestamp_1 = Date.now();

        // S3 test
        try {
            let thisTempFile = await new Promise((resolve, reject) => {
                tmp.createTempFile({ postfix: '.md' , dir: '/tmp' }, (err, path, fd, cleanupCallback) => {
                    if (err) {
                        reject(err);
                    } else {
                        resolve({ name: path, fd, removeCallback: cleanupCallback });
                    }
                });
            });
            if ("/README.md" in Object.keys(this_model_manifest_cache["s3"])) {
                let s3_test;
                if (this_model_manifest_cache["s3"]["/README.md"]["url"].startsWith("s3://")) {
                    s3_test = await this.download_s3(this_model_manifest_cache["s3"]["/README.md"]["url"], this_temp_file.name);
                } else {
                    s3_test = await this.download_s3(this_model_manifest_cache["s3"]["/README.md"]["path"], this_temp_file.name);
                }
                s3_test = s3_test.toString();
                if (!s3_test.includes("error")) {
                    let s3_test = fs.readFileSync(this_temp_file.name, 'utf8');
                    s3_test = s3_test.length > 0;
                } else {
                    s3_test = false;
                }
            }
        } catch (e) {
            s3_test = e;
        }

        let timestamp_2 = Date.now();

        // HTTPS test
        try {
            let thisTempFile = await new Promise((resolve, reject) => {
                tmpFile.createTempFile({ postfix: '.md' , dir: '/tmp' }, (err, path, fd, cleanupCallback) => {
                    if (err) {
                        reject(err);
                    } else {
                        resolve({ name: path, fd, removeCallback: cleanupCallback });
                    }
                });
            });
            if ("/README.md" in Object.keys(this_model_manifest_cache["https"])) {
                let https_url = this_model_manifest_cache["https"]["/README.md"]["url"];
                let https_test_file = await this.download_https(https_url, this_temp_file.name);
                let https_test = fs.readFileSync(https_test_file, 'utf8');
                https_test = https_test.length > 0;
            }
        } catch (e) {
            https_test = e;
        }

        let timestamp_3 = Date.now();

        let timestamps = {
            "ipfs": timestamp_1 - timestamp_0,
            "s3": timestamp_2 - timestamp_1,
            "https": timestamp_3 - timestamp_2,
            "local": 0
        };

        let test = {
            "ipfs": ipfs_test,
            "s3": s3_test,
            "https": https_test,
            "local": local_test
        };

        let download_src = null;
        let fastest = Object.keys(timestamps).reduce((a, b) => timestamps[a] < timestamps[b] ? a : b);

        while (test[fastest] === false || test[fastest] !== true) {
            delete timestamps[fastest];
            fastest = Object.keys(timestamps).reduce((a, b) => timestamps[a] < timestamps[b] ? a : b);
        }

        if (test[fastest] === true) {
            download_src = fastest;
        } else {
            download_src = null;
        }


        if (download_src === null) {
            throw new Error("Model not found");
        } else {
            let file_list = Object.keys(this_model_manifest_folder_data);
            let file_success = {};
            for (let file of file_list) {
                if (!file.startsWith("/")) {
                    file = "/" + file;
                }
                let suffix = null;
                if (file.includes(".")) {
                    suffix = "." + file.split(".").pop();
                } else {
                    fs.mkdirSync("/tmp/"+file, { recursive: true });
                }
                let this_download_src = download_src;
                let this_file_size = this_model_manifest_folder_data[file]["size"];
                let this_file_md5 = this_model_manifest_folder_data[file].hasOwnProperty("md5") ? this_model_manifest_folder_data[file]["md5"] : null;
                let this_tmp_file = "/tmp/" + file.split("/").slice(1).join("/");
                let this_local_file = this.local_path + "/" + this_model_manifest["id"] + this_model_manifest_cache["local"][file]["path"].slice(1);
                let this_local_file_size = null;
                let this_local_file_md5 = null;
                if (fs.existsSync(this_local_file)) {
                    this_local_file_size = fs.statSync(this_local_file).size;
                    this_local_file_md5 = child_process.execSync("md5sum " + this_local_file).toString().split(" ")[0];
                }
                if ((file === "/README.md" || file === "/manifest.json") || (this_file_size === this_local_file_size || this_file_size === null) && (this_file_md5 === this_local_file_md5 || this_file_md5 === null)) {
                    file_success[file] = true;
                } else {
                    // Implement the download_ipfs, download_s3, and download_https methods here
                }
            }
            if (Object.values(file_success).every(value => value === true)) {
                if (!fs.existsSync(this.local_path + "/" + this_model_manifest["id"])) {
                    fs.mkdirSync(this.local_path + "/" + this_model_manifest["id"], { recursive: true });
                }
                for (let file of file_list) {
                    if (file.startsWith("/")) {
                        file = file.slice(1);
                    }
                    let src_path = "/tmp/" + file;
                    let dst_path = this.local_path + "/" + this_model_manifest["id"] + "/" + file;
                    if (!fs.existsSync(dst_path) && fs.existsSync(src_path)) {
                        if (fs.lstatSync(src_path).isDirectory()) {
                            fs.mkdirSync(dst_path, { recursive: true });
                            child_process.execSync("cp -r " + src_path + "/* " + dst_path);
                            child_process.execSync("rm -r " + src_path);
                        } else {
                            fs.renameSync(src_path, dst_path);
                        }
                    }
                }
                return this_model_manifest;
            } else {
                throw new Error("Model not found");
            }
        }
    }

    async ls_models() {
        let ipfs_keys = [];
        let s3_keys = [];
        let local_keys = [];
        let https_keys = [];
        if (this.ipfs_collection !== null && _.isObject(this.s3_collection)) {
            ipfs_keys = Object.keys(this.ipfs_collection);
        }
        if (this.s3_collection !== null && _.isObject(this.s3_collection)) {
            s3_keys = Object.keys(this.s3_collection);
        }
        if (this.local_collection !== null && _.isObject(this.s3_collection)) {
            local_keys = Object.keys(this.local_collection);
        }
        if (this.https_collection !== null && _.isObject(this.s3_collection)) {
            https_keys = Object.keys(this.https_collection);
        }
        let all_keys = _.union(ipfs_keys, s3_keys, local_keys, https_keys);
        all_keys = _.without(all_keys, "cache", "error");
        return all_keys;
    }


    async ls_s3_models() {
        let ls_models = this.ls_models();
        let s3_models = {};
        let timestamps = {};
        let this_collection;
        let collections = {
            'ipfs': this.ipfs_collection,
            's3': this.s3_collection,
            'local': this.local_collection,
            'https': this.https_collection
        };

        for (let key in collections) {
            if (_.isObject(collections[key]) && collections[key].hasOwnProperty('cache') && collections[key]['cache'].hasOwnProperty('timestamp')) {
                timestamps[key] = collections[key]['cache']['timestamp'];
            }
        }

        if (Object.keys(timestamps).length !== 0) {
            let newest = Object.keys(timestamps).reduce((a, b) => timestamps[a] > timestamps[b] ? a : b);
            this_collection = collections[newest];
        } else {
            for (let key in collections) {
                if (Object.keys(collections).includes(key) && collections[key] != undefined && !collections[key].hasOwnProperty('error')) {
                    this_collection = collections[key];
                    for (let model of ls_models) {
                        if (this_collection.hasOwnProperty(model) && model !== "cache" && model !== "error") {
                            let results = this.checkS3(this_collection[model]);
                            if (results !== null && results !== false) {
                                s3_models[model] = results;
                            }
                        }
                    }            
                    break;
                }
            }
        }

        this.s3_models = s3_models;
        return s3_models;
    }

    async ls_local_models(kwargs) {
        let lsModels = this.ls_models();
        let localModels = {};
        let timestamps = {};
    
        if (typeof this.ipfsCollection === 'object' && 'cache' in this.ipfsCollection) {
            if ('timestamp' in this.ipfsCollection.cache) {
                let ipfsTimestamp = this.ipfsCollection.cache.timestamp;
                timestamps.ipfs = ipfsTimestamp;
            }
        }
        if (typeof this.s3Collection === 'object' && 'cache' in this.s3Collection) {
            if ('timestamp' in this.s3Collection.cache) {
                let s3Timestamp = this.s3Collection.cache.timestamp;
                timestamps.s3 = s3Timestamp;
            }
        }
        if (typeof this.localCollection === 'object' && 'cache' in this.localCollection) {
            if ('timestamp' in this.localCollection.cache) {
                let localTimestamp = this.localCollection.cache.timestamp;
                timestamps.local = localTimestamp;
            }
        }
        if (typeof this.httpsCollection === 'object' && 'cache' in this.httpsCollection) {
            if ('timestamp' in this.httpsCollection.cache) {
                let httpsTimestamp = this.httpsCollection.cache.timestamp;
                timestamps.https = httpsTimestamp;
            }
        }
    
        let thisCollection;
        if (Object.keys(timestamps).length !== 0) {
            let newest = Object.keys(timestamps).reduce((a, b) => timestamps[a] > timestamps[b] ? a : b);
            if (newest === 'local') {
                thisCollection = this.localCollection;
            } else if (newest === 's3') {
                thisCollection = this.s3Collection;
            } else if (newest === 'ipfs') {
                thisCollection = this.ipfsCollection;
            } else if (newest === 'https') {
                thisCollection = this.httpsCollection;
            }
        } else {
            if (!('error' in this.localCollection)) {
                thisCollection = this.localCollection;
            } else if (!('error' in this.s3Collection)) {
                thisCollection = this.s3Collection;
            } else if (!('error' in this.httpsCollection)) {
                thisCollection = this.httpsCollection;
            } else if (!('error' in this.ipfsCollection)) {
                thisCollection = this.ipfsCollection;
            }
        }
    
        for (let model of lsModels) {
            let collections = [thisCollection, this.localCollection, this.s3Collection, this.ipfsCollection, this.httpsCollection];
            for (let collection of collections) {
                if (model in collection && model !== 'cache' && model !== 'error') {
                    let thisFolderData = collection[model].folderData;
                    let results = this.checkLocal(collection[model]);
                    if (results !== null && results !== false) {
                        localModels[model] = results;
                    }
                }
            }
        }
    
        this.localModels = localModels;
        return localModels;
    }

    async ls_https_models() {
        let ls_models = this.ls_models();
        let https_models = {};
        let timestamps = {};
        let this_collection;
        let collections = {
            'ipfs': this.ipfs_collection,
            's3': this.s3_collection,
            'local': this.local_collection,
            'https': this.https_collection
        };

        for (let key in collections) {
            if (_.isObject(collections[key]) && collections[key].hasOwnProperty('cache') && collections[key]['cache'].hasOwnProperty('timestamp')) {
                timestamps[key] = collections[key]['cache']['timestamp'];
            }
        }

        if (Object.keys(timestamps).length !== 0) {
            let newest = Object.keys(timestamps).reduce((a, b) => timestamps[a] > timestamps[b] ? a : b);
            this_collection = collections[newest];
        } else {
            for (let key in collections) {
                if (Object.keys(collections).includes(key) && collections[key] != undefined && !collections[key].hasOwnProperty('error')) {
                    this_collection = collections[key];
                    break;
                }
            }
        }

        for (let model of ls_models) {
            if (this_collection.hasOwnProperty(model) && model !== "cache" && model !== "error") {
                let results = this.check_https(this_collection[model]);
                if (results !== null && results !== false) {
                    https_models[model] = results;
                }
            } else {
                for (let key in collections) {
                    if (Object.keys(collections).includes(key) && collections[key] != undefined && !collections[key].hasOwnProperty('error')) {
                        this_collection = collections[key];
                        for (let model of ls_models) {
                            if (this_collection.hasOwnProperty(model) && model !== "cache" && model !== "error") {
                                let results = this.checkS3(this_collection[model]);
                                if (results !== null && results !== false) {
                                    s3_models[model] = results;
                                }
                            }
                        }            
                        break;
                    }
                }
            }
        }

        this.https_models = https_models;
        return https_models;
    }


    async ls_ipfs_models() {
        let ls_models = await this.ls_models();
        let ipfs_models = {};
        let timestamps = {};
        let this_collection;
        let collections = {
            'ipfs': this.ipfs_collection,
            's3': this.s3_collection,
            'local': this.local_collection,
            'https': this.https_collection
        };

        for (let key in collections) {
            if (_.isObject(collections[key]) && collections[key].hasOwnProperty('cache') && collections[key]['cache'].hasOwnProperty('timestamp')) {
                timestamps[key] = collections[key]['cache']['timestamp'];
            }
        }

        if (Object.keys(timestamps).length !== 0) {
            let newest = Object.keys(timestamps).reduce((a, b) => timestamps[a] > timestamps[b] ? a : b);
            this_collection = collections[newest];
        } else {
            for (let key in collections) {
                if (Object.keys(collections).includes(key) && collections[key] != undefined && !collections[key].hasOwnProperty('error')) {
                    this_collection = collections[key];
                    for (let model of ls_models) {
                        if (this_collection.hasOwnProperty(model) && model !== "cache" && model !== "error") {
                            let results = this.checkIpfs(this_collection[model]);
                            if (results !== null && results !== false) {
                                s3_models[model] = results;
                            }
                        }
                    }            
                    break;        
                }
            }
        }

        for (let model of ls_models) {
            if (this_collection.hasOwnProperty(model) && model !== "cache" && model !== "error") {
                let results = this.check_ipfs(this_collection[model]);
                if (results !== null && results !== false) {
                    ipfs_models[model] = results;
                }
            } else {
                for (let key in collections) {
                    if (collections[key].hasOwnProperty(model) && model !== "cache" && model !== "error") {
                        let results = this.check_ipfs(collections[key][model]);
                        if (results !== null && results !== false) {
                            ipfs_models[model] = results;
                        }
                        break;
                    }
                }
            }
        }

        this.ipfs_models = ipfs_models;
        return ipfs_models;
    }

    async state(kwargs = {}) {
        const timestamp = Date.now() / 1000;
        const one_hour_ago = timestamp - 3600;
        const one_day_ago = timestamp - 86400;
        const ten_days_ago = timestamp - 8640000;

        try {
            if (fs.existsSync(path.join(this.ipfsPath, "state.json"))) {
                const state_mtime = fs.statSync(path.join(this.ipfsPath, "state.json")).mtime.getTime() / 1000;
                if (state_mtime > one_day_ago) {
                    this.last_update = state_mtime;
                    this.models = JSON.parse(fs.readFileSync(path.join(this.ipfsPath, "state.json"), 'utf8'));
                    this.last_update = timestamp;
                }
            } else {
                execSync(`touch ${path.join(this.ipfsPath, "state.json")}`);
            }
        } catch (e) {
            this.models = {};
        }
        let src = kwargs.hasOwnProperty("src") ? kwargs["src"] : "all";

        if (src !== "all") {
            if (src === "s3") {
                this.models["s3_models"] = this.ls_s3_models();
            } else if (src === "ipfs") {
                this.ipfs_pinset = this.ipfsKit.ipfsGetPinset();
                this.models["ipfs_models"] = this.ls_ipfs_models();
            } else if (src === "local") {
                this.models["local_models"] = this.ls_local_models();
            } else if (src === "https") {
                this.models["https_models"] = this.ls_https_models();
            }
        } else {
            if (this.last_update < ten_days_ago) {
                this.loadCollection();
                this.models["s3_models"] = this.ls_s3_models();
                this.models["ipfs_models"] = this.ls_ipfs_models();
                this.models["local_models"] = this.ls_local_models();
                this.models["https_models"] = this.ls_https_models();
                this.ipfs_pinset = this.ipfsKit.ipfsGetPinset();
                this.last_update = timestamp;
            }
        }
        
        if (this.models.hasOwnProperty("s3Models")) {
            this.models["s3_models"] = this.models["s3Models"];
            delete this.models["s3Models"];
        }
        if (this.models.hasOwnProperty("ipfsModels")) {
            this.models["ipfs_models"] = this.models["ipfsModels"];
            delete this.models["ipfsModels"];
        }
        if (this.models.hasOwnProperty("httpsModels")) {
            this.models["https_models"] = this.models["httpsModels"];
            delete this.models["httpsModels"];
        }
        if (this.models.hasOwnProperty("localModels")) {
            this.models["local_models"] = this.models["localModels"];
            delete this.models["localModels"];
        }
        
        for (let model in this.collection) {
            if (model !== "cache") {
                let this_model = this.collection[model];
                let cache = this_model["cache"];
                if (cache.hasOwnProperty("ipfs")) {
                    let ipfs = cache["ipfs"];
                    for (let file in ipfs) {
                        let this_file = ipfs[file];
                        if (this_file.hasOwnProperty("path")) {
                            let path = this_file["path"];
                            if (!this.collection_pins.includes(path)) {
                                if (this.ipfs_pinset["ipfs"].hasOwnProperty(path)) {
                                    let pin_type = this.ipfs_pinset["ipfs"][path];
                                    if (pin_type !== "indirect") {
                                        this.collection_pins.push(path);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        const stringified_models = JSON.stringify(this.models);
        const models_md5 = crypto.createHash('md5').update(stringified_models).digest('hex');
        let state_json_md5;

        try {
            const state_json = JSON.parse(fs.readFileSync(path.join(this.ipfsPath, "state.json"), 'utf8'));
            state_json_md5 = crypto.createHash('md5').update(JSON.stringify(state_json)).digest('hex');
        } catch (e) {
            fs.writeFileSync(path.join(this.ipfsPath, "state.json"), stringified_models);
            state_json_md5 = crypto.createHash('md5').update(fs.readFileSync(path.join(this.ipfsPath, "state.json"), 'utf8')).digest('hex');
        }

        if (models_md5 !== state_json_md5) {
            fs.writeFileSync(path.join(this.ipfsPath, "state.json"), stringified_models);
        }

        return this.models;
    }

    async evict_local(model, kwargs = {}) {
        const local_model_path = path.join(this.local_path, model);
        if (fs.existsSync(local_model_path)) {
            rimraf.sync(local_model_path);
        }
        return true;
    }

    async evict_s3(model, kwargs = {}) {
        const s3_model_path = this.collection[model]["cache"]["s3"];
        const s3_model_url = s3_model_path[0]["url"];
        const s3_model_path_parts = s3_model_url.split("/");
        const s3_model_bucket = s3_model_path_parts[2];
        const s3_model_dir = s3_model_path_parts[3];
        const results = await this.s3_kit.deleteObject({
            Bucket: s3_model_bucket,
            Key: s3_model_dir
        }).promise();
        return results;
    }

    async evict_models(kwargs = {}) {
        const ls_models = this.ls_models();
        const history = this.history();
        const current_timestamp = Date.now() / 1000;
    
        for (const model of ls_models) {
            if (this.models["local_models"].hasOwnProperty(model)) {
                const this_model_timestamp = this.models["local_models"][model];
                const this_history_timestamp = new Date(history[model]).getTime() / 1000;
                if (current_timestamp - this_model_timestamp > this.timing["local_time"] && current_timestamp - this_history_timestamp > this.timing["local_time"]) {
                    await this.evict_local(model);
                    delete this.models["local_models"][model];
                }
            } else if (this.models["s3_models"].hasOwnProperty(model)) {
                const this_model_timestamp = this.models["s3_models"][model];
                const this_history_timestamp = new Date(history[model]).getTime() / 1000;
                if (current_timestamp - this_model_timestamp > this.timing["s3_time"] && current_timestamp - this_history_timestamp > this.timing["s3_time"]) {
                    await this.evict_s3(model);
                    delete this.models["s3_models"][model];
                }
            }
        }
    
        for (const model in this.models["local_models"]) {
            if (!ls_models.includes(model)) {
                await this.evict_local(model);
                delete this.models["local_models"][model];
            }
        }
    
        for (const model in this.models["s3_models"]) {
            if (!ls_models.includes(model)) {
                await this.evict_s3(model);
                delete this.models["s3_models"][model];
            }
        }
    
        const results = {
            "s3_models": this.models["s3_models"],
            "ipfs_models": this.models["ipfs_models"],
            "local_models": this.models["local_models"],
            "https_models": this.models["https_models"]
        };
    
        return results;
    }


    async check_history_models(kwargs = {}) {
        const ls_models = this.ls_models();
        const current_timestamp = Date.now() / 1000;
        const history_json_path = path.join(this.ipfsPath, "history.json");
    
        if (Object.keys(this.history_models).length === 0) {
            if (fs.existsSync(history_json_path)) {
                try {
                    this.history_models = JSON.parse(fs.readFileSync(history_json_path, 'utf8'));
                } catch (e) {
                    fs.writeFileSync(history_json_path, JSON.stringify({}));
                }
            }
        }
    
        for (const model of ls_models) {
            if (!this.history_models.hasOwnProperty(model)) {
                this.history_models[model] = null;
            }
    
            if (this.history_models[model] !== null) {
                const this_model_timestamp = new Date(this.history[model]).getTime() / 1000;
                if (current_timestamp - this_model_timestamp > 60) {
                    this.history_models[model] = null;
                }
            }
        }
    
        for (const model in this.history_models) {
            if (!ls_models.includes(model)) {
                delete this.history_models[model];
            }
        }
    
        const history_json_mtime = fs.existsSync(history_json_path) ? fs.statSync(history_json_path).mtime.getTime() / 1000 : null;
        if (!history_json_mtime || current_timestamp - history_json_mtime > 60) {
            fs.writeFileSync(history_json_path, JSON.stringify(this.history_models));
        }
    
        return this.history_models;
    }


    async check_zombies(kwargs = {}) {
        const ls_models = this.ls_models();
        const local_files = fs.readdirSync(this.local_path, { withFileTypes: true });
        const ls_local_files = [];
        const collection_files = ["collection.json"];
        const zombies = {};
    
        local_files.forEach(file => {
            if (file.isFile()) {
                let tmp_filename = path.join(this.local_path, file.name);
                tmp_filename = tmp_filename.split(path.sep).slice(3).join(path.sep);
                const split_tmp_filename = tmp_filename.split(path.sep);
                if (split_tmp_filename.length > 1 && !tmp_filename.includes("ipfs") && !tmp_filename.includes("cloudkit")) {
                    ls_local_files.push(tmp_filename);
                }
            }
        });
    
        for (const model in this.collection) {
            if (model !== "cache") {
                const this_model = this.collection[model];
                const this_folder_name = this_model["id"];
                const this_folder_data = this_model["folderData"];
                this_folder_data.forEach(file => {
                    collection_files.push(this_folder_name + file);
                });
            }
        }
    
        const s3_files = await this.s3_kit.s3_ls_dir("", this.s3cfg["bucket"]);
        const s3_file_names = s3_files.map(file => file["key"]);
        const ipfs_files = await this.ipfs_kit.ipfs_ls_path("/");
        const ipfs_file_names = ipfs_files["ipfs_ls_path"].map(file => file["name"]);
    
        const collection_pins = this.collection_pins;
    
        const compare_s3_files = s3_file_names.filter(x => !collection_files.includes(x));
        zombies["s3"] = compare_s3_files;
        const compare_local_files = ls_local_files.filter(x => !collection_files.includes(x));
        zombies["local"] = compare_local_files;
        const compare_ipfs_files = ipfs_file_names.filter(x => !collection_files.includes(x));
        zombies["ipfs_files"] = compare_ipfs_files;
        const compare_ipfs_pins = collection_pins.filter(x => !this.ipfs_pinset.includes(x));
        zombies["ipfs"] = compare_ipfs_pins;
    
        this.zombies = zombies;
        return zombies;
    }

    async rand_history(kwargs = {}) {
        const history = this.history_models;
        const two_weeks_ago = Date.now() / 1000 - 14 * 24 * 60 * 60;
        const two_days_ago = Date.now() / 1000 - 2 * 24 * 60 * 60;
        const now = Date.now() / 1000;
    
        for (const model in history) {
            const random_float = Math.random();
            const random_timestamp = ((now - two_weeks_ago) * random_float) + two_weeks_ago;
            history[model] = random_timestamp;
        }
    
        this.history_models = history;
        return history;
    }

    async check_expired(kwargs = {}) {
        const ls_models = this.ls_models();
        const current_timestamp = Date.now() / 1000;
        const expired = {
        "local" : [],
        "s3" : [],
        "ipfs": [],
        };
    
        for (const model of ls_models) {
            if ("local_models" in this.models && model in this.models["local_models"]) {
                const this_model_timestamp = this.models["local_models"][model];
                if (current_timestamp - this_model_timestamp > this.timing["local_time"] && current_timestamp - this.history_models[model] > this.timing["local_time"]) {
                    expired["local"].push(model);
                }
            }
            if ("s3Models" in this.models && model in this.models["s3Models"]) {
                const this_model_timestamp = this.models["s3Models"][model];
                if (current_timestamp - this_model_timestamp > this.timing["s3_time"] && current_timestamp - this.history_models[model] > this.timing["s3_time"]) {
                    expired["s3"].push(model);
                }
            }
            if ("s3_models" in this.models && model in this.models["s3_models"]) {
                const this_model_timestamp = this.models["s3_models"][model];
                if (current_timestamp - this_model_timestamp > this.timing["s3_time"] && current_timestamp - this.history_models[model] > this.timing["s3_time"]) {
                    expired["s3"].push(model);
                }
            }
        }
    
        this.expired = expired;
        return this.expired;
    }

    async check_pinned_models(kwargs = {}) {
        const ls_models = this.ls_models();
        while (Object.keys(this.pinnedModels).length < 5) {
            const random_number = Math.random();
            const calculate = Math.round(random_number * ls_models.length);
            if (calculate < ls_models.length) {
                const chosen_model = ls_models[calculate];
                this.pinnedModels[chosen_model] = Date.now() / 1000;
            }
        }
        // remove later and get data from orchestrator
        return this.pinned;
    }

    async check_not_found(kwargs = {}) {
        const ls_models = this.ls_models();
        const not_found = {
            "local" : [],
            "s3" : [],
        };

        for (const model in this.history_models) {
            const current_time = Date.now() / 1000;
            const time_delta = current_time - this.history_models[model];
            if (time_delta < this.timing["local_time"]) {
                if ("local_models" in this.models && !(model in this.models["local_models"])) {
                    not_found["local"].push(model);
                }
                if ("s3_models" in this.models && !(model in this.models["s3_models"])) {
                    not_found["s3"].push(model);
                }
            }
        }
  
        for (const model in this.pinnedModels) {
            if ("local_models" in this.models && !(model in this.models["local_models"])) {
                not_found["local"].push(model);
            }
            if ("s3_models" in this.models && !(model in this.models["s3_models"])) {
                not_found["s3"].push(model);
            }
        }
  
        this.not_found = not_found;
        return this.not_found;
    }

    async download_missing(kwargs = {}) {
        const current_timestamp = Date.now() / 1000;
        const not_found = this.check_not_found();
        for (const model of not_found["local"]) {
            if (model in this.pinnedModels) {
                this.download_model(model);
                this.models["local_models"][model] = Date.now() / 1000;
            } else if (this.history_models[model] > current_timestamp - this.timing["local_time"]) {
                this.download_model(model);
                this.models["local_models"][model] = Date.now() / 1000;
            }
        }
        for (const model of not_found["s3"]) {
            if (model in this.pinnedModels) {
                this.s3_kit.s3_ul_dir(this.local_path + "/" + model, this.s3cfg["bucket"], this.models["s3_models"][model]["folderData"]);
                this.models["s3_models"][model] = Date.now() / 1000;
            } else if (this.history_models[model] > current_timestamp - this.timing["s3_time"]) {
                this.s3_kit.s3_ul_dir(this.local_path + "/" + model, this.s3cfg["bucket"], this.models["s3_models"][model]["folderData"]);
                this.models["s3_models"][model] = Date.now() / 1000;
            }
        }
        return null;
    }

    async evict_expired_models(kwargs = {}) {
        const current_timestamp = Date.now() / 1000;
        const expired = this.expired;
        for (const model of expired["local"]) {
        this.evict_local(model);
        delete this.models["local_models"][model];
        }
        for (const model of expired["s3"]) {
        this.evict_s3(model);
        delete this.models["s3_models"][model];
        }
        return null;
    }
    
    async  evict_zombies(kwargs = {}) {
        const zombies = this.zombies;
        for (const file of zombies["local"]) {
            fs.unlinkSync(path.join(this.local_path, file));
        }
        for (const file of zombies["s3"]) {
            this.s3_kit.s3_rm_file(file, this.s3cfg["bucket"]);
        }
        return null;
    }

    async test(kwargs = {}) {
        await this.loadCollectionCache();
        await this.state();
        await this.state({src: "s3"});
        await this.state({src: "local"});
        await this.state({src: "ipfs"});
        await this.state({src: "https"});
        await this.check_pinned_models();
        await this.check_history_models();
        await this.rand_history();
        await this.check_zombies();
        await this.check_expired();
        await this.check_not_found();
        // this.download_model('gte-small');
        // this.download_model('stablelm-zephyr-3b-GGUF-Q2_K');
        await this.download_missing();
        await this.evict_expired_models();
        await this.evict_zombies();
        return this;
    }

}

const endpoint = "https://object.ord1.coreweave.com"
const access_key = "CWVFBNRZEEDYTAUM"
const secret_key = "cwoBNj1ILmRGxcm18EsWE5Qth4hVtmtNJPkLVW2AETU"
const host_bucket = "%(bucket)s.object.ord1.coreweave.com"
const bucket = "cloudkit-beta";
const ipfs_src = "QmXBUkLywjKGTWNDMgxknk6FJEYu9fZaEepv3djmnEqEqD";
const s3cfg = {
    "endpoint": endpoint,
    "accessKey": access_key,
    "secretKey": secret_key,
    "hostBucket": host_bucket,   
    "bucket": bucket
};
const cluster_name = "cloudkit_storage";
//let ipfs_path = "/storage/";
const local_path = "/storage/cloudkit-models";
//ipfs_path = "/storage/ipfs/";
const ten_mins = 600;
const ten_hours = 36000;
const ten_days = 864000;
const never =  100000000;
const role = "worker";
const cache = {
    "local": "/storage/cloudkit-models/collection.json",
    "s3": "s3://cloudkit-beta/collection.json",
    "ipfs": ipfs_src,
    "https": "https://huggingface.co/endomorphosis/cloudkit-collection/resolve/main/collection.json"
};
const timing = {
    "local_time": ten_mins,
    "s3_time": ten_hours,
    "ipfsTime": ten_days,
    "httpsTime": never,
};
const meta = {
    "s3cfg": s3cfg,
    "ipfs_src": ipfs_src,
    "timing": timing,
    "cache": cache,
    "role": role,
    "cluster_name": cluster_name,
    //"ipfs_path": ipfs_path,
    //"local_path": local_path,
    //"ipfs_path": ipfs_path
};

const models_manager = new ModelManager(null, meta);
const results = await models_manager.test();
console.log(results);